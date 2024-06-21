import telebot
import requests
import logging
import base64
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
import types
from cripto_manager import encrypt_message,decrypt_message,generate_key

bot_token = '7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY'
logging.basicConfig(level=logging.DEBUG)

API_URL = 'https://jasstme.pythonanywhere.com'  # URL вашего Flask-приложения
global_data = {}  # Глобальный словарь для хранения данных

bot = telebot.TeleBot(bot_token)
logging.basicConfig(level=logging.DEBUG)




# Обработчик команды /start
@bot.message_handler(commands=['start'])
def main(message):
    bot.send_message(
        message.chat.id,
        f'Добро пожаловать, {message.from_user.first_name}, в Блокчейн Мессенджер! Перейдите по <a href="https://example.com">этой ссылке</a> для получения дополнительной информации.',
        parse_mode='HTML'
    )


# Обработчик команды /help
@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "Список доступных команд:\n"
        "/start - Начать взаимодействие с ботом\n"
        "/create_wallet - Создать новый кошелек\n"
        "/login_wallet - Войти в существующий кошелек\n"
        "/send_message - Отправить сообщение\n"
        "/get_messages - Получить все сообщения\n"
        "/view_address - Просмотреть свой адрес кошелька\n"
        "/view_phrase - Просмотреть свою мнемоническую фразу (пароль)\n"
        "/help - Показать этот список команд"
    )
    bot.send_message(message.chat.id, help_text)


# Обработчик команды /create_wallet
@bot.message_handler(commands=['create_wallet'])
def create_wallet(message):
    response = requests.post(f'{API_URL}/create_wallet')
    if response.status_code == 200:
        data = response.json()
        global_data['mnemonic_phrase'] = data["mnemonic_phrase"]
        global_data['address'] = data["address"]
        message_text = (
            f'Ваш новый кошелек создан.\n'
            f'Мнемоническая фраза: {global_data["mnemonic_phrase"]}\n'
            f'Адрес: {global_data["address"]}\n'
            f'Используйте мнемоническую фразу для входа в кошелек.'
        )
        bot.send_message(message.chat.id, message_text)
    else:
        bot.send_message(message.chat.id, 'Ошибка при создании кошелька.')


# Обработчик команды /login_wallet
@bot.message_handler(commands=['login_wallet'])
def login_wallet(message):
    msg = bot.send_message(message.chat.id, 'Введите вашу мнемоническую фразу:')
    bot.register_next_step_handler(msg, process_login)


def process_login(message):
    mnemonic_phrase = message.text
    response = requests.post(f'{API_URL}/login_wallet', json={'mnemonic_phrase': mnemonic_phrase})
    if response.status_code == 200:
        data = response.json()
        global_data['address'] = data["address"]
        bot.send_message(message.chat.id, f'Вы вошли в кошелек. Ваш адрес: {global_data["address"]}')
    else:
        bot.send_message(message.chat.id, f'Ошибка при входе в кошелек: {response.json()["error"]}')


# Обработчик команды /view_address
@bot.message_handler(commands=['view_address'])
def view_address(message):
    if 'address' in global_data:
        bot.send_message(message.chat.id, f'Ваш адрес кошелька: {global_data["address"]}')
    else:
        bot.send_message(message.chat.id, 'Вы еще не создали кошелек.')


# Обработчик команды /view_phrase
@bot.message_handler(commands=['view_phrase'])
def view_phrase(message):
    if 'mnemonic_phrase' in global_data:
        bot.send_message(message.chat.id, f'Ваша мнемоническая фраза (пароль): {global_data["mnemonic_phrase"]}')
    else:
        bot.send_message(message.chat.id, 'Вы еще не создали кошелек.')


# Обработчик команды /send_message
@bot.message_handler(commands=['send_message'])
def send_message(message):
    if 'mnemonic_phrase' not in global_data or 'address' not in global_data:
        bot.send_message(message.chat.id, 'Для отправки сообщения необходимо создать или войти в кошелек.')
        return

    msg = bot.send_message(message.chat.id, 'Введите адрес получателя:')
    bot.register_next_step_handler(msg, process_send_message_recipient)


def process_send_message_recipient(message):
    recipient = message.text
    global_data['recipient'] = recipient
    msg = bot.send_message(message.chat.id, 'Введите текст сообщения:')
    bot.register_next_step_handler(msg, process_send_message_content)


def process_send_message_content(message):
    content = message.text
    try:
        encrypted_content = encrypt_message(global_data['mnemonic_phrase'], content)
        response = requests.post(f'{API_URL}/send_message', json={
            'sender': global_data['address'],
            'recipient': global_data['recipient'],
            'content': encrypted_content
        })
        if response.status_code == 201:
            bot.send_message(message.chat.id, 'Сообщение успешно отправлено!')
        else:
            bot.send_message(message.chat.id, f'Ошибка при отправке сообщения: {response.json()["error"]}')
    except Exception as e:
        bot.send_message(message.chat.id, f'Ошибка при отправке сообщения: {str(e)}')


# Обработчик команды /get_messages
@bot.message_handler(commands=['get_messages'])
def get_messages(message):
    if 'mnemonic_phrase' not in global_data:
        bot.send_message(message.chat.id, 'Для просмотра сообщений необходимо войти в кошелек.')
        return

    try:
        response = requests.post(f'{API_URL}/get_messages', json={
            'mnemonic_phrase': global_data['mnemonic_phrase'],
        })
        if response.status_code == 200:
            messages = response.json()["messages"]
            decrypted_messages = []
            for message in messages:
                try:
                    key = generate_key(global_data['mnemonic_phrase'], message['sender'])
                    decrypted_content = decrypt_message(key, message['content'])
                    decrypted_message = f"From: {message['sender']}\nContent: {decrypted_content}"
                    decrypted_messages.append(decrypted_message)
                except Exception as e:
                    decrypted_messages.append(f"Failed to decrypt message: {str(e)}")

            if decrypted_messages:
                bot.send_message(message.chat.id, "Ваши сообщения:")
                for decrypted_message in decrypted_messages:
                    bot.send_message(message.chat.id, decrypted_message)
            else:
                bot.send_message(message.chat.id, "У вас нет сообщений.")

        else:
            bot.send_message(message.chat.id, f'Ошибка при получении сообщений: {response.json()["error"]}')
    except Exception as e:
        bot.send_message(message.chat.id, f'Ошибка при получении сообщений: {str(e)}')


# Обработчик всех текстовых сообщений
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.send_message(message.chat.id, 'Неизвестная команда. Используйте /help для списка команд.')


# Запуск бота
if __name__ == '__main__':
    bot.polling(none_stop=True)