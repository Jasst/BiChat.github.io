"""
routes/ai_assistant.py — Самообучающийся AI-ассистент с памятью, нейросетью,
поддержкой изображений и веб-поиском через ddgs (duckduckgo-search)
Версия: 6.0 (стабильный поиск через ddgs)
"""
import logging
import json
import asyncio
import time
import hashlib
import gzip
import pickle
import math
import random
import re
import atexit
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import deque
from dataclasses import dataclass, field, asdict
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import aiohttp
from ddgs import DDGS
import sys
from pathlib import Path

from config import (
    EASYDIFFUSION_ENABLED,
    EASYDIFFUSION_URL,
    EASYDIFFUSION_TIMEOUT,
    EASYDIFFUSION_DEFAULT_STEPS,
    EASYDIFFUSION_DEFAULT_WIDTH,
    EASYDIFFUSION_DEFAULT_HEIGHT,
)


try:
    from dependencies import require_auth
except ImportError:
    async def require_auth():
        return "anonymous"




logger = logging.getLogger(__name__)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# ==================================================================
# 🔧 Конфигурация
# ==================================================================
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_STUDIO_API_KEY = "lm-studio"
MEMORY_BASE_DIR = Path("ai_memory_v3")
MEMORY_BASE_DIR.mkdir(exist_ok=True)

EMBEDDING_DIM = 128
INITIAL_HIDDEN = 48
MAX_HIDDEN = 512
OUTPUT_METRICS_DIM = 8
METRIC_NAMES = ['confidence', 'complexity', 'relevance', 'coherence',
                'engagement', 'completeness', 'creativity', 'empathy']

LEARNING_RATE = 0.001
MIN_LR = 0.0001
MAX_LR = 0.01
LR_ADAPT_RATE = 0.05

WORKING_MEMORY_SIZE = 15
MEMORY_CONSOLIDATION_THRESHOLD = 0.7
FORGETTING_FACTOR = 0.1

QUALITY_CHECK_PROB = 0.3
MIN_QUALITY_SCORE = 0.4

INITIAL_VOCAB_SIZE = 2000
MAX_VOCAB_SIZE = 50000
VOCAB_EXPANSION_STEP = 1000

SAVE_EVERY_N_INTERACTIONS = 10

LM_STUDIO_TIMEOUT = 160
LM_STUDIO_STREAM_TIMEOUT = 500
MAX_IMAGE_SIZE_BASE64 = 5 * 1024 * 1024

# Кэш результатов поиска (на 5 минут)
SEARCH_CACHE_TTL = 300
_search_cache: Dict[str, Tuple[str, float]] = {}

# Количество страниц для загрузки из результатов поиска
MAX_PAGES_TO_FETCH = 7
PAGE_CONTENT_MAX_CHARS = 6000

# ==================================================================
# 🌍 Глобальная база коллективных знаний
# Все пользователи анонимно вносят вклад, AI учится от всех сразу.
# ==================================================================

GLOBAL_KNOWLEDGE_DIR = Path("ai_memory_v3/_global")
GLOBAL_KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

# Параметры глобального обучения
GLOBAL_VOCAB_PATH       = GLOBAL_KNOWLEDGE_DIR / "vocab.pkl.gz"
GLOBAL_NEURAL_PATH      = GLOBAL_KNOWLEDGE_DIR / "neural.pkl.gz"
GLOBAL_EPISODES_PATH    = GLOBAL_KNOWLEDGE_DIR / "episodes.pkl.gz"
GLOBAL_MERGE_LOG_PATH   = GLOBAL_KNOWLEDGE_DIR / "merge_log.jsonl"
GLOBAL_STATS_PATH       = GLOBAL_KNOWLEDGE_DIR / "stats.json"

# Сколько лучших эпизодов каждого пользователя берём при слиянии
MERGE_TOP_EPISODES_PER_USER = 20
# Веса при слиянии эмбеддингов: global vs local
GLOBAL_BLEND_ALPHA      = 0.3   # 30% от глобального, 70% своего
# Минимальный quality-порог для передачи знания в глобальный пул
MIN_GLOBAL_QUALITY      = 0.55
# Интервал автоматического слияния (секунды) – каждые ~30 мин
GLOBAL_MERGE_INTERVAL   = 1800
# Максимальный размер глобального эпизодического хранилища
MAX_GLOBAL_EPISODES     = 5000


@dataclass
class GlobalEpisode:
    """Анонимный эпизод в глобальной памяти."""
    content_hash: str          # SHA-256 от содержимого (анонимизация)
    embedding: np.ndarray
    importance: float
    topic_tags: List[str]      # автоматически извлечённые темы
    timestamp: float
    contributor_hash: str      # sha256(user_id) – не раскрывает личность
    usage_count: int = 0


