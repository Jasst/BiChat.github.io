import telebot
import requests
import logging
from crypto_manager import encrypt_message, decrypt_message, generate_key, generate_address
from functools import wraps
from telebot import types

bot_token = '7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY'
logging.basicConfig(level=logging.DEBUG)

API_URL = 'https://jasstme.pythonanywhere.com'
user_data = {}  # Словарь для хранения данных пользователя

bot = telebot.TeleBot(bot_token)
logging.basicConfig(level=logging.DEBUG)


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


@bot.message_handler(commands=['start'])
def main(message):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    itembtns = [
        types.KeyboardButton('/create'),
        types.KeyboardButton('/login'),
        types.KeyboardButton('/help'),
        types.KeyboardButton('/exit')  # Добавляем кнопку для выхода
    ]
    markup.add(*itembtns)

    bot.send_message(
        message.chat.id,
        f'Добро пожаловать, {message.from_user.first_name}, в Блокчейн Мессенджер! Вы можете использовать кнопки ниже или введите /help для получения дополнительной информации.',
        parse_mode='HTML',
        reply_markup=markup
    )


@bot.message_handler(commands=['help'])
def help_command(message):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    itembtns = [
        types.KeyboardButton('/create'),
        types.KeyboardButton('/login'),
        types.KeyboardButton('/exit')  # Добавляем кнопку для выхода
    ]
    markup.add(*itembtns)
    help_text = (
        "Список доступных команд:\n"
        "/create - Создать новый кошелек\n"
        "/login - Войти в существующий кошелек\n"
        "/send - Отправить сообщение\n"
        "/get - Получить сообщения\n"
        "/address - Просмотреть свой адрес кошелька\n"
        "/mnemonic - Просмотреть свою мнемоническую фразу (пароль)\n"
        "/exit - Выйти из кошелька\n"
        "/help - Показать этот список команд"
    )

    bot.send_message(message.chat.id, help_text, reply_markup=markup)

@bot.message_handler(commands=['exit'])
@requires_auth
def exit_wallet(message):
    user_id = message.from_user.id
    del user_data[user_id]

    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    itembtn_create = types.KeyboardButton('/create')
    itembtn_login = types.KeyboardButton('/login')
    itembtn_help = types.KeyboardButton('/help')
    markup.add(itembtn_create, itembtn_login, itembtn_help)

    bot.send_message(message.chat.id, 'Вы успешно вышли из кошелька.', reply_markup=markup)


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
            f'Ваш новый кошелек создан.\n'
            f'Мнемоническая фраза: {user_data[user_id]["mnemonic_phrase"]}\n'
            f'Адрес: {user_data[user_id]["address"]}\n'
            f'Используйте мнемоническую фразу для входа в кошелек.'
        )
        markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
        itembtn_mnemonic = types.KeyboardButton('/mnemonic')
        itembtn_address = types.KeyboardButton('/address')
        itembtn_get = types.KeyboardButton('/get')
        itembtn_send = types.KeyboardButton('/send')
        itembtn_exit = types.KeyboardButton('/exit')
        markup.add( itembtn_get, itembtn_send, itembtn_address, itembtn_mnemonic, itembtn_exit)


        bot.send_message(message.chat.id, message_text, reply_markup=markup)
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
        markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
        itembtn_mnemonic = types.KeyboardButton('/mnemonic')
        itembtn_address = types.KeyboardButton('/address')
        itembtn_get = types.KeyboardButton('/get')
        itembtn_send = types.KeyboardButton('/send')
        itembtn_exit = types.KeyboardButton('/exit')
        markup.add( itembtn_get, itembtn_send, itembtn_address, itembtn_mnemonic, itembtn_exit)
        bot.send_message(message.chat.id, f'Вы вошли в кошелек. Ваш адрес: {user_data[user_id]["address"]}')
    else:
        bot.send_message(message.chat.id,
                         f'Ошибка при входе в кошелек: {response.json().get("error", "Неизвестная ошибка")}')


@bot.message_handler(commands=['address'])
@requires_auth
def view_address(message):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    itembtn_mnemonic = types.KeyboardButton('/mnemonic')
    itembtn_address = types.KeyboardButton('/address')
    itembtn_get = types.KeyboardButton('/get')
    itembtn_send = types.KeyboardButton('/send')
    itembtn_exit = types.KeyboardButton('/exit')
    markup.add( itembtn_get, itembtn_send, itembtn_address, itembtn_mnemonic, itembtn_exit)
    user_id = message.from_user.id
    bot.send_message(message.chat.id, f'Ваш адрес кошелька: {user_data[user_id]["address"]}')


