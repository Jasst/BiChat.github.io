"""
check_config.py — Диагностика конфигурации
Запустите для проверки всех параметров из config.py и .env
"""
import os
import sys
from pathlib import Path

# Добавляем текущую директорию в путь для импорта config
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 70)
print("🔧 ПРОВЕРКА КОНФИГУРАЦИИ ПРИЛОЖЕНИЯ")
print("=" * 70)

# 1. Проверка наличия .env файла
env_path = Path(__file__).parent / '.env'
print(f"\n📁 .env файл: {'✅ существует' if env_path.exists() else '❌ НЕ НАЙДЕН'}")

if env_path.exists():
    # Пробуем разные кодировки
    env_vars = []
    content = None

    for encoding in ['utf-8', 'cp1251', 'latin-1', 'cp866']:
        try:
            with open(env_path, 'r', encoding=encoding) as f:
                content = f.read()
                print(f"   ✅ Файл прочитан в кодировке: {encoding}")
                break
        except UnicodeDecodeError:
            continue

    if content:
        # Разбираем строки
        lines = content.split('\n')
        env_vars = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                env_vars.append(line)

        print(f"   Переменных в .env: {len(env_vars)}")
        for var in env_vars[:5]:
            # Безопасное отображение (обрезаем длинные значения)
            parts = var.split('=', 1)
            if len(parts) == 2:
                name, value = parts
                if len(value) > 50:
                    value = value[:47] + '...'
                print(f"     - {name}={value}")
            else:
                print(f"     - {var}")
        if len(env_vars) > 5:
            print(f"     ... и ещё {len(env_vars) - 5}")
    else:
        print("   ❌ Не удалось прочитать файл .env")

# 2. Импорт и проверка значений из config
print("\n" + "=" * 70)
print("📋 ЗНАЧЕНИЯ ИЗ CONFIG.PY")
print("=" * 70)

try:
    from config import (
        ARCHIVE_ENABLED, FTS_ENABLED, ARCHIVE_OLD_MESSAGES_DAYS,
        ENABLE_MINING, ENABLE_STAKING, DATABASE_PATH,
        DB_POOL_SIZE, CONFIG, BLOCK_REWARD, MESSAGE_FEE,
        AIRDROP_AMOUNT, COIN, TRANSFER_FEE, SECRET_KEY, COIN_NAME
    )

    config_checks = [
        ("ARCHIVE_ENABLED", ARCHIVE_ENABLED, bool),
        ("FTS_ENABLED", FTS_ENABLED, bool),
        ("ARCHIVE_OLD_MESSAGES_DAYS", ARCHIVE_OLD_MESSAGES_DAYS, int),
        ("ENABLE_MINING", ENABLE_MINING, bool),
        ("ENABLE_STAKING", ENABLE_STAKING, bool),
        ("DATABASE_PATH", DATABASE_PATH, str),
        ("DB_POOL_SIZE", DB_POOL_SIZE, int),
        ("BLOCK_REWARD", BLOCK_REWARD, int),
        ("MESSAGE_FEE", MESSAGE_FEE, int),
        ("AIRDROP_AMOUNT", AIRDROP_AMOUNT, int),
        ("COIN", COIN, int),
        ("TRANSFER_FEE", TRANSFER_FEE, int),
    ]

    for name, value, expected_type in config_checks:
        status = "✅" if isinstance(value, expected_type) else "⚠️"
        # Безопасное отображение длинных строк
        display_value = str(value)
        if isinstance(value, str) and len(display_value) > 60:
            display_value = display_value[:57] + '...'
        print(f"{status} {name:30} = {display_value} ({type(value).__name__})")

    # Проверка SECRET_KEY (без вывода самого ключа)
    if SECRET_KEY:
        key_len = len(SECRET_KEY)
        status = "✅" if key_len >= 32 else "⚠️"
        print(f"{status} SECRET_KEY                = {'*' * 8} (длина: {key_len} символов)")
    else:
        print(f"❌ SECRET_KEY                = НЕ УСТАНОВЛЕН (риск!)")

    # Проверка вложенных параметров CONFIG
    print("\n" + "-" * 70)
    print("📦 Параметры внутри CONFIG словаря:")
    print("-" * 70)

    config_keys = [
        'POW_DIFFICULTY', 'POW_MAX_ITERATIONS', 'DB_TIMEOUT',
        'CACHE_SIZE_KEYS', 'RATE_LIMIT_PER_MINUTE', 'RATE_LIMIT_MESSAGE_PER_MINUTE',
        'LONG_POLLING_TIMEOUT', 'MAX_UPLOAD_SIZE', 'DB_POOL_SIZE'
    ]

    for key in config_keys:
        if key in CONFIG:
            value = CONFIG[key]
            print(f"   • {key:30} = {value}")
        else:
            print(f"   ❌ {key:30} = ОТСУТСТВУЕТ")

