import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
from typing import Dict, List, Optional, Tuple, Any
from collections import deque
from dataclasses import dataclass, field, asdict
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import aiohttp
from ddgs import DDGS

from agent_core import ReflectionLog, AutonomousAgent
from routes.emergence_extensions import EmergenceMixin

from config_ai import (
    LM_STUDIO_URL, LM_STUDIO_API_KEY, MEMORY_BASE_DIR,
    EMBEDDING_DIM, LATENT_DIM, LEARNING_RATE, REPLAY_BATCH_SIZE,
    REPLAY_FREQUENCY, WORKING_MEMORY_SIZE, MEMORY_CONSOLIDATION_THRESHOLD,
    FORGETTING_FACTOR, QUALITY_CHECK_PROB, MIN_QUALITY_SCORE,
    INITIAL_VOCAB_SIZE, MAX_VOCAB_SIZE, VOCAB_EXPANSION_STEP,
    SAVE_EVERY_N_INTERACTIONS, LM_STUDIO_TIMEOUT, LM_STUDIO_STREAM_TIMEOUT,
    MAX_IMAGE_SIZE_BASE64, GLOBAL_KNOWLEDGE_DIR, GLOBAL_VOCAB_PATH,
    GLOBAL_SUBCONSCIOUS_PATH, GLOBAL_EPISODES_PATH, GLOBAL_MERGE_LOG_PATH,
    GLOBAL_STATS_PATH, MERGE_TOP_EPISODES_PER_USER, GLOBAL_BLEND_ALPHA,
    MIN_GLOBAL_QUALITY, GLOBAL_MERGE_INTERVAL, MAX_GLOBAL_EPISODES,
    LONG_TERM_PLANNER_INTERVAL, RESOURCE_BUDGET_LLM_CALLS,
    SLEEP_CONSOLIDATION_INTERVAL, ANOMALY_THRESHOLD_QUALITY_DROP,
    EXPLAIN_MODE_TRIGGER, MAX_SEARCH_ITERATIONS, SEARCH_CACHE_TTL,
    PAGE_CONTENT_MAX_CHARS, MAX_PAGES_TO_FETCH, MIN_RELEVANCE_THRESHOLD,
    CHUNK_SIZE, CHUNK_OVERLAP, PARALLEL_FETCH_LIMIT, DDG_MIN_INTERVAL,
    DDG_MAX_RETRIES, SEARCH_CACHE_MAX_SIZE, AUTO_SEARCH_ENABLED,
    EASYDIFFUSION_ENABLED, EASYDIFFUSION_URL, EASYDIFFUSION_TIMEOUT,
    EASYDIFFUSION_DEFAULT_STEPS, EASYDIFFUSION_DEFAULT_WIDTH,
    EASYDIFFUSION_DEFAULT_HEIGHT,
)

try:
    from dependencies import require_auth
except ImportError:
    async def require_auth():
        return "anonymous"

logger = logging.getLogger(__name__)

# ==================================================================
# 🧠 PromptAdvisor — лёгкая онлайн-обучаемая нейросеть с LoRA-адаптерами
# ==================================================================
class PromptAdvisor:
    def __init__(self, input_dim=EMBEDDING_DIM, latent_dim=LATENT_DIM, hidden=128, seed=None, lora_rank=16):
        self.input_dim = input_dim
        self.latent_dim = latent_dim
        self.hidden = hidden
        self.prompt_vocab = [
            "Будь кратким и по делу.",
            "Прояви креативность в ответе.",
            "Приведи конкретные примеры из памяти.",
            "Ссылайся на источники из интернета, если нужно.",
            "Задай уточняющий вопрос, если не хватает данных.",
            "Предложи альтернативное решение.",
            "Покажи цепочку рассуждений.",
            "Будь эмпатичным и поддерживающим.",
            "Используй факты из глобальной базы знаний.",
            "Если фактов из интернета/памяти недостаточно — честно скажи об этом, не придумывай.",
        ]
        self.vocab_size = len(self.prompt_vocab)
        rng = np.random.default_rng(seed)
        in_dim = input_dim * 2 + latent_dim
        # Основные веса
        self.W1 = rng.normal(0, 1.0 / np.sqrt(in_dim), (in_dim, hidden))
        self.b1 = np.zeros(hidden)
        self.W2 = rng.normal(0, 1.0 / np.sqrt(hidden), (hidden, latent_dim))
        self.b2 = np.zeros(latent_dim)
        self.W3 = rng.normal(0, 1.0 / np.sqrt(latent_dim), (latent_dim, self.vocab_size))
        self.b3 = np.zeros(self.vocab_size)
        # LoRA-адаптеры (низкоранговые матрицы) для W1, W2, W3
        self.lora_rank = lora_rank
        self.lora_A1 = rng.normal(0, 0.01, (in_dim, lora_rank))
        self.lora_B1 = np.zeros((lora_rank, hidden))
        self.lora_A2 = rng.normal(0, 0.01, (hidden, lora_rank))
        self.lora_B2 = np.zeros((lora_rank, latent_dim))
        self.lora_A3 = rng.normal(0, 0.01, (latent_dim, lora_rank))
        self.lora_B3 = np.zeros((lora_rank, self.vocab_size))
        self.lora_scale = 1.0

        self.latent_state = np.zeros(latent_dim)
        self.lr = LEARNING_RATE
        self.replay_buffer = deque(maxlen=200)
        self.total_updates = 0

    def _forward_full(self, query_emb: np.ndarray, memory_emb: np.ndarray):
        x = np.concatenate([query_emb, memory_emb, self.latent_state])
        # Применяем W1 + LoRA
        h = np.tanh(x @ (self.W1 + self.lora_scale * (self.lora_A1 @ self.lora_B1)) + self.b1)
        latent = np.tanh(h @ (self.W2 + self.lora_scale * (self.lora_A2 @ self.lora_B2)) + self.b2)
        logits = latent @ (self.W3 + self.lora_scale * (self.lora_A3 @ self.lora_B3)) + self.b3
        return x, h, latent, logits

    def forward(self, query_emb: np.ndarray, memory_emb: np.ndarray):
        _, _, latent, logits = self._forward_full(query_emb, memory_emb)
        self.latent_state = latent
        return latent, logits

    @staticmethod
    def _softmax(logits):
        z = logits - np.max(logits)
        e = np.exp(z)
        return e / (np.sum(e) + 1e-8)

    def generate_prompt_instruction(self, logits):
        probs = self._softmax(logits)
        num = random.choices([1, 2, 3], weights=[0.5, 0.3, 0.2])[0]
        num = min(num, self.vocab_size)
        indices = list(np.random.choice(self.vocab_size, size=num, replace=False, p=probs))
        selected = [self.prompt_vocab[i] for i in indices]
        instruction = "### Внутренняя подсказка (адаптивный советник):\n" + "\n".join(f"- {s}" for s in selected)
        return instruction, indices

    def compute_reward(self, response: str, meta: Dict) -> float:
        score = 0.0
        length = len(response.split())
        if 20 <= length <= 2000:
            score += 0.3
        else:
            score -= 0.2
        if not any(err in response.lower() for err in ["ошибка", "извините", "не удалось", "не знаю"]):
            score += 0.2
        complexity = meta.get("complexity", 0.5)
        score += complexity * 0.3
        if meta.get("web_search_used") and length > 100:
            score += 0.2
        if meta.get("grounded") is False:
            score -= 0.3
        return float(np.clip(score, -1.0, 1.0))

    def _grad_step(self, query_emb, memory_emb, chosen_indices, reward):
        x, h, latent, logits = self._forward_full(query_emb, memory_emb)
        probs = self._softmax(logits)
        grad_logits = -probs.copy() * len(chosen_indices)
        for idx in chosen_indices:
            grad_logits[idx] += 1.0
        grad_logits *= reward

        # Градиенты для W3 и LoRA
        grad_W3 = np.outer(latent, grad_logits)
        grad_b3 = grad_logits
        grad_latent = grad_logits @ (self.W3 + self.lora_scale * (self.lora_A3 @ self.lora_B3)).T
        # LoRA градиенты для W3
        grad_lora_A3 = self.lora_B3 @ grad_logits.T
        grad_lora_B3 = self.lora_A3.T @ grad_logits

        grad_latent_pre = grad_latent * (1 - latent ** 2)
        grad_W2 = np.outer(h, grad_latent_pre)
        grad_b2 = grad_latent_pre
        grad_lora_A2 = self.lora_B2 @ grad_latent_pre.T
        grad_lora_B2 = self.lora_A2.T @ grad_latent_pre

        grad_h = grad_latent_pre @ (self.W2 + self.lora_scale * (self.lora_A2 @ self.lora_B2)).T
        grad_h_pre = grad_h * (1 - h ** 2)
        grad_W1 = np.outer(x, grad_h_pre)
        grad_b1 = grad_h_pre
        grad_lora_A1 = self.lora_B1 @ grad_h_pre.T
        grad_lora_B1 = self.lora_A1.T @ grad_h_pre

        # Обновление основных весов и LoRA
        for arr, grad in ((self.W1, grad_W1), (self.b1, grad_b1), (self.W2, grad_W2),
                          (self.b2, grad_b2), (self.W3, grad_W3), (self.b3, grad_b3)):
            np.clip(grad, -5.0, 5.0, out=grad)
            arr += self.lr * grad
        for arr, grad in ((self.lora_A1, grad_lora_A1), (self.lora_B1, grad_lora_B1),
                          (self.lora_A2, grad_lora_A2), (self.lora_B2, grad_lora_B2),
                          (self.lora_A3, grad_lora_A3), (self.lora_B3, grad_lora_B3)):
            np.clip(grad, -5.0, 5.0, out=grad)
            arr += self.lr * grad

    def learn(self, query_emb, memory_emb, chosen_indices, reward):
        self._grad_step(query_emb, memory_emb, chosen_indices, reward)
        self.total_updates += 1
        self.replay_buffer.append((query_emb.copy(), memory_emb.copy(), list(chosen_indices), reward))

    def experience_replay(self):
        if len(self.replay_buffer) < REPLAY_BATCH_SIZE:
            return
        batch = random.sample(self.replay_buffer, REPLAY_BATCH_SIZE)
        for q, m, indices, rew in batch:
            self._grad_step(q, m, indices, rew)

    def save(self, path: Path):
        np.savez(str(path.with_suffix('.npz')),
                 W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2, W3=self.W3, b3=self.b3,
                 lora_A1=self.lora_A1, lora_B1=self.lora_B1,
                 lora_A2=self.lora_A2, lora_B2=self.lora_B2,
                 lora_A3=self.lora_A3, lora_B3=self.lora_B3,
                 latent_state=self.latent_state, total_updates=np.array([self.total_updates]))

    def load(self, path: Path):
        npz_path = path.with_suffix('.npz')
        if npz_path.exists():
            data = np.load(str(npz_path))
            self.W1, self.b1 = data['W1'], data['b1']
            self.W2, self.b2 = data['W2'], data['b2']
            self.W3, self.b3 = data['W3'], data['b3']
            self.lora_A1, self.lora_B1 = data['lora_A1'], data['lora_B1']
            self.lora_A2, self.lora_B2 = data['lora_A2'], data['lora_B2']
            self.lora_A3, self.lora_B3 = data['lora_A3'], data['lora_B3']
            self.latent_state = data['latent_state']
            self.total_updates = int(data['total_updates'][0])

    def get_latent(self) -> np.ndarray:
        return self.latent_state.copy()

    def apply_global_weights(self, global_net, alpha=GLOBAL_BLEND_ALPHA):
        # Применяем глобальные веса только к основным, LoRA оставляем локальными
        for name in ('W1', 'b1', 'W2', 'b2', 'W3', 'b3'):
            local = getattr(self, name)
            glob = getattr(global_net, name)
            setattr(self, name, (1 - alpha) * local + alpha * glob)

