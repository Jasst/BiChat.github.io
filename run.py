import os
import atexit

PID_FILE = 'app.pid'

def remove_pid():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass

atexit.register(remove_pid)

if __name__ == '__main__':
    print("Запускайте через: gunicorn -c gunicorn_config.py app:app")