# run_waitress.py — синхронная версия (проверенная)
from waitress import serve
from app import app  # старый app.py (Flask)

if __name__ == '__main__':
    serve(
        app,
        host='127.0.0.1',
        port=8000,
        threads=8,
        connection_limit=1000,
        channel_timeout=30,
    )