# ==================================================================
# 🧠 Классификатор уверенности (ConfidenceClassifier)
# ==================================================================
class ConfidenceClassifier:
    """Небольшая нейросеть для оценки достаточности информации до генерации ответа."""
    def __init__(self, input_dim=EMBEDDING_DIM*2 + 64):
        self.fc1 = np.random.randn(input_dim, 32) * 0.01
        self.b1 = np.zeros(32)
        self.fc2 = np.random.randn(32, 1) * 0.01
        self.b2 = np.zeros(1)
        self.lr = 0.001

    def predict(self, query_emb: np.ndarray, ctx_emb: np.ndarray, meta_emb: np.ndarray) -> float:
        x = np.concatenate([query_emb, ctx_emb, meta_emb[:64]])
        h = np.tanh(x @ self.fc1 + self.b1)
        out = h @ self.fc2 + self.b2
        return float(1 / (1 + np.exp(-out)))  # sigmoid

    def train_on_log(self, query_emb, ctx_emb, meta_emb, target: float):
        x = np.concatenate([query_emb, ctx_emb, meta_emb[:64]])
        h = np.tanh(x @ self.fc1 + self.b1)
        pred = 1 / (1 + np.exp(-(h @ self.fc2 + self.b2)))
        grad_loss = pred - target
        grad_out = grad_loss * pred * (1 - pred)
        grad_fc2 = np.outer(h, grad_out)
        grad_b2 = grad_out
        grad_h = (grad_out * self.fc2.T).flatten()  # -> (32,)
        grad_h_tanh = grad_h * (1 - h ** 2)  # -> (32,)
        grad_fc1 = np.outer(x, grad_h_tanh)  # -> (input_dim, 32)
        grad_b1 = grad_h_tanh  # -> (32,)
        # обновления
        self.fc1 -= self.lr * grad_fc1
        self.b1 -= self.lr * grad_b1
        self.fc2 -= self.lr * grad_fc2
        self.b2 -= self.lr * grad_b2

# ==================================================================
# 🌍 Глобальная база знаний (без изменений)
# ==================================================================
@dataclass
class GlobalEpisode:
    content_hash: str
    embedding: np.ndarray
    importance: float
    topic_tags: List[str]
    timestamp: float
    contributor_hash: str
    usage_count: int = 0

class GlobalKnowledgeBase:
    _instance = None
    _lock = None
    def __init__(self):
        self._io_lock = asyncio.Lock()
        self._episodes: List[GlobalEpisode] = []
        self._global_subconscious: Optional[PromptAdvisor] = None
        self._global_embeddings: Dict[str, np.ndarray] = {}
        self._global_word_counts: Dict[str, int] = {}
        self.total_contributors = 0
        self.total_merges = 0
        self.total_episodes_added = 0
        self.last_merge_time = 0.0
        self._dirty = True
        self._load()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def get_lock(cls):
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    def _load(self):
        if GLOBAL_EPISODES_PATH.exists():
            try:
                with gzip.open(GLOBAL_EPISODES_PATH, 'rb') as f:
                    raw = pickle.load(f)
                self._episodes = []
                for d in raw:
                    d['embedding'] = np.array(d['embedding'])
                    self._episodes.append(GlobalEpisode(**d))
                self._dirty = True
            except Exception as e:
                logger.error(f"GlobalKB episodes load error: {e}")
        if GLOBAL_SUBCONSCIOUS_PATH.exists():
            try:
                self._global_subconscious = PromptAdvisor()
                self._global_subconscious.load(GLOBAL_SUBCONSCIOUS_PATH)
            except Exception as e:
                logger.error(f"GlobalKB subconscious load error: {e}")
        if GLOBAL_VOCAB_PATH.exists():
            try:
                with gzip.open(GLOBAL_VOCAB_PATH, 'rb') as f:
                    s = pickle.load(f)
                self._global_embeddings = {k: np.array(v) for k, v in s['embeddings'].items()}
                self._global_word_counts = s['counts']
            except Exception as e:
                logger.error(f"GlobalKB vocab load error: {e}")
        if GLOBAL_STATS_PATH.exists():
            try:
                with open(GLOBAL_STATS_PATH, 'r', encoding='utf-8') as f:
                    s = json.load(f)
                self.total_contributors = s.get('contributors', 0)
                self.total_merges = s.get('merges', 0)
                self.total_episodes_added = s.get('episodes_added', 0)
                self.last_merge_time = s.get('last_merge', 0.0)
            except Exception:
                pass

    def _save(self):
        try:
            raw = [{'content_hash': ep.content_hash, 'embedding': ep.embedding.tolist(),
                    'importance': ep.importance, 'topic_tags': ep.topic_tags,
                    'timestamp': ep.timestamp, 'contributor_hash': ep.contributor_hash,
                    'usage_count': ep.usage_count} for ep in self._episodes]
            with gzip.open(GLOBAL_EPISODES_PATH, 'wb') as f:
                pickle.dump(raw, f)
            if self._global_subconscious is not None:
                self._global_subconscious.save(GLOBAL_SUBCONSCIOUS_PATH)
            with gzip.open(GLOBAL_VOCAB_PATH, 'wb') as f:
                pickle.dump({'embeddings': {k: v.tolist() for k, v in self._global_embeddings.items()},
                             'counts': self._global_word_counts}, f)
            with open(GLOBAL_STATS_PATH, 'w', encoding='utf-8') as f:
                json.dump({'contributors': self.total_contributors, 'merges': self.total_merges,
                           'episodes_added': self.total_episodes_added, 'last_merge': self.last_merge_time},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"GlobalKB save error: {e}")

    async def contribute(self, user_id: str, content: str, embedding: np.ndarray,
                         importance: float, assistant: 'SelfImprovingAssistant') -> bool:
        if importance < MIN_GLOBAL_QUALITY:
            return False
        async with self.get_lock():
            c_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()[:32]
            if any(ep.content_hash == c_hash for ep in self._episodes):
                return False
            u_hash = hashlib.sha256(user_id.encode()).hexdigest()[:32]
            topics = self._extract_topics(content)
            ep = GlobalEpisode(content_hash=c_hash, embedding=embedding.copy(), importance=importance,
                               topic_tags=topics, timestamp=time.time(), contributor_hash=u_hash)
            self._episodes.append(ep)
            self._dirty = True
            self.total_episodes_added += 1
            for word, idx in assistant.vocab.word2idx.items():
                if idx < len(assistant.vocab.embeddings):
                    local_emb = assistant.vocab.embeddings[idx]
                    if word in self._global_embeddings:
                        n = self._global_word_counts.get(word, 1)
                        self._global_embeddings[word] = (self._global_embeddings[word] * n + local_emb) / (n + 1)
                        self._global_word_counts[word] = n + 1
                    else:
                        self._global_embeddings[word] = local_emb.copy()
                        self._global_word_counts[word] = 1
            if len(self._episodes) > MAX_GLOBAL_EPISODES:
                self._episodes.sort(key=lambda e: e.importance * (1 - min(1.0, (time.time()-e.timestamp)/86400/30)), reverse=True)
                self._episodes = self._episodes[:MAX_GLOBAL_EPISODES]
                self._dirty = True
            return True

    @staticmethod
    def _extract_topics(text: str) -> List[str]:
        stop_words = {'и','в','на','с','по','из','для','что','как','это','но','или',
                      'the','a','an','is','are','was','were','be','been','to','of',
                      'and','or','but','in','on','at','by','for','with','not'}
        words = re.findall(r'\b[а-яёa-z]{4,}\b', text.lower())
        freq = {}
        for w in words:
            if w not in stop_words:
                freq[w] = freq.get(w, 0) + 1
        return sorted(freq, key=freq.get, reverse=True)[:5]

    def search_global(self, query_emb: np.ndarray, top_k=3) -> List[Tuple[GlobalEpisode, float]]:
        if not self._episodes:
            return []
        if self._dirty:
            self._rebuild_matrix()
        qn = query_emb / (np.linalg.norm(query_emb)+1e-8)
        norms = np.linalg.norm(self._mat, axis=1, keepdims=True)
        norms[norms==0] = 1e-8
        sims = (self._mat / norms) @ qn
        idx = np.argsort(sims)[::-1][:top_k]
        return [(self._episodes[i], float(sims[i])) for i in idx if sims[i] > 0.3]

    def _rebuild_matrix(self):
        self._mat = np.vstack([ep.embedding for ep in self._episodes]) if self._episodes else np.zeros((0, EMBEDDING_DIM))
        self._dirty = False

    async def merge_all(self, assistants: List['SelfImprovingAssistant']) -> Dict:
        async with self.get_lock():
            t0 = time.time()
            episodes_added = 0
            contributor_ids = set()
            for a in assistants:
                contributor_ids.add(a.user_id)
                top_eps = sorted(a.memory.episodic.items, key=lambda e: e.importance, reverse=True)[:MERGE_TOP_EPISODES_PER_USER]
                for ep in top_eps:
                    added = await self.contribute(a.user_id, ep.content, ep.embedding, ep.importance, a)
                    if added:
                        episodes_added += 1
            if assistants and all(hasattr(a, 'subconscious') for a in assistants):
                if self._global_subconscious is None:
                    self._global_subconscious = PromptAdvisor()
                for param in self._global_subconscious.parameters():
                    param.data.zero_()
                total_weight = 0.0
                for a in assistants:
                    weight = a.subconscious.total_updates + 1
                    for gp, lp in zip(self._global_subconscious.parameters(), a.subconscious.parameters()):
                        gp.data += weight * lp.data
                    total_weight += weight
                if total_weight > 0:
                    for param in self._global_subconscious.parameters():
                        param.data /= total_weight
                for a in assistants:
                    a.subconscious.apply_global_weights(self._global_subconscious, alpha=GLOBAL_BLEND_ALPHA)
            for a in assistants:
                self.apply_global_vocab_to_local(a)
            self.total_contributors = max(self.total_contributors, len(contributor_ids))
            self.total_merges += 1
            self.last_merge_time = time.time()
            self._save()
            elapsed = time.time() - t0
            result = {'episodes_added': episodes_added, 'total_episodes': len(self._episodes),
                      'global_vocab': len(self._global_embeddings), 'contributors': len(contributor_ids),
                      'merge_time_s': round(elapsed, 2)}
            with open(GLOBAL_MERGE_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps({'ts': time.time(), **result}) + '\n')
            return result

    def apply_global_vocab_to_local(self, assistant: 'SelfImprovingAssistant', alpha=GLOBAL_BLEND_ALPHA):
        for word, g_emb in self._global_embeddings.items():
            if word in assistant.vocab.word2idx:
                idx = assistant.vocab.word2idx[word]
                local_emb = assistant.vocab.embeddings[idx]
                assistant.vocab.embeddings[idx] = (1 - alpha) * local_emb + alpha * g_emb
            else:
                new_idx = assistant.vocab.add_word(word)
                if new_idx < len(assistant.vocab.embeddings):
                    assistant.vocab.embeddings[new_idx] = g_emb.copy()

    def stats(self) -> Dict:
        return {'total_episodes': len(self._episodes), 'global_vocab_size': len(self._global_embeddings),
                'total_contributors': self.total_contributors, 'total_merges': self.total_merges,
                'episodes_added': self.total_episodes_added, 'last_merge': self.last_merge_time,
                'has_global_subconscious': self._global_subconscious is not None}

# ==================================================================
# 🌐 Интеллектуальный веб-поиск (с добавлением верификации)
# ==================================================================
_search_cache: Dict[str, Tuple[str, float]] = {}
_sufficiency_cache: Dict[str, Tuple[bool, float]] = {}