class GlobalKnowledgeBase:
    """
    Единое глобальное хранилище знаний, общее для всех пользователей.

    Архитектура:
    ┌─────────────────────────────────────────────────────┐
    │   Пользователь A  →  личная память  ──┐             │
    │   Пользователь B  →  личная память  ──┼──► Global   │
    │   Пользователь C  →  личная память  ──┘   KnBase    │
    │                                              │       │
    │   При загрузке каждый ассистент ◄────────────┘       │
    │   получает глобальный контекст                       │
    └─────────────────────────────────────────────────────┘

    Что хранится глобально (без персональных данных):
    - Обезличенные эмбеддинги вопрос/ответ пар
    - Частотный словарь с усреднёнными весами
    - Усреднённые веса нейросети (Federated Averaging)
    - Извлечённые концепты и темы
    """

    _instance: Optional['GlobalKnowledgeBase'] = None
    _lock: asyncio.Lock = None

    def __init__(self):
        self._io_lock  = asyncio.Lock()
        self._episodes: List[GlobalEpisode] = []
        self._mat: Optional[np.ndarray]     = None
        self._dirty                         = True

        # Глобальная нейросеть (Federated Averaging — усреднение весов)
        self._global_W1: Optional[np.ndarray] = None
        self._global_b1: Optional[np.ndarray] = None
        self._global_W2: Optional[np.ndarray] = None
        self._global_b2: Optional[np.ndarray] = None
        self._global_hidden: int               = INITIAL_HIDDEN

        # Глобальный словарь embeddings: word → averaged vector
        self._global_embeddings: Dict[str, np.ndarray] = {}
        self._global_word_counts: Dict[str, int]       = {}

        # Статистика
        self.total_contributors:   int   = 0
        self.total_merges:         int   = 0
        self.total_episodes_added: int   = 0
        self.last_merge_time:      float = 0.0

        self._load()
        logger.info(f"🌍 GlobalKnowledgeBase loaded: "
                    f"{len(self._episodes)} episodes, "
                    f"{len(self._global_embeddings)} words")

    # ── Singleton ──────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> 'GlobalKnowledgeBase':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def get_lock(cls) -> asyncio.Lock:
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    # ── Persist ────────────────────────────────────────────────────

    def _load(self):
        # Эпизоды
        if GLOBAL_EPISODES_PATH.exists():
            try:
                with gzip.open(GLOBAL_EPISODES_PATH, 'rb') as f:
                    raw = pickle.load(f)
                self._episodes = []
                for d in raw:
                    d['embedding'] = np.array(d['embedding'])
                    self._episodes.append(GlobalEpisode(**d))
                self._dirty = True
                logger.info(f"  ✅ {len(self._episodes)} global episodes loaded")
            except Exception as e:
                logger.error(f"GlobalKB episodes load error: {e}")

        # Нейросеть
        if GLOBAL_NEURAL_PATH.exists():
            try:
                with gzip.open(GLOBAL_NEURAL_PATH, 'rb') as f:
                    s = pickle.load(f)
                self._global_W1     = s['W1']
                self._global_b1     = s['b1']
                self._global_W2     = s['W2']
                self._global_b2     = s['b2']
                self._global_hidden = s['hidden']
                logger.info(f"  ✅ Global neural loaded h={self._global_hidden}")
            except Exception as e:
                logger.error(f"GlobalKB neural load error: {e}")

        # Словарь
        if GLOBAL_VOCAB_PATH.exists():
            try:
                with gzip.open(GLOBAL_VOCAB_PATH, 'rb') as f:
                    s = pickle.load(f)
                self._global_embeddings  = {k: np.array(v) for k, v in s['embeddings'].items()}
                self._global_word_counts = s['counts']
                logger.info(f"  ✅ Global vocab loaded: {len(self._global_embeddings)} words")
            except Exception as e:
                logger.error(f"GlobalKB vocab load error: {e}")

        # Статы
        if GLOBAL_STATS_PATH.exists():
            try:
                with open(GLOBAL_STATS_PATH, 'r', encoding='utf-8') as f:
                    s = json.load(f)
                self.total_contributors   = s.get('contributors', 0)
                self.total_merges         = s.get('merges', 0)
                self.total_episodes_added = s.get('episodes_added', 0)
                self.last_merge_time      = s.get('last_merge', 0.0)
            except Exception:
                pass

    def _save(self):
        try:
            # Эпизоды
            raw = []
            for ep in self._episodes:
                raw.append({
                    'content_hash':     ep.content_hash,
                    'embedding':        ep.embedding.tolist(),
                    'importance':       ep.importance,
                    'topic_tags':       ep.topic_tags,
                    'timestamp':        ep.timestamp,
                    'contributor_hash': ep.contributor_hash,
                    'usage_count':      ep.usage_count,
                })
            with gzip.open(GLOBAL_EPISODES_PATH, 'wb') as f:
                pickle.dump(raw, f)

            # Нейросеть
            if self._global_W1 is not None:
                with gzip.open(GLOBAL_NEURAL_PATH, 'wb') as f:
                    pickle.dump({
                        'W1': self._global_W1, 'b1': self._global_b1,
                        'W2': self._global_W2, 'b2': self._global_b2,
                        'hidden': self._global_hidden,
                    }, f)

            # Словарь
            with gzip.open(GLOBAL_VOCAB_PATH, 'wb') as f:
                pickle.dump({
                    'embeddings': {k: v.tolist() for k, v in self._global_embeddings.items()},
                    'counts':     self._global_word_counts,
                }, f)

            # Статы
            with open(GLOBAL_STATS_PATH, 'w', encoding='utf-8') as f:
                json.dump({
                    'contributors':   self.total_contributors,
                    'merges':         self.total_merges,
                    'episodes_added': self.total_episodes_added,
                    'last_merge':     self.last_merge_time,
                }, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"GlobalKB save error: {e}")

    # ── Вспомогательные ────────────────────────────────────────────

    @staticmethod
    def _anon_hash(text: str) -> str:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:32]

    @staticmethod
    def _extract_topics(text: str) -> List[str]:
        """Извлекает ключевые темы из текста по частотности."""
        stop_words = {
            'и','в','на','с','по','из','для','что','как','это','но','или',
            'the','a','an','is','are','was','were','be','been','to','of',
            'and','or','but','in','on','at','by','for','with','not',
        }
        words = re.findall(r'\b[а-яёa-z]{4,}\b', text.lower())
        freq: Dict[str, int] = {}
        for w in words:
            if w not in stop_words:
                freq[w] = freq.get(w, 0) + 1
        return sorted(freq, key=freq.get, reverse=True)[:5]

    def _rebuild_matrix(self):
        if self._episodes:
            self._mat   = np.vstack([ep.embedding for ep in self._episodes])
        else:
            self._mat   = np.zeros((0, EMBEDDING_DIM))
        self._dirty = False

    # ── Поиск в глобальной памяти ─────────────────────────────────

    def search_global(self, query_emb: np.ndarray, top_k: int = 5) -> List[Tuple[GlobalEpisode, float]]:
        if not self._episodes:
            return []
        if self._dirty:
            self._rebuild_matrix()
        qn     = query_emb / (np.linalg.norm(query_emb) + 1e-8)
        norms  = np.linalg.norm(self._mat, axis=1, keepdims=True)
        norms[norms == 0] = 1e-8
        sims   = (self._mat / norms) @ qn
        idx    = np.argsort(sims)[::-1][:top_k]
        return [(self._episodes[i], float(sims[i]))
                for i in idx if sims[i] > 0.30]

    def get_global_context(self, query_emb: np.ndarray, top_k: int = 3) -> str:
        """Возвращает строку с релевантными глобальными знаниями для подмешивания в промт."""
        hits = self.search_global(query_emb, top_k=top_k)
        if not hits:
            return ""
        parts = ["=== 🌍 Знания сообщества (анонимно) ==="]
        for ep, score in hits:
            tags = ', '.join(ep.topic_tags[:3]) if ep.topic_tags else '—'
            parts.append(f"[{score:.2f} | {tags}] (обезличенный опыт #{ep.content_hash[:8]})")
        return "\n".join(parts)

    # ── Приём знаний от пользователя ──────────────────────────────

    async def contribute(
        self,
        user_id:   str,
        content:   str,
        embedding: np.ndarray,
        importance: float,
        assistant: 'SelfImprovingAssistant',
    ) -> bool:
        """
        Анонимно добавляет эпизод от пользователя в глобальную базу.
        Ничего персонального не хранится — только хэш контента и эмбеддинг.
        """
        if importance < MIN_GLOBAL_QUALITY:
            return False

        async with self.get_lock():
            c_hash    = self._anon_hash(content)
            u_hash    = self._anon_hash(user_id)
            topics    = self._extract_topics(content)

            # Дедупликация по хэшу контента
            existing_hashes = {ep.content_hash for ep in self._episodes}
            if c_hash in existing_hashes:
                return False

            ep = GlobalEpisode(
                content_hash     = c_hash,
                embedding        = embedding.copy(),
                importance       = importance,
                topic_tags       = topics,
                timestamp        = time.time(),
                contributor_hash = u_hash,
            )
            self._episodes.append(ep)
            self._dirty             = True
            self.total_episodes_added += 1

            # Обновляем глобальный словарь (running average)
            for word, idx in assistant.vocab.word2idx.items():
                if idx < len(assistant.vocab.embeddings):
                    local_emb = assistant.vocab.embeddings[idx]
                    if word in self._global_embeddings:
                        n = self._global_word_counts.get(word, 1)
                        # running mean: new_avg = (n*old + new) / (n+1)
                        self._global_embeddings[word] = (
                            self._global_embeddings[word] * n + local_emb
                        ) / (n + 1)
                        self._global_word_counts[word] = n + 1
                    else:
                        self._global_embeddings[word]  = local_emb.copy()
                        self._global_word_counts[word]  = 1

            # Обрезаем при переполнении (удаляем наименее важные старые)
            if len(self._episodes) > MAX_GLOBAL_EPISODES:
                self._episodes.sort(key=lambda e: e.importance * (
                    1.0 - min(1.0, (time.time() - e.timestamp) / (86400 * 30))
                ), reverse=True)
                self._episodes = self._episodes[:MAX_GLOBAL_EPISODES]
                self._dirty = True

            return True

    # ── Federated Averaging нейросети ─────────────────────────────

    async def federated_average_neural(
        self,
        assistants: List['SelfImprovingAssistant'],
    ) -> None:
        """
        Усредняет веса нейросетей всех пользователей.
        Реализует упрощённый Federated Averaging (McMahan et al. 2017).
        Совместимые слои усредняются поэлементно с взвешиванием по числу обновлений.
        """
        if not assistants:
            return

        valid = [a for a in assistants if a.neural.total_updates > 0]
        if not valid:
            return

        total_updates = sum(a.neural.total_updates for a in valid)
        if total_updates == 0:
            return

        # Берём размерность самой «умной» сети как ориентир
        ref = max(valid, key=lambda a: a.neural.total_updates)

        W1_agg = np.zeros_like(ref.neural.W1)
        b1_agg = np.zeros_like(ref.neural.b1)
        W2_agg = np.zeros_like(ref.neural.W2)
        b2_agg = np.zeros_like(ref.neural.b2)

        weight_sum = 0.0
        for a in valid:
            w = a.neural.total_updates / total_updates
            n = a.neural

            # Совместимость по размеру скрытого слоя — берём минимум
            h_min  = min(n.hidden, ref.neural.hidden)
            in_dim = min(n.input_dim, ref.neural.input_dim)
            out_   = min(n.output, ref.neural.output)

            W1_agg[:in_dim, :h_min]  += w * n.W1[:in_dim, :h_min]
            b1_agg[:h_min]           += w * n.b1[:h_min]
            W2_agg[:h_min, :out_]    += w * n.W2[:h_min, :out_]
            b2_agg[:out_]            += w * n.b2[:out_]
            weight_sum += w

        if weight_sum > 0:
            self._global_W1     = W1_agg / weight_sum
            self._global_b1     = b1_agg / weight_sum
            self._global_W2     = W2_agg / weight_sum
            self._global_b2     = b2_agg / weight_sum
            self._global_hidden = ref.neural.hidden

        logger.info(f"🔗 Federated avg: {len(valid)} users, {total_updates} updates")

    # ── Применение глобальных знаний к локальной сети ─────────────

    def apply_global_to_local(
        self,
        assistant: 'SelfImprovingAssistant',
        alpha: float = GLOBAL_BLEND_ALPHA,
    ) -> None:
        """
        Подмешивает глобальные веса в локальную нейросеть.
        alpha = 0.3 означает: 30% глобальное, 70% личное.
        """
        if self._global_W1 is None:
            return

        n = assistant.neural
        h_min  = min(n.hidden, self._global_hidden)
        in_dim = min(n.input_dim, self._global_W1.shape[0])
        out_   = min(n.output,  self._global_W2.shape[1])

        try:
            n.W1[:in_dim, :h_min] = (
                (1 - alpha) * n.W1[:in_dim, :h_min]
                + alpha     * self._global_W1[:in_dim, :h_min]
            )
            n.b1[:h_min] = (
                (1 - alpha) * n.b1[:h_min]
                + alpha     * self._global_b1[:h_min]
            )
            n.W2[:h_min, :out_] = (
                (1 - alpha) * n.W2[:h_min, :out_]
                + alpha     * self._global_W2[:h_min, :out_]
            )
            n.b2[:out_] = (
                (1 - alpha) * n.b2[:out_]
                + alpha     * self._global_b2[:out_]
            )
        except Exception as e:
            logger.warning(f"apply_global_to_local: {e}")

    def apply_global_vocab_to_local(
        self,
        assistant: 'SelfImprovingAssistant',
        alpha: float = GLOBAL_BLEND_ALPHA,
    ) -> None:
        """
        Обогащает локальный словарь глобальными усреднёнными эмбеддингами.
        Новые слова из глобального словаря добавляются в локальный.
        """
        if not self._global_embeddings:
            return

        added = 0
        blended = 0
        for word, g_emb in self._global_embeddings.items():
            if word in assistant.vocab.word2idx:
                idx       = assistant.vocab.word2idx[word]
                local_emb = assistant.vocab.embeddings[idx]
                # Смешиваем: alpha глобального + (1-alpha) локального
                assistant.vocab.embeddings[idx] = (
                    (1 - alpha) * local_emb + alpha * g_emb
                )
                blended += 1
            else:
                # Добавляем новое слово из глобального словаря
                new_idx = assistant.vocab.add_word(word)
                if new_idx < len(assistant.vocab.embeddings):
                    assistant.vocab.embeddings[new_idx] = g_emb.copy()
                    added += 1

        if added or blended:
            logger.debug(f"Global vocab → {assistant.user_id[:8]}: "
                         f"+{added} new, {blended} blended")

    # ── Периодическое слияние ──────────────────────────────────────

    async def merge_all(self, assistants: List['SelfImprovingAssistant']) -> Dict:
        """
        Полный цикл слияния:
        1. Собираем лучшие эпизоды от всех пользователей
        2. Federated Averaging нейросетей
        3. Применяем глобальные знания ко всем локальным ассистентам
        4. Сохраняем глобальное состояние
        """
        async with self.get_lock():
            t0 = time.time()

            # 1. Сбор эпизодов
            episodes_added = 0
            contributor_ids = set()
            for a in assistants:
                contributor_ids.add(a.user_id)
                top_eps = sorted(
                    a.memory.episodic.items,
                    key=lambda e: e.importance, reverse=True
                )[:MERGE_TOP_EPISODES_PER_USER]

                for ep in top_eps:
                    added = await self._add_episode_unlocked(
                        user_id   = a.user_id,
                        content   = ep.content,
                        embedding = ep.embedding,
                        importance= ep.importance,
                        assistant = a,
                    )
                    if added:
                        episodes_added += 1

            # 2. Federated Averaging
            await self.federated_average_neural(assistants)

            # 3. Применяем глобальные знания к каждому ассистенту
            for a in assistants:
                self.apply_global_to_local(a, alpha=GLOBAL_BLEND_ALPHA)
                self.apply_global_vocab_to_local(a, alpha=GLOBAL_BLEND_ALPHA)

            self.total_contributors = max(self.total_contributors, len(contributor_ids))
            self.total_merges      += 1
            self.last_merge_time    = time.time()

            # 4. Сохраняем
            self._save()

            elapsed = time.time() - t0
            result  = {
                'episodes_added': episodes_added,
                'total_episodes': len(self._episodes),
                'global_vocab':   len(self._global_embeddings),
                'contributors':   len(contributor_ids),
                'merge_time_s':   round(elapsed, 2),
            }

            # Пишем лог
            try:
                with open(GLOBAL_MERGE_LOG_PATH, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({
                        'ts':      time.time(),
                        'elapsed': elapsed,
                        **result,
                    }) + '\n')
            except Exception:
                pass

            logger.info(f"🌍 Merge #{self.total_merges}: "
                        f"+{episodes_added} eps, "
                        f"{len(self._episodes)} total, "
                        f"{elapsed:.1f}s")
            return result

    async def _add_episode_unlocked(
        self,
        user_id:    str,
        content:    str,
        embedding:  np.ndarray,
        importance: float,
        assistant:  'SelfImprovingAssistant',
    ) -> bool:
        """Внутренняя версия contribute() без повторного захвата лока."""
        if importance < MIN_GLOBAL_QUALITY:
            return False
        c_hash = self._anon_hash(content)
        if any(ep.content_hash == c_hash for ep in self._episodes):
            return False

        topics = self._extract_topics(content)
        u_hash = self._anon_hash(user_id)
        ep     = GlobalEpisode(
            content_hash     = c_hash,
            embedding        = embedding.copy(),
            importance       = importance,
            topic_tags       = topics,
            timestamp        = time.time(),
            contributor_hash = u_hash,
        )
        self._episodes.append(ep)
        self._dirty              = True
        self.total_episodes_added += 1

        # Обновляем глобальный словарь
        for word, idx in assistant.vocab.word2idx.items():
            if idx < len(assistant.vocab.embeddings):
                local_emb = assistant.vocab.embeddings[idx]
                if word in self._global_embeddings:
                    n = self._global_word_counts.get(word, 1)
                    self._global_embeddings[word] = (
                        self._global_embeddings[word] * n + local_emb
                    ) / (n + 1)
                    self._global_word_counts[word] = n + 1
                else:
                    self._global_embeddings[word]  = local_emb.copy()
                    self._global_word_counts[word]  = 1

        if len(self._episodes) > MAX_GLOBAL_EPISODES:
            self._episodes.sort(
                key=lambda e: e.importance * (
                    1.0 - min(1.0, (time.time() - e.timestamp) / (86400 * 30))
                ), reverse=True
            )
            self._episodes = self._episodes[:MAX_GLOBAL_EPISODES]
            self._dirty    = True

        return True

    def stats(self) -> Dict:
        return {
            'total_episodes':     len(self._episodes),
            'global_vocab_size':  len(self._global_embeddings),
            'total_contributors': self.total_contributors,
            'total_merges':       self.total_merges,
            'episodes_added':     self.total_episodes_added,
            'last_merge':         self.last_merge_time,
            'has_global_neural':  self._global_W1 is not None,
        }


