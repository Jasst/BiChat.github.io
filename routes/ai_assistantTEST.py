"""
routes/ai_assistant.py — самообучающийся AI‑ассистент с многоуровневой памятью
Поддерживает потоковый ответ и долговременное запоминание.
"""

import logging
import json
import asyncio
import time
import hashlib
import gzip
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from collections import deque, defaultdict
from enum import Enum
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

EMBEDDING_DIM = 384
CACHE_TTL = 3600
MAX_CACHED_RESPONSES = 100

# Параметры памяти
MEMORY_DECAY_L1 = 0.99      # за минуту
MEMORY_DECAY_L2 = 0.95      # за час
MEMORY_DECAY_L3 = 0.999     # за день
FORGET_THRESHOLD = 0.1
CONSOLIDATION_THRESHOLD = 0.75
RELEVANCE_BOOST_ON_ACCESS = 0.1
MAX_WORKING_ITEMS = 10
MAX_SHORT_TERM_ITEMS = 200
MAX_LONG_TERM_ITEMS = 2000


class MemoryLevel(str, Enum):
    WORKING = "working"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


@dataclass
class MemoryItem:
    """Элемент памяти"""
    content: str
    level: MemoryLevel
    timestamp: float
    importance: float = 0.5
    quality: float = 0.5
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    embedding: Optional[np.ndarray] = None

    def decay(self, current_time: float) -> float:
        """Текущая релевантность с учётом забывания"""
        elapsed = current_time - self.last_accessed
        if self.level == MemoryLevel.WORKING:
            decay = MEMORY_DECAY_L1 ** (elapsed / 60)
        elif self.level == MemoryLevel.SHORT_TERM:
            decay = MEMORY_DECAY_L2 ** (elapsed / 3600)
        else:
            decay = MEMORY_DECAY_L3 ** (elapsed / 86400)
        base = self.importance * decay
        # бонус за частоту доступа
        access_bonus = min(0.3, self.access_count * 0.05)
        return min(1.0, base + access_bonus)

    def access(self):
        self.access_count += 1
        self.last_accessed = time.time()
        self.importance = min(1.0, self.importance + RELEVANCE_BOOST_ON_ACCESS)

    def promote(self):
        """Повысить уровень памяти"""
        if self.level == MemoryLevel.WORKING:
            self.level = MemoryLevel.SHORT_TERM
            self.importance = min(1.0, self.importance * 1.2)
        elif self.level == MemoryLevel.SHORT_TERM and self.importance > CONSOLIDATION_THRESHOLD:
            self.level = MemoryLevel.LONG_TERM
            self.importance = 1.0

    def should_forget(self, current_time: float) -> bool:
        return self.decay(current_time) < FORGET_THRESHOLD


# ═══════════════════════════════════════════════════════════════
# 🧠 Эмбеддинги (хеш‑трюк)
# ═══════════════════════════════════════════════════════════════
def simple_embed(text: str, dim: int = EMBEDDING_DIM) -> np.ndarray:
    words = text.lower().split()
    vec = np.zeros(dim)
    for w in words:
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        for i in range(5):
            idx = (h + i) % dim
            vec[idx] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


