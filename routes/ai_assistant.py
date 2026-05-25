"""
routes/ai_assistant.py — Самообучающийся AI-ассистент с памятью и нейросетью
Версия: 2.0 (на базе Ultimate AGI v36)
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
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dependencies import require_auth
import aiohttp

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/ai', tags=['ai'])

# ═══════════════════════════════════════════════════════════════
# 🔧 Конфигурация
# ═══════════════════════════════════════════════════════════════
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_STUDIO_API_KEY = "lm-studio"

MEMORY_BASE_DIR = Path("ai_memory_v2")
MEMORY_BASE_DIR.mkdir(exist_ok=True)

# Параметры нейросети
EMBEDDING_DIM = 128
INITIAL_HIDDEN = 48
MAX_HIDDEN = 512
OUTPUT_METRICS_DIM = 8
METRIC_NAMES = ['confidence', 'complexity', 'relevance', 'coherence',
                'engagement', 'completeness', 'creativity', 'empathy']

# Параметры обучения
LEARNING_RATE = 0.001
MIN_LR = 0.0001
MAX_LR = 0.01
LR_ADAPT_RATE = 0.05

# Параметры памяти
WORKING_MEMORY_SIZE = 15
MEMORY_CONSOLIDATION_THRESHOLD = 0.7
FORGETTING_FACTOR = 0.1

# LLM-оценка качества
QUALITY_CHECK_PROB = 0.3
MIN_QUALITY_SCORE = 0.4

# Словарь
INITIAL_VOCAB_SIZE = 2000
MAX_VOCAB_SIZE = 50000
VOCAB_EXPANSION_STEP = 1000
WORD_QUALITY_THRESHOLD = 0.3

# Сохранение
AUTO_SAVE_INTERVAL = 300   # 5 минут
BACKUP_RETENTION_DAYS = 30

# ═══════════════════════════════════════════════════════════════
# 🔤 Адаптивный словарь (обучаемые эмбеддинги)
# ═══════════════════════════════════════════════════════════════
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
        new_emb = np.random.randn(add, self.dim) * 0.01
        self.embeddings = np.vstack([self.embeddings, new_emb])
        self.m = np.vstack([self.m, np.zeros((add, self.dim))])
        self.v = np.vstack([self.v, np.zeros((add, self.dim))])
        self.cur_size = new_size
        logger.info(f"📈 Vocab expanded: {new_size}")
        return True

    def add_word(self, word: str, context: str = "") -> int:
        if word in self.word2idx:
            self.meta[word].usage_count += 1
            self.meta[word].last_used = time.time()
            return self.word2idx[word]

        if self.next_idx >= self.cur_size:
            new_sz = min(self.cur_size + VOCAB_EXPANSION_STEP, self.max_size)
            if not self._expand(new_sz):
                return 0

        idx = self.next_idx
        self.word2idx[word] = idx
        self.idx2word[idx] = word
        self.meta[word] = WordMeta(word=word, usage_count=1)
        self.next_idx += 1
        return idx

    def get_embedding(self, word: str) -> np.ndarray:
        if word not in self.word2idx:
            self.add_word(word)
        return self.embeddings[self.word2idx[word]].copy()

    def encode(self, text: str) -> np.ndarray:
        words = text.lower().split()
        if not words:
            return np.zeros(self.dim)
        embs = [self.get_embedding(w) for w in words if len(w) > 2]
        return np.mean(embs, axis=0) if embs else np.zeros(self.dim)

    def update_embedding(self, word: str, grad: np.ndarray, lr: float):
        if word not in self.word2idx:
            return
        idx = self.word2idx[word]
        self.t += 1
        b1, b2, eps = 0.9, 0.999, 1e-8
        self.m[idx] = b1 * self.m[idx] + (1 - b1) * grad
        self.v[idx] = b2 * self.v[idx] + (1 - b2) * (grad ** 2)
        mh = self.m[idx] / (1 - b1 ** self.t)
        vh = self.v[idx] / (1 - b2 ** self.t)
        self.embeddings[idx] -= lr * mh / (np.sqrt(vh) + eps)

    def update_quality(self, word: str, quality: float):
        if word in self.meta:
            m = self.meta[word]
            m.quality = m.quality * 0.85 + quality * 0.15

    def stats(self) -> Dict:
        avg_q = np.mean([m.quality for m in self.meta.values()]) if self.meta else 0
        return {
            'size': self.next_idx,
            'capacity': self.cur_size,
            'avg_quality': round(float(avg_q), 3),
        }


# ═══════════════════════════════════════════════════════════════
# 🧬 Динамическая нейросеть (Adam, expand/prune)
# ═══════════════════════════════════════════════════════════════
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

        self.mW1 = np.zeros_like(self.W1); self.vW1 = np.zeros_like(self.W1)
        self.mb1 = np.zeros_like(self.b1); self.vb1 = np.zeros_like(self.b1)
        self.mW2 = np.zeros_like(self.W2); self.vW2 = np.zeros_like(self.W2)
        self.mb2 = np.zeros_like(self.b2); self.vb2 = np.zeros_like(self.b2)
        self.t = 0

    @staticmethod
    def relu(x): return np.maximum(0, x)
    @staticmethod
    def relu_d(x): return (x > 0).astype(float)
    @staticmethod
    def sigmoid(x): return 1 / (1 + np.exp(-np.clip(x, -500, 500)))

    def forward(self, x: np.ndarray, store: bool = True) -> np.ndarray:
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
        x, z1, a1, a2 = c['x'], c['z1'], c['a1'], c['a2']
        loss = float(np.mean((a2 - target) ** 2))

        dz2 = 2 * (a2 - target) * a2 * (1 - a2)
        dW2 = a1[:, None] @ dz2[None, :]
        db2 = dz2
        da1 = dz2 @ self.W2.T
        dz1 = da1 * self.relu_d(z1)
        dW1 = x[:, None] @ dz1[None, :]
        db1 = dz1

        self._adam('W1', dW1, lr); self._adam('b1', db1, lr)
        self._adam('W2', dW2, lr); self._adam('b2', db2, lr)

        self.loss_history.append(loss)
        self.total_updates += 1

        if self.total_updates > 50 and self.total_updates % 20 == 0:
            self._check_plateau()
        if self.total_updates % 100 == 0:
            self._prune()
        return loss

    def _adam(self, param: str, grad: np.ndarray, lr: float):
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
        first = np.mean(lh[:10])
        second = np.mean(lh[10:])
        if second - first < 1e-4 and self.hidden < self.max_hidden:
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

        # Обрезаем веса
        self.W1 = self.W1[:, active]
        self.b1 = self.b1[active]
        self.W2 = self.W2[active, :]

        # Adam-состояния для W1 и b1
        for name in ['mW1', 'vW1']:
            mat = getattr(self, name)
            setattr(self, name, mat[:, active])
        for name in ['mb1', 'vb1']:
            vec = getattr(self, name)
            setattr(self, name, vec[active])

        # Adam-состояния для W2 и b2
        for name in ['mW2', 'vW2']:
            mat = getattr(self, name)
            setattr(self, name, mat[active, :])
        for name in ['mb2', 'vb2']:
            vec = getattr(self, name)
            setattr(self, name, vec[active])

        self.neuron_activations = self.neuron_activations[active]

        pruned = int(inactive.sum())
        self.hidden = int(active.sum())
        self.prunings += 1
        if pruned:
            logger.info(f"✂️ Pruned {pruned} neurons → {self.hidden}")

    def stats(self) -> Dict:
        return {
            'arch': f"{self.input_dim}→{self.hidden}→{self.output}",
            'updates': self.total_updates,
            'expansions': self.expansions,
            'prunings': self.prunings,
            'loss_avg': round(np.mean(self.loss_history) if self.loss_history else 0, 5),
        }


# ═══════════════════════════════════════════════════════════════
# 🧠 Память (эпизодическая + семантическая)
# ═══════════════════════════════════════════════════════════════
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
        if not self.items:
            self._mat = np.zeros((0, self.dim))
        else:
            self._mat = np.vstack([i.embedding for i in self.items])
        self._dirty = False

    def search(self, query_emb: np.ndarray, top_k: int = 5) -> List[Tuple]:
        if self._dirty:
            self._rebuild()
        if len(self.items) == 0:
            return []
        qn = query_emb / (np.linalg.norm(query_emb) + 1e-8)
        mn = self._mat / (np.linalg.norm(self._mat, axis=1, keepdims=True) + 1e-8)
        sim = mn @ qn
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
        self.working: deque = deque(maxlen=WORKING_MEMORY_SIZE)
        self.total_searches = 0

    def add_episode(self, content: str, importance: float = 0.5,
                    emotional_valence: float = 0.0, arousal: float = 0.0):
        emb = self.embed(content)
        ep = Episode(content=content, timestamp=time.time(), embedding=emb,
                     importance=importance, emotional_valence=emotional_valence,
                     arousal=arousal)
        self.episodic.add(ep)
        self.working.append(content)

    def add_concept(self, name: str, definition: str, confidence: float = 0.5):
        emb = self.embed(f"{name}: {definition}")
        self.semantic.add(Concept(name=name, definition=definition,
                                  embedding=emb, confidence=confidence))

    def recall(self, query: str, top_k: int = 5) -> List[Tuple[Episode, float]]:
        self.total_searches += 1
        q_emb = self.embed(query)
        return self.episodic.search(q_emb, top_k)

    def get_context(self, query: str) -> str:
        parts = []
        if self.working:
            parts.append("=== Недавние сообщения ===")
            parts.extend(self.working)
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
            'searches': self.total_searches,
        }

    def save(self, path: Path):
        def ep_dict(e: Episode) -> Dict:
            d = asdict(e)
            d['embedding'] = e.embedding.tolist()
            return d
        state = {
            'episodic': [ep_dict(e) for e in self.episodic.items],
            'semantic': [{'name': c.name, 'definition': c.definition,
                          'embedding': c.embedding.tolist(), 'confidence': c.confidence}
                         for c in self.semantic.items],
            'working': list(self.working),
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


# ═══════════════════════════════════════════════════════════════
# 🤖 Основной ассистент
# ═══════════════════════════════════════════════════════════════
class SelfImprovingAssistant:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.vocab = DynamicVocab()
        self.neural = DynamicNeuralNet(EMBEDDING_DIM, INITIAL_HIDDEN, OUTPUT_METRICS_DIM)
        self.memory = CognitiveMemory(self.vocab.encode)
        self.cache: Dict[str, Tuple[str, float]] = {}
        self.user_dir = MEMORY_BASE_DIR / user_id
        self.user_dir.mkdir(exist_ok=True)
        self.neural_path = self.user_dir / 'neural.pkl.gz'
        self.memory_path = self.user_dir / 'memory.pkl.gz'
        self.cache_path = self.user_dir / 'cache.pkl.gz'
        self._load()
        self.current_lr = LEARNING_RATE
        self.total_interactions = 0
        self.successful_learnings = 0

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
                self.neural.W1 = s['W1']; self.neural.b1 = s['b1']
                self.neural.W2 = s['W2']; self.neural.b2 = s['b2']
                self.neural.hidden = s['hidden']
                self.neural.total_updates = s.get('updates', 0)
                self.neural.expansions = s.get('expansions', 0)
                self.neural.prunings = s.get('prunings', 0)
                self.total_interactions = s.get('total', 0)
                self.successful_learnings = s.get('learned', 0)
                self.current_lr = s.get('lr', LEARNING_RATE)
                logger.info(f"✅ Neural loaded for {self.user_id}")
            except Exception as e:
                logger.error(f"Load neural failed: {e}")
        self.memory.load(self.memory_path)
        if self.cache_path.exists():
            try:
                with gzip.open(self.cache_path, 'rb') as f:
                    self.cache = pickle.load(f)
                now = time.time()
                self.cache = {k: (v, ts) for k, (v, ts) in self.cache.items() if now - ts < 3600}
            except:
                pass

    def _save(self):
        state = {
            'emb': self.vocab.embeddings, 'w2i': self.vocab.word2idx,
            'i2w': self.vocab.idx2word, 'meta': {w: asdict(m) for w, m in self.vocab.meta.items()},
            'next_idx': self.vocab.next_idx, 'cur_size': self.vocab.cur_size,
            'W1': self.neural.W1, 'b1': self.neural.b1,
            'W2': self.neural.W2, 'b2': self.neural.b2,
            'hidden': self.neural.hidden, 'updates': self.neural.total_updates,
            'expansions': self.neural.expansions, 'prunings': self.neural.prunings,
            'total': self.total_interactions, 'learned': self.successful_learnings,
            'lr': self.current_lr,
        }
        with gzip.open(self.neural_path, 'wb') as f:
            pickle.dump(state, f)
        self.memory.save(self.memory_path)
        with gzip.open(self.cache_path, 'wb') as f:
            pickle.dump(self.cache, f)

    def _cache_key(self, msg: str) -> str:
        return hashlib.md5(msg.encode()).hexdigest()

    async def get_response(self, message: str) -> Tuple[str, Dict]:
        start = time.time()
        self.total_interactions += 1

        cache_key = self._cache_key(message)
        if cache_key in self.cache:
            cached, ts = self.cache[cache_key]
            logger.info(f"Cache hit for {self.user_id}")
            return cached, {'cached': True, 'response_time': time.time() - start}

        context = self.memory.get_context(message)

        emb = self.vocab.encode(f"{message}\n{context}")
        preds = self.neural.forward(emb, store=False)
        pred_metrics = {METRIC_NAMES[i]: float(preds[i]) for i in range(OUTPUT_METRICS_DIM)}

        system = """Ты — самообучающийся AI-ассистент с долговременной памятью и динамической нейросетью.
