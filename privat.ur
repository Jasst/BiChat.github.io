import sys
import os

# Добавьте путь к вашему приложению
path = '/home/jasstme/BiChat.github.io'
if path not in sys.path:
    sys.path.append(path)

# Установите переменную окружения для Flask
os.environ['FLASK_APP'] = 'app.py'

# Импортируйте Flask и ваше приложение
from flask import Flask
from app import app as application

# Создайте экземпляр приложения Flask
app = application
