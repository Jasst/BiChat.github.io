import telebot

bot = telebot.TeleBot('7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY')
@bot.message_handler(commands=['start'])
def main(message):
    bot.send_message(message.chat.id,'Привет')


bot.polling(none_stop=True)

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


# В функции process_send_message_content
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

# В функции get_messages


# Обработчик команды /get_messages
@bot.message_handler(commands=['get_messages'])
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
            decrypted_messages = []
            for message_data in messages:
                try:
                    sender = message_data['sender']
                    content = message_data['content']
                    key = generate_key(global_data['mnemonic_phrase'], sender)
                    decrypted_content = decrypt_message(key, content)
                    decrypted_message = f"From: {sender}\nContent: {decrypted_content}"
                    decrypted_messages.append(decrypted_message)
                except Exception as e:
                    decrypted_messages.append(f"Failed to decrypt message: {str(e)}")

            if decrypted_messages:
                messages_text = "\n\n".join(decrypted_messages)
                bot.send_message(message.chat.id, f"Ваши сообщения:\n\n{messages_text}")
            else:
                bot.send_message(message.chat.id, "У вас нет сообщений.")

        else:
            bot.send_message(message.chat.id, f'Ошибка при получении сообщений: {response.json()["error"]}')
    except Exception as e:
        bot.send_message(message.chat.id, f'Ошибка при получении сообщений: {str(e)}')
