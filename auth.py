import base64

import requests
import json

# ДАННЫЕ ДЛЯ ВХОДА (ЗАМЕНИТЕ НА СВОИ!)
USERNAME = "nel.tern@gmail.com"
PASSWORD = "Jasstme66!"
DOMAIN = "blockcoin.ru"  # Ваш основной домен
SUBDOMAIN = "@"  # "@" означает сам домен blockcoin.ru


def get_current_ip():
    """Получает текущий внешний IP-адрес"""
    try:
        response = requests.get('https://api.ipify.org', timeout=10)
        response.raise_for_status()
        print(f"✓ Текущий IP-адрес: {response.text}")
        return response.text
    except Exception as e:
        print(f"✗ Ошибка при получении IP: {e}")
        return None


def update_dns_record(ip_address):
    """Обновляет A-запись для домена через API REG.RU"""
    # URL для управления DNS-зоной через API REG.RU
    url = "https://api.reg.ru/api/regru2/zone/update_record"

    # Формируем данные для запроса
    data = {
        "input_format": "json",
        "input_data": json.dumps({
            "username": USERNAME,
            "password": PASSWORD,
            "domains": [{"dname": DOMAIN}],
            "subdomain": SUBDOMAIN,  # "@" для основного домена
            "type": "A",
            "content": ip_address,
            "ttl": 300
        })
    }

    # Заголовки для запроса
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    print(f"→ Отправляем запрос на обновление DNS для {DOMAIN}...")
    try:
        response = requests.post(url, headers=headers, data=data, timeout=30)
        response.raise_for_status()
        result = response.json()

        # Проверяем результат
        if result.get('result') == 'success':
            print(f"✓ DNS-запись успешно обновлена! IP: {ip_address}")
            return True
        else:
            error_msg = result.get('error_text', 'Неизвестная ошибка')
            print(f"✗ Ошибка API REG.RU: {error_msg}")
            # Дополнительная проверка на неверные DNS-серверы
            if "DOMAIN_IS_NOT_USE_REGRU_NSS" in str(result):
                print("⚠ Важно: Убедитесь, что для домена используются DNS-серверы REG.RU (ns1.reg.ru, ns2.reg.ru) или")
                print("  что вы управляете DNS-записями через панель хостинга, а API имеет к ним доступ.")
            return False
    except Exception as e:
        print(f"✗ Ошибка при отправке запроса: {e}")
        return False


if __name__ == "__main__":
    print("--- Начинаем процесс обновления DNS-записи ---")
    current_ip = get_current_ip()
    if current_ip:
        success = update_dns_record(current_ip)
        if success:
            print("\n✅ Готово! Ваш домен指向当前IP地址.")
            print("   Изменения вступят в силу в течение часа.")
        else:
            print("\n❌ Не удалось обновить DNS-запись.")
            print("   Проверьте логин, пароль и права доступа к API.")
    else:
        print("\n❌ Не удалось определить IP-адрес.")
        print("   Проверьте подключение к интернету.")