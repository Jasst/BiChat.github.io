
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext

# Замените на ваш токен бота
TOKEN = '7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY'

async def start(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    await context.bot.send_message(chat_id=chat_id, text=f"Привет! Ваш chat_id: {chat_id}")

async def main():
    # Создание приложения
    application = Application.builder().token(TOKEN).build()

    # Удаление webhook
    await application.bot.delete_webhook(drop_pending_updates=True)

    # Добавление обработчиков команд
    application.add_handler(CommandHandler("start", start))

    # Запуск бота
    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
