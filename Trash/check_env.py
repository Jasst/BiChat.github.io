import os

env_path = '/var/www/u3498810/data/www/blockchat.ru/.env'
if not os.path.exists(env_path):
    print(f"❌ Файл .env не найден по пути: {env_path}")
    exit(1)

with open(env_path, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            v = v.strip('"').strip("'")
            os.environ[k.strip()] = v

sk = os.getenv('SECRET_KEY', '')
print("📄 .env успешно прочитан")
print(f"🔑 SECRET_KEY длина символов: {len(sk)}")
print(f"✅ Загружен корректно (≥32): {len(sk) >= 32}")
print(f"🌐 FLASK_ENV: {os.getenv('FLASK_ENV', 'не задан')}")
print(f"🗄️  DATABASE_PATH: {os.getenv('DATABASE_PATH', 'не задан')}")