# Фоновая задача автоматического слияния
_merge_task: Optional[asyncio.Task] = None

async def _auto_merge_loop():
    """Запускается при старте приложения, каждые GLOBAL_MERGE_INTERVAL секунд сливает знания."""
    await asyncio.sleep(60)   # первый запуск через 1 минуту
    while True:
        try:
            gkb = GlobalKnowledgeBase.get_instance()
            async with _assistants_lock:
                all_assistants = list(_assistants.values())
            if len(all_assistants) >= 1:
                result = await gkb.merge_all(all_assistants)
                logger.info(f"🌍 Auto-merge: {result}")
            else:
                logger.debug("Auto-merge skipped: no active assistants")
        except Exception as e:
            logger.error(f"Auto-merge error: {e}")
        await asyncio.sleep(GLOBAL_MERGE_INTERVAL)


def start_global_merge_task():
    """Вызывается один раз при старте FastAPI-приложения."""
    global _merge_task
    _merge_task = asyncio.create_task(_auto_merge_loop())
    logger.info("🌍 Global merge task started")

# ==================================================================
# 🌐 Web Search Tool — использующий ddgs (duckduckgo-search)
# ==================================================================
# Модель для запроса генерации изображения
class ImageGenRequest(BaseModel):
    prompt: str = Field(..., description="Текстовое описание изображения")
    negative_prompt: Optional[str] = Field("", description="Что не нужно изображать")
    steps: int = Field(EASYDIFFUSION_DEFAULT_STEPS, ge=1, le=50)
    width: int = Field(EASYDIFFUSION_DEFAULT_WIDTH, ge=256, le=1024)
    height: int = Field(EASYDIFFUSION_DEFAULT_HEIGHT, ge=256, le=1024)
    cfg_scale: float = Field(7.0, ge=1.0, le=20.0)
    seed: Optional[int] = Field(None, description="Фиксированный seed для повторяемости")

class WebSearchTool:
    """
    Веб-поиск через стабильную библиотеку ddgs + загрузка нескольких страниц.
    """

    FETCH_TIMEOUT = 12
    MAX_PAGE_CHARS = 4000
    MAX_RESULTS = 6

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    }

    @classmethod
    def classify_query(cls, message: str) -> Tuple[str, str]:
        """Классифицирует запрос и возвращает (тип, очищенный_запрос)."""
        msg = message.lower().strip()

        url_match = re.search(r'https?://[^\s]+', message)
        if url_match:
            return 'url', url_match.group(0)

        currency_patterns = [
            r'\bкурс\b', r'\bдолл[ао]р', r'\bевро\b', r'\busd\b', r'\beur\b',
            r'\bрубл[ьея]\b', r'\bкурс.*валют', r'\bvalute\b', r'\bfx\b',
            r'\bбитко[йи]н\b', r'\bbitcoin\b', r'\bbtc\b', r'\beth\b',
            r'\bкрипт[оа]\b', r'\bcrypto\b', r'\bcoin\b',
        ]
        for p in currency_patterns:
            if re.search(p, msg):
                return 'currency', msg

        if re.search(r'\bпогод[аеу]\b|\bweather\b|\bтемператур', msg):
            return 'weather', msg

        if re.search(r'\bновост[иь]\b|\bnews\b|\bпоследн[иеяь]\b|\bсегодня\b|\btoday\b|\bсейчас\b', msg):
            return 'news', msg

        search_triggers = [
            r'\bпоищи\b', r'\bнайди\b', r'\bпоиск\b', r'\bsearch\b',
            r'\bчто такое\b', r'\bwhat is\b', r'\bwho is\b', r'\bкто такой\b',
            r'\bгде\b', r'\bwhere\b', r'\bкогда\b', r'\bwhen\b',
            r'\bсколько\b', r'\bhow much\b', r'\bцена\b', r'\bprice\b',
            r'\bвики\b', r'\bwiki\b',
        ]
        for p in search_triggers:
            if re.search(p, msg):
                return 'general', msg

        return 'none', msg

    @classmethod
    def should_auto_search(cls, message: str) -> bool:
        query_type, _ = cls.classify_query(message)
        return query_type != 'none'

    # ---------- Специализированные источники (без изменений) ----------
    @classmethod
    async def get_currency_rates(cls) -> Optional[Dict]:
        try:
            async with aiohttp.ClientSession(headers=cls.HEADERS) as session:
                async with session.get(
                    "https://www.cbr.ru/scripts/XML_daily.asp",
                    timeout=aiohttp.ClientTimeout(total=cls.FETCH_TIMEOUT)
                ) as resp:
                    if resp.status == 200:
                        text = await resp.text(encoding='windows-1251', errors='replace')
                        rates = {}
                        for valute in re.finditer(
                            r'<CharCode>(\w+)</CharCode>.*?<Name>(.*?)</Name>.*?<Nominal>(\d+)</Nominal>.*?<Value>([\d,]+)</Value>',
                            text, re.DOTALL
                        ):
                            code, name, nominal, value = valute.groups()
                            val = float(value.replace(',', '.'))
                            nom = int(nominal)
                            rates[code] = {
                                'name': name.strip(),
                                'rate': round(val, 4),
                                'nominal': nom,
                                'per_unit': round(val / nom, 4)
                            }
                        date_m = re.search(r'Date="([\d.]+)"', text)
                        date_str = date_m.group(1) if date_m else 'сегодня'
                        return {'rates': rates, 'date': date_str, 'source': 'ЦБ РФ'}
        except Exception as e:
            logger.warning(f"CBR rates error: {e}")
        return None

    @classmethod
    async def get_crypto_prices(cls) -> Optional[str]:
        try:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": "bitcoin,ethereum,tether,binancecoin,solana,ripple",
                "vs_currencies": "usd,rub",
                "include_24hr_change": "true"
            }
            async with aiohttp.ClientSession(headers=cls.HEADERS) as session:
                async with session.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=cls.FETCH_TIMEOUT)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        names = {
                            'bitcoin': 'Bitcoin (BTC)',
                            'ethereum': 'Ethereum (ETH)',
                            'tether': 'Tether (USDT)',
                            'binancecoin': 'BNB',
                            'solana': 'Solana (SOL)',
                            'ripple': 'XRP',
                        }
                        lines = [f"=== КУРСЫ КРИПТОВАЛЮТ (CoinGecko) ==="]
                        for coin_id, info in data.items():
                            name = names.get(coin_id, coin_id)
                            usd = info.get('usd', '?')
                            rub = info.get('rub', '?')
                            change = info.get('usd_24h_change', 0)
                            sign = '+' if change and change > 0 else ''
                            change_str = f" ({sign}{change:.1f}% за 24ч)" if change else ""
                            lines.append(f"  {name}: ${usd:,.2f} / ₽{rub:,.0f}{change_str}")
                        return '\n'.join(lines)
        except Exception as e:
            logger.warning(f"CoinGecko error: {e}")
        return None

    @classmethod
    def format_currency_result(cls, rates_data: Dict, query: str) -> str:
        if not rates_data:
            return ""
        rates = rates_data['rates']
        date = rates_data['date']
        source = rates_data['source']
        q = query.lower()
        wanted = []
        if any(w in q for w in ['доллар', 'usd', '$']):
            wanted.append('USD')
        if any(w in q for w in ['евро', 'eur', '€']):
            wanted.append('EUR')
        if any(w in q for w in ['фунт', 'gbp']):
            wanted.append('GBP')
        if any(w in q for w in ['юань', 'cny', 'rmb']):
            wanted.append('CNY')
        if any(w in q for w in ['franc', 'chf', 'франк']):
            wanted.append('CHF')
        if not wanted:
            wanted = ['USD', 'EUR', 'CNY', 'GBP']
        lines = [f"=== ОФИЦИАЛЬНЫЕ КУРСЫ ЦБ РФ на {date} ==="]
        for code in wanted:
            if code in rates:
                r = rates[code]
                lines.append(
                    f"  {code} ({r['name']}): {r['nominal']} {code} = {r['rate']} ₽  "
                    f"(1 {code} = {r['per_unit']} ₽)"
                )
        lines.append(f"  Источник: {source} (официальный)")
        return '\n'.join(lines)

    # ---------- Поиск через ddgs ----------
    @classmethod
    async def _ddg_search(cls, query: str) -> List[Dict]:
        """Асинхронная обёртка над синхронным DDGS.text()."""
        results = []
        try:
            # Запускаем синхронный поиск в отдельном потоке
            def sync_search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=cls.MAX_RESULTS))
            search_results = await asyncio.to_thread(sync_search)
            for r in search_results:
                results.append({
                    'title': r.get('title', '')[:120],
                    'url': r.get('href', ''),
                    'snippet': r.get('body', '')[:500],
                    'source': 'ddgs',
                })
        except Exception as e:
            logger.warning(f"DDGS search error: {e}")
        return results

    # ---------- Загрузка страниц ----------
    @classmethod
    async def fetch_url(cls, url: str) -> str:
        if not url or not url.startswith(("http://", "https://")):
            return ""
        try:
            async with aiohttp.ClientSession(headers=cls.HEADERS) as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=cls.FETCH_TIMEOUT),
                    allow_redirects=True, ssl=False,
                ) as resp:
                    if resp.status != 200:
                        return f"[HTTP {resp.status}]"
                    ct = resp.headers.get("Content-Type", "")
                    if "text" not in ct and "json" not in ct:
                        return f"[Binary: {ct}]"
                    html = await resp.text(errors="replace")
                    return cls._extract_text(html)
        except asyncio.TimeoutError:
            return "[Timeout при загрузке]"
        except Exception as e:
            return f"[Ошибка: {e}]"

    @classmethod
    def _extract_text(cls, html: str) -> str:
        html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<nav[^>]*>.*?</nav>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<footer[^>]*>.*?</footer>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', html)
        text = text.replace('&nbsp;', ' ').replace('&amp;', '&') \
                   .replace('&lt;', '<').replace('&gt;', '>') \
                   .replace('&quot;', '"').replace('&#39;', "'")
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:cls.MAX_PAGE_CHARS]

    @classmethod
    async def fetch_multiple_pages(cls, results: List[Dict], limit: int = MAX_PAGES_TO_FETCH) -> str:
        if not results:
            return ""
        to_fetch = []
        for r in results:
            url = r.get('url')
            if url and url.startswith(('http://', 'https://')):
                to_fetch.append((r.get('title', 'Без названия'), url))
                if len(to_fetch) >= limit:
                    break
        if not to_fetch:
            return ""

        async def fetch_one(title, url):
            content = await cls.fetch_url(url)
            if len(content) > PAGE_CONTENT_MAX_CHARS:
                content = content[:PAGE_CONTENT_MAX_CHARS] + "\n[...обрезано]"
            return f"### {title}\nURL: {url}\n\n{content}\n\n"

        tasks = [fetch_one(title, url) for title, url in to_fetch]
        pages_content = await asyncio.gather(*tasks, return_exceptions=True)

        parts = ["\n=== ПОЛНОЕ СОДЕРЖИМОЕ ЗАГРУЖЕННЫХ СТРАНИЦ ===\n"]
        for i, res in enumerate(pages_content):
            if isinstance(res, Exception):
                parts.append(f"[Страница {i+1} не загружена: {res}]\n")
            else:
                parts.append(res)
        return ''.join(parts)

    # ---------- Основной метод поиска ----------
    @classmethod
    async def search(cls, query: str, query_type: str = 'general') -> Tuple[List[Dict], Optional[str]]:
        special_data = None
        results = []

        if query_type == 'currency':
            q_lower = query.lower()
            is_crypto = any(w in q_lower for w in [
                'биткоин', 'bitcoin', 'btc', 'eth', 'ethereum',
                'крипт', 'crypto', 'coin', 'solana', 'bnb', 'xrp'
            ])
            if is_crypto:
                crypto = await cls.get_crypto_prices()
                if crypto:
                    special_data = crypto
                    return [], special_data
            else:
                rates = await cls.get_currency_rates()
                if rates:
                    special_data = cls.format_currency_result(rates, query)
                    return [], special_data

        # Основной поиск через ddgs
        results = await cls._ddg_search(query)
        return results[:cls.MAX_RESULTS], special_data

    @classmethod
    def format_for_prompt(cls, results: List[Dict], special_data: Optional[str],
                          full_pages_content: str, original_query: str) -> str:
        parts = []
        if special_data:
            parts.append(special_data)
        if results:
            parts.append(f"\n=== РЕЗУЛЬТАТЫ ПОИСКА (краткие сниппеты): «{original_query}» ===")
            for i, r in enumerate(results, 1):
                parts.append(f"\n[{i}] {r.get('title', '(без заголовка)')}")
                if r.get('url'):
                    parts.append(f"    Источник: {r['url']}")
                if r.get('snippet'):
                    parts.append(f"    {r['snippet']}")
        if full_pages_content:
            parts.append(full_pages_content)
        if not parts:
            return (
                f"[ПОИСК НЕ ДАЛ РЕЗУЛЬТАТОВ для запроса: «{original_query}»]\n"
                f"ВАЖНО: НЕ отвечай из памяти для запросов о текущих ценах/курсах/новостях. "
                f"Сообщи пользователю, что не удалось получить актуальные данные."
            )
        parts.append("\n=== КОНЕЦ ДАННЫХ ===")
        return '\n'.join(parts)

