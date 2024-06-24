import telebot
import requests
import logging
from crypto_manager import encrypt_message, decrypt_message, generate_key
from functools import wraps
from telebot import types

bot_token = '7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY'
logging.basicConfig(level=logging.DEBUG)

API_URL = 'https://jasstme.pythonanywhere.com'
user_data = {}  # Словарь для хранения данных пользователя

bot = telebot.TeleBot(bot_token)

# Декоратор для проверки аутентификации
def requires_auth(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        if user_id not in user_data or 'mnemonic_phrase' not in user_data[user_id]:
            bot.send_message(message.chat.id, 'Для использования этой команды необходимо войти в кошелек.')
            return
        return func(message, *args, **kwargs)
    return wrapper

def generate_markup(authenticated=False):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    if authenticated:
        buttons = [
            types.KeyboardButton('/mnemonic'),
            types.KeyboardButton('/address'),
            types.KeyboardButton('/get'),
            types.KeyboardButton('/send'),
            types.KeyboardButton('/exit')
        ]
    else:
        buttons = [
            types.KeyboardButton('/create'),
            types.KeyboardButton('/login'),
            types.KeyboardButton('/help')
        ]
    markup.add(*buttons)
    return markup

@bot.message_handler(commands=['start'])
def main(message):
    bot.send_message(
        message.chat.id,
        f'Добро пожаловать {message.from_user.first_name},в Блокчейн Мессенджер! Используйте кнопки ниже или /help,Для получения дополнительной информации <a href="https://jasstme.pythonanywhere.com/">https://jasstme.pythonanywhere.com/</a>',
        parse_mode='HTML',
        reply_markup=generate_markup()
    )

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "Список доступных команд:\n"
        "/create - Создать новый кошелек\n"
        "/login - Войти в существующий кошелек\n"
        "/get - Проверить сообщения\n"
        "/address - Просмотреть свой адрес кошелька\n"
        "/mnemonic - Просмотреть свою мнемоническую фразу (пароль)\n"
        "/send - Отправить сообщение\n"
        "/exit - Выйти из кошелька\n"
        "/help - Показать этот список команд"
    )
    bot.send_message(message.chat.id, help_text, reply_markup=generate_markup())

@bot.message_handler(commands=['exit'])
@requires_auth
def exit_wallet(message):
    user_id = message.from_user.id
    del user_data[user_id]
    bot.send_message(message.chat.id, 'Вы успешно вышли из кошелька.', reply_markup=generate_markup())

@bot.message_handler(commands=['create'])
def create_wallet(message):
    response = requests.post(f'{API_URL}/create_wallet')
    if response.status_code == 200:
        data = response.json()
        user_id = message.from_user.id
        user_data[user_id] = {
            'mnemonic_phrase': data["mnemonic_phrase"],
            'address': data["address"]
        }
        message_text = (
            f'🔐 <b>Ваш новый кошелек создан.</b>\n\n'
            f'🗝️ <b>Мнемоническая фраза:</b> <code>{user_data[user_id]["mnemonic_phrase"]}</code>\n'
            f'➡️ <i>Скопируйте и сохраните эту фразу в безопасном месте.</i>\n\n'
            f'📬 <b>Адрес:</b> <code>{user_data[user_id]["address"]}</code>\n'
            f'➡️ <i>Скопируйте этот адрес для получения платежей.</i>'
        )
        bot.send_message(message.chat.id, message_text, reply_markup=generate_markup(authenticated=True), parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, 'Ошибка при создании кошелька.')

@bot.message_handler(commands=['login'])
def login_wallet(message):
    msg = bot.send_message(message.chat.id, 'Введите вашу мнемоническую фразу:')
    bot.register_next_step_handler(msg, process_login)

