import logging
import os
import json
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
    CallbackContext,
)
from datetime import datetime, timedelta, time as dt_time
import pytz
from threading import Thread
from flask import Flask
import asyncio

# --- Logging setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

# --- Conversation states ---
LANGUAGE, LEVEL, NOTIFY_TIME, EMAIL = range(4)

# --- Bot data ---
languages = ['English', 'French']
levels = ['A1', 'A2', 'B1', 'B2']
DATA_FILE = "users.json"
TIMEZONE = pytz.timezone("America/New_York")

# --- Sample lessons ---
lessons = {
    'English': {
        'A1': [
            {"word": "apple", "meaning": "A fruit", "sentence": "I eat an apple every day."},
            {"word": "book", "meaning": "A set of pages", "sentence": "She reads a book."},
            {"word": "cat", "meaning": "A small animal", "sentence": "The cat is sleeping."},
        ],
        'A2': [
            {"word": "travel", "meaning": "To go somewhere", "sentence": "We travel to new places."},
            {"word": "weather", "meaning": "The state of the atmosphere", "sentence": "The weather is nice today."},
        ],
    },
    'French': {
        'A1': [
            {"word": "pomme", "meaning": "Apple", "sentence": "Je mange une pomme."},
            {"word": "livre", "meaning": "Book", "sentence": "Elle lit un livre."},
        ],
    },
}

# --- Web server for Render keep-alive ---
app = Flask("")

@app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# --- Utility: Save user data ---
def save_user_data(user_id, data):
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                all_data = json.load(f)
        else:
            all_data = {}
        all_data[str(user_id)] = data
        with open(DATA_FILE, "w") as f:
            json.dump(all_data, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving user data: {e}")

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[lang] for lang in languages]
    await update.message.reply_text(
        "👋 Welcome to WordNest!\nPlease choose your language 🌐:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return LANGUAGE

async def language_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = update.message.text
    if lang not in languages:
        await update.message.reply_text("❗ Please choose a valid language.")
        return LANGUAGE
    context.user_data['language'] = lang

    keyboard = [[lvl] for lvl in levels]
    await update.message.reply_text(
        f"✅ Selected language: {lang}\nNow choose your level 📚:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return LEVEL

async def level_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    level = update.message.text
    if level not in levels:
        await update.message.reply_text("❗ Please choose a valid level.")
        return LEVEL
    context.user_data['level'] = level

    await update.message.reply_text(
        "🕒 What time should we send your daily word?\nFormat: HH:MM (e.g. 06:00 or 20:30) — New York Time 🇺🇸"
    )
    return NOTIFY_TIME

async def notify_time_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        notify_time = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await update.message.reply_text("❗ Invalid time format. Please send like 08:30 or 21:00.")
        return NOTIFY_TIME

    context.user_data['notify_time'] = text
    await update.message.reply_text("📧 Great! Now please enter your email address:")
    return EMAIL

async def email_collected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text
    context.user_data['email'] = email

    user_id = update.message.from_user.id
    save_user_data(user_id, context.user_data.copy())

    await update.message.reply_text(
        f"✅ All set! We'll send your daily word at {context.user_data['notify_time']} ⏰\nUse /cancel to stop."
    )

    # --- Schedule job ---
    hour, minute = map(int, context.user_data['notify_time'].split(':'))
    now = datetime.now(TIMEZONE)
    first_time = datetime.combine(now.date(), dt_time(hour, minute, tzinfo=TIMEZONE))
    if first_time < now:
        first_time += timedelta(days=1)

    delay = (first_time - now).total_seconds()

    job_queue = context.application.job_queue
    job_queue.run_repeating(
        callback=send_daily_word,
        interval=86400,
        first=delay,
        name=str(user_id),
        data={'user_id': user_id}
    )

    return ConversationHandler.END

async def send_daily_word(context: CallbackContext):
    user_id = context.job.data['user_id']
    try:
        with open(DATA_FILE, 'r') as f:
            all_data = json.load(f)
        data = all_data.get(str(user_id))
        if not data:
            return
    except:
        return

    lang = data['language']
    level = data['level']
    word_index = data.get('word_index', 0)

    word_list = lessons.get(lang, {}).get(level, [])
    if not word_list:
        return

    if word_index >= len(word_list):
        word_index = 0

    word = word_list[word_index]
    message = (
        f"📘 Daily Word:\n\n"
        f"🔤 Word: {word['word']}\n"
        f"📖 Meaning: {word['meaning']}\n"
        f"📝 Example: {word['sentence']}"
    )

    await context.bot.send_message(chat_id=user_id, text=message)

    # Update index
    data['word_index'] = word_index + 1
    with open(DATA_FILE, 'w') as f:
        all_data[str(user_id)] = data
        json.dump(all_data, f, indent=2)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    jobs = context.application.job_queue.get_jobs_by_name(str(user_id))
    for job in jobs:
        job.schedule_removal()
    await update.message.reply_text("❌ Notifications canceled. Use /start to begin again.")
    return ConversationHandler.END

# --- Main ---
def main():
    TOKEN = os.getenv("TOKEN")
    Thread(target=run_flask).start()

    app_telegram = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, language_chosen)],
            LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, level_chosen)],
            NOTIFY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, notify_time_chosen)],
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, email_collected)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app_telegram.add_handler(conv_handler)
    app_telegram.add_handler(CommandHandler("cancel", cancel))
    app_telegram.run_polling()

if __name__ == "__main__":
    main()
