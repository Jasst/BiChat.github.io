#!/usr/bin/env python3
"""
Генерация VAPID-ключей для Web Push через cryptography
"""

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
import base64
import os

def generate_vapid_keys():
    # Генерация ключей на кривой P-256 (NIST P-256)
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    # Приватный ключ в raw bytes (32 байта) -> base64url
    private_raw = private_key.private_numbers().private_value.to_bytes(32, 'big')
    private_b64url = base64.urlsafe_b64encode(private_raw).decode().rstrip('=')

    # Публичный ключ в формате uncompressed point (65 байт: 0x04 + x + y) -> base64url
    public_raw = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    public_b64url = base64.urlsafe_b64encode(public_raw).decode().rstrip('=')

    return private_b64url, public_b64url

# Путь к .env (предполагается, что он в той же папке)
env_path = os.path.join(os.path.dirname(__file__), '.env')

# Генерируем
vapid_private, vapid_public = generate_vapid_keys()

# Читаем существующий .env
env_vars = {}
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                env_vars[key] = val

# Добавляем VAPID-переменные
env_vars['VAPID_PRIVATE_KEY'] = vapid_private
env_vars['VAPID_PUBLIC_KEY'] = vapid_public
env_vars['VAPID_SUBJECT'] = 'jasstme@ya.ru'  # Замените на свою почту

# Записываем обратно
with open(env_path, 'w') as f:
    for k, v in env_vars.items():
        f.write(f"{k}={v}\n")

print("✅ VAPID-ключи сгенерированы и добавлены в .env")
print(f"🔑 Публичный ключ: {vapid_public}")
print(f"🔒 Приватный ключ: {vapid_private}")
print("\n⚠️ Храните приватный ключ в секрете!")