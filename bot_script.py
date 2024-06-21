import telebot
import requests
import logging

bot = telebot.TeleBot('7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY')
logging.basicConfig(level=logging.DEBUG)

API_URL = 'https://jasstme.pythonanywhere.com'  # URL вашего Flask-приложения
global_data = {}  # Глобальный словарь для хранения данных

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

@bot.message_handler(commands=['view_address'])
def view_address(message):
    if 'address' in global_data:
        bot.send_message(message.chat.id, f'Ваш адрес кошелька: {global_data["address"]}')
    else:
        bot.send_message(message.chat.id, 'Вы еще не создали кошелек.')

@bot.message_handler(commands=['view_phrase'])
def view_phrase(message):
    if 'mnemonic_phrase' in global_data:
        bot.send_message(message.chat.id, f'Ваша мнемоническая фраза (пароль): {global_data["mnemonic_phrase"]}')
    else:
        bot.send_message(message.chat.id, 'Вы еще не создали кошелек.')

# Добавьте остальные команды и обработчики здесь

if __name__ == '__main__':
    bot.polling(none_stop=True)

