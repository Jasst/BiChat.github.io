import asyncio
from telegram import Bot
from telegram.ext import Application, CommandHandler
import logging

logging.basicConfig(level=logging.DEBUG)

# Инициализация бота
TOKEN = '7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY'
bot = Bot(token=TOKEN)
application = Application.builder().token(TOKEN).build()


async def get_updates():
    updates = await bot.get_updates(timeout=10)
    for update in updates:
        print(update)


if __name__ == '__main__':
    # Получение обновлений без использования оффсета
    loop = asyncio.get_event_loop()
    loop.run_until_complete(get_updates())

    application.run_polling()
