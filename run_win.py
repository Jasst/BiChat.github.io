"""run_waitress.py — Запуск Waitress вместо Gunicorn"""
import multiprocessing
from waitress import serve
from app import app

if __name__ == '__main__':
    serve(
        app,
        host='127.0.0.1',
        port=8000,
        threads=multiprocessing.cpu_count() * 2,
        connection_limit=1000,
        channel_timeout=30,
    )