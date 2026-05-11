"""
query_optimizer.py — Предкомпилированные запросы и кэширование результатов
"""
import time
import threading
from functools import lru_cache
from typing import Optional, Dict, Any


class QueryCache:
    """
    Простой in-memory кэш для часто используемых запросов.
    Инвалидируется по времени жизни.
    """

    def __init__(self, ttl_seconds: float = 5.0):
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, tuple] = {}  # key -> (value, expiry_time)
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Получает значение из кэша"""
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    self._hits += 1
                    return value
                else:
                    del self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any) -> None:
        """Сохраняет значение в кэш"""
        with self._lock:
            self._cache[key] = (value, time.time() + self.ttl_seconds)

    def invalidate(self, key: str = None) -> None:
        """Инвалидирует кэш (все или по ключу)"""
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    def get_stats(self) -> dict:
        """Статистика использования кэша"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            return {
                'size': len(self._cache),
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': f"{hit_rate:.1f}%",
                'ttl_seconds': self.ttl_seconds,
            }


# Глобальные кэши для разных типов запросов
balance_cache = QueryCache(ttl_seconds=30.0)  # Баланс меняется редко
contact_cache = QueryCache(ttl_seconds=60.0)  # Контакты меняются редко
group_cache = QueryCache(ttl_seconds=30.0)  # Группы могут меняться
block_count_cache = QueryCache(ttl_seconds=10.0)  # Количество блоков
supply_cache = QueryCache(ttl_seconds=60.0)  # Общая эмиссия


def cached_query(cache: QueryCache, key_prefix: str = ""):
    """
    Декоратор для кэширования результатов запросов.

    Использование:
        @cached_query(balance_cache, key_prefix='balance')
        def get_balance(address):
            ...
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            # Создаем ключ кэша из аргументов
            cache_key = f"{key_prefix}:{args}:{kwargs}"

            # Проверяем кэш
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

            # Выполняем запрос
            result = func(*args, **kwargs)

            # Сохраняем в кэш
            cache.set(cache_key, result)

            return result

        return wrapper

    return decorator


def invalidate_user_caches(address: str) -> None:
    """Инвалидирует все кэши, связанные с пользователем"""
    # В текущей реализации просто очищаем всё
    # Можно сделать более гранулярно
    balance_cache.invalidate()
    contact_cache.invalidate()
    group_cache.invalidate()