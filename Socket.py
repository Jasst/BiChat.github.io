import requests
import json

BASE_URL = 'http://127.0.0.1:5000'  # Замените на URL вашего Flask-сервера

def create_wallet():
    url = f'{BASE_URL}/create_wallet'
    response = requests.post(url)
    print(response.json())

def login_wallet():
    mnemonic_phrase = input("Введите вашу мнемоническую фразу: ")
    url = f'{BASE_URL}/login_wallet'

    data = {
        'mnemonic_phrase': mnemonic_phrase
    }

    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))
    print(response.json())

def send_message():
    mnemonic_phrase = input("Введите вашу мнемоническую фразу: ")
    recipient = input("Введите адрес получателя: ")
    content = input("Введите текст сообщения: ")

    url = f'{BASE_URL}/send_message'

    data = {
        'mnemonic_phrase': mnemonic_phrase,
        'recipient': recipient,
        'content': content
    }

    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))
    print(response.json())

def get_messages():
    mnemonic_phrase = input("Введите вашу мнемоническую фразу: ")
    url = f'{BASE_URL}/get_messages'

    data = {
        'mnemonic_phrase': mnemonic_phrase
    }

    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))
    print(response.json())

def main():
    while True:
        print("\nВыберите действие:")
        print("1. Создать кошелек")
        print("2. Войти в кошелек")
        print("3. Отправить сообщение")
        print("4. Получить сообщения")
        print("5. Выйти")

        choice = input("Введите номер действия: ")

        if choice == '1':
            create_wallet()
        elif choice == '2':
            login_wallet()
        elif choice == '3':
            send_message()
        elif choice == '4':
            get_messages()
        elif choice == '5':
            print("Выход из программы.")
            break
        else:
            print("Некорректный ввод. Попробуйте снова.")

if __name__ == "__main__":
    main()
