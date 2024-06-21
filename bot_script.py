import telebot
from mnemonic import Mnemonic
from blockchain import Blockchain
from cripto_manager import encrypt_message, decrypt_message, generate_key, generate_address
import logging

mnemonic = Mnemonic('english')
blockchain = Blockchain()
logging.basicConfig(level=logging.DEBUG)
bot = telebot.TeleBot('7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY')


@bot.message_handler(commands=['start'])
def main(message):
    bot.send_message(message.chat.id, 'Привет')


# добавьте другие обработчики сообщений

if __name__ == '__main__':
    bot.polling(none_stop=True)