except ImportError as e:
    print(f"❌ Ошибка импорта config: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Ошибка при чтении config: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 3. Проверка наличия и корректности путей
print("\n" + "=" * 70)
print("📂 ПРОВЕРКА ПУТЕЙ И ДОСТУПА")
print("=" * 70)

try:
    from config import BASE_DIR, DATA_DIR, UPLOAD_FOLDER

    print(f"📁 BASE_DIR:          {BASE_DIR}")
    print(f"   Существует:        {'✅' if BASE_DIR.exists() else '❌'}")
    print(f"📁 DATA_DIR:          {DATA_DIR}")
    print(f"   Существует:        {'✅' if DATA_DIR.exists() else '❌'}")
    print(f"📁 UPLOAD_FOLDER:     {UPLOAD_FOLDER}")
    print(f"   Существует:        {'✅' if Path(UPLOAD_FOLDER).exists() else '❌'}")
    print(f"💾 DATABASE_PATH:     {DATABASE_PATH}")
    db_exists = Path(DATABASE_PATH).exists()
    print(f"   Файл БД существует: {'✅' if db_exists else '❌ (будет создан при первом запуске)'}")

    if db_exists:
        import sqlite3
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sqlite_master")
            table_count = cursor.fetchone()[0]
            print(f"   Таблиц в БД:         {table_count}")

            # Проверка режима WAL
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            print(f"   Journal mode:        {journal_mode}")

            # Проверка размера БД
            db_size = Path(DATABASE_PATH).stat().st_size / (1024 * 1024)
            print(f"   Размер БД:           {db_size:.2f} MB")

            conn.close()
        except Exception as e:
            print(f"   ⚠️ Ошибка доступа к БД: {e}")

except Exception as e:
    print(f"❌ Ошибка при проверке путей: {e}")

# 4. Проверка значений архивации и поиска (интерпретация)
print("\n" + "=" * 70)
print("⚙️ ИНТЕРПРЕТАЦИЯ НАСТРОЕК")
print("=" * 70)

print(f"\n📦 АРХИВАЦИЯ:")
if ARCHIVE_ENABLED:
    print(f"   ✅ ВКЛЮЧЕНА")
    print(f"   📅 Сообщения старше {ARCHIVE_OLD_MESSAGES_DAYS} дней будут перемещены в архив")
    print(f"   ⚠️ ВНИМАНИЕ: После архивации сообщения исчезнут из основной таблицы!")
    print(f"   💡 Для полной истории установите ARCHIVE_ENABLED=0 в .env")
else:
    print(f"   ❌ ВЫКЛЮЧЕНА")
    print(f"   ✅ Все сообщения сохраняются навсегда в таблице transactions")

print(f"\n🔍 ПОЛНОТЕКСТОВЫЙ ПОИСК (FTS):")
if FTS_ENABLED:
    print(f"   ✅ ВКЛЮЧЕН")
    print(f"   🔎 Метод search_messages() будет работать")
    print(f"   ⏱️ При первом запуске индексация может занять время")
else:
    print(f"   ❌ ВЫКЛЮЧЕН")
    print(f"   🔎 Метод search_messages() будет возвращать пустой список")

print(f"\n⛏️ МАЙНИНГ:")
if ENABLE_MINING:
    print(f"   ✅ ВКЛЮЧЕН")
    reward_value = BLOCK_REWARD / 1_000_000
    print(f"   💰 Награда за блок: {reward_value:.6f} {COIN_NAME}")
else:
    print(f"   ❌ ВЫКЛЮЧЕН")

print(f"\n💎 СТЕЙКИНГ:")
if ENABLE_STAKING:
    print(f"   ✅ ВКЛЮЧЕН")
else:
    print(f"   ❌ ВЫКЛЮЧЕН")

# 5. Рекомендации
print("\n" + "=" * 70)
print("💡 РЕКОМЕНДАЦИИ")
print("=" * 70)

recommendations = []

if not ARCHIVE_ENABLED:
    recommendations.append("✅ Архивация выключена — все сообщения сохраняются полностью")
else:
    recommendations.append("⚠️ Архивация включена — старые сообщения будут удаляться из чата")
    recommendations.append("   → Чтобы отключить, добавьте в .env: ARCHIVE_ENABLED=0")

if not FTS_ENABLED:
    recommendations.append("ℹ️ FTS выключен — поиск по сообщениям недоступен")
    recommendations.append("   → Чтобы включить, добавьте в .env: FTS_ENABLED=1")

if not Path(DATABASE_PATH).parent.exists():
    recommendations.append("❌ Директория для БД не существует — проверьте DATABASE_PATH")

if SECRET_KEY and len(SECRET_KEY) < 32:
    recommendations.append("⚠️ SECRET_KEY слишком короткий (<32 символов) — сгенерируйте новый")

# Проверка DB_POOL_SIZE
if 'DB_POOL_SIZE' in CONFIG:
    pool_size = CONFIG['DB_POOL_SIZE']
    if pool_size < 5:
        recommendations.append(f"ℹ️ DB_POOL_SIZE={pool_size} (рекомендуется 5-10 для продакшена)")
elif 'DB_POOL_SIZE' in locals():
    if DB_POOL_SIZE < 5:
        recommendations.append(f"ℹ️ DB_POOL_SIZE={DB_POOL_SIZE} (рекомендуется 5-10 для продакшена)")

if recommendations:
    for rec in recommendations:
        print(f"   {rec}")
else:
    print("   ✅ Все настройки оптимальны!")

print("\n" + "=" * 70)
print("🏁 ПРОВЕРКА ЗАВЕРШЕНА")
print("=" * 70)