def process_login(message):
    mnemonic_phrase = message.text
    response = requests.post(f'{API_URL}/login_wallet', json={'mnemonic_phrase': mnemonic_phrase})
    if response.status_code == 200:
        data = response.json()
        user_id = message.from_user.id
        user_data[user_id] = {
            'mnemonic_phrase': mnemonic_phrase,
            'address': data["address"]
        }
        bot.send_message(message.chat.id, f'Вы вошли в кошелек. Ваш адрес: {user_data[user_id]["address"]}', reply_markup=generate_markup(authenticated=True))
    else:
        bot.send_message(message.chat.id, f'Ошибка при входе в кошелек: {response.json().get("error", "Неизвестная ошибка")}')

@bot.message_handler(commands=['address'])
@requires_auth
def view_address(message):
    user_id = message.from_user.id
    bot.send_message(message.chat.id, f'Ваш адрес кошелька: {user_data[user_id]["address"]}', reply_markup=generate_markup(authenticated=True))

@bot.message_handler(commands=['mnemonic'])
@requires_auth
def view_phrase(message):
    user_id = message.from_user.id
    bot.send_message(message.chat.id, f'Ваша мнемоническая фраза (пароль): {user_data[user_id]["mnemonic_phrase"]}', reply_markup=generate_markup(authenticated=True))

@bot.message_handler(commands=['get'])
@requires_auth
def get_messages(message):
    user_id = message.from_user.id
    bot.send_message(message.chat.id, 'Получение сообщений...')
    try:
        response = requests.post(f'{API_URL}/get_messages', json={'mnemonic_phrase': user_data[user_id]['mnemonic_phrase']})
        if response.status_code == 200:
            messages = response.json()["messages"]
            if messages:
                bot.send_message(message.chat.id, f'Количество сообщений: {len(messages)}', reply_markup=generate_markup(authenticated=True))
                bot.send_message(message.chat.id, f'{message.from_user.first_name}, перейдите в веб-версию чтобы прочитать сообщения: <a href="https://jasstme.pythonanywhere.com/">https://jasstme.pythonanywhere.com/</a>', parse_mode='HTML')
            else:
                bot.send_message(message.chat.id, "У вас нет сообщений.", reply_markup=generate_markup(authenticated=True))
        else:
            bot.send_message(message.chat.id, f'Ошибка при получении сообщений: {response.json().get("error", "Неизвестная ошибка")}', reply_markup=generate_markup(authenticated=True))
    except Exception as e:
        bot.send_message(message.chat.id, f'Ошибка при получении сообщений: {str(e)}', reply_markup=generate_markup(authenticated=True))

@bot.message_handler(commands=['send'])
@requires_auth
def send_message(message):
    msg = bot.send_message(message.chat.id, 'Введите адрес получателя:')
    bot.register_next_step_handler(msg, process_send_message_recipient)

def process_send_message_recipient(message):
    recipient = message.text
    user_id = message.from_user.id
    user_data[user_id]['recipient'] = recipient
    msg = bot.send_message(message.chat.id, 'Введите текст сообщения:')
    bot.register_next_step_handler(msg, process_send_message_content)

def process_send_message_content(message):
    content = message.text
    user_id = message.from_user.id
    try:
        sender = user_data[user_id]['address']
        recipient = user_data[user_id]['recipient']
        key = generate_key(sender, recipient)
        encrypted_content = encrypt_message(key, content)
        response = requests.post(f'{API_URL}/send_message', json={
            'mnemonic_phrase': user_data[user_id]['mnemonic_phrase'],
            'recipient': recipient,
            'content': encrypted_content
        })
        if response.status_code == 201:
            bot.send_message(message.chat.id, 'Сообщение успешно отправлено!', reply_markup=generate_markup(authenticated=True))
        else:
            bot.send_message(message.chat.id, f'Ошибка при отправке сообщения: {response.json().get("error", "Неизвестная ошибка")}', reply_markup=generate_markup(authenticated=True))
    except Exception as e:
        bot.send_message(message.chat.id, f'Ошибка при отправке сообщения: {str(e)}', reply_markup=generate_markup(authenticated=True))

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.send_message(message.chat.id, 'Неизвестная команда. Используйте /help для списка команд.', reply_markup=generate_markup())

if __name__ == '__main__':
    bot.polling(none_stop=True)