@bot.message_handler(commands=['mnemonic'])
@requires_auth
def view_phrase(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    itembtn_mnemonic = types.KeyboardButton('/mnemonic')
    itembtn_address = types.KeyboardButton('/address')
    itembtn_get = types.KeyboardButton('/get')
    itembtn_send = types.KeyboardButton('/send')
    itembtn_exit = types.KeyboardButton('/exit')
    markup.add( itembtn_get, itembtn_send, itembtn_address, itembtn_mnemonic, itembtn_exit)
    bot.send_message(message.chat.id, f'Ваша мнемоническая фраза (пароль): {user_data[user_id]["mnemonic_phrase"]}')


@bot.message_handler(commands=['get'])
@requires_auth
def get_messages(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    itembtn_mnemonic = types.KeyboardButton('/mnemonic')
    itembtn_address = types.KeyboardButton('/address')
    itembtn_get = types.KeyboardButton('/get')
    itembtn_send = types.KeyboardButton('/send')
    itembtn_exit = types.KeyboardButton('/exit')
    markup.add( itembtn_get, itembtn_send, itembtn_address, itembtn_mnemonic, itembtn_exit)
    bot.send_message(message.chat.id, 'Получение сообщений...')

    try:
        response = requests.post(f'{API_URL}/get_messages', json={
            'mnemonic_phrase': user_data[user_id]['mnemonic_phrase'],
        })
        if response.status_code == 200:
            messages = response.json()["messages"]
            num_messages = len(messages)

            if num_messages > 0:
                bot.send_message(message.chat.id, f'Количество сообщений: {num_messages}')
                all_decrypted_messages = []

                for message_data in messages:
                    try:
                        sender = message_data['sender']
                        recipient = message_data['recipient']
                        content = message_data['content']
                        key = generate_key(sender, recipient)
                        decrypted_content = decrypt_message(key, content)
                        decrypted_message = f"От: {sender}\nСодержание: {decrypted_content}"
                        all_decrypted_messages.append(decrypted_message)
                    except Exception as e:
                        all_decrypted_messages.append(f"Ошибка при расшифровке сообщения: {str(e)}")

                messages_text = "\n\n".join(all_decrypted_messages)
                bot.send_message(message.chat.id, f"Ваши сообщения:\n\n{messages_text}")

            else:
                bot.send_message(message.chat.id, "У вас нет сообщений.")

        else:
            bot.send_message(message.chat.id,
                             f'Ошибка при получении сообщений: {response.json().get("error", "Неизвестная ошибка")}')

    except Exception as e:
        markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
        itembtn_mnemonic = types.KeyboardButton('/mnemonic')
        itembtn_address = types.KeyboardButton('/address')
        itembtn_get = types.KeyboardButton('/get')
        itembtn_send = types.KeyboardButton('/send')
        itembtn_exit = types.KeyboardButton('/exit')
        markup.add(itembtn_mnemonic, itembtn_get, itembtn_address, itembtn_send, itembtn_exit)
        bot.send_message(message.chat.id, f'Ошибка при получении сообщений: {str(e)}')


@bot.message_handler(commands=['send'])
@requires_auth
def send_message(message):
    user_id = message.from_user.id
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
        key = generate_key(sender, user_data[user_id]['recipient'])
        encrypted_content = encrypt_message(key, content)
        response = requests.post(f'{API_URL}/send_message', json={
            'mnemonic_phrase': user_data[user_id]['mnemonic_phrase'],
            'recipient': user_data[user_id]['recipient'],
            'content': encrypted_content
        })
        if response.status_code == 201:
            bot.send_message(message.chat.id, 'Сообщение успешно отправлено!')
        else:
            bot.send_message(message.chat.id,
                             f'Ошибка при отправке сообщения: {response.json().get("error", "Неизвестная ошибка")}')
    except Exception as e:
        bot.send_message(message.chat.id, f'Ошибка при отправке сообщения: {str(e)}')


@bot.message_handler(func=lambda message: True)
def echo_all(message):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    itembtn_help = types.KeyboardButton('/help')
    itembtn_exit = types.KeyboardButton('/exit')
    markup.add(itembtn_help, itembtn_exit)
    bot.send_message(message.chat.id, 'Неизвестная команда. Используйте /help для списка команд.')


if __name__ == '__main__':
    bot.polling(none_stop=True)
