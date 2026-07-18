# config.py
# Централизованная конфигурация для всей AI-системы

import sys
from pathlib import Path

# -------------------------------
# Общие пути и настройки
# -------------------------------
MEMORY_BASE_DIR = Path("ai_memory_v3")
MEMORY_BASE_DIR.mkdir(exist_ok=True)

# -------------------------------
# Настройки LM Studio (LLM)
# -------------------------------
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_STUDIO_API_KEY = "lm-studio"
LM_STUDIO_TIMEOUT = 160          # таймаут для обычных запросов (сек)
LM_STUDIO_STREAM_TIMEOUT = 500   # таймаут для стриминга (сек)

# -------------------------------
# Размерности и параметры обучения
# -------------------------------
EMBEDDING_DIM = 128          # размерность эмбеддингов слов
LATENT_DIM = 64              # размерность скрытого состояния подсознания
LEARNING_RATE = 0.0005       # начальная скорость обучения
REPLAY_BATCH_SIZE = 32       # размер батча для воспроизведения опыта
REPLAY_FREQUENCY = 10        # частота вызова experience_replay

# -------------------------------
# Параметры памяти
# -------------------------------
WORKING_MEMORY_SIZE = 15                      # размер рабочей памяти (последние сообщения)
MEMORY_CONSOLIDATION_THRESHOLD = 0.7         # порог важности для консолидации
FORGETTING_FACTOR = 0.1                      # коэффициент забывания (в день)
QUALITY_CHECK_PROB = 0.3                     # вероятность проверки качества (не используется)
MIN_QUALITY_SCORE = 0.4                      # минимальное качество для сохранения эпизода

# -------------------------------
# Адаптивный словарь
# -------------------------------
INITIAL_VOCAB_SIZE = 2000
MAX_VOCAB_SIZE = 50000
VOCAB_EXPANSION_STEP = 1000

# -------------------------------
# Сохранение состояния
# -------------------------------
SAVE_EVERY_N_INTERACTIONS = 10   # сохранять состояние каждые N взаимодействий

# -------------------------------
# Ограничения для изображений
# -------------------------------
MAX_IMAGE_SIZE_BASE64 = 5 * 1024 * 1024   # 5 MB

# -------------------------------
# Глобальное обучение (общая база знаний)
# -------------------------------
GLOBAL_KNOWLEDGE_DIR = Path("ai_memory_v3/_global")
GLOBAL_KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

GLOBAL_VOCAB_PATH        = GLOBAL_KNOWLEDGE_DIR / "vocab.pkl.gz"
GLOBAL_SUBCONSCIOUS_PATH = GLOBAL_KNOWLEDGE_DIR / "subconscious.pt"
GLOBAL_EPISODES_PATH     = GLOBAL_KNOWLEDGE_DIR / "episodes.pkl.gz"
GLOBAL_MERGE_LOG_PATH    = GLOBAL_KNOWLEDGE_DIR / "merge_log.jsonl"
GLOBAL_STATS_PATH        = GLOBAL_KNOWLEDGE_DIR / "stats.json"

MERGE_TOP_EPISODES_PER_USER = 20    # сколько лучших эпизодов от каждого пользователя участвует в слиянии
GLOBAL_BLEND_ALPHA = 0.3            # коэффициент смешивания глобальных весов (0..1)
MIN_GLOBAL_QUALITY = 0.55           # минимальное качество для внесения в глобальную базу
GLOBAL_MERGE_INTERVAL = 1800        # интервал автоматического слияния (сек) = 30 минут
MAX_GLOBAL_EPISODES = 5000          # максимальное количество глобальных эпизодов

# -------------------------------
# Конфигурация автономности
# -------------------------------
LONG_TERM_PLANNER_INTERVAL = 3600 * 6     # 6 часов – интервал долгосрочного планирования
RESOURCE_BUDGET_LLM_CALLS = 100            # макс. вызовов LLM в час
SLEEP_CONSOLIDATION_INTERVAL = 3600 * 4    # 4 часа – интервал «сна» для консолидации памяти
ANOMALY_THRESHOLD_QUALITY_DROP = 0.15      # падение качества за 10 шагов для срабатывания детектора
EXPLAIN_MODE_TRIGGER = "#explain"          # префикс для включения режима объяснимости

# -------------------------------
# Настройки веб-поиска
# -------------------------------
MAX_SEARCH_ITERATIONS = 3
SEARCH_CACHE_TTL = 300                     # время жизни кэша поиска (сек)
PAGE_CONTENT_MAX_CHARS = 6000              # макс. символов с одной страницы
MAX_PAGES_TO_FETCH = 5                     # сколько страниц загружать за один поиск
MIN_RELEVANCE_THRESHOLD = 0.28             # порог релевантности чанка
CHUNK_SIZE = 800                           # размер чанка для разбивки текста
CHUNK_OVERLAP = 150                        # перекрытие между чанками
PARALLEL_FETCH_LIMIT = 4                   # число одновременных загрузок страниц
DDG_MIN_INTERVAL = 1.2                     # минимальный интервал между запросами к DuckDuckGo (сек)
DDG_MAX_RETRIES = 3                        # число повторных попыток при ошибках
SEARCH_CACHE_MAX_SIZE = 200                # максимальное число записей в кэше поиска
AUTO_SEARCH_ENABLED = True                 # автоматически инициировать поиск при необходимости

# -------------------------------
# Настройки генерации изображений (EasyDiffusion)
# -------------------------------
EASYDIFFUSION_ENABLED = False              # включена ли генерация изображений
EASYDIFFUSION_URL = "http://localhost:9000"
EASYDIFFUSION_TIMEOUT = 120                # таймаут генерации (сек)
EASYDIFFUSION_DEFAULT_STEPS = 20
EASYDIFFUSION_DEFAULT_WIDTH = 512
EASYDIFFUSION_DEFAULT_HEIGHT = 512

# -------------------------------
# Настройки агента (agent_core.py)
# -------------------------------
MAX_AGENT_STEPS = 8          # максимальное число шагов в агентном цикле
TOOL_TIMEOUT = 30            # таймаут выполнения инструмента (сек)
REFLECTION_INTERVAL = 20     # через сколько взаимодействий запускать рефлексию
GOAL_HORIZON = 5             # сколько целей генерировать автоматически
MIN_GOAL_CONFIDENCE = 0.55   # минимальная уверенность для авто-цели
AGENT_SAVE_INTERVAL = 15     # сохранять состояние агента каждые N взаимодействий
AUTO_LEARN_FROM_WEB = True   # автоматически извлекать факты из результатов поиска
MIN_CONFIDENCE_TO_LEARN = 0.6   # минимальная уверенность для сохранения факта
MAX_FACTS_PER_SEARCH = 10    # макс. число фактов, извлекаемых за один поиск
ENABLE_QUERY_REWRITE = True  # переписывать запросы перед поиском
SHARE_LEARNED_FACTS_GLOBALLY = True   # публиковать выученные факты в глобальную базу

# -------------------------------
# Безопасность
# -------------------------------
ENABLE_CODE_EXECUTION = False   # ВНИМАНИЕ! Включать только в доверенной среде

# -------------------------------
# Дополнительные настройки из emergence_extensions
# -------------------------------
# (здесь можно добавить параметры для CuriosityEngine, MetaLearner и т.д.)
CURIOSITY_UNCERTAINTY_THRESHOLD = 0.7
CURIOSITY_RESEARCH_INTERVAL = 600   # сек
META_ADJUST_INTERVAL = 300          # сек