class RelevantChunk:
    __slots__ = ('text', 'source_url', 'title', 'score', 'engine')
    def __init__(self, text, source_url, title, score, engine="web"):
        self.text, self.source_url, self.title, self.score, self.engine = text, source_url, title, score, engine
    def to_dict(self):
        return {'text': self.text, 'source_url': self.source_url, 'title': self.title, 'score': self.score, 'engine': self.engine}

class AdaptiveWebSearch:
    SEARCH_TRIGGER_WORDS = {
        'ru': {'сколько','когда','где','кто такой','что такое','курс','цена','стоимость','погода','новости',
               'последние','актуальн','сегодня','сейчас','в этом году','рейтинг','топ','лучший','сравн','обзор',
               'отзыв','статистика','данные','расписание','результат','победитель','версия','релиз','обновлён',
               'обновлен','выйти','вышла','найди','поищи','поиск','загугли','интернет','в сети','онлайн','проверь',
               'правда ли','действительно','подтверди','узнай','сколько стоит','какой сейчас','что нового',
               'последн','текущ','свеж'},
        'en': {'latest','recent','current','today','now','price','cost','rate','news','weather','score','result',
               'ranking','best','top','compare','review','find','search','look up','online','update','release',
               'version','who is','what is the','how much','how many','check','verify','confirm','true','fact','2024','2025'}
    }
    SKIP_DOMAINS = {'youtube.com','twitter.com','x.com','instagram.com','facebook.com','tiktok.com','reddit.com',
                    'pinterest.com','linkedin.com','apps.apple.com','play.google.com','vimeo.com','t.me','telegram.org'}

    def __init__(self, assistant):
        self.assistant = assistant
        self.session: Optional[aiohttp.ClientSession] = None
        self._user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
        self._last_ddg_call = 0.0
        self._ddg_min_interval = DDG_MIN_INTERVAL
        self._bs4_available = False
        try:
            from bs4 import BeautifulSoup as _BS
            self._bs4_available = True
            self._BS = _BS
        except ImportError:
            logger.debug("beautifulsoup4 not installed")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
            self.session = aiohttp.ClientSession(headers={"User-Agent": self._user_agent}, timeout=timeout)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    def should_search_fast(self, question: str, memory_context: str = "") -> bool:
        q_lower = question.lower()
        for lang_words in self.SEARCH_TRIGGER_WORDS.values():
            for word in lang_words:
                if word in q_lower:
                    return True
        if re.search(r'\b(20[2-3]\d)\b', question):
            return True
        starters = {'кто','что','где','когда','сколько','какой','какая','какие','чей','which','who','what','where','when','how','whose'}
        first_word = q_lower.split()[0] if q_lower.split() else ""
        if first_word in starters and len(question.split()) >= 4:
            if memory_context and len(memory_context) > 200:
                q_words = set(q_lower.split()) - {'и','в','на','с','по','из','для','что','как','это'}
                m_words = set(memory_context.lower().split())
                if len(q_words & m_words) >= 3:
                    return False
            return True
        return False

    async def should_search(self, question: str, memory_context: str = "") -> bool:
        if self.should_search_fast(question, memory_context):
            return True
        if len(question.split()) >= 8:
            prompt = ("Нужна ли актуальная информация из интернета для ответа? "
                      "Если про текущие события, курсы, новости, технические данные — ДА. "
                      "Если про общие знания, логику, мнение — НЕТ. Ответь только ДА или НЕТ.\n"
                      f"Вопрос: {question}")
            try:
                response = await self.assistant._call_llm([{"role": "user", "content": prompt}])
                return "да" in response.lower().strip()[:10]
            except Exception:
                return False
        return False

    async def generate_search_query(self, original_question: str, previous_attempts: Optional[List[str]] = None) -> str:
        words = original_question.split()
        if len(words) <= 6 and not previous_attempts:
            stop = {'ли','же','ну','а','и','в','на','с','по','из','для','что','как','это','не','то','все','так',
                    'is','the','a','an','do','does','did','will','can','could','please'}
            clean = " ".join(w for w in words if w.lower() not in stop)
            if len(clean.split()) >= 2:
                return clean
        context = ""
        if previous_attempts:
            context = f"\nПредыдущие неудачные запросы: {', '.join(previous_attempts[-3:])}. Сформулируй новый, более точный запрос."
        prompt = ("Сформулируй краткий поисковый запрос (до 8 слов, на русском или английском) для DuckDuckGo. "
                  "Убери вопросительные слова, оставь суть. Выведи ТОЛЬКО запрос.\n"
                  f"Вопрос: {original_question}{context}\nЗапрос:")
        query = await self.assistant._call_llm([{"role": "user", "content": prompt}])
        query = query.strip().strip('"').strip("'")
        if len(query) > 100:
            query = " ".join(query.split()[:8])
        return query or original_question

    async def _ddg_search(self, query: str, max_results: int = 10) -> List[Dict]:
        last_exc = None
        for attempt in range(DDG_MAX_RETRIES):
            try:
                return await self._ddg_search_once(query, max_results)
            except Exception as e:
                last_exc = e
                err_str = str(e).lower()
                is_rate_limit = ("202" in str(e) or "ratelimit" in err_str or "rate limit" in err_str or
                                 "too many" in err_str or "429" in str(e))
                wait = (1.5 ** attempt) * self._ddg_min_interval + random.uniform(0, 0.8)
                if is_rate_limit:
                    logger.warning(f"DDG rate-limit попытка {attempt+1}/{DDG_MAX_RETRIES}, ожидание {wait:.1f}с")
                else:
                    logger.warning(f"DDG ошибка (попытка {attempt+1}): {e}")
                if attempt < DDG_MAX_RETRIES - 1:
                    await asyncio.sleep(wait)
        logger.error(f"DDG не ответил после {DDG_MAX_RETRIES} попыток: {last_exc}")
        return []

    async def _ddg_search_once(self, query: str, max_results: int = 10) -> List[Dict]:
        now = time.time()
        elapsed = now - self._last_ddg_call
        if elapsed < self._ddg_min_interval:
            await asyncio.sleep(self._ddg_min_interval - elapsed)
        self._last_ddg_call = time.time()
        lang_hint = "ru-ru"
        latin_ratio = sum(1 for c in query if c.isascii() and c.isalpha()) / max(1, len(query))
        if latin_ratio > 0.6:
            lang_hint = "wt-wt"
        def sync_search():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results, safesearch="moderate", region=lang_hint))
        search_results = await asyncio.to_thread(sync_search)
        results = []
        for r in search_results:
            url = r.get("href", "")
            domain = self._extract_domain(url)
            results.append({"title": r.get("title", "")[:200], "url": url,
                            "snippet": r.get("body", "")[:800], "skip_fetch": domain in self.SKIP_DOMAINS})
        return results

    async def _wikipedia_search_lang(self, query: str, lang: str) -> List[Dict]:
        results = []
        try:
            session = await self._get_session()
            base_url = f"https://{lang}.wikipedia.org/w/api.php"
            search_params = {"action": "query", "list": "search", "srsearch": query, "srlimit": 3, "format": "json"}
            async with session.get(base_url, params=search_params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                hits = data.get("query", {}).get("search", [])
            for hit in hits:
                page_id = hit.get("pageid")
                title = hit.get("title", "")
                if not page_id:
                    continue
                extract_params = {"action": "query", "pageids": page_id, "prop": "extracts",
                                  "exintro": 1, "explaintext": 1, "format": "json"}
                try:
                    async with session.get(base_url, params=extract_params, timeout=aiohttp.ClientTimeout(total=8)) as ext_resp:
                        if ext_resp.status != 200:
                            continue
                        ext_data = await ext_resp.json()
                        pages = ext_data.get("query", {}).get("pages", {})
                        for pid, page in pages.items():
                            extract = page.get("extract", "")
                            if extract and len(extract) > 100:
                                results.append({"title": f"[{lang.upper()}] {title}",
                                                "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title)}",
                                                "snippet": extract[:800], "full_text": extract[:PAGE_CONTENT_MAX_CHARS]})
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Wikipedia [{lang}] error: {e}")
        return results

    async def _wikipedia_search(self, query: str, lang: str = "ru") -> List[Dict]:
        latin_ratio = sum(1 for c in query if c.isascii() and c.isalpha()) / max(1, len(query))
        langs = ["en", "ru"] if latin_ratio > 0.7 else ["ru", "en"]
        tasks = [self._wikipedia_search_lang(query, l) for l in langs]
        all_results_nested = await asyncio.gather(*tasks, return_exceptions=True)
        merged, seen = [], set()
        for res in all_results_nested:
            if isinstance(res, list):
                for r in res:
                    key = r["title"].split("] ", 1)[-1].lower()[:40]
                    if key not in seen:
                        seen.add(key)
                        merged.append(r)
        return merged

    async def _fetch_page_text(self, url: str, timeout: int = 12) -> Tuple[str, str]:
        if not url.startswith(("http://", "https://")):
            return "", "Invalid URL"
        domain = self._extract_domain(url)
        if domain in self.SKIP_DOMAINS:
            return "", f"Skipped domain: {domain}"
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout),
                                   allow_redirects=True, ssl=False) as resp:
                if resp.status != 200:
                    return "", f"HTTP {resp.status}"
                content_type = resp.headers.get("Content-Type", "")
                if "text" not in content_type and "json" not in content_type:
                    return "", f"Binary: {content_type}"
                html = await resp.text(errors="replace")
                text = self._parse_with_bs4(html) if self._bs4_available else self._parse_with_regex(html)
                return text, ""
        except asyncio.TimeoutError:
            return "", "Timeout"
        except Exception as e:
            return "", str(e)[:200]

    def _parse_with_bs4(self, html: str) -> str:
        try:
            soup = self._BS(html, "html.parser")
            for tag in soup.find_all(["script","style","nav","footer","header","aside","iframe","noscript","form","svg","button","input","select","textarea","figure figcaption"]):
                tag.decompose()
            for tag in soup.find_all(True, attrs={"class": re.compile(r"(menu|nav|sidebar|widget|banner|ad|cookie|popup|subscribe|share|social|related|recommend|comment)", re.I)}):
                tag.decompose()
            main_content = None
            selectors = ["article","main",'[role="main"]',".article-body",".article-content",".article-text",
                         ".post-content",".post-body",".entry-content",".story-body",".story-content",
                         ".content-body",".page-content","#article","#content","#main","#post",".news-body",".text",".body"]
            for selector in selectors:
                main_content = soup.select_one(selector)
                if main_content and len(main_content.get_text(strip=True)) > 200:
                    break
            if not main_content:
                best_div, best_score = None, 0
                for div in soup.find_all(["div","section"]):
                    text_len = len(div.get_text(strip=True))
                    tag_count = len(div.find_all()) + 1
                    score = text_len / tag_count
                    if score > best_score and text_len > 300:
                        best_score, best_div = score, div
                main_content = best_div
            content = main_content or soup.body or soup
            text = content.get_text(separator=" ", strip=True)
            return re.sub(r"\s+", " ", text).strip()
        except Exception:
            return self._parse_with_regex(html)

    @staticmethod
    def _parse_with_regex(html: str) -> str:
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL|re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL|re.IGNORECASE)
        html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.DOTALL|re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = text.replace("&nbsp;"," ").replace("&amp;","&").replace("&lt;","<").replace("&gt;",">").replace("&quot;",'"')
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _chunk_text(text: str, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> List[str]:
        if not text or len(text) < 100:
            return []
        paragraphs = re.split(r"\n\s*\n|\r\n\s*\r\n", text)
        if len(paragraphs) <= 2 and len(text) > chunk_size:
            sentences = re.split(r"(?<=[.!?。])\s+", text)
            paragraphs, current = [], ""
            for sent in sentences:
                if len(current) + len(sent) < chunk_size * 0.8:
                    current += (" " + sent if current else sent)
                else:
                    if current:
                        paragraphs.append(current.strip())
                    current = sent
            if current:
                paragraphs.append(current.strip())
        chunks, current_chunk = [], ""
        for para in paragraphs:
            para = para.strip()
            if not para or len(para) < 30:
                continue
            if len(current_chunk) + len(para) + 1 <= chunk_size:
                current_chunk += ("\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    if overlap > 0 and len(current_chunk) > overlap:
                        current_chunk = current_chunk[-overlap:] + " " + para
                    else:
                        current_chunk = para
                else:
                    current_chunk = para
                if len(current_chunk) > chunk_size * 1.5:
                    words = current_chunk.split()
                    sub = ""
                    for word in words:
                        if len(sub) + len(word) + 1 <= chunk_size:
                            sub += (" " if sub else "") + word
                        else:
                            if sub:
                                chunks.append(sub.strip())
                            sub = word
                    current_chunk = sub if sub else ""
        if current_chunk:
            chunks.append(current_chunk.strip())
        return [c for c in chunks if len(c) >= 50]

    @staticmethod
    def _compute_relevance(chunk: str, question: str, question_emb: np.ndarray, chunk_emb: np.ndarray) -> float:
        emb_sim = 0.0
        q_norm, c_norm = np.linalg.norm(question_emb), np.linalg.norm(chunk_emb)
        if q_norm > 1e-8 and c_norm > 1e-8:
            emb_sim = float(np.dot(question_emb, chunk_emb) / (q_norm * c_norm))
        stop = {"и","в","на","с","по","из","для","что","как","это","но","или","не","то","все","так","бы","ли","же",
                "the","and","for","are","but","not","you","all","can","had","her","was","one","our","has","have"}
        q_words = set(re.findall(r"\b\w{3,}\b", question.lower())) - stop
        c_words = set(re.findall(r"\b\w{3,}\b", chunk.lower())) - stop
        keyword_score = len(q_words & c_words) / len(q_words) if q_words and c_words else 0.0
        return 0.5 * emb_sim + 0.5 * keyword_score

    async def _extract_relevant_chunks(self, text: str, question: str, url: str, title: str, engine: str = "web") -> List[RelevantChunk]:
        if not text or len(text) < 100:
            return []
        question_emb = self.assistant.vocab.encode(question)
        chunks = self._chunk_text(text)
        if not chunks:
            return []
        scored = []
        for chunk in chunks:
            chunk_emb = self.assistant.vocab.encode(chunk)
            score = self._compute_relevance(chunk, question, question_emb, chunk_emb)
            if score >= MIN_RELEVANCE_THRESHOLD:
                scored.append((score, chunk))
        scored.sort(reverse=True, key=lambda x: x[0])
        selected = []
        for sim, chunk in scored[:8]:
            if len(selected) >= 4:
                break
            chunk_words = set(chunk.lower().split())
            is_dup = False
            for existing in selected:
                existing_words = set(existing.text.lower().split())
                if chunk_words and existing_words:
                    jaccard = len(chunk_words & existing_words) / len(chunk_words | existing_words)
                    if jaccard > 0.7:
                        is_dup = True
                        break
            if not is_dup:
                selected.append(RelevantChunk(chunk, url, title, sim, engine=engine))
        return selected

    async def _fetch_and_filter_pages(self, search_results: List[Dict], question: str) -> List[RelevantChunk]:
        if not search_results:
            return []
        all_chunks = []
        fetch_list, snippet_only = [], []
        for r in search_results:
            if r.get("skip_fetch") or not r.get("url"):
                if r.get("snippet") and len(r["snippet"]) > 50:
                    snippet_only.append(r)
            else:
                fetch_list.append(r)
        fetch_list = fetch_list[:MAX_PAGES_TO_FETCH]
        semaphore = asyncio.Semaphore(PARALLEL_FETCH_LIMIT)
        async def fetch_one(r_item):
            async with semaphore:
                text, err = await self._fetch_page_text(r_item["url"])
                if err or len(text) < 200:
                    snippet = r_item.get("snippet", "")
                    if snippet and len(snippet) > 50:
                        q_emb = self.assistant.vocab.encode(question)
                        s_emb = self.assistant.vocab.encode(snippet)
                        score = self._compute_relevance(snippet, question, q_emb, s_emb)
                        if score >= MIN_RELEVANCE_THRESHOLD * 0.7:
                            return [RelevantChunk(snippet, r_item["url"], r_item.get("title",""), score, engine="snippet")]
                    return []
                return await self._extract_relevant_chunks(text, question, r_item["url"], r_item.get("title",""), engine="web")
        tasks = [fetch_one(r) for r in fetch_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                all_chunks.extend(res)
        q_emb = self.assistant.vocab.encode(question)
        for r in snippet_only:
            snippet = r.get("snippet", "")
            if not snippet or len(snippet) <= 50:
                continue
            s_emb = self.assistant.vocab.encode(snippet)
            score = self._compute_relevance(snippet, question, q_emb, s_emb)
            if score >= MIN_RELEVANCE_THRESHOLD * 0.7:
                all_chunks.append(RelevantChunk(snippet, r.get("url",""), r.get("title",""), score, engine="snippet"))
        all_chunks.sort(key=lambda x: x.score, reverse=True)
        return all_chunks[:12]

    # ---- НОВЫЙ МЕТОД ДЛЯ ВЕРИФИКАЦИИ УТВЕРЖДЕНИЙ ----
    async def verify_claim(self, claim: str) -> Tuple[bool, float, List[str]]:
        """
        Проверяет утверждение через веб-поиск и возвращает (подтверждено, уверенность, источники).
        """
        # Ищем по утверждению
        context, chunks, meta = await self.iterative_search(claim, max_iterations=2)
        if not chunks:
            return False, 0.0, []
        # Анализируем найденные фрагменты на наличие подтверждений
        claim_emb = self.assistant.vocab.encode(claim)
        supporting = []
        for c in chunks:
            sim = self._compute_relevance(c.text, claim, claim_emb, self.assistant.vocab.encode(c.text))
            if sim > 0.4:
                supporting.append((c.text, sim))
        if not supporting:
            return False, 0.0, []
        # Оценка уверенности по количеству и релевантности источников
        avg_score = np.mean([s for _, s in supporting])
        confidence = min(1.0, avg_score * 1.2)
        sources = [c.source_url for c in chunks if c.source_url]
        return True, confidence, sources

    async def is_information_sufficient(self, question: str, collected_chunks: List[RelevantChunk]) -> Tuple[bool, Optional[str]]:
        if not collected_chunks:
            return False, None
        high_score = sum(1 for c in collected_chunks if c.score > 0.5)
        total_text = sum(len(c.text) for c in collected_chunks)
        wiki_present = any(c.engine == "wikipedia" for c in collected_chunks)
        sources_count = len({c.source_url for c in collected_chunks})
        if high_score >= 3 and total_text > 2500 and sources_count >= 2:
            return True, None
        if wiki_present and high_score >= 1 and total_text > 1500:
            return True, None
        if len(question.split()) <= 5 and high_score >= 1 and total_text > 500:
            return True, None
        cache_key = hashlib.md5((question + str(len(collected_chunks)) + str(total_text)).encode()).hexdigest()
        if cache_key in _sufficiency_cache:
            cached_result, ts = _sufficiency_cache[cache_key]
            if time.time() - ts < 120:
                return cached_result, None
        chunks_text = "\n\n---\n\n".join(f"[{c.engine.upper()}] {c.title[:60]}\n{c.text[:600]}" for c in collected_chunks[:5])
        prompt = (f"Вопрос: {question}\n\nФрагменты из интернета:\n{chunks_text}\n\nДостаточно ли данных для полного ответа?\n"
                  f"Если ДА: ответь ДОСТАТОЧНО\nЕсли НЕТ: ответь ЗАПРОС: <уточняющий запрос>\nТолько один из двух форматов выше.")
        try:
            response = await self.assistant._call_llm([{"role": "user", "content": prompt}])
        except Exception:
            return total_text > 800, None
        response_upper = response.strip().upper()
        if response_upper.startswith("ДОСТАТОЧНО"):
            _sufficiency_cache[cache_key] = (True, time.time())
            return True, None
        if "ЗАПРОС:" in response_upper:
            new_query = response.split("ЗАПРОС:")[-1].split("запрос:")[-1].strip().strip("\"'")
            if new_query and len(new_query) > 2:
                _sufficiency_cache[cache_key] = (False, time.time())
                return False, new_query
        _sufficiency_cache[cache_key] = (total_text > 1000, time.time())
        return total_text > 1000, None

    async def iterative_search(self, question: str, max_iterations: int = MAX_SEARCH_ITERATIONS) -> Tuple[str, List[RelevantChunk], Dict]:
        start_time = time.time()
        all_chunks = []
        meta = {"iterations": 0, "queries": [], "total_chunks": 0, "sufficient_at_iteration": None,
                "sources_used": [], "elapsed_s": 0}
        cache_key = hashlib.md5(question.encode()).hexdigest()
        if cache_key in _search_cache and _search_cache[cache_key][1] > time.time() - SEARCH_CACHE_TTL:
            try:
                data = json.loads(_search_cache[cache_key][0])
                all_chunks = [RelevantChunk(**c) for c in data["chunks"]]
                meta = data["meta"]
                logger.info(f"📦 Кэш поиска: {question[:50]}")
                return self._format_search_context(all_chunks), all_chunks, meta
            except Exception:
                pass
        current_query = await self.generate_search_query(question)
        meta["queries"].append(current_query)
        for iteration in range(max_iterations):
            meta["iterations"] = iteration + 1
            logger.info(f"🔍 Итерация {iteration + 1}: '{current_query}'")
            ddg_task = asyncio.create_task(self._ddg_search(current_query, max_results=10))
            wiki_task = asyncio.create_task(self._wikipedia_search(current_query)) if iteration == 0 else None
            ddg_results = await ddg_task
            wiki_results = (await wiki_task) if wiki_task else []
            if ddg_results and "duckduckgo" not in meta["sources_used"]:
                meta["sources_used"].append("duckduckgo")
            if wiki_results and "wikipedia" not in meta["sources_used"]:
                meta["sources_used"].append("wikipedia")
            for wr in wiki_results:
                full_text = wr.get("full_text", "")
                if not full_text:
                    continue
                chunks = self._chunk_text(full_text)
                question_emb = self.assistant.vocab.encode(question)
                for chunk in chunks[:4]:
                    chunk_emb = self.assistant.vocab.encode(chunk)
                    score = self._compute_relevance(chunk, question, question_emb, chunk_emb)
                    if score >= MIN_RELEVANCE_THRESHOLD * 0.8:
                        all_chunks.append(RelevantChunk(chunk, wr["url"], wr["title"], score, engine="wikipedia"))
            if ddg_results:
                new_chunks = await self._fetch_and_filter_pages(ddg_results, question)
                existing_urls = {c.source_url for c in all_chunks}
                for chunk in new_chunks:
                    if chunk.source_url not in existing_urls or chunk.engine == "snippet":
                        all_chunks.append(chunk)
            meta["total_chunks"] = len(all_chunks)
            if not ddg_results and not wiki_results:
                logger.warning(f"Нет результатов: '{current_query}'")
                if iteration < max_iterations - 1:
                    current_query = await self.generate_search_query(question, previous_attempts=meta["queries"])
                    meta["queries"].append(current_query)
                    continue
                break
            sufficient, new_query = await self.is_information_sufficient(question, all_chunks)
            if sufficient:
                meta["sufficient_at_iteration"] = iteration + 1
                logger.info(f"✅ Достаточно информации после итерации {iteration + 1}")
                break
            if new_query and iteration + 1 < max_iterations:
                current_query = new_query
                meta["queries"].append(current_query)
            else:
                break
            await asyncio.sleep(0.3)
        meta["elapsed_s"] = round(time.time() - start_time, 2)
        cache_data = {"chunks": [c.to_dict() for c in all_chunks], "meta": meta}
        _search_cache[cache_key] = (json.dumps(cache_data, ensure_ascii=False), time.time())
        now = time.time()
        expired = [k for k, (_, ts) in _search_cache.items() if now - ts > SEARCH_CACHE_TTL]
        for k in expired:
            del _search_cache[k]
        if len(_search_cache) > SEARCH_CACHE_MAX_SIZE:
            sorted_keys = sorted(_search_cache.keys(), key=lambda k: _search_cache[k][1])
            for k in sorted_keys[:len(_search_cache) - SEARCH_CACHE_MAX_SIZE // 2]:
                del _search_cache[k]
        return self._format_search_context(all_chunks), all_chunks, meta

    def _format_search_context(self, chunks: List[RelevantChunk]) -> str:
        if not chunks:
            return "⚠️ Поиск в интернете не дал релевантных результатов."
        engine_label = {"wikipedia": "📖 Wiki", "snippet": "📝 Сниппет", "web": "🌐 Веб"}
        parts = ["=== РЕЗУЛЬТАТЫ ИНТЕЛЛЕКТУАЛЬНОГО ПОИСКА ===\n"]
        for i, chunk in enumerate(chunks[:8], 1):
            label = engine_label.get(chunk.engine, "🌐")
            parts.append(f"[{i}] {label} | {chunk.title[:80]}")
            parts.append(f"    Источник: {chunk.source_url} (релевантность: {chunk.score:.2f})")
            parts.append(f"    {chunk.text[:1500]}\n")
        parts.append("=== КОНЕЦ ДАННЫХ ===")
        return "\n".join(parts)

    async def fetch_single_url(self, url: str, question: str) -> Tuple[str, List[RelevantChunk]]:
        text, err = await self._fetch_page_text(url, timeout=20)
        if err or not text:
            return f"Ошибка загрузки {url}: {err}", []
        chunks = await self._extract_relevant_chunks(text, question, url, "Загруженная страница", engine="web")
        return self._format_search_context(chunks), chunks

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc.replace("www.", "")
        except Exception:
            return ""

# ==================================================================
# 🔤 Адаптивный словарь с кэшированием эмбеддингов (без изменений)
# ==================================================================
@dataclass
class WordMeta:
    word: str
    usage_count: int = 0
    quality: float = 0.5
    first_seen: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)

class DynamicVocab:
    def __init__(self, dim=EMBEDDING_DIM):
        self.dim = dim
        self.cur_size = INITIAL_VOCAB_SIZE
        self.max_size = MAX_VOCAB_SIZE
        self.embeddings = np.random.randn(INITIAL_VOCAB_SIZE, dim) * 0.01
        self.word2idx = {}
        self.idx2word = {}
        self.meta = {}
        self.next_idx = 0
        self.m = np.zeros_like(self.embeddings)
        self.v = np.zeros_like(self.embeddings)
        self.t = 0
        self._embed_cache = {}
        self._cache_order = []

    def _expand(self, new_size):
        if new_size > self.max_size:
            return False
        add = new_size - self.cur_size
        self.embeddings = np.vstack([self.embeddings, np.random.randn(add, self.dim) * 0.01])
        self.m = np.vstack([self.m, np.zeros((add, self.dim))])
        self.v = np.vstack([self.v, np.zeros((add, self.dim))])
        self.cur_size = new_size
        return True

    def add_word(self, word):
        w = word.lower()
        if w in self.word2idx:
            self.meta[w].usage_count += 1
            self.meta[w].last_used = time.time()
            return self.word2idx[w]
        if self.next_idx >= self.cur_size:
            if not self._expand(min(self.cur_size + VOCAB_EXPANSION_STEP, self.max_size)):
                return 0
        idx = self.next_idx
        self.word2idx[w] = idx
        self.idx2word[idx] = w
        self.meta[w] = WordMeta(word=w, usage_count=1)
        self.next_idx += 1
        return idx

    def get_embedding(self, word):
        return self.embeddings[self.add_word(word)].copy()

    def encode(self, text):
        cache_key = hashlib.md5(text.encode('utf-8')).hexdigest()
        if cache_key in self._embed_cache:
            return self._embed_cache[cache_key].copy()
        words = re.findall(r'\b\w+\b', text.lower())
        if not words:
            emb = np.zeros(self.dim)
        else:
            embs = [self.get_embedding(w) for w in words if len(w) > 2]
            emb = np.mean(embs, axis=0) if embs else np.zeros(self.dim)
        if len(self._embed_cache) >= 1000:
            oldest = self._cache_order.pop(0)
            del self._embed_cache[oldest]
        self._embed_cache[cache_key] = emb.copy()
        self._cache_order.append(cache_key)
        return emb

    def update_embedding(self, word, grad, lr):
        w = word.lower()
        if w not in self.word2idx:
            return
        idx = self.word2idx[w]
        self.t += 1
        b1, b2, eps = 0.9, 0.999, 1e-8
        self.m[idx] = b1 * self.m[idx] + (1 - b1) * grad
        self.v[idx] = b2 * self.v[idx] + (1 - b2) * (grad**2)
        mh = self.m[idx] / (1 - b1**self.t)
        vh = self.v[idx] / (1 - b2**self.t)
        self.embeddings[idx] -= lr * mh / (np.sqrt(vh) + eps)

    def update_quality(self, word, quality):
        w = word.lower()
        if w in self.meta:
            self.meta[w].quality = self.meta[w].quality * 0.85 + quality * 0.15

    def stats(self):
        avg_q = np.mean([m.quality for m in self.meta.values()]) if self.meta else 0.0
        return {'size': self.next_idx, 'capacity': self.cur_size, 'avg_quality': round(float(avg_q), 3)}

# ==================================================================
# 🧠 Память (без изменений)
# ==================================================================
@dataclass
class Concept:
    name: str
    definition: str
    embedding: np.ndarray
    confidence: float = 0.5

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
    search_meta: Optional[Dict] = None
    def decay(self):
        age_h = (time.time() - self.timestamp) / 3600
        self.importance *= math.exp(-FORGETTING_FACTOR * age_h / 24)
    def strengthen(self):
        self.importance = min(1.0, self.importance + 0.05)
        self.access_count += 1
        self.last_accessed = time.time()

class VectorMemory:
    def __init__(self, dim):
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
    def search(self, q, top_k=5):
        if self._dirty:
            self._rebuild()
        if not self.items:
            return []
        qn = q / (np.linalg.norm(q)+1e-8)
        norms = np.linalg.norm(self._mat, axis=1, keepdims=True)
        norms[norms==0] = 1e-8
        sim = (self._mat / norms) @ qn
        idx = np.argsort(sim)[::-1][:top_k]
        return [(self.items[i], float(sim[i])) for i in idx if sim[i] > 0.25]
    def consolidate(self, threshold):
        before = len(self.items)
        self.items = [i for i in self.items if i.importance >= threshold]
        if len(self.items) < before:
            self._dirty = True
    def get_all(self):
        return self.items

class CognitiveMemory:
    def __init__(self, embed_func):
        self.embed = embed_func
        self.episodic = VectorMemory(EMBEDDING_DIM)
        self.semantic = VectorMemory(EMBEDDING_DIM)
        self.working = deque(maxlen=WORKING_MEMORY_SIZE)
        self.total_searches = 0
    def add_episode(self, content, importance=0.5, emotional_valence=0.0, arousal=0.0, search_meta=None):
        emb = self.embed(content)
        self.episodic.add(Episode(content=content, timestamp=time.time(), embedding=emb,
                                  importance=importance, emotional_valence=emotional_valence,
                                  arousal=arousal, search_meta=search_meta))
        self.working.append(content)
    def recall(self, query, top_k=5):
        self.total_searches += 1
        return self.episodic.search(self.embed(query), top_k)
    def get_context(self, query):
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
    def stats(self):
        return {'episodes': len(self.episodic.items), 'concepts': len(self.semantic.items),
                'working': len(self.working), 'searches': self.total_searches}
    def save(self, path):
        def ep_dict(e):
            d = asdict(e)
            d['embedding'] = e.embedding.tolist()
            return d
        state = {'episodic': [ep_dict(e) for e in self.episodic.items],
                 'semantic': [{'name': c.name, 'definition': c.definition, 'embedding': c.embedding.tolist(), 'confidence': c.confidence} for c in self.semantic.items],
                 'working': list(self.working)}
        with gzip.open(path, 'wb') as f:
            pickle.dump(state, f)
    def load(self, path):
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
# Автономные компоненты (без изменений)
# ==================================================================
class LongTermPlanner:
    def __init__(self, assistant):
        self._assistant = assistant
        self._last_run = 0
        self._generated_goals = set()
    async def run(self, force=False):
        now = time.time()
        if not force and now - self._last_run < LONG_TERM_PLANNER_INTERVAL:
            return
        self._last_run = now
        try:
            trends = await self._fetch_trends()
            if not trends:
                return
            goals = await self._generate_goals_from_trends(trends)
            for goal in goals[:3]:
                if goal not in self._generated_goals:
                    self._generated_goals.add(goal)
                    if hasattr(self._assistant, 'hierarchical_planner'):
                        await self._assistant.hierarchical_planner.add_goal(goal)
                    logger.info(f"📌 Long-term goal added: {goal[:80]}")
        except Exception as e:
            logger.warning(f"LongTermPlanner error: {e}")
    async def _fetch_trends(self) -> List[str]:
        web_searcher = getattr(self._assistant, 'web_searcher', None)
        if web_searcher is None:
            return []
        topics = []
        try:
            agent = getattr(self._assistant, '_agent', None)
            if agent is not None and hasattr(agent, 'goals'):
                topics = [t for t, _ in sorted(agent.goals._topic_freq.items(), key=lambda x: -x[1])[:2]]
        except Exception:
            topics = []
        query = ("новости технологий " + " ".join(topics)) if topics else "актуальные технологические новости сегодня"
        try:
            results = await web_searcher._ddg_search(query, max_results=5)
        except Exception as e:
            logger.debug(f"LongTermPlanner._fetch_trends search failed: {e}")
            return []
        return [r["title"] for r in results if r.get("title")][:5]
    async def _generate_goals_from_trends(self, trends: List[str]) -> List[str]:
        prompt = "На основе следующих трендов сформулируй 3 конкретные исследовательские цели для AI-ассистента. Каждая цель должна быть измеримой и выполнимой за 1-2 дня.\nТренды: " + ", ".join(trends)
        response = await self._assistant._call_llm([{"role": "user", "content": prompt}])
        lines = [line.strip("-• ") for line in response.split("\n") if line.strip()]
        return lines[:3] if lines else ["Изучить влияние ИИ на образование"]

class ResourceManager:
    def __init__(self):
        self._call_counter = 0
        self._reset_time = time.time()
        self._budget = RESOURCE_BUDGET_LLM_CALLS
        self._pause_flag = False
    def allocate(self, priority: int = 0) -> bool:
        now = time.time()
        if now - self._reset_time > 3600:
            self._call_counter = 0
            self._reset_time = now
            self._pause_flag = False
        if self._pause_flag:
            return False
        if self._call_counter >= self._budget:
            self._pause_flag = True
            logger.warning("ResourceManager: budget exhausted, pausing non-critical tasks")
            return False
        self._call_counter += 1
        return True
    def release(self):
        self._call_counter = max(0, self._call_counter - 1)
    def is_paused(self) -> bool:
        return self._pause_flag
    def stats(self) -> Dict:
        return {"calls_used": self._call_counter, "budget": self._budget, "paused": self._pause_flag}

class MemoryConsolidator:
    def __init__(self, assistant):
        self._assistant = assistant
        self._last_run = 0
    async def run(self, force=False):
        now = time.time()
        if not force and now - self._last_run < SLEEP_CONSOLIDATION_INTERVAL:
            return
        self._last_run = now
        try:
            episodes = self._assistant.memory.episodic.get_all()
            if len(episodes) < 5:
                return
            clusters = self._cluster_episodes(episodes)
            for cluster in clusters:
                if len(cluster) > 1:
                    concept_text = await self._summarize_cluster(cluster)
                    emb = self._assistant.vocab.encode(concept_text)
                    self._assistant.memory.semantic.add(Concept(name=cluster[0].content[:30], definition=concept_text, embedding=emb, confidence=0.7))
                    for ep in cluster[1:]:
                        self._assistant.memory.episodic.items.remove(ep)
            logger.info(f"💤 Memory consolidation: {len(episodes)} → {len(self._assistant.memory.episodic.items)} episodes, {len(self._assistant.memory.semantic.items)} concepts")
        except Exception as e:
            logger.warning(f"MemoryConsolidator error: {e}")
    def _cluster_episodes(self, episodes, threshold=0.6) -> List[List[Episode]]:
        clusters = []
        for ep in episodes:
            added = False
            for cluster in clusters:
                if np.dot(ep.embedding, cluster[0].embedding) / (np.linalg.norm(ep.embedding)*np.linalg.norm(cluster[0].embedding)+1e-8) > threshold:
                    cluster.append(ep)
                    added = True
                    break
            if not added:
                clusters.append([ep])
        return clusters
    async def _summarize_cluster(self, cluster: List[Episode]) -> str:
        texts = [ep.content for ep in cluster[:5]]
        combined = "\n".join(texts)
        prompt = f"Обобщи следующие фрагменты в одно краткое определение (не более 30 слов):\n{combined}"
        return await self._assistant._call_llm([{"role": "user", "content": prompt}]) or "Обобщённый концепт"

class AnomalyDetector:
    def __init__(self, assistant):
        self._assistant = assistant
        self._quality_history = deque(maxlen=20)
        self._error_count = 0
        self._last_action = 0
    def observe(self, quality: float, error: bool = False):
        self._quality_history.append(quality)
        if error:
            self._error_count += 1
    async def check_and_correct(self):
        if len(self._quality_history) < 10:
            return
        recent = list(self._quality_history)[-10:]
        avg_recent = np.mean(recent)
        avg_old = np.mean(list(self._quality_history)[:10]) if len(self._quality_history) >= 20 else avg_recent
        drop = avg_old - avg_recent
        if drop > ANOMALY_THRESHOLD_QUALITY_DROP or self._error_count > 3:
            await self._apply_correction(drop)
            self._error_count = 0
    async def _apply_correction(self, drop):
        logger.warning(f"⚠️ Anomaly detected: quality drop {drop:.2f}. Applying correction.")
        self._assistant.cache.clear()
        self._assistant.image_cache.clear()
        self._assistant._llm_temperature = getattr(self._assistant, '_llm_temperature', 0.75)
        self._assistant._llm_temperature = max(0.2, self._assistant._llm_temperature - 0.1)
        if hasattr(self._assistant, 'reflective_action'):
            entry = await self._assistant.reflect.reflect(self._assistant.total_interactions, self._assistant._call_llm)
            if entry:
                await self._assistant.reflective_action.apply_reflection(entry)
        self._last_action = time.time()

class FactConflictResolver:
    def __init__(self, assistant):
        self._assistant = assistant
        self._fact_store = {}
    async def resolve(self, claim: str, sources: List[Tuple[str, float]]) -> str:
        key = hashlib.md5(claim.encode()).hexdigest()
        if key not in self._fact_store:
            self._fact_store[key] = {"value": claim, "sources": list(sources)}
        else:
            self._fact_store[key]["sources"].extend(sources)
        all_vals = [conf for _, conf in self._fact_store[key]["sources"]]
        avg_conf = float(np.mean(all_vals)) if all_vals else 0.0
        self._fact_store[key]["avg_confidence"] = avg_conf
        if len(all_vals) > 1 and float(np.std(all_vals)) > 0.3:
            logger.info(f"🔄 Fact conflict detected for '{claim[:50]}' (avg_conf={avg_conf:.2f}). Re-verifying...")
            src_lines = "\n".join(f"- {src}: уверенность {conf:.2f}" for src, conf in self._fact_store[key]["sources"])
            prompt = (f"Утверждение: '{claim}'\nИсточники и их уверенность:\n{src_lines}\n"
                      "Согласованы ли источники? Если нет — какой версии стоит доверять больше и почему? Ответь 1-2 предложениями.")
            resolution = await self._assistant._call_llm([{"role": "user", "content": prompt}])
            resolved_value = f"{claim} [средняя уверенность {avg_conf:.2f}; разброс мнений источников — {resolution[:150]}]"
            self._fact_store[key]["value"] = resolved_value
            return resolved_value
        return f"{claim} [уверенность {avg_conf:.2f}]" if avg_conf else claim

# ==================================================================
# 🤖 ОСНОВНОЙ АССИСТЕНТ с улучшениями
# ==================================================================
class SelfImprovingAssistant(EmergenceMixin):
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.vocab = DynamicVocab()
        self.subconscious = PromptAdvisor()
        self.memory = CognitiveMemory(self.vocab.encode)
        self.cache: Dict[str, Tuple[str, float]] = {}
        self.image_cache: Dict[str, Tuple[str, float]] = {}
        self.user_dir = MEMORY_BASE_DIR / user_id
        self.user_dir.mkdir(exist_ok=True)
        self.subconscious_path = self.user_dir / 'subconscious.pt'
        self.memory_path = self.user_dir / 'memory.pkl.gz'
        self.cache_path = self.user_dir / 'cache.pkl.gz'
        self.image_cache_path = self.user_dir / 'image_cache.pkl.gz'
        self._load()
        self.total_interactions = 0
        self.successful_learnings = 0
        self.current_lr = LEARNING_RATE
        self._agent = None
        self.web_searcher = AdaptiveWebSearch(self)
        self.init_emergence()
        self._quality_threshold = 0.4
        self._llm_temperature = 0.75
        self.long_term_planner = LongTermPlanner(self)
        self.resource_manager = ResourceManager()
        self.memory_consolidator = MemoryConsolidator(self)
        self.anomaly_detector = AnomalyDetector(self)
        self.fact_resolver = FactConflictResolver(self)
        # Новые компоненты
        self.confidence_classifier = ConfidenceClassifier()
        self._confidence_threshold = 0.55   # ниже этого порога – отказ от ответа или уточнение

        # Управление фоновыми задачами
        self._background_tasks = []
        self._stop_event = asyncio.Event()
        self._start_background_tasks()

    def _start_background_tasks(self):
        self._background_tasks.append(
            asyncio.create_task(self._autonomy_background_loop())
        )

    async def shutdown(self):
        self._stop_event.set()
        for task in self._background_tasks:
            task.cancel()
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        if hasattr(self, 'web_searcher'):
            await self.web_searcher.close()
        self._save()

    @property
    def agent(self):
        if self._agent is None:
            try:
                from agent_core import AutonomousAgent
                self._agent = AutonomousAgent(self)
            except ImportError as e:
                logger.warning(f"agent_core не найден: {e}")
                self._agent = None
        return self._agent

    def _load(self):
        if self.subconscious_path.exists():
            self.subconscious.load(self.subconscious_path)
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
        try:
            gkb = GlobalKnowledgeBase.get_instance()
            gkb.apply_global_vocab_to_local(self, alpha=GLOBAL_BLEND_ALPHA)
            if gkb._global_subconscious is not None:
                self.subconscious.apply_global_weights(gkb._global_subconscious, alpha=GLOBAL_BLEND_ALPHA)
        except Exception as e:
            logger.warning(f"Global KB apply on load failed: {e}")

    def _save(self):
        self.subconscious.save(self.subconscious_path)
        self.memory.save(self.memory_path)
        for path, attr in [(self.cache_path, 'cache'), (self.image_cache_path, 'image_cache')]:
            with gzip.open(path, 'wb') as f:
                pickle.dump(getattr(self, attr), f)

    def _cache_key(self, message, image_base64=None):
        if image_base64:
            img_hash = hashlib.md5(image_base64.encode()).hexdigest()[:16]
            return hashlib.md5(f"{message}|{img_hash}".encode()).hexdigest()
        return hashlib.md5(message.encode()).hexdigest()

    def get_subconscious_instruction(self, text: str, context: str = "") -> str:
        try:
            query_emb = self.vocab.encode(text)
            mem_emb = self.vocab.encode(context) if context else np.zeros(EMBEDDING_DIM)
            _, logits = self.subconscious.forward(query_emb, mem_emb)
            instruction, _ = self.subconscious.generate_prompt_instruction(logits)
            return instruction
        except Exception as e:
            logger.debug(f"get_subconscious_instruction error: {e}")
            return ""

    def _build_system_prompt(self, reasoning: bool, has_web: bool, sub_instruction: str = "") -> str:
        prompt = ("Ты — самообучающийся AI-ассистент с долговременной памятью и доступом к интернету.\n"
                  "Если передано изображение — внимательно опиши его и ответь на вопросы.\n"
                  "Отвечай естественно, полезно и по существу на языке пользователя.")
        if has_web:
            prompt += ("\n\n⚠️ ПРАВИЛА РАБОТЫ С ДАННЫМИ ИЗ ИНТЕРНЕТА:\n"
                       "1. Используй ТОЛЬКО данные из блока «РЕЗУЛЬТАТЫ ИНТЕЛЛЕКТУАЛЬНОГО ПОИСКА» ниже — не домысливай.\n"
                       "2. Если данные есть — процитируй конкретные цифры/факты и укажи источник.\n"
                       "3. Если данных НЕТ — честно сообщи: «Не удалось получить актуальные данные».\n")
        if reasoning:
            prompt += "\n\n🔍 РЕЖИМ РАССУЖДЕНИЙ:\nПеред ответом покажи цепочку мыслей.\n"
        if sub_instruction:
            prompt += f"\n\n{sub_instruction}"
        return prompt

    def _check_grounding(self, response: str, web_ctx: Optional[str]) -> bool:
        if not web_ctx:
            return True
        low = response.lower()
        honest = ("не удалось получить актуальные данные", "не нашёл", "не удалось найти",
                  "недостаточно данных", "не смог подтвердить")
        if any(m in low for m in honest):
            return True
        resp_emb = self.vocab.encode(response)
        ctx_emb = self.vocab.encode(web_ctx)
        rn, cn = np.linalg.norm(resp_emb), np.linalg.norm(ctx_emb)
        sim = float(np.dot(resp_emb, ctx_emb) / (rn * cn + 1e-8)) if rn > 1e-8 and cn > 1e-8 else 0.0
        resp_words = set(re.findall(r'\b[а-яёa-z]{4,}\b', low))
        ctx_words = set(re.findall(r'\b[а-яёa-z]{4,}\b', web_ctx.lower()))
        overlap = len(resp_words & ctx_words) / max(1, len(resp_words))
        return sim > 0.15 or overlap > 0.12

    async def _apply_reflection(self):
        entry = await self.reflect.reflect(self.total_interactions, self._call_llm)
        if entry:
            await self.reflective_action.apply_reflection(entry)

    async def _call_llm(self, messages: List[Dict]) -> str:
        if not self.resource_manager.allocate():
            logger.warning("Resource budget exhausted, returning placeholder")
            return "⚠️ Ресурсы временно исчерпаны, попробуйте позже."
        try:
            payload = {"messages": messages, "temperature": self._llm_temperature, "max_tokens": 2500, "stream": False}
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LM_STUDIO_API_KEY}"}
            async with aiohttp.ClientSession() as session:
                async with session.post(LM_STUDIO_URL, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=LM_STUDIO_TIMEOUT)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        try:
                            return data['choices'][0]['message']['content'].strip()
                        except Exception:
                            return data.get('choices', [{}])[0].get('text', '').strip()
                    else:
                        logger.error(f"LM Studio HTTP {resp.status}")
                        return ""
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"LLM call failed: {e}", exc_info=True)
            return ""
        except Exception as e:
            logger.exception("Unexpected error in LLM call")
            return ""
        finally:
            self.resource_manager.release()

    # ---- ВСПОМОГАТЕЛЬНЫЙ МЕТОД _prepare_request (с доработками) ----
    async def _prepare_request(self, message, image_base64=None, image_mime=None,
                               reasoning=False, web_search=False, url_to_fetch=None):
        explain_mode = message.strip().startswith(EXPLAIN_MODE_TRIGGER)
        if explain_mode:
            message = message[len(EXPLAIN_MODE_TRIGGER):].strip()

        web_ctx, search_meta, has_web = None, None, False
        if AUTO_SEARCH_ENABLED and not web_search and not url_to_fetch and not image_base64:
            mem_preview = self.memory.get_context(message)
            if self.web_searcher.should_search_fast(message, mem_preview):
                web_search = True
                logger.info(f"🔎 Auto-search triggered: {message[:60]}")

        if url_to_fetch:
            web_ctx, chunks = await self.web_searcher.fetch_single_url(url_to_fetch, message)
            has_web = True
            search_meta = {"type": "single_url", "url": url_to_fetch, "chunks_count": len(chunks)}
        elif web_search:
            web_ctx, chunks, meta = await self.web_searcher.iterative_search(message)
            has_web = True
            search_meta = meta

        mem_ctx = self.memory.get_context(message)
        query_emb = self.vocab.encode(message)
        memory_emb = self.vocab.encode(mem_ctx) if mem_ctx else np.zeros(EMBEDDING_DIM)
        latent, logits = self.subconscious.forward(query_emb, memory_emb)
        sub_instruction, chosen_indices = self.subconscious.generate_prompt_instruction(logits)

        # ---- ОЦЕНКА УВЕРЕННОСТИ ----
        meta_emb = np.array([len(message.split()), len(web_ctx) if web_ctx else 0, has_web, len(mem_ctx) if mem_ctx else 0])
        # Дополняем до 64 нулями
        meta_emb_pad = np.pad(meta_emb, (0, max(0, 64 - len(meta_emb))), 'constant')
        confidence = self.confidence_classifier.predict(query_emb, memory_emb, meta_emb_pad)
        # Если уверенность низкая – отключаем генерацию и вернём специальный ответ позже
        low_confidence = confidence < self._confidence_threshold

        content_parts = [{"type": "text", "text": message.strip()}]
        if web_ctx:
            content_parts[0]["text"] += f"\n\n{web_ctx}"
        if mem_ctx:
            content_parts[0]["text"] += f"\n\n{mem_ctx}"
        if image_base64 and image_mime and len(image_base64) <= MAX_IMAGE_SIZE_BASE64:
            content_parts.append({"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_base64}"}})

        system_prompt = self._build_system_prompt(reasoning, has_web, sub_instruction)
        if explain_mode:
            system_prompt += "\n\n🔎 РЕЖИМ ОБЪЯСНИМОСТИ: После ответа добавь краткое пояснение своего решения."
        if low_confidence:
            system_prompt += "\n\n⚠️ ВАЖНО: Уверенность в ответе низкая. Если данных недостаточно – честно сообщи об этом и предложи уточнить вопрос."

        messages_llm = [{"role": "system", "content": system_prompt}, {"role": "user", "content": content_parts}]
        ck = self._cache_key(message, image_base64)
        store = self.image_cache if image_base64 else self.cache

        return {
            'explain_mode': explain_mode,
            'web_ctx': web_ctx,
            'search_meta': search_meta,
            'has_web': has_web,
            'mem_ctx': mem_ctx,
            'query_emb': query_emb,
            'memory_emb': memory_emb,
            'sub_instruction': sub_instruction,
            'chosen_indices': chosen_indices,
            'system_prompt': system_prompt,
            'messages_llm': messages_llm,
            'ck': ck,
            'store': store,
            'confidence': confidence,
            'low_confidence': low_confidence,
        }

    # ---- get_response с пост-обработкой ----
    async def get_response(self, message: str, image_base64=None, image_mime=None,
                           reasoning=False, web_search=False, url_to_fetch=None) -> Tuple[str, Dict]:
        start = time.time()
        self.total_interactions += 1
        req = await self._prepare_request(message, image_base64, image_mime, reasoning, web_search, url_to_fetch)

        ck = req['ck']
        store = req['store']
        if ck in store and not req['has_web'] and not reasoning and not req['explain_mode']:
            cached, _ = store[ck]
            return cached, {'cached': True, 'response_time': time.time() - start}

        # Если уверенность низкая – сразу отказ
        if req['low_confidence'] and not req['has_web'] and not image_base64:
            response = "⚠️ У меня недостаточно информации, чтобы дать уверенный ответ. Пожалуйста, уточните вопрос или дайте больше контекста."
            # Обучаем классификатор на этом примере (target=0)
            self.confidence_classifier.train_on_log(req['query_emb'], req['memory_emb'],
                                                     np.pad(np.array([len(message.split()), 0, 0, 0]), (0, 60), 'constant'),
                                                     0.0)
            return response, {'confidence': req['confidence'], 'response_time': time.time() - start, 'low_confidence': True}

        response = await self._call_llm(req['messages_llm'])
        if not response:
            response = "⚠️ Не удалось получить ответ от модели."

        # ---- ВЕРИФИКАЦИЯ ФАКТОВ (если есть утверждения) ----
        if len(response.split()) > 30 and not image_base64:
            # Извлекаем потенциальные факты (простейший способ)
            facts = re.findall(r'[А-ЯЁA-Z][^.!?]*[.!?]', response)
            verified_facts = []
            for fact in facts[:3]:  # проверяем не более 3
                if len(fact) > 20:
                    is_true, conf, sources = await self.web_searcher.verify_claim(fact)
                    if not is_true and conf < 0.4:
                        # Помечаем как неподтверждённое
                        verified_facts.append((fact, False, conf))
                    else:
                        verified_facts.append((fact, True, conf))
            # Если есть неподтверждённые факты, добавляем предупреждение
            if any(not v[1] for v in verified_facts):
                response += "\n\n⚠️ Некоторые утверждения не удалось подтвердить по внешним источникам."

        grounded = self._check_grounding(response, req['web_ctx']) if req['has_web'] else True
        if req['has_web'] and not grounded:
            logger.warning(f"⚠️ Низкая заземлённость ответа: {message[:60]}")
            response += ("\n\n⚠️ Не удалось однозначно подтвердить часть этого ответа найденными источниками.")

        meta = {'complexity': min(1.0, len(message.split()) / 20),
                'web_search_used': req['has_web'],
                'response_length': len(response.split()),
                'grounded': grounded}
        reward = self.subconscious.compute_reward(response, meta)
        self.subconscious.learn(req['query_emb'], req['memory_emb'], req['chosen_indices'], reward)
        if self.total_interactions % REPLAY_FREQUENCY == 0:
            self.subconscious.experience_replay()

        quality = max(0.0, (reward + 1) / 2)
        error = any(err in response.lower() for err in ["ошибка", "извините", "не удалось"])
        self.anomaly_detector.observe(quality, error)
        asyncio.create_task(self.anomaly_detector.check_and_correct())

        # Обучение классификатора уверенности на обратной связи (цель – качество)
        meta_emb = np.array([len(message.split()), len(req['web_ctx']) if req['web_ctx'] else 0, req['has_web'],
                             len(req['mem_ctx']) if req['mem_ctx'] else 0])
        meta_emb_pad = np.pad(meta_emb, (0, max(0, 64 - len(meta_emb))), 'constant')
        self.confidence_classifier.train_on_log(req['query_emb'], req['memory_emb'], meta_emb_pad, quality)

        if quality > MIN_QUALITY_SCORE and grounded:
            self.memory.add_episode(f"Q: {message}\nA: {response}", importance=quality, search_meta=req['search_meta'])
            if not req['has_web'] and quality > 0.6:
                store[ck] = (response, time.time())
                if len(store) > 100:
                    oldest = min(store.items(), key=lambda x: x[1][1])[0]
                    del store[oldest]

        if quality >= MIN_GLOBAL_QUALITY and grounded:
            try:
                emb_contrib = self.vocab.encode(message + " " + response)
                asyncio.create_task(GlobalKnowledgeBase.get_instance().contribute(
                    user_id=self.user_id, content="Q: " + message + "\nA: " + response,
                    embedding=emb_contrib, importance=quality, assistant=self))
            except Exception as e:
                logger.debug(f"Global contribute failed: {e}")

        if self.total_interactions % SAVE_EVERY_N_INTERACTIONS == 0:
            self.memory.consolidate()
            self._save()

        asyncio.create_task(self.curiosity.check_and_research(message, response, meta))
        self.meta_learner.observe_quality(quality)

        if quality < 0.3 and random.random() < 0.1:
            reflection_entry = await self.reflect.reflect(self.total_interactions, self._call_llm)
            if reflection_entry:
                await self.reflective_action.apply_reflection(reflection_entry)

        if quality > 0.8 and len(response) > 100:
            key_fact = await self._extract_key_fact(response)
            if key_fact:
                self.message_bus.publish('global_fact', {'fact': key_fact, 'source': self.user_id})

        return response, {'quality': round(quality, 3), 'reward': round(reward, 3),
                          'response_time': time.time() - start,
                          'memory_episodes': len(self.memory.episodic.items),
                          'web_search_used': req['has_web'],
                          'search_meta': req['search_meta'],
                          'confidence': req['confidence']}

    # ---- stream_response с аналогичными улучшениями ----
    async def stream_response(self, message: str, image_base64=None, image_mime=None,
                              reasoning=False, web_search=False, url_to_fetch=None):
        start = time.time()
        self.total_interactions += 1
        req = await self._prepare_request(message, image_base64, image_mime, reasoning, web_search, url_to_fetch)

        ck = req['ck']
        store = req['store']
        if ck in store and not req['has_web'] and not reasoning and not req['explain_mode']:
            cached, _ = store[ck]
            yield f"data: {json.dumps({'token': cached})}\n\n"
            yield "data: [DONE]\n\n"
            return

        if req['low_confidence'] and not req['has_web'] and not image_base64:
            response = "⚠️ У меня недостаточно информации, чтобы дать уверенный ответ. Пожалуйста, уточните вопрос или дайте больше контекста."
            yield f"data: {json.dumps({'token': response})}\n\n"
            yield "data: [DONE]\n\n"
            self.confidence_classifier.train_on_log(req['query_emb'], req['memory_emb'],
                                                     np.pad(np.array([len(message.split()), 0, 0, 0]), (0, 60), 'constant'),
                                                     0.0)
            return

        payload = {"messages": req['messages_llm'], "temperature": self._llm_temperature,
                   "max_tokens": 2500, "stream": True}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LM_STUDIO_API_KEY}"}
        full_response = ""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(LM_STUDIO_URL, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=LM_STUDIO_STREAM_TIMEOUT)) as resp:
                    if resp.status != 200:
                        yield f"data: {json.dumps({'error': f'LM Studio error: {resp.status}'})}\n\n"
                        yield "data: [DONE]\n\n"
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
                                token = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                                if token:
                                    full_response += token
                                    yield f"data: {json.dumps({'token': token})}\n\n"
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.exception("Streaming error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"
            return

        if full_response:
            # Верификация фактов (упрощённо)
            if len(full_response.split()) > 30 and not image_base64:
                facts = re.findall(r'[А-ЯЁA-Z][^.!?]*[.!?]', full_response)
                verified_facts = []
                for fact in facts[:3]:
                    if len(fact) > 20:
                        is_true, conf, sources = await self.web_searcher.verify_claim(fact)
                        if not is_true and conf < 0.4:
                            verified_facts.append((fact, False, conf))
                        else:
                            verified_facts.append((fact, True, conf))
                if any(not v[1] for v in verified_facts):
                    full_response += "\n\n⚠️ Некоторые утверждения не удалось подтвердить по внешним источникам."

            grounded = self._check_grounding(full_response, req['web_ctx']) if req['has_web'] else True
            if req['has_web'] and not grounded:
                logger.warning(f"⚠️ Низкая заземлённость ответа (stream): {message[:60]}")
                full_response += ("\n\n⚠️ Не удалось однозначно подтвердить часть этого ответа найденными источниками.")

            meta = {'complexity': min(1.0, len(message.split()) / 20),
                    'web_search_used': req['has_web'],
                    'response_length': len(full_response.split()),
                    'grounded': grounded}
            reward = self.subconscious.compute_reward(full_response, meta)
            self.subconscious.learn(req['query_emb'], req['memory_emb'], req['chosen_indices'], reward)
            if self.total_interactions % REPLAY_FREQUENCY == 0:
                self.subconscious.experience_replay()
            quality = max(0.0, (reward + 1) / 2)

            error = any(err in full_response.lower() for err in ["ошибка", "извините", "не удалось"])
            self.anomaly_detector.observe(quality, error)
            asyncio.create_task(self.anomaly_detector.check_and_correct())

            meta_emb = np.array([len(message.split()), len(req['web_ctx']) if req['web_ctx'] else 0, req['has_web'],
                                 len(req['mem_ctx']) if req['mem_ctx'] else 0])
            meta_emb_pad = np.pad(meta_emb, (0, max(0, 64 - len(meta_emb))), 'constant')
            self.confidence_classifier.train_on_log(req['query_emb'], req['memory_emb'], meta_emb_pad, quality)

            if quality > MIN_QUALITY_SCORE and grounded:
                self.memory.add_episode(f"Q: {message}\nA: {full_response}", importance=quality,
                                        search_meta=req['search_meta'])
                if not req['has_web'] and quality > 0.6:
                    store[ck] = (full_response, time.time())
                    if len(store) > 100:
                        oldest = min(store.items(), key=lambda x: x[1][1])[0]
                        del store[oldest]

            if quality >= MIN_GLOBAL_QUALITY and grounded:
                try:
                    emb_contrib = self.vocab.encode(message + " " + full_response)
                    asyncio.create_task(GlobalKnowledgeBase.get_instance().contribute(
                        user_id=self.user_id, content="Q: " + message + "\nA: " + full_response,
                        embedding=emb_contrib, importance=quality, assistant=self))
                except Exception as e:
                    logger.debug(f"Global contribute failed: {e}")

            if self.total_interactions % SAVE_EVERY_N_INTERACTIONS == 0:
                self.memory.consolidate()
                self._save()

            asyncio.create_task(self.curiosity.check_and_research(message, full_response, meta))
            self.meta_learner.observe_quality(quality)

            if quality < 0.3 and random.random() < 0.1:
                reflection_entry = await self.reflect.reflect(self.total_interactions, self._call_llm)
                if reflection_entry:
                    await self.reflective_action.apply_reflection(reflection_entry)

            if quality > 0.8 and len(full_response) > 100:
                key_fact = await self._extract_key_fact(full_response)
                if key_fact:
                    self.message_bus.publish('global_fact', {'fact': key_fact, 'source': self.user_id})

        yield "data: [DONE]\n\n"

    # ---- Фоновый цикл автономности ----
    async def _autonomy_background_loop(self):
        while not self._stop_event.is_set():
            try:
                await self.long_term_planner.run()
                await self.memory_consolidator.run()
                await self.anomaly_detector.check_and_correct()
                self._save()
            except Exception as e:
                logger.warning(f"Autonomy background error: {e}")
            await asyncio.sleep(300)

    async def _extract_key_fact(self, text: str) -> Optional[str]:
        sentences = text.split('.')
        for s in sentences:
            if len(s) > 20 and ('является' in s or 'составляет' in s or 'равно' in s):
                return s.strip()
        return None

# ==================================================================
# 🌐 FastAPI роутер (без изменений)
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
    image_base64: Optional[str] = None
    image_mime: Optional[str] = None
    stream: bool = True
    reasoning: bool = False
    web_search: bool = False
    url_to_fetch: Optional[str] = None

class ImageGenRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = ""
    steps: int = EASYDIFFUSION_DEFAULT_STEPS
    width: int = EASYDIFFUSION_DEFAULT_WIDTH
    height: int = EASYDIFFUSION_DEFAULT_HEIGHT
    cfg_scale: float = 7.0
    seed: Optional[int] = None

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
            headers={"Cache-Control": "no-cache,no-store,must-revalidate", "X-Accel-Buffering": "no"}
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
        assistant = await get_assistant(address)
        content, chunks = await assistant.web_searcher.fetch_single_url(url, query or "URL content")
        return {"type": "url", "url": url, "content": content}
    if not query:
        return {"error": "query or url required"}
    from ddgs import DDGS
    results = []
    try:
        def sync_search():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=6))
        search_results = await asyncio.to_thread(sync_search)
        for r in search_results:
            results.append({'title': r.get('title', ''), 'url': r.get('href', ''), 'snippet': r.get('body', '')})
    except Exception as e:
        logger.warning(f"Search error: {e}")
    return {"type": "search", "query": query, "query_type": "general", "results": results, "special_data": None, "full_pages": ""}

