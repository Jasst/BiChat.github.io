import telebot
import requests
import logging
from functools import wraps
from telebot import types
from cryptography.fernet import Fernet

bot_token = '7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY'
logging.basicConfig(level=logging.DEBUG)

API_URL = 'https://jasstme.pythonanywhere.com'
user_data = {}  # Словарь для хранения данных пользователя

bot = telebot.TeleBot(bot_token)


# Генерация ключа для шифрования
def generate_key():
    key = Fernet.generate_key()
    return key


# Шифрование мнемонической фразы
def encrypt_mnemonic(mnemonic_phrase, key):
    cipher_suite = Fernet(key)
    encrypted_phrase = cipher_suite.encrypt(mnemonic_phrase.encode())
    return encrypted_phrase


# Расшифровка мнемонической фразы
def decrypt_mnemonic(encrypted_phrase, key):
    cipher_suite = Fernet(key)
    decrypted_phrase = cipher_suite.decrypt(encrypted_phrase).decode()
    return decrypted_phrase


# Декоратор для проверки аутентификации
def requires_auth(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        if user_id not in user_data or 'encrypted_mnemonic' not in user_data[user_id]:
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
            # types.KeyboardButton('/send'),
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
        f'Добро пожаловать {message.from_user.first_name}, в Блокчейн Мессенджер! Используйте кнопки ниже или /help для получения дополнительной информации <a href="https://jasstme.pythonanywhere.com/">https://jasstme.pythonanywhere.com/</a>',
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
        # "/send - Отправить сообщение\n"
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
        key = generate_key()
        encrypted_mnemonic = encrypt_mnemonic(data["mnemonic_phrase"], key)
        user_data[user_id] = {
            'encrypted_mnemonic': encrypted_mnemonic,
            'address': data["address"],
            'key': key
        }
        message_text = (
            f'🔐 <b>Ваш новый кошелек создан.</b>\n\n'
            f'📬 <b>Адрес:</b> <code>{data["address"]}</code>\n'
            f'➡️ <i>Скопируйте этот адрес для получения платежей.</i>'
        )
        bot.send_message(message.chat.id, message_text, reply_markup=generate_markup(authenticated=True),
                         parse_mode='HTML')
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
        key = generate_key()
        encrypted_mnemonic = encrypt_mnemonic(mnemonic_phrase, key)
        user_data[user_id] = {
            'encrypted_mnemonic': encrypted_mnemonic,
            'address': data["address"],
            'key': key
        }
        message_text = (
            f'📬 <b>Ваш адрес кошелька:</b>\n'
            f'<code>{data["address"]}</code>\n'
            f'➡️ <i>Скопируйте этот адрес для получения сообщений.</i>'
        )
        bot.send_message(message.chat.id, message_text, reply_markup=generate_markup(authenticated=True),
                         parse_mode='HTML')
    else:
        bot.send_message(message.chat.id,
                         f'Ошибка при входе в кошелек: {response.json().get("error", "Неизвестная ошибка")}')


@bot.message_handler(commands=['mnemonic'])
@requires_auth
def view_phrase(message):
    user_id = message.from_user.id
    key = user_data[user_id]['key']
    decrypted_phrase = decrypt_mnemonic(user_data[user_id]['encrypted_mnemonic'], key)
    message_text = (
        f'🗝️ <b>Ваша мнемоническая фраза (пароль):</b>\n'
        f'<code>{decrypted_phrase}</code>\n'
        f'➡️ <i>Скопируйте и сохраните эту фразу в безопасном месте.</i>'
    )
    bot.send_message(message.chat.id, message_text, parse_mode='HTML', reply_markup=generate_markup(authenticated=True))


@bot.message_handler(commands=['address'])
@requires_auth
def view_address(message):
    user_id = message.from_user.id
    message_text = (
        f'📬 <b>Ваш адрес кошелька:</b>\n'
        f'<code>{user_data[user_id]["address"]}</code>\n'
        f'➡️ <i>Скопируйте этот адрес для получения сообщений.</i>'
    )
    bot.send_message(message.chat.id, message_text, parse_mode='HTML', reply_markup=generate_markup(authenticated=True))


@bot.message_handler(commands=['get'])
@requires_auth
def get_messages(message):
    user_id = message.from_user.id
    key = user_data[user_id]['key']
    decrypted_phrase = decrypt_mnemonic(user_data[user_id]['encrypted_mnemonic'], key)
    bot.send_message(message.chat.id, 'Получение сообщений...')
    try:
        response = requests.post(f'{API_URL}/get_messages',
                                 json={'mnemonic_phrase': decrypted_phrase})
        response.raise_for_status()  # Проверяем статус код ответа
        if response.status_code == 200:
            messages = response.json()["messages"]
            if messages:
                bot.send_message(message.chat.id, f'Количество сообщений: {len(messages)}',
                                 reply_markup=generate_markup(authenticated=True))
                bot.send_message(message.chat.id,
                                 f'{message.from_user.first_name}, перейдите в веб-версию чтобы прочитать сообщения: <a href="https://jasstme.pythonanywhere.com/">https://jasstme.pythonanywhere.com/</a>',
                                 parse_mode='HTML')
            else:
                bot.send_message(message.chat.id, "У вас нет сообщений.",
                                 reply_markup=generate_markup(authenticated=True))
        else:
            bot.send_message(message.chat.id,
                             f'Ошибка при получении сообщений: {response.json().get("error", "Неизвестная ошибка")}',
                             reply_markup=generate_markup(authenticated=True))
    except requests.exceptions.RequestException as e:
        bot.send_message(message.chat.id, f'Ошибка при отправке запроса: {str(e)}',
                         reply_markup=generate_markup(authenticated=True))
    except Exception as e:
        bot.send_message(message.chat.id, f'Произошла ошибка: {str(e)}',
                         reply_markup=generate_markup(authenticated=True))


@bot.message_handler(commands=['send'])
@requires_auth
def send_message(message):
    bot.send_message(
        message.chat.id,
        f'{message.from_user.first_name}, перейдите <a href="https://jasstme.pythonanywhere.com/">https://jasstme.pythonanywhere.com/</a> или нажмите кнопку меню для отправки сообщений  ',
        parse_mode='HTML',
        reply_markup=generate_markup(authenticated=True)
    )


@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.send_message(message.chat.id, 'Неизвестная команда. Используйте /help для списка команд.',
                     reply_markup=generate_markup())


if __name__ == '__main__':
    bot.polling(none_stop=True)