# ==================================================================
# 🔤 Адаптивный словарь
# ==================================================================
@dataclass
class WordMeta:
    word: str
    usage_count: int = 0
    quality: float = 0.5
    first_seen: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)

    def retention_score(self) -> float:
        hours = (time.time() - self.last_used) / 3600
        recency = max(0.1, 1.0 - hours / 168)
        usage = min(1.0, self.usage_count / 10)
        return usage * 0.4 + self.quality * 0.4 + recency * 0.2

class DynamicVocab:
    def __init__(self, dim: int = EMBEDDING_DIM):
        self.dim = dim
        self.cur_size = INITIAL_VOCAB_SIZE
        self.max_size = MAX_VOCAB_SIZE
        self.embeddings = np.random.randn(INITIAL_VOCAB_SIZE, dim) * 0.01
        self.word2idx: Dict[str, int] = {}
        self.idx2word: Dict[int, str] = {}
        self.meta: Dict[str, WordMeta] = {}
        self.next_idx = 0
        self.m = np.zeros_like(self.embeddings)
        self.v = np.zeros_like(self.embeddings)
        self.t = 0

    def _expand(self, new_size: int) -> bool:
        if new_size > self.max_size:
            return False
        add = new_size - self.cur_size
        self.embeddings = np.vstack([self.embeddings, np.random.randn(add, self.dim) * 0.01])
        self.m = np.vstack([self.m, np.zeros((add, self.dim))])
        self.v = np.vstack([self.v, np.zeros((add, self.dim))])
        self.cur_size = new_size
        return True

    def add_word(self, word: str) -> int:
        wn = word.lower()
        if wn in self.word2idx:
            self.meta[wn].usage_count += 1
            self.meta[wn].last_used = time.time()
            return self.word2idx[wn]
        if self.next_idx >= self.cur_size:
            if not self._expand(min(self.cur_size + VOCAB_EXPANSION_STEP, self.max_size)):
                return 0
        idx = self.next_idx
        self.word2idx[wn] = idx
        self.idx2word[idx] = wn
        self.meta[wn] = WordMeta(word=wn, usage_count=1)
        self.next_idx += 1
        return idx

    def get_embedding(self, word: str) -> np.ndarray:
        return self.embeddings[self.add_word(word)].copy()

    def encode(self, text: str) -> np.ndarray:
        words = re.findall(r'\b\w+\b', text.lower())
        if not words:
            return np.zeros(self.dim)
        embs = [self.get_embedding(w) for w in words if len(w) > 2]
        return np.mean(embs, axis=0) if embs else np.zeros(self.dim)

    def update_embedding(self, word: str, grad: np.ndarray, lr: float):
        wn = word.lower()
        if wn not in self.word2idx:
            return
        idx = self.word2idx[wn]
        self.t += 1
        b1, b2, eps = 0.9, 0.999, 1e-8
        self.m[idx] = b1 * self.m[idx] + (1 - b1) * grad
        self.v[idx] = b2 * self.v[idx] + (1 - b2) * (grad ** 2)
        mh = self.m[idx] / (1 - b1 ** self.t)
        vh = self.v[idx] / (1 - b2 ** self.t)
        self.embeddings[idx] -= lr * mh / (np.sqrt(vh) + eps)

    def update_quality(self, word: str, quality: float):
        wn = word.lower()
        if wn in self.meta:
            self.meta[wn].quality = self.meta[wn].quality * 0.85 + quality * 0.15

    def stats(self) -> Dict:
        avg_q = np.mean([m.quality for m in self.meta.values()]) if self.meta else 0.0
        return {'size': self.next_idx, 'capacity': self.cur_size, 'avg_quality': round(float(avg_q), 3)}