@router.post("/classify")
async def classify_query_endpoint(body: dict, address: str = Depends(require_auth)):
    message = body.get("message", "").strip()
    if not message:
        return {"should_search": False, "query_type": "none"}
    msg_low = message.lower()
    keywords = ['курс', 'доллар', 'евро', 'биткоин', 'новости', 'погода', 'сегодня', 'последние', 'найди', 'поищи']
    should = any(k in msg_low for k in keywords)
    return {"should_search": should, "query_type": "auto"}

@router.post("/generate_image")
async def generate_image(body: ImageGenRequest, address: str = Depends(require_auth)):
    if not EASYDIFFUSION_ENABLED:
        raise HTTPException(503, "Image generation disabled")
    api_url = f"{EASYDIFFUSION_URL}/render"
    payload = {
        "prompt": body.prompt, "negative_prompt": body.negative_prompt or "",
        "width": body.width, "height": body.height, "num_inference_steps": body.steps,
        "guidance_scale": body.cfg_scale, "sampler_name": "euler_a", "seed": body.seed if body.seed is not None else -1,
        "clip_skip": True, "use_stable_diffusion_model": "fallenleafNSFWXLPony_v0620steps",
        "use_lora_model": "Realism Lora By Stable Yogi_V3_Lite", "use_vae_model": "",
    }
    headers = {"Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=EASYDIFFUSION_TIMEOUT)) as resp:
                if resp.status != 200:
                    raise HTTPException(502, "Image service error")
                raw_text = await resp.text()
                if raw_text.startswith("data: "):
                    raw_text = raw_text[6:].strip()
                data = json.loads(raw_text)
                if "queue" in data and "stream" in data:
                    stream_url = f"{EASYDIFFUSION_URL}{data['stream']}"
                    start_time = time.time()
                    while time.time() - start_time < EASYDIFFUSION_TIMEOUT:
                        await asyncio.sleep(1)
                        async with session.get(stream_url) as stream_resp:
                            if stream_resp.status != 200:
                                continue
                            stream_text = await stream_resp.text()
                            if stream_text.startswith("data: "):
                                stream_text = stream_text[6:].strip()
                            stream_data = json.loads(stream_text)
                            output = stream_data.get("output")
                            if output and isinstance(output, list) and len(output) > 0 and "data" in output[0]:
                                return {"image_base64": output[0]["data"], "cached": False}
                    raise HTTPException(504, "Timeout")
                output = data.get("output")
                if output and isinstance(output, list) and len(output) > 0 and "data" in output[0]:
                    return {"image_base64": output[0]["data"], "cached": False}
                raise HTTPException(500, "Unexpected response")
    except Exception as e:
        logger.exception("Image generation failed")
        raise HTTPException(500, str(e))

@router.post("/enhance_prompt")
async def enhance_prompt(body: dict, address: str = Depends(require_auth)):
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return {"enhanced": prompt}
    assistant = await get_assistant(address)
    system = "You are an expert prompt engineer. Convert user request into detailed English prompt for Stable Diffusion. Output ONLY the prompt."
    messages = [{"role": "system", "content": system}, {"role": "user", "content": f"User request: {prompt}"}]
    enhanced = await assistant._call_llm(messages)
    if not enhanced:
        enhanced = prompt
    return {"enhanced": enhanced.strip()}

@router.get("/global_stats")
async def global_knowledge_stats(address: str = Depends(require_auth)):
    gkb = GlobalKnowledgeBase.get_instance()
    assistant = await get_assistant(address)
    return {
        "global": gkb.stats(),
        "my_episodes": len(assistant.memory.episodic.items),
        "my_vocab_size": assistant.vocab.next_idx,
        "my_interactions": assistant.total_interactions,
        "my_lr": assistant.current_lr,
        "subconscious_updates": assistant.subconscious.total_updates,
        "resource_stats": assistant.resource_manager.stats(),
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
    gkb = GlobalKnowledgeBase.get_instance()
    assistant = await get_assistant(address)
    gkb.apply_global_vocab_to_local(assistant, alpha=GLOBAL_BLEND_ALPHA)
    if gkb._global_subconscious is not None:
        assistant.subconscious.apply_global_weights(gkb._global_subconscious, alpha=GLOBAL_BLEND_ALPHA)
    return {"status": "applied", "global_episodes": len(gkb._episodes), "global_vocab": len(gkb._global_embeddings)}

class AgentRequest(BaseModel):
    goal: str

@router.post("/agent/run")
async def agent_run_goal(body: AgentRequest, address: str = Depends(require_auth)):
    assistant = await get_assistant(address)
    if not assistant.agent:
        raise HTTPException(501, "Agent mode unavailable")
    result = await assistant.agent.run_goal(body.goal)
    return {"result": result}

@router.post("/research")
async def research_goal(body: AgentRequest, address: str = Depends(require_auth)):
    assistant = await get_assistant(address)
    if not assistant.agent:
        raise HTTPException(501, "Agent unavailable")
    if hasattr(assistant.agent, 'research'):
        result = await assistant.agent.research(body.goal)
        return result
    result = await assistant.agent.run_goal(body.goal)
    return {"answer": result}

def _shutdown_all():
    try:
        gkb = GlobalKnowledgeBase.get_instance()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(gkb.merge_all(list(_assistants.values())))
        loop.close()
        logger.info("Global merge on shutdown done")
    except Exception as e:
        logger.error(f"Shutdown merge failed: {e}")
    for uid, a in _assistants.items():
        try:
            a._save()
            if hasattr(a, 'web_searcher') and a.web_searcher.session:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(a.web_searcher.close())
                loop.close()
        except Exception as e:
            logger.error(f"Save failed {uid}: {e}")

_merge_task: Optional[asyncio.Task] = None

async def _auto_merge_loop():
    await asyncio.sleep(60)
    while True:
        try:
            gkb = GlobalKnowledgeBase.get_instance()
            async with _assistants_lock:
                all_assistants = list(_assistants.values())
            if all_assistants:
                await gkb.merge_all(all_assistants)
                logger.info("🌍 Auto-merge completed")
        except Exception as e:
            logger.error(f"Auto-merge error: {e}")
        await asyncio.sleep(GLOBAL_MERGE_INTERVAL)

def start_global_merge_task():
    global _merge_task
    if _merge_task is None:
        _merge_task = asyncio.create_task(_auto_merge_loop())
        logger.info("🌍 Global merge task started")

atexit.register(_shutdown_all)