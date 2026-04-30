#!/usr/bin/env python3
"""🔧 Тест криптографии: проверка ECDH + AES-GCM"""
import sys

sys.path.insert(0, '.')

from crypto_manager import (
    generate_address, get_public_key_b64,
    encrypt_hybrid, decrypt_hybrid,
    generate_symmetric_key, encrypt_message_aead, decrypt_message_aead
)

# Тестовые мнемоники (НЕ ИСПОЛЬЗУЙТЕ В ПРОДАКШЕНЕ!)
MNEM_A = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
MNEM_B = "legal winner thank year wave sausage worth useful legal winner thank yellow"


def test_direct_encryption():
    print("🔐 Тест: Прямое шифрование AES-GCM")
    key = b'0' * 32  # Тестовый ключ
    msg = "Hello, World! 🎉"

    enc = encrypt_message_aead(key, msg)
    dec = decrypt_message_aead(key, enc)

    print(f"  Original: {msg}")
    print(f"  Encrypted: {enc[:50]}...")
    print(f"  Decrypted: {dec}")
    print(f"  ✅ PASS" if dec == msg else f"  ❌ FAIL")
    return dec == msg


def test_hybrid():
    print("\n🔐 Тест: Гибридное шифрование (ECDH + AES-GCM)")

    addr_a = generate_address(MNEM_A)  # Alice
    addr_b = generate_address(MNEM_B)  # Bob
    pubkey_b = get_public_key_b64(MNEM_B)

    print(f"  Alice address: {addr_a[:16]}...")
    print(f"  Bob address:   {addr_b[:16]}...")

    # 🔐 Alice шифрует для Bob:
    # peer_public_key_b64 = публичный ключ получателя (Bob)
    # peer_address = адрес получателя (Bob)
    payload = encrypt_hybrid(MNEM_A, pubkey_b, addr_b, "Secret message 🤫")

    # 🔓 Bob расшифровывает:
    # peer_public_key_b64 = публичный ключ отправителя (Alice)
    # peer_address = адрес отправителя (Alice) ← ЭТО БЫЛО НЕПРАВИЛЬНО!
    pubkey_a = get_public_key_b64(MNEM_A)
    result = decrypt_hybrid(MNEM_B, pubkey_a, addr_a, payload)  # addr_a = Alice = отправитель ✅

    print(f"  Decrypted content: {result['content']}")
    print(f"  ✅ PASS" if result['content'] == "Secret message 🤫" else f"  ❌ FAIL")
    return result['content'] == "Secret message 🤫"


def test_group_key():
    print("\n🔐 Тест: Групповой симметричный ключ")

    addr_a = generate_address(MNEM_A)
    addr_b = generate_address(MNEM_B)

    # 🔧 Ключ должен быть одинаковым независимо от того, чья мнемоника используется
    key_ab = generate_symmetric_key(addr_a, addr_b, MNEM_A)
    key_ba = generate_symmetric_key(addr_b, addr_a, MNEM_B)

    print(f"  Key A->B: {key_ab[:8].hex()}...")
    print(f"  Key B->A: {key_ba[:8].hex()}...")

    if key_ab == key_ba:
        print(f"  ✅ PASS: Keys match")
        # Дополнительно: проверим шифрование/расшифровку
        msg = "Group secret"
        aad = addr_a.encode()  # Alice отправляет
        enc = encrypt_message_aead(key_ab, msg, associated_data=aad)
        dec = decrypt_message_aead(key_ba, enc, associated_data=aad)
        if dec == msg:
            print(f"  ✅ PASS: Round-trip encryption works")
            return True
        else:
            print(f"  ❌ FAIL: Decryption mismatch")
            return False
    else:
        print(f"  ❌ FAIL: Keys don't match")
        return False


if __name__ == '__main__':
    print("🧪 Crypto Manager Tests\n" + "=" * 50)

    results = [
        test_direct_encryption(),
        test_hybrid(),
        test_group_key()
    ]

    print(f"\n{'=' * 50}\nРезультат: {sum(results)}/3 тестов пройдено")
    sys.exit(0 if all(results) else 1)