# ==================================================================
# 🧬 Динамическая нейросеть
# ==================================================================
class DynamicNeuralNet:
    def __init__(self, input_dim: int, hidden: int, output: int):
        self.input_dim = input_dim
        self.hidden = hidden
        self.output = output
        self.max_hidden = MAX_HIDDEN
        self._init_weights()
        self.loss_history = deque(maxlen=20)
        self.neuron_activations = np.zeros(hidden)
        self.total_updates = 0
        self.expansions = 0
        self.prunings = 0
        self.cache = {}

    def _init_weights(self):
        s1 = np.sqrt(2.0 / self.input_dim)
        s2 = np.sqrt(2.0 / self.hidden)
        self.W1 = np.random.randn(self.input_dim, self.hidden) * s1
        self.b1 = np.zeros(self.hidden)
        self.W2 = np.random.randn(self.hidden, self.output) * s2
        self.b2 = np.zeros(self.output)
        for n in ['W1', 'b1', 'W2', 'b2']:
            p = getattr(self, n)
            setattr(self, f'm{n}', np.zeros_like(p))
            setattr(self, f'v{n}', np.zeros_like(p))
        self.t = 0

    @staticmethod
    def relu(x):
        return np.maximum(0, x)

    @staticmethod
    def relu_d(x):
        return (x > 0).astype(float)

    @staticmethod
    def sigmoid(x):
        return 1 / (1 + np.exp(-np.clip(x, -500, 500)))

    def forward(self, x: np.ndarray, store: bool = True) -> np.ndarray:
        if x.shape[0] != self.input_dim:
            x = np.pad(x, (0, max(0, self.input_dim - x.shape[0])))[:self.input_dim]
        z1 = x @ self.W1 + self.b1
        a1 = self.relu(z1)
        z2 = a1 @ self.W2 + self.b2
        a2 = self.sigmoid(z2)
        if store:
            self.cache = {'x': x, 'z1': z1, 'a1': a1, 'a2': a2}
            self.neuron_activations += (a1 > 0).astype(float)
        return a2

    def backward(self, target: np.ndarray, lr: float) -> float:
        c = self.cache
        if not c:
            return 0.0
        x, z1, a1, a2 = c['x'], c['z1'], c['a1'], c['a2']
        loss = float(np.mean((a2 - target) ** 2))
        dz2 = 2 * (a2 - target) * a2 * (1 - a2)
        dW2 = a1[:, None] @ dz2[None, :]
        da1 = dz2 @ self.W2.T
        dz1 = da1 * self.relu_d(z1)
        dW1 = x[:, None] @ dz1[None, :]
        for n, g in [('W1', dW1), ('b1', dz1), ('W2', dW2), ('b2', dz2)]:
            self._adam(n, g, lr)
        self.loss_history.append(loss)
        self.total_updates += 1
        if self.total_updates > 50 and self.total_updates % 20 == 0:
            self._check_plateau()
        if self.total_updates % 100 == 0:
            self._prune()
        return loss

    def _adam(self, param, grad, lr):
        b1, b2, eps = 0.9, 0.999, 1e-8
        self.t += 1
        m = getattr(self, f'm{param}')
        v = getattr(self, f'v{param}')
        m = b1 * m + (1 - b1) * grad
        v = b2 * v + (1 - b2) * (grad ** 2)
        mh = m / (1 - b1 ** self.t)
        vh = v / (1 - b2 ** self.t)
        p = getattr(self, param)
        setattr(self, param, p - lr * mh / (np.sqrt(vh) + eps))
        setattr(self, f'm{param}', m)
        setattr(self, f'v{param}', v)

    def _check_plateau(self):
        if len(self.loss_history) < 20:
            return
        lh = list(self.loss_history)
        if np.mean(lh[10:]) - np.mean(lh[:10]) < 1e-4 and self.hidden < self.max_hidden:
            self._expand()

    def _expand(self):
        add = 16
        new_h = min(self.hidden + add, self.max_hidden)
        if new_h == self.hidden:
            return
        add = new_h - self.hidden
        s1 = np.sqrt(2.0 / self.input_dim)
        s2 = np.sqrt(2.0 / new_h)
        self.W1 = np.hstack([self.W1, np.random.randn(self.input_dim, add) * s1])
        self.b1 = np.concatenate([self.b1, np.zeros(add)])
        self.W2 = np.vstack([self.W2, np.random.randn(add, self.output) * s2])
        for m in ['mW1', 'vW1']:
            setattr(self, m, np.hstack([getattr(self, m), np.zeros((self.input_dim, add))]))
        for m in ['mb1', 'vb1']:
            setattr(self, m, np.concatenate([getattr(self, m), np.zeros(add)]))
        for m in ['mW2', 'vW2']:
            setattr(self, m, np.vstack([getattr(self, m), np.zeros((add, self.output))]))
        self.neuron_activations = np.concatenate([self.neuron_activations, np.zeros(add)])
        self.hidden = new_h
        self.expansions += 1
        logger.info(f"🧬 Neural expanded → {self.hidden}")

    def _prune(self):
        if self.total_updates < 100:
            return
        ratio = self.neuron_activations / (self.total_updates + 1e-8)
        inactive = ratio < 0.01
        if not inactive.any():
            return
        active = ~inactive
        self.W1 = self.W1[:, active]
        self.b1 = self.b1[active]
        self.W2 = self.W2[active, :]
        for n in ['mW1', 'vW1']:
            setattr(self, n, getattr(self, n)[:, active])
        for n in ['mb1', 'vb1']:
            setattr(self, n, getattr(self, n)[active])
        for n in ['mW2', 'vW2']:
            setattr(self, n, getattr(self, n)[active, :])
        self.neuron_activations = self.neuron_activations[active]
        self.hidden = int(active.sum())
        self.prunings += 1

    def stats(self) -> Dict:
        return {
            'arch': f"{self.input_dim}→{self.hidden}→{self.output}",
            'updates': self.total_updates,
            'expansions': self.expansions,
            'prunings': self.prunings,
            'loss_avg': round(np.mean(self.loss_history) if self.loss_history else 0, 5)
        }


# ==================================================================
# 🧠 Память
# ==================================================================
@dataclass
class Episode:
    content: str
    timestamp: float
    embedding: np.ndarray
    importance: float = 0.5
    emotional_valence: float = 0.0
    arousal: float = 0.0
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)

    def decay(self):
        age_h = (time.time() - self.timestamp) / 3600
        self.importance *= math.exp(-FORGETTING_FACTOR * age_h / 24)

    def strengthen(self):
        self.importance = min(1.0, self.importance + 0.05)
        self.access_count += 1
        self.last_accessed = time.time()

@dataclass
class Concept:
    name: str
    definition: str
    embedding: np.ndarray
    confidence: float = 0.5

class VectorMemory:
    def __init__(self, dim: int):
        self.dim = dim
        self.items = []
        self._mat = None
        self._dirty = True

    def add(self, item):
        self.items.append(item)
        self._dirty = True

    def _rebuild(self):
        self._mat = np.vstack([i.embedding for i in self.items]) if self.items else np.zeros((0, self.dim))
        self._dirty = False

    def search(self, q: np.ndarray, top_k: int = 5) -> List[Tuple]:
        if self._dirty:
            self._rebuild()
        if not self.items:
            return []
        qn = q / (np.linalg.norm(q) + 1e-8)
        norms = np.linalg.norm(self._mat, axis=1, keepdims=True)
        norms[norms == 0] = 1e-8
        sim = (self._mat / norms) @ qn
        idx = np.argsort(sim)[::-1][:top_k]
        return [(self.items[i], float(sim[i])) for i in idx if sim[i] > 0.25]

    def consolidate(self, threshold: float = 0.7):
        before = len(self.items)
        self.items = [i for i in self.items if i.importance >= threshold]
        if len(self.items) < before:
            self._dirty = True

class CognitiveMemory:
    def __init__(self, embed_func):
        self.embed = embed_func
        self.episodic = VectorMemory(EMBEDDING_DIM)
        self.semantic = VectorMemory(EMBEDDING_DIM)
        self.working = deque(maxlen=WORKING_MEMORY_SIZE)
        self.total_searches = 0

    def add_episode(self, content, importance=0.5, emotional_valence=0.0, arousal=0.0):
        emb = self.embed(content)
        self.episodic.add(Episode(content=content, timestamp=time.time(), embedding=emb,
                                  importance=importance, emotional_valence=emotional_valence,
                                  arousal=arousal))
        self.working.append(content)

    def recall(self, query, top_k=5):
        self.total_searches += 1
        return self.episodic.search(self.embed(query), top_k)

    def get_context(self, query) -> str:
        parts = []
        if self.working:
            parts.append("=== Недавние сообщения ===")
            parts.extend(list(self.working)[-3:])
        eps = self.recall(query)
        if eps:
            parts.append("\n=== Похожие воспоминания ===")
            for ep, score in eps[:3]:
                parts.append(f"[{score:.2f}] {ep.content[:200]}")
        return "\n".join(parts)

    def consolidate(self):
        for ep in self.episodic.items:
            ep.decay()
        self.episodic.consolidate(MEMORY_CONSOLIDATION_THRESHOLD)

    def stats(self) -> Dict:
        return {
            'episodes': len(self.episodic.items),
            'concepts': len(self.semantic.items),
            'working': len(self.working),
            'searches': self.total_searches
        }

    def save(self, path: Path):
        def ep_dict(e):
            d = asdict(e)
            d['embedding'] = e.embedding.tolist()
            return d
        state = {
            'episodic': [ep_dict(e) for e in self.episodic.items],
            'semantic': [{'name': c.name, 'definition': c.definition,
                          'embedding': c.embedding.tolist(), 'confidence': c.confidence}
                         for c in self.semantic.items],
            'working': list(self.working)
        }
        with gzip.open(path, 'wb') as f:
            pickle.dump(state, f)

    def load(self, path: Path):
        if not path.exists():
            return
        with gzip.open(path, 'rb') as f:
            state = pickle.load(f)
        for d in state.get('episodic', []):
            d['embedding'] = np.array(d['embedding'])
            self.episodic.add(Episode(**d))
        for d in state.get('semantic', []):
            d['embedding'] = np.array(d['embedding'])
            self.semantic.add(Concept(**d))
        self.working.extend(state.get('working', []))


