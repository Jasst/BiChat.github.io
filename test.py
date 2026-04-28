#!/usr/bin/env python3
"""
Диагностика группового чата — показывает ВСЕ детали шифрования/расшифровки
"""
import os
import sys
import json
import sqlite3
import hashlib

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_manager import (
    generate_symmetric_key,
    encrypt_message,
    decrypt_message,
    generate_address
)

# === Тестовые данные — ЗАМЕНИТЕ НА СВОИ ===
MNEMONIC_ALICE = "ваша_фраза_алисы_12_слов_для_теста_только"
MNEMONIC_BOB = "ваша_фраза_боба_12_слов_для_теста_только"
ADDR_ALICE = generate_address(MNEMONIC_ALICE)
ADDR_BOB = generate_address(MNEMONIC_BOB)
GROUP_ID = "test_group_123456"  # любой идентификатор

print("=== 🔬 ДИАГНОСТИКА ГРУППОВОГО ЧАТА ===\n")
print(f"👤 Alice address: {ADDR_ALICE[:16]}...")
print(f"👤 Bob address:   {ADDR_BOB[:16]}...")
print(f"👥 Group ID:      {GROUP_ID}\n")

# === Тест 1: Генерация ключей ===
print("🔑 Тест 1: Генерация ключей")
key_alice_to_bob = generate_symmetric_key(ADDR_ALICE, ADDR_BOB, MNEMONIC_ALICE)
key_bob_to_alice = generate_symmetric_key(ADDR_ALICE, ADDR_BOB, MNEMONIC_BOB)
key_alice_to_alice = generate_symmetric_key(ADDR_ALICE, ADDR_ALICE, MNEMONIC_ALICE)

print(f"   Alice→Bob (mnem Alice): {key_alice_to_bob.hex()[:32]}")
print(f"   Alice→Bob (mnem Bob):   {key_bob_to_alice.hex()[:32]}")
print(f"   Alice→Alice:            {key_alice_to_alice.hex()[:32]}")
print(f"   ✅ Ключи совпадают: {key_alice_to_bob == key_bob_to_alice}\n")

# === Тест 2: Шифрование и расшифровка ===
print("🔐 Тест 2: Шифрование/расшифровка")
original_text = "Привет из группового чата! 🔐"
print(f"   Исходный текст: '{original_text}'")

# Алиса шифрует для Боба
encrypted = encrypt_message(key_alice_to_bob, original_text)
print(f"   Зашифровано (base64): {encrypted[:50]}...")

# Боб расшифровывает
decrypted = decrypt_message(key_bob_to_alice, encrypted)
print(f"   Расшифровано: '{decrypted}'")
print(f"   ✅ Текст совпадает: {decrypted == original_text}\n")

# === Тест 3: Структура encrypted_map (как в БД) ===
print("📦 Тест 3: Структура сообщения (как сохраняется в БД)")
encrypted_map = {
    ADDR_ALICE: {
        'content': encrypt_message(generate_symmetric_key(ADDR_ALICE, ADDR_ALICE, MNEMONIC_ALICE), original_text),
        'image': None
    },
    ADDR_BOB: {
        'content': encrypt_message(generate_symmetric_key(ADDR_ALICE, ADDR_BOB, MNEMONIC_ALICE), original_text),
        'image': None
    }
}
json_payload = json.dumps(encrypted_map)
print(f"   JSON payload (первые 200 симв.): {json_payload[:200]}...")

# === Тест 4: Имитация расшифровки Бобом ===
print("\n🔍 Тест 4: Имитация расшифровки Бобом (как в process_message_decryption)")
loaded = json.loads(json_payload)
print(f"   Загруженные ключи в encrypted_data: {list(loaded.keys())}")
print(f"   Адрес Боба есть в ключах: {ADDR_BOB in loaded}")

if ADDR_BOB in loaded:
    bob_data = loaded[ADDR_BOB]
    key_for_bob = generate_symmetric_key(ADDR_ALICE, ADDR_BOB, MNEMONIC_BOB)
    result = decrypt_message(key_for_bob, bob_data.get('content'))
    print(f"   Ключ Боба (hex): {key_for_bob.hex()[:32]}")
    print(f"   Результат расшифровки: '{result}'")
    print(f"   ✅ Успех: {result == original_text}")
else:
    print("   ❌ Адрес Боба НЕ найден в encrypted_data!")

# === Тест 5: Проверка БД (если есть) ===
print("\n🗄️  Тест 5: Проверка blockchain.db")
if os.path.exists('blockchain.db'):
    try:
        conn = sqlite3.connect('blockchain.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Ищем групповые сообщения
        cursor.execute("""
            SELECT id, sender, recipient, content, metadata 
            FROM transactions 
            WHERE recipient LIKE 'group:%' 
            ORDER BY timestamp DESC LIMIT 3
        """)
        rows = cursor.fetchall()

        if rows:
            print(f"   Найдено групповых сообщений: {len(rows)}")
            for i, row in enumerate(rows, 1):
                print(f"\n   📨 Сообщение #{i}:")
                print(f"      ID: {row['id']}")
                print(f"      Отправитель: {row['sender'][:16]}...")
                print(f"      Получатель: {row['recipient']}")

                # Пробуем распарсить content
                try:
                    content_data = json.loads(row['content']) if isinstance(row['content'], str) else row['content']
                    print(
                        f"      Ключи в content: {list(content_data.keys()) if isinstance(content_data, dict) else 'NOT DICT'}")

                    # Проверяем, есть ли адрес Боба
                    if isinstance(content_data, dict) and ADDR_BOB in content_data:
                        print(f"      ✅ Адрес Боба найден в сообщении")
                        bob_enc = content_data[ADDR_BOB].get('content', '')
                        print(f"      Зашифрованный контент (превью): {bob_enc[:40]}...")
                    else:
                        print(f"      ❌ Адрес Боба НЕ найден в сообщении")

                except Exception as e:
                    print(f"      ❌ Ошибка парсинга content: {e}")
        else:
            print("   ⚪ Нет групповых сообщений в БД")

        conn.close()
    except Exception as e:
        print(f"   ❌ Ошибка чтения БД: {e}")
else:
    print("   ⚪ Файл blockchain.db не найден")

print("\n=== ✅ Диагностика завершена ===")
print("\n📋 Если где-то видите ❌ — это и есть проблема.")
print("📤 Скопируйте вывод и пришлите мне — я точно скажу, что исправить.")