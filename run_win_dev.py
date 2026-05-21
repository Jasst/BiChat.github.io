"""
run_win_dev.py — Режим разработки с автоматической перезагрузкой
Используйте для локальной разработки, НЕ для production
"""

import sys
import os
from waitress import serve
from app import app

if __name__ == '__main__':
    print("=" * 60)
    print("🐛 DEVELOPMENT MODE - DO NOT USE IN PRODUCTION")
    print("=" * 60)
    print(f"   Port: 8000")
    print(f"   URL: http://127.0.0.1:8000")
    print(f"   Debug: ENABLED")
    print("=" * 60)
    print()

    # В режиме разработки используем встроенный сервер Flask с debug
    app.run(
        host='127.0.0.1',
        port=8000,
        debug=True,
        use_reloader=True
    )