# ==================================================================
# 🤖 Основной ассистент (исправлен: загрузка нескольких страниц)
# ==================================================================
class SelfImprovingAssistant:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.vocab = DynamicVocab()
        self.neural = DynamicNeuralNet(EMBEDDING_DIM, INITIAL_HIDDEN, OUTPUT_METRICS_DIM)
        self.memory = CognitiveMemory(self.vocab.encode)
        self.cache: Dict[str, Tuple[str, float]] = {}
        self.image_cache: Dict[str, Tuple[str, float]] = {}
        self.user_dir = MEMORY_BASE_DIR / user_id
        self.user_dir.mkdir(exist_ok=True)
        self.neural_path = self.user_dir / 'neural.pkl.gz'
        self.memory_path = self.user_dir / 'memory.pkl.gz'
        self.cache_path = self.user_dir / 'cache.pkl.gz'
        self.image_cache_path = self.user_dir / 'image_cache.pkl.gz'
        self._load()
        self.current_lr = LEARNING_RATE
        self.total_interactions = 0
        self.successful_learnings = 0
        # внутри __init__, после других инициализаций
        self.image_generation_cache: Dict[str, Tuple[str, float]] = {}
        self.image_gen_cache_path = self.user_dir / 'image_gen_cache.pkl.gz'
        self._load_image_gen_cache()
        self._agent = None  # lazy init

    @property
    def agent(self):
        if self._agent is None :
            from agent_core import AutonomousAgent
            self._agent = AutonomousAgent(self)
        return self._agent

    def _load(self):
        if self.neural_path.exists():
            try:
                with gzip.open(self.neural_path, 'rb') as f:
                    s = pickle.load(f)
                self.vocab.embeddings = s['emb']
                self.vocab.word2idx = s['w2i']
                self.vocab.idx2word = s['i2w']
                self.vocab.meta = {w: WordMeta(**d) for w, d in s.get('meta', {}).items()}
                self.vocab.next_idx = s['next_idx']
                self.vocab.cur_size = s['cur_size']
                self.neural.W1 = s['W1']
                self.neural.b1 = s['b1']
                self.neural.W2 = s['W2']
                self.neural.b2 = s['b2']
                self.neural.hidden = s['hidden']
                self.neural.total_updates = s.get('updates', 0)
                self.neural.expansions = s.get('expansions', 0)
                self.neural.prunings = s.get('prunings', 0)
                self.total_interactions = s.get('total', 0)
                self.successful_learnings = s.get('learned', 0)
                self.current_lr = s.get('lr', LEARNING_RATE)
                logger.info(f"✅ Loaded for {self.user_id}")
            except Exception as e:
                logger.error(f"Load failed: {e}")
        self.memory.load(self.memory_path)
        for path, cache_attr in [(self.cache_path, 'cache'), (self.image_cache_path, 'image_cache')]:
            if path.exists():
                try:
                    with gzip.open(path, 'rb') as f:
                        data = pickle.load(f)
                    now = time.time()
                    setattr(self, cache_attr, {k: (v, ts) for k, (v, ts) in data.items() if now - ts < 3600})
                except Exception:
                    pass

        # ── Обогащаем новый ассистент глобальными знаниями ──────────
        try:
            gkb = GlobalKnowledgeBase.get_instance()
            gkb.apply_global_vocab_to_local(self, alpha=GLOBAL_BLEND_ALPHA)
            gkb.apply_global_to_local(self, alpha=GLOBAL_BLEND_ALPHA)
            logger.info(f"🌍 Global knowledge applied to {self.user_id[:8]}")
        except Exception as e:
            logger.warning(f"Global KB apply on load failed: {e}")

    def _save(self):
        state = {
            'emb': self.vocab.embeddings,
            'w2i': self.vocab.word2idx,
            'i2w': self.vocab.idx2word,
            'meta': {w: asdict(m) for w, m in self.vocab.meta.items()},
            'next_idx': self.vocab.next_idx,
            'cur_size': self.vocab.cur_size,
            'W1': self.neural.W1,
            'b1': self.neural.b1,
            'W2': self.neural.W2,
            'b2': self.neural.b2,
            'hidden': self.neural.hidden,
            'updates': self.neural.total_updates,
            'expansions': self.neural.expansions,
            'prunings': self.neural.prunings,
            'total': self.total_interactions,
            'learned': self.successful_learnings,
            'lr': self.current_lr,
        }
        with gzip.open(self.neural_path, 'wb') as f:
            pickle.dump(state, f)
        self.memory.save(self.memory_path)
        for path, attr in [(self.cache_path, 'cache'), (self.image_cache_path, 'image_cache')]:
            with gzip.open(path, 'wb') as f:
                pickle.dump(getattr(self, attr), f)
        self._save_image_gen_cache()

    def _cache_key(self, message, image_base64=None):
        if image_base64:
            img_hash = hashlib.md5(image_base64.encode()).hexdigest()[:16]
            return hashlib.md5(f"{message}|{img_hash}".encode()).hexdigest()
        return hashlib.md5(message.encode()).hexdigest()

    def _adapt_lr(self):
        if len(self.neural.loss_history) > 10:
            lh = list(self.neural.loss_history)
            trend = np.mean(lh[-5:]) - np.mean(lh[:5])
            if trend < -0.01:
                self.current_lr = min(MAX_LR, self.current_lr * (1 + LR_ADAPT_RATE))
            elif trend > 0.01:
                self.current_lr = max(MIN_LR, self.current_lr * (1 - LR_ADAPT_RATE))

    def _build_system_prompt(self, reasoning: bool, has_web: bool, query_type: str = 'none') -> str:
        prompt = (
            "Ты — самообучающийся AI-ассистент с долговременной памятью и доступом к интернету.\n"
            "Если передано изображение — внимательно опиши его и ответь на вопросы.\n"
            "Отвечай естественно, полезно и по существу на языке пользователя."
        )
        if has_web:
            prompt += (
                "\n\n⚠️ ПРАВИЛА РАБОТЫ С ДАННЫМИ ИЗ ИНТЕРНЕТА:\n"
                "1. Используй ТОЛЬКО данные из блока «РЕЗУЛЬТАТЫ» ниже — не домысливай.\n"
                "2. Если данные есть — процитируй конкретные цифры/факты и укажи источник.\n"
                "3. Если данных НЕТ или блок содержит сообщение об ошибке поиска — "
                "   ЧЕСТНО сообщи: «Не удалось получить актуальные данные. "
                "   Проверьте на [конкретный сайт].» НЕ придумывай цифры.\n"
                "4. Для курсов валют — источник ЦБ РФ является официальным и актуальным.\n"
                "5. Никогда не выдавай устаревшие данные из обучения как актуальные."
            )
        if query_type in ('currency', 'news', 'weather'):
            prompt += (
                "\n\n🕐 Это запрос о РЕАЛЬНОМ ВРЕМЕНИ (курсы/новости/погода). "
                "Если в результатах поиска нет данных — скажи об этом явно."
            )
        if reasoning:
            prompt += (
                "\n\n🔍 РЕЖИМ РАССУЖДЕНИЙ:\n"
                "Перед ответом покажи цепочку мыслей:\n\n"
                "💭 РАССУЖДЕНИЕ:\n1. ...\n2. ...\n\n---\n\nЗатем дай ответ."
            )
        else:
            prompt += "\nОтвечай кратко и по делу."
        return prompt

    async def _do_web_search(self, message: str, force: bool = False,
                              url_to_fetch: Optional[str] = None) -> Tuple[Optional[str], str, List[Dict]]:
        """
        Выполняет поиск и при необходимости загружает несколько страниц.
        Возвращает (контекст_для_LLM, тип_запроса, список_результатов_для_источников)
        """
        if url_to_fetch:
            content = await WebSearchTool.fetch_url(url_to_fetch)
            ctx = f"=== СОДЕРЖИМОЕ СТРАНИЦЫ ({url_to_fetch}) ===\n{content}"
            return ctx, 'url', [{'title': url_to_fetch, 'url': url_to_fetch}]

        url_in_msg = re.search(r'https?://[^\s]+', message)
        if url_in_msg:
            url = url_in_msg.group(0)
            content = await WebSearchTool.fetch_url(url)
            ctx = f"=== СОДЕРЖИМОЕ СТРАНИЦЫ ({url}) ===\n{content}"
            return ctx, 'url', [{'title': url, 'url': url}]

        query_type, clean_query = WebSearchTool.classify_query(message)
        if not force and query_type == 'none':
            return None, 'none', []

        cache_key = f"{query_type}:{clean_query}"
        now = time.time()
        if cache_key in _search_cache:
            cached_ctx, cached_ts = _search_cache[cache_key]
            if now - cached_ts < SEARCH_CACHE_TTL:
                logger.debug(f"Using cached search for {cache_key}")
                return cached_ctx, query_type, []

        # 1. Получаем результаты поиска (сниппеты)
        results, special_data = await WebSearchTool.search(clean_query, query_type)

        # 2. Загружаем полное содержимое нескольких страниц
        full_pages = ""
        if results:
            full_pages = await WebSearchTool.fetch_multiple_pages(results, limit=MAX_PAGES_TO_FETCH)

        # 3. Формируем итоговый контекст
        web_ctx = WebSearchTool.format_for_prompt(results, special_data, full_pages, message)

        _search_cache[cache_key] = (web_ctx, now)
        if len(_search_cache) > 100:
            for k in list(_search_cache.keys()):
                if now - _search_cache[k][1] > SEARCH_CACHE_TTL:
                    del _search_cache[k]

        return web_ctx, query_type, results

    async def get_response(self, message: str,
                           image_base64: Optional[str] = None,
                           image_mime: Optional[str] = None,
                           reasoning: bool = False,
                           web_search: bool = False,
                           url_to_fetch: Optional[str] = None) -> Tuple[str, Dict]:
        start = time.time()
        self.total_interactions += 1

        # web_search теперь — единый флаг интернета (вкл/выкл)
        should_search = web_search
        web_ctx, query_type, raw_results = await self._do_web_search(
            message, force=should_search, url_to_fetch=url_to_fetch)
        has_web = web_ctx is not None

        if not has_web and not should_search:
            ck = self._cache_key(message, image_base64)
            store = self.image_cache if image_base64 else self.cache
            if ck in store:
                cached, _ = store[ck]
                return cached, {'cached': True, 'response_time': time.time() - start}

        content_parts = []
        if message.strip():
            txt = message.strip()
            if web_ctx:
                txt += f"\n\n{web_ctx}"
            ctx = self.memory.get_context(message)
            if ctx:
                txt += f"\n\n{ctx}"
            content_parts.append({"type": "text", "text": txt})

        if image_base64 and image_mime and len(image_base64) <= MAX_IMAGE_SIZE_BASE64:
            content_parts.append({"type": "image_url",
                                   "image_url": {"url": f"data:{image_mime};base64,{image_base64}"}})
        if not content_parts:
            return "Нет данных для ответа.", {"error": "no content"}

        emb = self.vocab.encode(f"{message}\n{self.memory.get_context(message)}")
        try:
            preds = self.neural.forward(emb, store=False)
        except:
            preds = np.zeros(OUTPUT_METRICS_DIM) + 0.5

        messages_llm = [
            {"role": "system", "content": self._build_system_prompt(reasoning, has_web, query_type)},
            {"role": "user", "content": content_parts}
        ]
        response = await self._call_llm(messages_llm)
        if not response:
            response = "⚠️ Не удалось получить ответ от модели."

        quality = min(1.0, len(response) / 300)
        if any(w in response.lower() for w in ['ошибка', 'извините', 'не удалось']):
            quality *= 0.7

        actual = np.array([
            np.clip(quality + np.random.normal(0, 0.05), 0, 1),
            min(1.0, len(message.split()) / 20), quality,
            min(1.0, quality + 0.1), quality,
            min(1.0, len(response.split()) / 30),
            0.5 + np.random.normal(0, 0.08), 0.5 + np.random.normal(0, 0.08),
        ]).clip(0, 1)

        loss = 0.0
        if quality >= MIN_QUALITY_SCORE:
            try:
                self.neural.forward(emb, store=True)
                loss = self.neural.backward(actual, self.current_lr)
                self.successful_learnings += 1
                self._adapt_lr()
                for word in re.findall(r'\b\w+\b', message.lower()):
                    if len(word) > 3:
                        grad = (preds - actual).mean() * self.vocab.get_embedding(word) * 0.01
                        self.vocab.update_embedding(word, grad, self.current_lr)
                        self.vocab.update_quality(word, quality)
            except Exception as e:
                logger.error(f"Learning failed: {e}")

        if quality > 0.4:
            self.memory.add_episode(f"Q: {message}\nA: {response}", importance=quality,
                                    emotional_valence=(quality - 0.5) * 2,
                                    arousal=min(1.0, len(message.split()) / 15))
            if quality > 0.7 and not has_web:
                ck = self._cache_key(message, image_base64)
                store = self.image_cache if image_base64 else self.cache
                store[ck] = (response, time.time())
                if len(store) > 100:
                    oldest = min(store.items(), key=lambda x: x[1][1])[0]
                    del store[oldest]

        if self.total_interactions % SAVE_EVERY_N_INTERACTIONS == 0:
            self.memory.consolidate()
            self._save()

        # ── Вклад в глобальную базу знаний (анонимно) ────────────────
        if quality >= MIN_GLOBAL_QUALITY and not has_web:
            try:
                emb_contrib = self.vocab.encode(message + " " + response)
                asyncio.create_task(
                    GlobalKnowledgeBase.get_instance().contribute(
                        user_id   = self.user_id,
                        content   = "Q: " + message + "\nA: " + response,
                        embedding = emb_contrib,
                        importance= quality,
                        assistant = self,
                    )
                )
            except Exception as e:
                logger.debug(f"Global contribute failed: {e}")

        return response, {
            'quality': round(quality, 3), 'loss': loss,
            'response_time': time.time() - start,
            'memory_episodes': len(self.memory.episodic.items),
            'web_search_used': has_web, 'query_type': query_type,
        }

    async def _call_llm(self, messages: List[Dict]) -> str:
        payload = {"messages": messages, "temperature": 0.75, "max_tokens": 2500, "stream": False}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LM_STUDIO_API_KEY}"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(LM_STUDIO_URL, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=LM_STUDIO_TIMEOUT)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        try:
                            return data['choices'][0]['message']['content'].strip()
                        except:
                            return data.get('choices', [{}])[0].get('text', '') or data.get('response', '').strip()
                    else:
                        logger.error(f"LM Studio HTTP {resp.status}: {(await resp.text())[:200]}")
                        return ""
        except asyncio.TimeoutError:
            return "⏱️ Превышено время ожидания."
        except:
            logger.exception("LM Studio call failed")
            return ""

    async def stream_response(self, message: str,
                              image_base64: Optional[str] = None,
                              image_mime: Optional[str] = None,
                              reasoning: bool = False,
                              web_search: bool = False,
                              url_to_fetch: Optional[str] = None):
        self.total_interactions += 1

        should_search = web_search   # теперь интернет включается этой кнопкой

        query_type_hint, _ = WebSearchTool.classify_query(message)
        if should_search:
            status_msg = {
                'url': f'🔗 Загружаю страницу…',
                'currency': '💱 Запрашиваю курсы валют…',
                'weather': '🌤 Ищу погоду…',
                'news': '📰 Ищу новости…',
                'general': '🔍 Ищу в интернете…',
            }.get(query_type_hint, '🔍 Ищу в интернете…')
            yield f"data: {json.dumps({'status': 'searching', 'text': status_msg})}\n\n"

        web_ctx, query_type, raw_results = await self._do_web_search(
            message, force=should_search, url_to_fetch=url_to_fetch)
        has_web = web_ctx is not None

        if has_web:
            yield f"data: {json.dumps({'status': 'search_done', 'query_type': query_type})}\n\n"
            if raw_results and len(raw_results) > 0:
                # Сообщаем фронту источники для отображения
                sources_for_front = [{'title': r.get('title', ''), 'url': r.get('url', '')}
                                     for r in raw_results if r.get('url')]
                if sources_for_front:
                    yield f"data: {json.dumps({'sources': sources_for_front})}\n\n"
            # Если есть загруженные страницы, отправляем статус
            yield f"data: {json.dumps({'status': 'fetching_pages', 'count': MAX_PAGES_TO_FETCH})}\n\n"

        content_parts = []
        if message.strip():
            txt = message.strip()
            if web_ctx:
                txt += f"\n\n{web_ctx}"
            ctx = self.memory.get_context(message)
            if ctx:
                txt += f"\n\n{ctx}"
            content_parts.append({"type": "text", "text": txt})

        if image_base64 and image_mime and len(image_base64) <= MAX_IMAGE_SIZE_BASE64:
            content_parts.append({"type": "image_url",
                                   "image_url": {"url": f"data:{image_mime};base64,{image_base64}"}})

        emb = self.vocab.encode(message)
        preds = self.neural.forward(emb, store=False)

        messages_llm = [
            {"role": "system", "content": self._build_system_prompt(reasoning, has_web, query_type)},
            {"role": "user", "content": content_parts}
        ]
        payload = {"messages": messages_llm, "temperature": 0.75, "max_tokens": 2500, "stream": True}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LM_STUDIO_API_KEY}"}

        full_response = ""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(LM_STUDIO_URL, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=LM_STUDIO_STREAM_TIMEOUT)) as resp:
                    if resp.status != 200:
                        yield f"data: {json.dumps({'error': 'AI service unavailable'})}\n\n"
                        return
                    buffer = ""
                    async for chunk in resp.content.iter_any():
                        if not chunk:
                            continue
                        buffer += chunk.decode('utf-8', errors='ignore')
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                token = None
                                if 'choices' in data and data['choices']:
                                    delta = data['choices'][0].get('delta', {})
                                    token = delta.get('content', '')
                                if token:
                                    full_response += token
                                    yield f"data: {json.dumps({'token': token})}\n\n"
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.error(f"Streaming failed: {e}")
            yield f"data: {json.dumps({'token': '❌ Ошибка связи с AI-сервером.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        if full_response:
            quality = min(1.0, len(full_response) / 300)
            if any(w in full_response.lower() for w in ['ошибка', 'извините', 'не удалось']):
                quality *= 0.7
            actual = np.array([
                np.clip(quality + np.random.normal(0, 0.05), 0, 1),
                min(1.0, len(message.split()) / 20), quality,
                min(1.0, quality + 0.1), quality,
                min(1.0, len(full_response.split()) / 30),
                0.5 + np.random.normal(0, 0.08), 0.5 + np.random.normal(0, 0.08),
            ]).clip(0, 1)
            if quality >= MIN_QUALITY_SCORE:
                try:
                    self.neural.forward(emb, store=True)
                    self.neural.backward(actual, self.current_lr)
                    self.successful_learnings += 1
                    self._adapt_lr()
                except Exception as e:
                    logger.error(f"Post-stream learning: {e}")
            if quality > 0.4:
                self.memory.add_episode(f"Q: {message}\nA: {full_response}", importance=quality,
                                        emotional_valence=(quality - 0.5) * 2,
                                        arousal=min(1.0, len(message.split()) / 15))
            if self.total_interactions % SAVE_EVERY_N_INTERACTIONS == 0:
                self.memory.consolidate()
                self._save()

            # ── Вклад в глобальную базу знаний (анонимно) ────────────
            if quality >= MIN_GLOBAL_QUALITY and not has_web:
                try:
                    emb_contrib = self.vocab.encode(f"{message}\n{full_response}")
                    asyncio.create_task(
                        GlobalKnowledgeBase.get_instance().contribute(
                            user_id   = self.user_id,
                            content   = "Q: " + message + "\nA: " + full_response,
                            embedding = emb_contrib,
                            importance= quality,
                            assistant = self,
                        )
                    )
                except Exception as e:
                    logger.debug(f"Global contribute (stream) failed: {e}")

        yield "data: [DONE]\n\n"

    @property
    def research_agent(self):
        if not hasattr(self, '_research_agent'):
            try:
                from agent_core import ResearchAgent
                self._research_agent = ResearchAgent(self)
            except Exception as e:
                logger.error(f"Failed to create ResearchAgent: {e}", exc_info=True)
                return None
        return self._research_agent


    def _load_image_gen_cache(self):
        if self.image_gen_cache_path.exists():
            try:
                with gzip.open(self.image_gen_cache_path, 'rb') as f:
                    data = pickle.load(f)
                now = time.time()
                self.image_generation_cache = {k: (v, ts) for k, (v, ts) in data.items() if now - ts < 3600}
            except Exception as e:
                logger.warning(f"Failed to load image gen cache: {e}")

    def _save_image_gen_cache(self):
        try:
            with gzip.open(self.image_gen_cache_path, 'wb') as f:
                pickle.dump(self.image_generation_cache, f)
        except Exception as e:
            logger.error(f"Failed to save image gen cache: {e}")