Используй предоставленный контекст. Отвечай естественно, полезно, 3-5 предложений."""
        user_prompt = f"""Запрос: {message}

{context}

Предсказанные метрики (внутренние): {pred_metrics}

Ответ:"""
        response = await self._call_llm(system, user_prompt)
        if not response:
            response = "⚠️ Не удалось получить ответ от модели."

        quality = 0.5
        if random.random() < QUALITY_CHECK_PROB:
            llm_q = await self._assess_quality(message, response)
            quality = llm_q.get('overall_quality', 0.5)
            if llm_q.get('is_spam', False):
                logger.warning(f"Spam detected for {self.user_id}")
                return response, {'quality': 0.0, 'spam': True}
        else:
            quality = min(1.0, len(response) / 300)
            if any(w in response.lower() for w in ['ошибка', 'извините', 'не удалось']):
                quality *= 0.7

        actual = np.array([
            np.clip(quality + np.random.normal(0, 0.05), 0, 1),
            min(1.0, len(message.split()) / 20),
            quality,
            min(1.0, quality + 0.1),
            quality,
            min(1.0, len(response.split()) / 30),
            0.5 + np.random.normal(0, 0.08),
            0.5 + np.random.normal(0, 0.08),
        ]).clip(0, 1)

        loss = 0.0
        if quality >= MIN_QUALITY_SCORE:
            self.neural.forward(emb, store=True)
            loss = self.neural.backward(actual, self.current_lr)
            self.successful_learnings += 1

            if len(self.neural.loss_history) > 10:
                lh = list(self.neural.loss_history)
                trend = np.mean(lh[-5:]) - np.mean(lh[:5])
                if trend < -0.01:
                    self.current_lr = min(MAX_LR, self.current_lr * (1 + LR_ADAPT_RATE))
                elif trend > 0.01:
                    self.current_lr = max(MIN_LR, self.current_lr * (1 - LR_ADAPT_RATE))

            for word in message.lower().split():
                if len(word) > 3:
                    grad = (preds - actual).mean() * self.vocab.get_embedding(word) * 0.01
                    self.vocab.update_embedding(word, grad, self.current_lr)
                    self.vocab.update_quality(word, quality)

        if quality > 0.4:
            valence = (quality - 0.5) * 2
            arousal = min(1.0, len(message.split()) / 15)
            self.memory.add_episode(
                f"Q: {message}\nA: {response}",
                importance=quality,
                emotional_valence=valence,
                arousal=arousal,
            )
            if quality > 0.7:
                self.cache[cache_key] = (response, time.time())
                if len(self.cache) > 100:
                    oldest = min(self.cache.items(), key=lambda x: x[1][1])[0]
                    del self.cache[oldest]

        if self.total_interactions % 10 == 0:
            self.memory.consolidate()
            self._save()

        response_time = time.time() - start
        metadata = {
            'quality': round(quality, 3),
            'loss': loss,
            'predicted': pred_metrics,
            'response_time': response_time,
            'memory_episodes': len(self.memory.episodic.items),
        }
        logger.info(f"[{self.user_id}] Q={quality:.2f} | Loss={loss:.4f} | T={response_time:.1f}s")
        return response, metadata

    async def _call_llm(self, system: str, user: str) -> str:
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "temperature": 0.75,
            "max_tokens": 500,
            "stream": False
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LM_STUDIO_API_KEY}"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(LM_STUDIO_URL, json=payload, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content'].strip()
                else:
                    return ""

    async def _assess_quality(self, user_input: str, response: str) -> Dict:
        prompt = (
            f"Оцени взаимодействие (0-1):\n\nUser: {user_input}\nAssistant: {response}\n\n"
            f"JSON: {{\"importance\":0.X,\"informativeness\":0.X,\"emotional_value\":0.X,\"is_spam\":false}}"
        )
        result = await self._call_llm("", prompt)
        try:
            m = re.search(r'\{[^}]+\}', result)
            if m:
                d = json.loads(m.group())
                overall = d.get('importance', 0.5) * 0.4 + d.get('informativeness', 0.5) * 0.3 + d.get('emotional_value', 0.5) * 0.3
                return {'overall_quality': overall, 'is_spam': d.get('is_spam', False)}
        except:
            pass
        return {'overall_quality': 0.5, 'is_spam': False}


_assistants: Dict[str, SelfImprovingAssistant] = {}
_assistants_lock = asyncio.Lock()

async def get_assistant(user_id: str) -> SelfImprovingAssistant:
    async with _assistants_lock:
        if user_id not in _assistants:
            _assistants[user_id] = SelfImprovingAssistant(user_id)
        return _assistants[user_id]


# ═══════════════════════════════════════════════════════════════
# 📡 API endpoints
# ═══════════════════════════════════════════════════════════════
class AIRequest(BaseModel):
    message: str
    image_base64: Optional[str] = None
    image_mime: Optional[str] = None
    stream: bool = True


@router.post("/chat")
async def chat_with_ai(body: AIRequest, address: str = Depends(require_auth)):
    if body.stream:
        return StreamingResponse(
            stream_with_memory(body.message, address, body.image_base64, body.image_mime),
            media_type="text/event-stream"
        )
    else:
        assistant = await get_assistant(address)
        response, meta = await assistant.get_response(body.message)
        return {"reply": response, "meta": meta}


async def stream_with_memory(message: str, user_id: str,
                             image_base64: Optional[str] = None,
                             image_mime: Optional[str] = None):
    assistant = await get_assistant(user_id)
    context = assistant.memory.get_context(message)
    emb = assistant.vocab.encode(f"{message}\n{context}")
    preds = assistant.neural.forward(emb, store=False)
    pred_metrics = {METRIC_NAMES[i]: float(preds[i]) for i in range(OUTPUT_METRICS_DIM)}

    system = """Ты — самообучающийся AI-ассистент с долговременной памятью.
