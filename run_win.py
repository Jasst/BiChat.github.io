"""
run_win.py — Оптимизированный запуск Waitress для Xeon E5-2690 v3
Совместим с start_app.bat (server controller)
Поддерживает graceful shutdown и PID файл
"""

import multiprocessing
import os
import sys
import signal
import atexit
from waitress import serve
from app import app

# PID файл для совместимости с server controller
PID_FILE = os.path.join(os.path.dirname(__file__), 'app.pid')


def save_pid():
    """Сохраняет PID процесса в файл для server controller"""
    try:
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        print(f"📝 PID saved: {os.getpid()}")
    except Exception as e:
        print(f"⚠ Could not save PID: {e}")


def remove_pid():
    """Удаляет PID файл при остановке"""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
            print("📝 PID file removed")
    except Exception as e:
        pass


def graceful_shutdown(signum, frame):
    """Graceful shutdown handler"""
    print("\n🛑 Received shutdown signal, stopping gracefully...")
    remove_pid()
    sys.exit(0)


if __name__ == '__main__':
    # Регистрируем обработчики
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    atexit.register(remove_pid)

    # Сохраняем PID
    save_pid()

    # Xeon E5-2690 v3: 12 физических ядер, 24 потока
    cpu_count = multiprocessing.cpu_count()

    # Режим через переменную окружения (поддерживается server controller)
    mode = os.getenv('WAITRESS_MODE', 'auto')

    if mode == 'dev':
        threads = 4
    elif mode == 'stable':
        threads = 12
    elif mode == 'max':
        threads = min(cpu_count * 2, 32)
    else:  # auto
        # Для Xeon с Hyper-Threading оптимально: ядра * 1.5
        threads = min(int(cpu_count * 1.5), 24)

    print("=" * 60)
    print("🚀 BiChat Messenger Server - Xeon E5-2690 v3")
    print("=" * 60)
    print(f"   Mode: {mode}")
    print(f"   CPU cores: {cpu_count}")
    print(f"   Waitress threads: {threads}")
    print(f"   Port: 8000")
    print(f"   PID: {os.getpid()}")
    print("=" * 60)
    print()

    try:
        serve(
            app,
            host='127.0.0.1',
            port=8000,
            threads=threads,
            connection_limit=1000,
            channel_timeout=60,
            asyncore_use_poll=True,
            clear_untrusted_proxy_headers=True,
            ident='BiChat Messenger Xeon',
            backlog=512,
            recv_bytes=8192,
            send_bytes=8192,
            url_scheme='http',
        )
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"\n❌ Server error: {e}")
    finally:
        remove_pid()