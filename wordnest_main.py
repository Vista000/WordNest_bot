import logging
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
from datetime import time, datetime, timedelta
import pytz

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

LANGUAGE, LEVEL, NOTIFY_TIME = range(3)

languages = ['English', 'French']
levels = ['A1', 'A2', 'B1', 'B2']

lessons = {
    'English': {
        'A1': [
            {"word": "apple", "meaning": "سیب", "sentence": "I eat an apple every day."},
            {"word": "book", "meaning": "کتاب", "sentence": "She reads a book."},
            {"word": "cat", "meaning": "گربه", "sentence": "The cat is sleeping."},
        ],
        'A2': [
            {"word": "travel", "meaning": "سفر کردن", "sentence": "We travel to new places."},
            {"word": "weather", "meaning": "آب و هوا", "sentence": "The weather is nice today."},
        ],
    },
    'French': {
        'A1': [
            {"word": "pomme", "meaning": "سیب", "sentence": "Je mange une pomme."},
            {"word": "livre", "meaning": "کتاب", "sentence": "Elle lit un livre."},
        ],
    },
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[lang] for lang in languages]
    await update.message.reply_text(
        "Please choose your language:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return LANGUAGE

async def language_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_lang = update.message.text
    if user_lang not in languages:
        await update.message.reply_text("Please choose a valid language.")
        return LANGUAGE
    context.user_data['language'] = user_lang

    keyboard = [[lvl] for lvl in levels]
    await update.message.reply_text(
        f"Selected language: {user_lang}\nPlease choose your level:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return LEVEL

async def level_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_level = update.message.text
    if user_level not in levels:
        await update.message.reply_text("Please choose a valid level.")
        return LEVEL
    context.user_data['level'] = user_level

    await update.message.reply_text(
        "At what hour do you want to receive the daily notification? (0-23)"
    )
    return NOTIFY_TIME

async def notify_time_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text.isdigit():
        await update.message.reply_text("Please send a number between 0 and 23.")
        return NOTIFY_TIME
    hour = int(text)
    if not (0 <= hour <= 23):
        await update.message.reply_text("Hour must be between 0 and 23.")
        return NOTIFY_TIME

    context.user_data['notify_hour'] = hour
    user_id = update.message.from_user.id
    context.application.user_data[user_id] = context.user_data.copy()

    context.application.user_data[user_id]['word_index'] = 0

    job_queue = context.application.job_queue

    current_jobs = job_queue.get_jobs_by_name(str(user_id))
    for job in current_jobs:
        job.schedule_removal()

    tz = pytz.timezone('Asia/Tehran')
    now = datetime.now(tz)
    target_time = time(hour=hour, minute=0, second=0, tzinfo=tz)

    first_time = datetime.combine(now.date(), target_time)
    if first_time < now:
        first_time += timedelta(days=1)

    delay_seconds = (first_time - now).total_seconds()

    job_queue.run_repeating(
        callback=send_daily_word,
        interval=24*3600,
        first=delay_seconds,
        name=str(user_id),
        data={'user_id': user_id}
    )

    await update.message.reply_text(
        f"Great! You will get a daily word at {hour}:00.\nUse /cancel to stop notifications."
    )
    return ConversationHandler.END

async def send_daily_word(context: CallbackContext):
    job = context.job
    user_id = job.data['user_id']

    user_data = context.application.user_data.get(user_id)
    if not user_data:
        job.schedule_removal()
        return

    lang = user_data.get('language')
    level = user_data.get('level')
    idx = user_data.get('word_index', 0)

    if not lang or not level:
        job.schedule_removal()
        return

    word_list = lessons.get(lang, {}).get(level, [])
    if not word_list:
        job.schedule_removal()
        return

    if idx >= len(word_list):
        idx = 0

    word_info = word_list[idx]

    message = (
        f"📚 Daily word:\n\n"
        f"Word: {word_info['word']}\n"
        f"Meaning: {word_info['meaning']}\n"
        f"Example: {word_info['sentence']}"
    )

    try:
        await context.bot.send_message(chat_id=user_id, text=message)
    except Exception as e:
        print(f"Error sending message to {user_id}: {e}")

    user_data['word_index'] = idx + 1

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    job_queue = context.application.job_queue
    current_jobs = job_queue.get_jobs_by_name(str(user_id))
    for job in current_jobs:
        job.schedule_removal()

    await update.message.reply_text("Notifications canceled. Use /start to begin again.")
    return ConversationHandler.END

def main():
    TOKEN = "YOUR_BOT_TOKEN_HERE"
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, language_chosen)],
            LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, level_chosen)],
            NOTIFY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, notify_time_chosen)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("cancel", cancel))

    app.run_polling()

if __name__ == "__main__":
    main()
