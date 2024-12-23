import threading
import pickle
import os
from datetime import datetime
from collections import deque

class Thought:
    """Класс для представления мысли."""
    def __init__(self, content):
        self.content = content
        self.emotions = []

    def add_emotion(self, emotion):
        """Добавление эмоции к мысли."""
        self.emotions.append(emotion)

class User:
    """Класс для представления пользователя."""
    def __init__(self, username):
        self.username = username
        self.memory = {
            'facts': {},
            'emotions': {},
            'thoughts': [],
            'tasks': [],
            'notes': []
        }
        self.interaction_log = []

class SelfAwareAI:
    """Класс для представления самоосознающего ИИ."""
    def __init__(self):
        self.users = {}
        self.current_user = None
        self.load_memory()
        self.thought_queue = deque()
        self.emotion_queue = deque()
        self.context_queue = deque(maxlen=5)  # Хранение последних 5 контекстов
        self.final_response = ""

    def load_memory(self):
        """Загрузка памяти пользователей из файла."""
        if os.path.exists('users_memory.pkl'):
            with open('users_memory.pkl', 'rb') as file:
                self.users = pickle.load(file)
                print("Память пользователей загружена.")

    def save_memory(self):
        """Сохранение памяти пользователей в файл."""
        with open('users_memory.pkl', 'wb') as file:
            pickle.dump(self.users, file)
            print("Память пользователей сохранена.")

    def add_user(self, username):
        """Добавление нового пользователя."""
        if username not in self.users:
            self.users[username] = User(username)
            print(f"Пользователь '{username}' добавлен.")
        else:
            print(f"Пользователь '{username}' уже существует.")

    def switch_user(self, username):
        """Переключение на другого пользователя."""
        if username in self.users:
            self.current_user = self.users[username]
            print(f"Переключено на пользователя '{username}'.")
        else:
            print(f"Пользователь '{username}' не найден.")

    def learn(self, data):
        """Обучение на новых данных и обновление памяти."""
        tokenized_data = self.tokenize(data)
        key = tokenized_data[0]
        self.current_user.memory['facts'][key] = tokenized_data[1:]
        self.thought_queue.append(f"Я узнал о '{key}': {', '.join(tokenized_data[1:])}")

    def tokenize(self, data):
        """Токенизация данных."""
        return data.split()

    def create_thought(self, content):
        """Создание нового потока мысли."""
        thought = Thought(content)
        self.current_user.memory['thoughts'].append(thought)
        self.emotion_queue.append(content)

    def add_emotion(self, emotion, content):
        """Добавление эмоции в память."""
        if emotion not in self.current_user.memory['emotions']:
            self.current_user.memory['emotions'][emotion] = []
        self.current_user.memory['emotions'][emotion].append(content)

    def interact(self, input_data):
        """Взаимодействие с пользователем."""
        self.learn(input_data)
        self.current_user.interaction_log.append((datetime.now(), input_data))

        thought_thread = threading.Thread(target=self.process_thoughts)
        emotion_thread = threading.Thread(target=self.process_emotions)
        context_thread = threading.Thread(target=self.process_context)
        response_thread = threading.Thread(target=self.generate_response)

        thought_thread.start()
        emotion_thread.start()
        context_thread.start()
        response_thread.start()

        thought_thread.join()
        emotion_thread.join()
        context_thread.join()
        response_thread.join()

        self.request_feedback()  # Запрос обратной связи после формирования ответа
        return self.final_response

    def process_thoughts(self):
        """Обработка мыслей."""
        while self.thought_queue:
            thought = self.thought_queue.popleft()
            self.create_thought(thought)

    def process_emotions(self):
        """Обработка эмоций."""
        while self.emotion_queue:
            content = self.emotion_queue.popleft()
            self.auto_add_emotion(content)

    def auto_add_emotion(self, content):
        """Автоматическое добавление эмоции на основе содержания мысли."""
        if "радость" in content:
            self.add_emotion("радость", content)
        elif "грусть" in content:
            self.add_emotion("грусть", content)
        elif "интересно" in content:
            self.add_emotion("интерес", content)
        else:
            self.add_emotion("нейтральное", content)

    def process_context(self):
        """Обработка контекста из предыдущих взаимодействий."""
        if self.current_user.interaction_log:
            last_interaction = self.current_user.interaction_log[-1][1]
            self.context_queue.append(last_interaction)

    def generate_response(self):
        """Генерация окончательного ответа."""
        thoughts_response = self.generate_thoughts_response()
        emotions_response = self.generate_emotions_response()
        context_response = self.generate_context_response()

        self.final_response = f"{thoughts_response} {emotions_response} {context_response}".strip() + "."

    def generate_thoughts_response(self):
        """Генерация ответа на основе мыслей."""
        return "Я помню, что..."

    def generate_emotions_response(self):
        """Генерация ответа на основе эмоций."""
        return "Я чувствую..."

    def generate_context_response(self):
        """Генерация ответа на основе контекста."""
        if self.context_queue:
            return f"В прошлый раз вы сказали: '{self.context_queue[-1]}'."
        return ""

    def request_feedback(self):
        """Запрос обратной связи у пользователя о качестве ответа."""
        feedback = input("Как вы оцениваете мой ответ? (хорошо/плохо): ")
        if feedback.lower() == "плохо":
            self.create_thought("Пользователь не удовлетворен моим ответом.")
            print("Спасибо за обратную связь! Я постараюсь улучшиться.")
        elif feedback.lower() == "хорошо":
            self.create_thought("Пользователь удовлетворен моим ответом.")
            print("Спасибо! Рад, что смог помочь.")

    def run(self):
        """Запуск программы."""
        print("Добро пожаловать! Введите 'выход' для завершения.")
        while True:
            user_input = input("Вы: ")
            if user_input.lower() == 'выход':
                self.save_memory()
                print("До свидания!")
                break
            response = self.interact(user_input)
            print(f"AI: {response}")

if __name__ == "__main__":
    ai = SelfAwareAI()
    ai.run()