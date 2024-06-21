import telebot

bot = telebot.TeleBot('7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY')
@bot.message_handler(commands=['start'])
def main(message):
    bot.send_message(message.chat.id,'Привет')


bot.polling(none_stop=True)