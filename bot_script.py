import telebot
import requests
import logging
from crypto_manager import encrypt_message, decrypt_message, generate_key, generate_address

bot_token = '7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY'
logging.basicConfig(level=logging.DEBUG)

API_URL = 'https://jasstme.pythonanywhere.com'  # URL вашего Flask-приложения
global_data = {}  # Глобальный словарь для хранения данных

bot = telebot.TeleBot(bot_token)
logging.basicConfig(level=logging.DEBUG)


@bot.message_handler(commands=['start'])
def main(message):
    bot.send_message(
        message.chat.id,
        f'Добро пожаловать, {message.from_user.first_name}, в Блокчейн Мессенджер! Перейдите по <a href="https://jasstme.pythonanywhere.com">этой ссылке</a> или введи /help для получения дополнительной информации.',
        parse_mode='HTML'
    )


@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "Список доступных команд:\n"
        "/start - Начать взаимодействие с ботом\n"
        "/create - Создать новый кошелек\n"
        "/login - Войти в существующий кошелек\n"
        "/send - Отправить сообщение\n"
        "/get - Получить количество сообщений\n"
        "/wallet - Просмотреть свой адрес кошелька\n"
        "/mnemonic - Просмотреть свою мнемоническую фразу (пароль)\n"
        "/help - Показать этот список команд"
    )
    bot.send_message(message.chat.id, help_text)


@bot.message_handler(commands=['create'])
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


@bot.message_handler(commands=['login'])
def login_wallet(message):
    msg = bot.send_message(message.chat.id, 'Введите вашу мнемоническую фразу:')
    bot.register_next_step_handler(msg, process_login)


def process_login(message):
    mnemonic_phrase = message.text
    response = requests.post(f'{API_URL}/login_wallet', json={'mnemonic_phrase': mnemonic_phrase})
    if response.status_code == 200:
        data = response.json()
        global_data['mnemonic_phrase'] = mnemonic_phrase  # Сохраняем мнемоническую фразу в global_data
        global_data['address'] = data["address"]
        bot.send_message(message.chat.id, f'Вы вошли в кошелек. Ваш адрес: {global_data["address"]}')
    else:
        bot.send_message(message.chat.id, f'Ошибка при входе в кошелек: {response.json()["error"]}')


@bot.message_handler(commands=['view'])
def view_address(message):
    if 'address' in global_data:
        bot.send_message(message.chat.id, f'Ваш адрес кошелька: {global_data["address"]}')
    else:
        bot.send_message(message.chat.id, 'Вы еще не создали кошелек.')


@bot.message_handler(commands=['view2'])
def view_phrase(message):
    if 'mnemonic_phrase' in global_data:
        bot.send_message(message.chat.id, f'Ваша мнемоническая фраза (пароль): {global_data["mnemonic_phrase"]}')
    else:
        bot.send_message(message.chat.id, 'Вы еще не создали кошелек.')


@bot.message_handler(commands=['get'])
def get_messages(message):
    if 'mnemonic_phrase' not in global_data:
        bot.send_message(message.chat.id, 'Для просмотра сообщений необходимо войти в кошелек.')
        return

    bot.send_message(message.chat.id, 'Получение сообщений...')

    try:
        response = requests.post(f'{API_URL}/get_messages', json={
            'mnemonic_phrase': global_data['mnemonic_phrase'],
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
                        decrypted_message = f"From: {sender}\nContent: {decrypted_content}"
                        all_decrypted_messages.append(decrypted_message)
                    except Exception as e:
                        all_decrypted_messages.append(f"Failed to decrypt message: {str(e)}")

                messages_text = "\n\n".join(all_decrypted_messages)
                bot.send_message(message.chat.id, f"Ваши сообщения:\n\n{messages_text}")

            else:
                bot.send_message(message.chat.id, "У вас нет сообщений.")

        else:
            bot.send_message(message.chat.id, f'Ошибка при получении сообщений: {response.json()["error"]}')

    except Exception as e:
        bot.send_message(message.chat.id, f'Ошибка при получении сообщений: {str(e)}')


@bot.message_handler(commands=['send'])
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
        sender = global_data['address']
        key = generate_key(sender, global_data['recipient'])
        encrypted_content = encrypt_message(key, content)
        response = requests.post(f'{API_URL}/send_message', json={
            'mnemonic_phrase': global_data['mnemonic_phrase'],
            'recipient': global_data['recipient'],
            'content': encrypted_content
        })
        if response.status_code == 201:
            bot.send_message(message.chat.id, 'Сообщение успешно отправлено!')
        else:
            bot.send_message(message.chat.id, f'Ошибка при отправке сообщения: {response.json()["error"]}')
    except Exception as e:
        bot.send_message(message.chat.id, f'Ошибка при отправке сообщения: {str(e)}')


@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.send_message(message.chat.id, 'Неизвестная команда. Используйте /help для списка команд.')


if __name__ == '__main__':
    bot.polling(none_stop=True)
