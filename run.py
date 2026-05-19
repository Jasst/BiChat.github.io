import os
import atexit
from waitress import serve
from app import app

# --- Запись PID для последующей остановки ---
PID_FILE = 'app.pid'

def write_pid():
    """Записывает PID текущего процесса в файл."""
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

def remove_pid():
    """Удаляет PID-файл при штатном завершении."""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass

# Записываем PID сразу при запуске
write_pid()
# Регистрируем удаление при завершении (Ctrl+C, exit и т.д.)
atexit.register(remove_pid)

# --- Запуск Waitress ---
if __name__ == '__main__':
    # Убедитесь, что app — это ваш экземпляр Flask из app.py
    serve(app,
          host='127.0.0.1',
          port=8000,
          url_scheme='https',   # Важно для правильной генерации ссылок за прокси
          threads=4,
          channel_timeout=300)  # Таймаут для долгих соединений