# ==================================================================
# 🌐 FastAPI роутер
# ==================================================================
router = APIRouter(prefix='/ai', tags=['ai'])
_assistants: Dict[str, SelfImprovingAssistant] = {}
_assistants_lock = asyncio.Lock()

async def get_assistant(user_id: str) -> SelfImprovingAssistant:
    async with _assistants_lock:
        if user_id not in _assistants:
            _assistants[user_id] = SelfImprovingAssistant(user_id)
        return _assistants[user_id]




class AIRequest(BaseModel):
    message: str = Field(..., description="Текстовый запрос пользователя")
    image_base64: Optional[str] = Field(None)
    image_mime: Optional[str] = Field(None)
    stream: bool = Field(True)
    reasoning: bool = Field(False)
    web_search: bool = Field(False, description="Включить интернет-поиск и загрузку страниц")
    url_to_fetch: Optional[str] = Field(None, description="Конкретный URL для загрузки")

@router.post("/chat")
async def chat_with_ai(body: AIRequest, address: str = Depends(require_auth)):
    assistant = await get_assistant(address)
    if body.stream:
        return StreamingResponse(
            assistant.stream_response(
                message=body.message, image_base64=body.image_base64,
                image_mime=body.image_mime, reasoning=body.reasoning,
                web_search=body.web_search, url_to_fetch=body.url_to_fetch,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache,no-store,must-revalidate",
                "X-Accel-Buffering": "no",
                "Content-Encoding": "identity",  # запрещаем сжатие
            }
        )
    response, meta = await assistant.get_response(
        message=body.message, image_base64=body.image_base64,
        image_mime=body.image_mime, reasoning=body.reasoning,
        web_search=body.web_search, url_to_fetch=body.url_to_fetch,
    )
    return {"reply": response, "meta": meta}

@router.post("/search")
async def direct_search(body: dict, address: str = Depends(require_auth)):
    query = body.get("query", "").strip()
    url = body.get("url", "").strip()
    if url:
        content = await WebSearchTool.fetch_url(url)
        return {"type": "url", "url": url, "content": content}
    if not query:
        return {"error": "query or url required"}
    query_type, _ = WebSearchTool.classify_query(query)
    results, special = await WebSearchTool.search(query, query_type)
    pages = await WebSearchTool.fetch_multiple_pages(results, limit=MAX_PAGES_TO_FETCH) if results else ""
    return {"type": "search", "query": query, "query_type": query_type,
            "results": results, "special_data": special, "full_pages": pages}

@router.post("/classify")
async def classify_query_endpoint(body: dict, address: str = Depends(require_auth)):
    message = body.get("message", "").strip()
    if not message:
        return {"should_search": False, "query_type": "none"}
    query_type, _ = WebSearchTool.classify_query(message)
    should = WebSearchTool.should_auto_search(message)
    return {"should_search": should, "query_type": query_type}