# ═══════════════════════════════════════════════════════════════
# 📚 Многоуровневая память
# ═══════════════════════════════════════════════════════════════
class MultiLevelMemory:
    def __init__(self, embedding_func):
        self.embed_func = embedding_func
        self.working: List[MemoryItem] = []          # L1
        self.short_term: List[MemoryItem] = []       # L2
        self.long_term: Dict[str, MemoryItem] = {}   # L3 (индекс по хешу)

    def add(self, content: str, importance: float = 0.5, quality: float = 0.5, level: MemoryLevel = MemoryLevel.WORKING):
        emb = self.embed_func(content)
        item = MemoryItem(
            content=content,
            level=level,
            timestamp=time.time(),
            importance=importance,
            quality=quality,
            embedding=emb
        )
        if level == MemoryLevel.WORKING:
            self.working.append(item)
            if len(self.working) > MAX_WORKING_ITEMS:
                self.working.sort(key=lambda x: x.decay(time.time()), reverse=True)
                self.working = self.working[:MAX_WORKING_ITEMS]
        elif level == MemoryLevel.SHORT_TERM:
            self.short_term.append(item)
            if len(self.short_term) > MAX_SHORT_TERM_ITEMS:
                self.short_term.sort(key=lambda x: x.decay(time.time()), reverse=True)
                self.short_term = self.short_term[:MAX_SHORT_TERM_ITEMS]
        else:
            mem_id = hashlib.md5(content.encode()).hexdigest()[:16]
            self.long_term[mem_id] = item
            if len(self.long_term) > MAX_LONG_TERM_ITEMS:
                to_del = sorted(self.long_term.items(), key=lambda kv: kv[1].decay(time.time()))[:100]
                for mid, _ in to_del:
                    del self.long_term[mid]

    def search(self, query: str, top_k: int = 5) -> List[Tuple[MemoryItem, float]]:
        """Семантический поиск по всем уровням"""
        q_emb = self.embed_func(query)
        results = []

        # L3 (долговременная)
        for item in self.long_term.values():
            if item.embedding is not None:
                sim = np.dot(q_emb, item.embedding)
                # учитываем релевантность и качество
                score = sim * (0.6 + 0.2 * item.decay(time.time()) + 0.2 * item.quality)
                results.append((item, score))

        # L2 (краткосрочная)
        for item in self.short_term:
            if item.embedding is not None:
                sim = np.dot(q_emb, item.embedding)
                score = sim * (0.6 + 0.2 * item.decay(time.time()) + 0.2 * item.quality)
                results.append((item, score))

        # L1 (рабочая) – последние, высокий вес
        for item in self.working:
            if item.embedding is not None:
                sim = np.dot(q_emb, item.embedding)
                score = sim * 0.9 + 0.1 * item.importance  # рабочие почти всегда актуальны
                results.append((item, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def access_item(self, item: MemoryItem):
        item.access()

    def consolidate(self):
        """Продвижение важных воспоминаний на следующий уровень"""
        # L1 → L2
        promoted = []
        for item in self.working[:]:
            if item.importance > CONSOLIDATION_THRESHOLD:
                item.promote()
                if item.level == MemoryLevel.SHORT_TERM:
                    self.short_term.append(item)
                    promoted.append(item)
        for item in promoted:
            self.working.remove(item)

        # L2 → L3
        promoted = []
        for item in self.short_term[:]:
            if item.importance > CONSOLIDATION_THRESHOLD:
                item.promote()
                if item.level == MemoryLevel.LONG_TERM:
                    mem_id = hashlib.md5(item.content.encode()).hexdigest()[:16]
                    self.long_term[mem_id] = item
                    promoted.append(item)
        for item in promoted:
            self.short_term.remove(item)

    def forget(self):
        """Удаление забытых воспоминаний"""
        now = time.time()
        # L2
        self.short_term = [item for item in self.short_term if not item.should_forget(now)]
        # L3
        to_del = [mid for mid, item in self.long_term.items() if item.should_forget(now)]
        for mid in to_del:
            del self.long_term[mid]
        # L1 не забываем полностью, но он ограничен размером

    def get_context_string(self, query: str, max_length: int = 500) -> str:
        relevant = self.search(query, top_k=5)
        if not relevant:
            return ""
        lines = []
        total = 0
        for item, score in relevant:
            snippet = f"[{item.level.value[:3]}] {item.content[:150]}"
            if total + len(snippet) > max_length:
                break
            lines.append(snippet)
            total += len(snippet)
        return "\n".join(lines)

    def save(self, path: Path):
        state = {
            'working': [{'content': i.content, 'level': i.level.value, 'timestamp': i.timestamp,
                         'importance': i.importance, 'quality': i.quality,
                         'access_count': i.access_count, 'last_accessed': i.last_accessed}
                        for i in self.working],
            'short_term': [{'content': i.content, 'level': i.level.value, 'timestamp': i.timestamp,
                            'importance': i.importance, 'quality': i.quality,
                            'access_count': i.access_count, 'last_accessed': i.last_accessed}
                           for i in self.short_term],
            'long_term': {mid: {'content': i.content, 'level': i.level.value, 'timestamp': i.timestamp,
                                'importance': i.importance, 'quality': i.quality,
                                'access_count': i.access_count, 'last_accessed': i.last_accessed}
                          for mid, i in self.long_term.items()}
        }
        with gzip.open(path, 'wb') as f:
            pickle.dump(state, f)

    def load(self, path: Path):
        if not path.exists():
            return
        with gzip.open(path, 'rb') as f:
            state = pickle.load(f)
        self.working = [MemoryItem(**{**d, 'level': MemoryLevel(d['level'])}) for d in state['working']]
        self.short_term = [MemoryItem(**{**d, 'level': MemoryLevel(d['level'])}) for d in state['short_term']]
        self.long_term = {}
        for mid, d in state['long_term'].items():
            self.long_term[mid] = MemoryItem(**{**d, 'level': MemoryLevel(d['level'])})
        # пересчитать эмбеддинги
        for i in self.working + self.short_term + list(self.long_term.values()):
            i.embedding = self.embed_func(i.content)


# ═══════════════════════════════════════════════════════════════
# 🤖 Самообучающийся ассистент (с памятью и кэшем)
# ═══════════════════════════════════════════════════════════════
class SelfImprovingAssistant:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.memory = MultiLevelMemory(simple_embed)
        self.cache: Dict[str, Tuple[str, float]] = {}
        self.user_dir = MEMORY_BASE_DIR / user_id
        self.user_dir.mkdir(exist_ok=True)
        self.memory_file = self.user_dir / 'memory_v2.pkl.gz'
        self.cache_file = self.user_dir / 'cache.pkl.gz'
        self._load()

    def _load(self):
        self.memory.load(self.memory_file)
        if self.cache_file.exists():
            try:
                with gzip.open(self.cache_file, 'rb') as f:
                    self.cache = pickle.load(f)
                now = time.time()
                self.cache = {k: (resp, ts) for k, (resp, ts) in self.cache.items() if now - ts < CACHE_TTL}
            except:
                pass

    def _save(self):
        self.memory.save(self.memory_file)
        with gzip.open(self.cache_file, 'wb') as f:
            pickle.dump(self.cache, f)

    def _get_cache_key(self, msg: str) -> str:
        return hashlib.md5(msg.encode()).hexdigest()

    async def get_context_and_prompt(self, message: str):
        """Возвращает (system_prompt, user_prompt, cached_response, is_cached)"""
        cache_key = self._get_cache_key(message)
        if cache_key in self.cache:
            cached_response, ts = self.cache[cache_key]
            return None, None, cached_response, True

        # RAG – извлекаем контекст
        context = self.memory.get_context_string(message)
        system = """Ты — самообучающийся AI-ассистент с долговременной памятью.
Используй предоставленный контекст из памяти, чтобы отвечать персонализированно.
Если не уверен — задай уточняющий вопрос."""
        user = f"""Вопрос: {message}

=== Память ===
{context if context else "Нет релевантных воспоминаний."}

Ответ (3-5 предложений):"""
        return system, user, None, False

    async def store_interaction(self, message: str, response: str, quality: float):
        if quality > 0.5:
            # добавляем в рабочую память (L1)
            self.memory.add(
                f"User: {message}\nAssistant: {response}",
                importance=quality,
                quality=quality,
                level=MemoryLevel.WORKING
            )
            # кэшируем хорошие ответы
            if quality > 0.7:
                key = self._get_cache_key(message)
                self.cache[key] = (response, time.time())
                if len(self.cache) > MAX_CACHED_RESPONSES:
                    oldest = min(self.cache.items(), key=lambda x: x[1][1])[0]
                    del self.cache[oldest]
        # периодическая консолидация и забывание (каждые 10 сохранений)
        if len(self.memory.working) % 10 == 0:
            self.memory.consolidate()
            self.memory.forget()
        self._save()

    @staticmethod
    def estimate_quality(user_msg: str, assistant_msg: str) -> float:
        if len(assistant_msg) < 10:
            return 0.2
        if any(w in assistant_msg.lower() for w in ['ошибка', 'извините', 'не удалось']):
            return 0.3
        score = min(1.0, len(assistant_msg) / 300)
        if any(w in assistant_msg.lower() for w in ['совет', 'помощь', 'рекомендую']):
            score += 0.2
        return min(1.0, score)


# Глобальный менеджер
_assistants: Dict[str, SelfImprovingAssistant] = {}
_assistants_lock = asyncio.Lock()

async def get_assistant(user_id: str) -> SelfImprovingAssistant:
    async with _assistants_lock:
        if user_id not in _assistants:
            _assistants[user_id] = SelfImprovingAssistant(user_id)
        return _assistants[user_id]


# ═══════════════════════════════════════════════════════════════
# 📡 API ENDPOINTS
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
            stream_with_memory(body.message, address),
            media_type="text/event-stream"
        )
    else:
        assistant = await get_assistant(address)
        system, user, cached, is_cached = await assistant.get_context_and_prompt(body.message)
        if is_cached:
            return {"reply": cached}
        response = await call_llm(system, user)
        quality = assistant.estimate_quality(body.message, response)
        await assistant.store_interaction(body.message, response, quality)
        return {"reply": response}


async def call_llm(system: str, user: str) -> str:
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": 0.7,
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
                return "⚠️ Ошибка AI-сервера."


async def stream_with_memory(message: str, user_id: str):
    """Потоковый ответ с сохранением в память"""
    assistant = await get_assistant(user_id)
    system, user, cached, is_cached = await assistant.get_context_and_prompt(message)
    if is_cached:
        yield f"data: {json.dumps({'token': cached})}\n\n"
        yield "data: [DONE]\n\n"
        return

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    payload = {
        "messages": messages,
        "temperature": 0.7,
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
            # сохраняем взаимодействие
            quality = assistant.estimate_quality(message, full_response)
            await assistant.store_interaction(message, full_response, quality)
            yield "data: [DONE]\n\n"