Используй контекст, отвечай естественно."""
    user_prompt = f"""Запрос: {message}

{context}

Ответ:"""

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "messages": messages,
        "temperature": 0.75,
        "max_tokens": 500,
        "stream": True
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LM_STUDIO_API_KEY}"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(LM_STUDIO_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                yield f"data: {json.dumps({'error': 'AI service unavailable'})}\n\n"
                return

            buffer = ""
            full_response = ""
            async for chunk in resp.content.iter_any():
                if not chunk:
                    continue
                buffer += chunk.decode('utf-8', errors='ignore')
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if not line.startswith('data: '):
                        continue
                    data_str = line[6:]
                    if data_str == '[DONE]':
                        break
                    try:
                        data = json.loads(data_str)
                        token = None
                        if 'choices' in data and data['choices']:
                            choice = data['choices'][0]
                            if 'delta' in choice and 'content' in choice['delta']:
                                token = choice['delta'].get('content', '')
                        if token:
                            full_response += token
                            yield f"data: {json.dumps({'token': token})}\n\n"
                    except:
                        continue

            if full_response:
                quality = min(1.0, len(full_response) / 300)
                if any(w in full_response.lower() for w in ['ошибка', 'извините', 'не удалось']):
                    quality *= 0.7

                actual = np.array([
                    np.clip(quality + np.random.normal(0, 0.05), 0, 1),
                    min(1.0, len(message.split()) / 20),
                    quality,
                    min(1.0, quality + 0.1),
                    quality,
                    min(1.0, len(full_response.split()) / 30),
                    0.5 + np.random.normal(0, 0.08),
                    0.5 + np.random.normal(0, 0.08),
                ]).clip(0, 1)

                if quality >= MIN_QUALITY_SCORE:
                    assistant.neural.forward(emb, store=True)
                    loss = assistant.neural.backward(actual, assistant.current_lr)
                    assistant.successful_learnings += 1

                    if len(assistant.neural.loss_history) > 10:
                        lh = list(assistant.neural.loss_history)
                        trend = np.mean(lh[-5:]) - np.mean(lh[:5])
                        if trend < -0.01:
                            assistant.current_lr = min(MAX_LR, assistant.current_lr * (1 + LR_ADAPT_RATE))
                        elif trend > 0.01:
                            assistant.current_lr = max(MIN_LR, assistant.current_lr * (1 - LR_ADAPT_RATE))

                    for word in message.lower().split():
                        if len(word) > 3:
                            grad = (preds - actual).mean() * assistant.vocab.get_embedding(word) * 0.01
                            assistant.vocab.update_embedding(word, grad, assistant.current_lr)
                            assistant.vocab.update_quality(word, quality)

                if quality > 0.4:
                    valence = (quality - 0.5) * 2
                    arousal = min(1.0, len(message.split()) / 15)
                    assistant.memory.add_episode(
                        f"Q: {message}\nA: {full_response}",
                        importance=quality,
                        emotional_valence=valence,
                        arousal=arousal,
                    )
                    if quality > 0.7:
                        key = hashlib.md5(message.encode()).hexdigest()
                        assistant.cache[key] = (full_response, time.time())

                assistant.total_interactions += 1
                if assistant.total_interactions % 10 == 0:
                    assistant.memory.consolidate()
                    assistant._save()

            yield "data: [DONE]\n\n"


@router.on_event("shutdown")
async def shutdown_event():
    for assistant in _assistants.values():
        assistant._save()
    logger.info("All assistants saved.")