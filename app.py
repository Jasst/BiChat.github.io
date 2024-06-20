import sqlite3
import time
import base64
import hashlib
import json
import logging
import os
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from mnemonic import Mnemonic
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
import asyncio
from blockchain import Blockchain


def encrypt_message(key, message):
    backend = default_backend()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
    encryptor = cipher.encryptor()
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_message = padder.update(message.encode()) + padder.finalize()
    encrypted_message = encryptor.update(padded_message) + encryptor.finalize()
    return base64.b64encode(iv + encrypted_message).decode()


def decrypt_message(key, encrypted_message):
    if encrypted_message is None:
        return None

    backend = default_backend()
    encrypted_message = base64.b64decode(encrypted_message)
    iv = encrypted_message[:16]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
    decryptor = cipher.decryptor()
    decrypted_padded_message = decryptor.update(encrypted_message[16:]) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    decrypted_message = unpadder.update(decrypted_padded_message) + unpadder.finalize()
    return decrypted_message.decode()


def generate_key(sender, recipient):
    shared_secret = ''.join(sorted([sender, recipient]))
    return hashlib.sha256(shared_secret.encode()).digest()


def generate_address(phrase):
    return hashlib.sha256(phrase.encode()).hexdigest()


mnemonic = Mnemonic('english')
blockchain = Blockchain()
logging.basicConfig(level=logging.DEBUG)

# Инициализация бота
TOKEN = '7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY'
bot = Bot(token=TOKEN)
application = Application.builder().token(TOKEN).build()


async def create_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phrase = mnemonic.generate(256)
    logging.debug(f'Generated phrase: {phrase}')
    address = generate_address(phrase)
    logging.debug(f'Generated address: {address}')
    response = f'Mnemonic Phrase: {phrase}\nAddress: {address}'
    await update.message.reply_text(response)


async def login_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phrase = context.args[0] if context.args else None
    if not phrase:
        await update.message.reply_text('Mnemonic phrase is required.')
        return

    if not mnemonic.check(phrase):
        await update.message.reply_text('Invalid mnemonic phrase.')
        return

    address = generate_address(phrase)
    response = f'Address: {address}'
    await update.message.reply_text(response)


async def send_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message_parts = update.message.text.split()
        if len(message_parts) < 3:
            await update.message.reply_text('Usage: /send <recipient> <content>')
            return

        phrase = context.args[0]
        recipient = context.args[1]
        content = ' '.join(context.args[2:])

        sender = generate_address(phrase)
        key = generate_key(sender, recipient)
        encrypted_content = encrypt_message(key, content)

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            blockchain.new_transaction(sender, recipient, encrypted_content, None)
            proof = blockchain.proof_of_work(blockchain.last_block(cursor)['proof'])
            blockchain.new_block(cursor, proof)

        response = 'Transaction will be added to Block'
        await update.message.reply_text(response)

    except Exception as e:
        logging.error(f"Error sending message: {e}")
        await update.message.reply_text('Internal server error')


async def get_messages_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text('Address is required.')
            return

        address = context.args[0]

        messages = blockchain.get_messages(address)
        if not messages:
            await update.message.reply_text('No messages found for this address.')
            return

        response = ""
        for message in messages:
            key = generate_key(message['sender'], message['recipient'])
            decrypted_content = decrypt_message(key, message['content'])
            response += f"From: {message['sender']}, To: {message['recipient']}, Message: {decrypted_content}\n"

        await update.message.reply_text(response)
    except IndexError:
        await update.message.reply_text('Address is required.')
    except Exception as e:
        logging.error(f"Error getting messages: {e}")
        await update.message.reply_text("Internal server error")

    except Exception as e:
        logging.error(f"Error getting messages: {e}")
        await update.message.reply_text('Internal server error')


async def mine_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            last_block = blockchain.last_block(cursor)
            last_proof = last_block['proof']
            proof = blockchain.proof_of_work(last_proof)

            blockchain.new_block(cursor, proof)

        response = f"New Block Forged\nIndex: {last_block['index'] + 1}\nProof: {proof}\nPrevious Hash: {blockchain.hash_block(last_block)}"
        await update.message.reply_text(response)

    except Exception as e:
        logging.error(f"Error mining block: {e}")
        await update.message.reply_text('Internal server error')


async def get_updates():
    updates = await bot.get_updates(timeout=10)
    for update in updates:
        print(update)


if __name__ == '__main__':
    application.add_handler(CommandHandler('create', create_wallet_command))
    application.add_handler(CommandHandler('login', login_wallet_command))
    application.add_handler(CommandHandler('send', send_message_command))
    application.add_handler(CommandHandler('messages', get_messages_command))
    application.add_handler(CommandHandler('mine', mine_command))

    # Получение обновлений без использования оффсета
    loop = asyncio.get_event_loop()
    loop.run_until_complete(get_updates())

    application.run_polling()