@router.post("/generate_image")
async def generate_image(body: ImageGenRequest, address: str = Depends(require_auth)):
    if not EASYDIFFUSION_ENABLED:
        raise HTTPException(503, "Image generation is disabled on this server")

    api_url = f"{EASYDIFFUSION_URL}/render"
    payload = {
        "prompt": body.prompt,
        "negative_prompt": body.negative_prompt or "",
        "width": body.width,
        "height": body.height,
        "num_inference_steps": body.steps,
        "guidance_scale": body.cfg_scale,
        "sampler_name": "euler_a",
        "seed": body.seed if body.seed is not None else -1,
        "clip_skip": True,
        "use_stable_diffusion_model": "fallenleafNSFWXLPony_v0620steps",
        'use_lora_model': 'Realism Lora By Stable Yogi_V3_Lite',
        "use_vae_model": "",
    }
    headers = {"Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                api_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=EASYDIFFUSION_TIMEOUT)
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Easy Diffusion HTTP {resp.status}: {error_text[:200]}")
                    raise HTTPException(502, f"Image service error: {error_text[:100]}")

                # Читаем как текст, чтобы избежать проблем с лишними данными
                raw_text = await resp.text()
                logger.debug(f"Raw response: {raw_text[:500]}")

                # Пытаемся извлечь первый JSON-объект
                data = None
                decoder = json.JSONDecoder()
                try:
                    data, end_idx = decoder.raw_decode(raw_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}, raw: {raw_text[:200]}")
                    # Возможно, ответ в формате SSE: ищем строку "data: "
                    if raw_text.startswith("data: "):
                        json_part = raw_text[6:].strip()
                        data = json.loads(json_part)
                    else:
                        raise HTTPException(500, f"Invalid JSON response: {raw_text[:200]}")

                if not data or not isinstance(data, dict):
                    raise HTTPException(500, f"Invalid response format: {data}")

            # Если получили асинхронный ответ с queue и stream
            if "queue" in data and "stream" in data:
                stream_url = f"{EASYDIFFUSION_URL}{data['stream']}"
                task_id = data.get("task")
                logger.info(f"Task {task_id} queued, polling {stream_url}")

                start_time = time.time()
                while time.time() - start_time < EASYDIFFUSION_TIMEOUT:
                    await asyncio.sleep(1)
                    async with session.get(stream_url) as stream_resp:
                        if stream_resp.status != 200:
                            continue
                        stream_text = await stream_resp.text()
                        # Извлекаем JSON из потока (может быть несколько строк)
                        try:
                            stream_data = json.loads(stream_text)
                        except:
                            # Если это SSE, ищем "data: {"
                            if stream_text.startswith("data: "):
                                stream_text = stream_text[6:].strip()
                                stream_data = json.loads(stream_text)
                            else:
                                continue
                        output = stream_data.get("output")
                        if output and isinstance(output, list) and len(output) > 0 and "data" in output[0]:
                            return {"image_base64": output[0]["data"], "cached": False}
                raise HTTPException(504, "Timeout waiting for image generation")

            # Синхронный ответ
            output = data.get("output")
            if output and isinstance(output, list) and len(output) > 0 and "data" in output[0]:
                return {"image_base64": output[0]["data"], "cached": False}

            raise HTTPException(500, f"Unexpected response: {data}")

    except asyncio.TimeoutError:
        raise HTTPException(504, "Image generation timeout")
    except aiohttp.ClientError as e:
        logger.error(f"Easy Diffusion connection error: {e}")
        raise HTTPException(503, f"Cannot connect to Easy Diffusion at {EASYDIFFUSION_URL}")
    except Exception as e:
        logger.exception("Unexpected error in image generation")
        raise HTTPException(500, f"Generation failed: {str(e)}")


@router.post("/enhance_prompt")
async def enhance_prompt(body: dict, address: str = Depends(require_auth)):
    """
    Улучшает промт для генерации изображений.
    Принимает запрос пользователя на любом языке, возвращает детальный английский промт.
    """
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return {"enhanced": prompt}

    assistant = await get_assistant(address)

    system = (
        "You are an expert prompt engineer for Stable Diffusion. "
        "Your task: convert the user's request into a detailed, vivid, English prompt for image generation. "
        "Include subject, environment, lighting, colors, composition, mood, style (e.g., photorealistic, cinematic, oil painting, anime), "
        "and any specific details the user mentioned. "
        "Do NOT include technical parameters like steps, width, height, or CFG scale. "
        "Output ONLY the prompt text, nothing else. No quotes, no extra commentary."
    )

    user_msg = (
        f"User request: \"{prompt}\"\n"
        "Generate a rich, detailed English prompt for Stable Diffusion that captures all the key elements."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg}
    ]

    enhanced = await assistant._call_llm(messages)

    # Если не удалось получить качественный промт, пробуем хотя бы перевести
    if not enhanced or len(enhanced) < 5:
        fallback_msg = f"Translate the following into English, keep it detailed:\n{prompt}"
        messages_fb = [
            {"role": "system", "content": "You are a translator. Output only the English translation."},
            {"role": "user", "content": fallback_msg}
        ]
        enhanced = await assistant._call_llm(messages_fb)
        if not enhanced:
            enhanced = prompt

    # Очистка от возможных кавычек и лишних пробелов
    enhanced = enhanced.strip().strip('"').strip("'")
    return {"enhanced": enhanced}


# ==================================================================
# 📊 Endpoints глобальной базы знаний
# ==================================================================

@router.get("/global_stats")
async def global_knowledge_stats(address: str = Depends(require_auth)):
    gkb = GlobalKnowledgeBase.get_instance()
    assistant = await get_assistant(address)
    return {
        "global":          gkb.stats(),
        "my_episodes":     len(assistant.memory.episodic.items),
        "my_vocab_size":   assistant.vocab.next_idx,
        "my_interactions": assistant.total_interactions,
        "my_lr":           round(assistant.current_lr, 6),
        "neural_arch":     assistant.neural.stats(),
    }


@router.post("/force_merge")
async def force_global_merge(address: str = Depends(require_auth)):
    gkb = GlobalKnowledgeBase.get_instance()
    async with _assistants_lock:
        all_assistants = list(_assistants.values())
    if not all_assistants:
        return {"status": "no active assistants"}
    result = await gkb.merge_all(all_assistants)
    return {"status": "merged", **result}


@router.post("/apply_global")
async def apply_global_to_me(address: str = Depends(require_auth)):
    gkb       = GlobalKnowledgeBase.get_instance()
    assistant = await get_assistant(address)
    gkb.apply_global_to_local(assistant,       alpha=GLOBAL_BLEND_ALPHA)
    gkb.apply_global_vocab_to_local(assistant, alpha=GLOBAL_BLEND_ALPHA)
    return {
        "status":          "applied",
        "global_episodes": len(gkb._episodes),
        "global_vocab":    len(gkb._global_embeddings),
        "has_neural":      gkb._global_W1 is not None,
    }


# ── Агентные endpoints ─────────────────────────────────────────

class AgentRequest(BaseModel):
    goal: str = Field(..., description="Цель для автономного агента")


@router.post("/agent/run")
async def agent_run_goal(body: AgentRequest, address: str = Depends(require_auth)):
    """
    Запускает автономную агентную петлю для достижения цели.
    Использует ReAct (Reason + Act): планирует шаги, вызывает инструменты,
    синтезирует ответ.
    """
    assistant = await get_assistant(address)
    if not assistant.agent:
        raise HTTPException(501, "Агентный режим недоступен")
    result = await assistant.agent.run_goal(body.goal)
    return {"result": result, "agent_stats": assistant.agent.stats()}

@router.post("/research")
async def research_goal(body: AgentRequest, address: str = Depends(require_auth)):
    assistant = await get_assistant(address)
    if assistant.research_agent is None:      # ← БЕЗ СКОБОК, проверка на None
        raise HTTPException(501, "Research agent unavailable")
    result = await assistant.research_agent.research(body.goal)
    return result

@router.post("/agent/chat")
async def agent_chat(body: AIRequest, address: str = Depends(require_auth)):
    """
    Чат с агентным режимом.
    Простые запросы → стандартный ответ (без overhead).
    Сложные задачи → агентная петля с инструментами.
    """
    assistant = await get_assistant(address)
    if not assistant.agent:
        # Fallback на стандартный чат
        return await chat_with_ai(body, address)

    if body.stream:
        return StreamingResponse(
            assistant.agent.stream_with_agent(
                message=body.message,
                image_base64=body.image_base64,
                image_mime=body.image_mime,
                reasoning=body.reasoning,
                web_search=body.web_search,
                url_to_fetch=body.url_to_fetch,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache,no-store,must-revalidate",
                "X-Accel-Buffering": "no",
                "Content-Encoding": "identity",
            }
        )

    response, meta = await assistant.agent.chat(
        message=body.message,
        image_base64=body.image_base64,
        image_mime=body.image_mime,
        reasoning=body.reasoning,
        web_search=body.web_search,
        url_to_fetch=body.url_to_fetch,
    )
    return {"reply": response, "meta": meta}


@router.get("/agent/stats")
async def agent_stats(address: str = Depends(require_auth)):
    """Статистика агента: инструменты, цели, рефлексия, память."""
    assistant = await get_assistant(address)
    if not assistant.agent:
        return {"error": "Агентный режим недоступен"}
    return assistant.agent.stats()


@router.get("/agent/goals")
async def agent_goals(address: str = Depends(require_auth)):
    """Список авто-целей агента (сгенерированных из паттернов разговоров)."""
    assistant = await get_assistant(address)
    if not assistant.agent:
        return {"goals": []}
    pending = assistant.agent.goals.get_pending(10)
    return {
        "pending": [
            {
                "id": g.goal_id,
                "description": g.description,
                "priority": round(g.priority, 2),
                "source": g.source,
            }
            for g in pending
        ],
        "topic_stats": assistant.agent.goals.stats()["top_topics"],
    }


@router.post("/agent/goals/run_pending")
async def agent_run_pending_goals(address: str = Depends(require_auth)):
    """
    Запускает одну ожидающую авто-цель (наивысший приоритет).
    Можно вызывать периодически (cron / celery beat).
    """
    assistant = await get_assistant(address)
    if not assistant.agent:
        return {"status": "agent unavailable"}
    pending = assistant.agent.goals.get_pending(1)
    if not pending:
        return {"status": "no pending goals"}
    goal = pending[0]
    result = await assistant.agent.run_goal(goal.description)
    return {"goal": goal.description, "result": result[:500]}


@router.post("/agent/reflect")
async def agent_force_reflect(address: str = Depends(require_auth)):
    """Запускает немедленную рефлексию (анализ качества последних ответов)."""
    assistant = await get_assistant(address)
    if not assistant.agent:
        return {"error": "Агентный режим недоступен"}
    entry = await assistant.agent.reflect.reflect(
        assistant.total_interactions,
        assistant.agent._call_llm_direct,
    )
    if not entry:
        return {"status": "недостаточно данных для рефлексии"}
    return {
        "summary": entry.summary,
        "weak_points": entry.weak_points,
        "improvements": entry.improvements,
        "quality": entry.quality_score,
    }


@router.post("/agent/tools/register")
async def register_custom_tool(body: dict, address: str = Depends(require_auth)):
    """
    Регистрирует кастомный инструмент через URL-callback.
    body: {"name": "my_tool", "url": "https://...", "description": "..."}

    Агент будет POST-ить на этот URL с {"input": "..."} и ожидать {"output": "..."}.
    """
    assistant = await get_assistant(address)
    if not assistant.agent:
        return {"error": "Агентный режим недоступен"}

    name = body.get("name", "").strip()
    url = body.get("url", "").strip()
    desc = body.get("description", name)

    if not name or not url:
        raise HTTPException(400, "name и url обязательны")

    import aiohttp

    async def remote_tool(tool_input: str) -> str:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                    url,
                    json={"input": tool_input},
                    timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    return str(data.get("output", ""))
                return f"[Remote tool error: HTTP {r.status}]"

    assistant.agent.tools.register(name, remote_tool, desc)
    return {"status": "registered", "tool": name}


def _shutdown_all():
    try:
        gkb = GlobalKnowledgeBase.get_instance()
        import asyncio as _asyncio
        loop = _asyncio.new_event_loop()
        loop.run_until_complete(gkb.merge_all(list(_assistants.values())))
        loop.close()
        logger.info("Global merge on shutdown done")
    except Exception as e:
        logger.error(f"Shutdown merge failed: {e}")

    for uid, a in _assistants.items():
        try:
            a._save()
            logger.info(f"Saved {uid}")
        except Exception as e:
            logger.error(f"Save failed {uid}: {e}")

atexit.register(_shutdown_all)