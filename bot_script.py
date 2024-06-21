import telebot
import requests
import logging
from telebot import types  # Импортируем типы клавиатуры Telegram

bot = telebot.TeleBot('7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY')
logging.basicConfig(level=logging.DEBUG)

API_URL = 'https://jasstme.pythonanywhere.com/'  # URL вашего Flask-приложения

@bot.message_handler(commands=['start'])
def main(message):
    bot.send_message(
        message.chat.id,
        f'Добро пожаловать, {message.from_user.first_name}, в Блокчейн Мессенджер! Перейдите по <a href="https://example.com">этой ссылке</a> для получения дополнительной информации.',
        parse_mode='HTML'
    )

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

@bot.message_handler(commands=['create_wallet'])
def create_wallet(message):
    response = requests.post(f'{API_URL}/create_wallet')
    if response.status_code == 200:
        data = response.json()
        mnemonic_phrase = data["mnemonic_phrase"]
        address = data["address"]

        # Создаем InlineKeyboardMarkup с кнопками "Copy" для мнемонической фразы и адреса
        keyboard = types.InlineKeyboardMarkup()
        copy_button_mnemonic = types.InlineKeyboardButton(text="Copy мнемоническую фразу", callback_data=f"copy_mnemonic {mnemonic_phrase}")
        copy_button_address = types.InlineKeyboardButton(text="Copy адрес", callback_data=f"copy_address {address}")
        keyboard.add(copy_button_mnemonic, copy_button_address)

        # Отправляем сообщение с мнемонической фразой и адресом кошелька
        bot.send_message(message.chat.id, f'Ваш новый кошелек создан.\nМнемоническая фраза: {mnemonic_phrase}\nАдрес: {address}', reply_markup=keyboard)
    else:
        bot.send_message(message.chat.id, 'Ошибка при создании кошелька.')

@bot.callback_query_handler(func=lambda call: call.data.startswith('copy_mnemonic'))
def copy_mnemonic_callback(call):
    _, mnemonic_phrase = call.data.split(maxsplit=1)
    bot.answer_callback_query(call.id, text=f'Скопировано: {mnemonic_phrase}')

@bot.callback_query_handler(func=lambda call: call.data.startswith('copy_address'))
def copy_address_callback(call):
    _, address = call.data.split(maxsplit=1)
    bot.answer_callback_query(call.id, text=f'Скопировано: {address}')

@bot.message_handler(commands=['login_wallet'])
def login_wallet(message):
    msg = bot.send_message(message.chat.id, 'Введите вашу мнемоническую фразу:')
    bot.register_next_step_handler(msg, process_login)

def process_login(message):
    mnemonic_phrase = message.text
    response = requests.post(f'{API_URL}/login_wallet', json={'mnemonic_phrase': mnemonic_phrase})
    if response.status_code == 200:
        data = response.json()
        address = data["address"]

        # Создаем InlineKeyboardMarkup с кнопкой "Copy" для адреса кошелька
        keyboard = types.InlineKeyboardMarkup()
        copy_button_address = types.InlineKeyboardButton(text="Copy адрес", callback_data=f"copy_address {address}")
        keyboard.add(copy_button_address)

        # Отправляем сообщение с адресом кошелька
        bot.send_message(message.chat.id, f'Вы вошли в кошелек. Ваш адрес: {address}', reply_markup=keyboard)
    else:
        bot.send_message(message.chat.id, f'Ошибка при входе в кошелек: {response.json()["error"]}')

@bot.message_handler(commands=['view_address'])
def view_address(message):
    msg = bot.send_message(message.chat.id, 'Введите вашу мнемоническую фразу:')
    bot.register_next_step_handler(msg, process_view_address)

def process_view_address(message):
    mnemonic_phrase = message.text
    response = requests.post(f'{API_URL}/login_wallet', json={'mnemonic_phrase': mnemonic_phrase})
    if response.status_code == 200:
        data = response.json()
        address = data["address"]

        # Создаем InlineKeyboardMarkup с кнопкой "Copy" для адреса кошелька
        keyboard = types.InlineKeyboardMarkup()
        copy_button_address = types.InlineKeyboardButton(text="Copy адрес", callback_data=f"copy_address {address}")
        keyboard.add(copy_button_address)

        # Отправляем сообщение с адресом кошелька
        bot.send_message(message.chat.id, f'Ваш адрес кошелька: {address}', reply_markup=keyboard)
    else:
        bot.send_message(message.chat.id, f'Ошибка при получении адреса: {response.json()["error"]}')

@bot.message_handler(commands=['view_phrase'])
def view_phrase(message):
    msg = bot.send_message(message.chat.id, 'Введите ваш адрес:')
    bot.register_next_step_handler(msg, process_view_phrase)

def process_view_phrase(message):
    address = message.text
    response = requests.post(f'{API_URL}/get_phrase', json={'address': address})
    if response.status_code == 200:
        data = response.json()
        mnemonic_phrase = data["mnemonic_phrase"]

        # Создаем InlineKeyboardMarkup с кнопкой "Copy" для мнемонической фразы
        keyboard = types.InlineKeyboardMarkup()
        copy_button_mnemonic = types.InlineKeyboardButton(text="Copy мнемоническую фразу", callback_data=f"copy_mnemonic {mnemonic_phrase}")
        keyboard.add(copy_button_mnemonic)

        # Отправляем сообщение с мнемонической фразой
        bot.send_message(message.chat.id, f'Ваша мнемоническая фраза (пароль): {mnemonic_phrase}', reply_markup=keyboard)
    else:
        bot.send_message(message.chat.id, f'Ошибка при получении мнемонической фразы: {response.json()["error"]}')

# Добавьте остальные команды и обработчики здесь

if __name__ == '__main__':
    bot.polling(none_stop=True)
