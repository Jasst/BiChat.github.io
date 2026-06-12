"""
routes/ai_assistant.py — Самообучающийся AI-ассистент с памятью, нейросетью,
поддержкой изображений и веб-поиском через ddgs (duckduckgo-search)
Версия: 7.0 (подсознание + глобальное обучение)
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
from typing import Dict, List, Optional, Tuple, Any, Callable
from collections import deque
from dataclasses import dataclass, field, asdict
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import aiohttp
from ddgs import DDGS
import sys

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
LATENT_DIM = 64
LEARNING_RATE = 0.0005
REPLAY_BATCH_SIZE = 32
REPLAY_FREQUENCY = 10

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

SEARCH_CACHE_TTL = 300
_search_cache: Dict[str, Tuple[str, float]] = {}

MAX_PAGES_TO_FETCH = 7
PAGE_CONTENT_MAX_CHARS = 6000

# Глобальное обучение
GLOBAL_KNOWLEDGE_DIR = Path("ai_memory_v3/_global")
GLOBAL_KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

GLOBAL_VOCAB_PATH       = GLOBAL_KNOWLEDGE_DIR / "vocab.pkl.gz"
GLOBAL_SUBCONSCIOUS_PATH = GLOBAL_KNOWLEDGE_DIR / "subconscious.pt"
GLOBAL_EPISODES_PATH    = GLOBAL_KNOWLEDGE_DIR / "episodes.pkl.gz"
GLOBAL_MERGE_LOG_PATH   = GLOBAL_KNOWLEDGE_DIR / "merge_log.jsonl"
GLOBAL_STATS_PATH       = GLOBAL_KNOWLEDGE_DIR / "stats.json"

MERGE_TOP_EPISODES_PER_USER = 20
GLOBAL_BLEND_ALPHA      = 0.3   # 30% глобального, 70% личного
MIN_GLOBAL_QUALITY      = 0.55
GLOBAL_MERGE_INTERVAL   = 1800
MAX_GLOBAL_EPISODES     = 5000

# ==================================================================
# 🧠 Подсознание (влияет на LLM через контекст)
# ==================================================================
class Subconscious(nn.Module):
    """
    Генерирует латентный вектор (подсознание) на основе эмбеддингов запроса и памяти.
    Декодирует его в текстовую инструкцию для системного промпта.
    Обучается через REINFORCE с наградой от качества ответа LLM.
    """
    def __init__(self, input_dim=EMBEDDING_DIM, latent_dim=LATENT_DIM, hidden=128):
        super().__init__()
        self.latent_dim = latent_dim
        self.input_dim = input_dim
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
            "Инициатива: предложи пользователю новую тему.",
        ]
        self.vocab_size = len(self.prompt_vocab)

        # Кодировщик: запрос + память + прошлое состояние
        self.encoder = nn.Sequential(
            nn.Linear(input_dim * 2 + latent_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, latent_dim)
        )
        # Декодер для выбора фраз
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, self.vocab_size)
        )
        # Рекуррентное состояние (персистентное)
        self.register_buffer('latent_state', torch.zeros(1, latent_dim))

        # Оптимизатор и буфер воспроизведения
        self.optimizer = torch.optim.Adam(self.parameters(), lr=LEARNING_RATE)
        self.replay_buffer = deque(maxlen=200)  # (query_emb, memory_emb, chosen_indices, reward)
        self.total_updates = 0

    def forward(self, query_emb: torch.Tensor, memory_emb: torch.Tensor):
        # query_emb, memory_emb: (1, input_dim)
        x = torch.cat([query_emb, memory_emb, self.latent_state], dim=-1)
        latent = self.encoder(x)                     # (1, latent_dim)
        self.latent_state = latent.detach()
        logits = self.decoder(latent)                # (1, vocab_size)
        return latent, logits

    def generate_prompt_instruction(self, logits: torch.Tensor) -> Tuple[str, List[int]]:
        probs = torch.softmax(logits.squeeze(), dim=-1)
        # Выбираем 1–3 фразы с вероятностями
        num = random.choices([1, 2, 3], weights=[0.5, 0.3, 0.2])[0]
        indices = torch.multinomial(probs, num, replacement=False).tolist()
        selected = [self.prompt_vocab[i] for i in indices]
        instruction = "### Подсознание (внутренний голос):\n" + "\n".join(f"- {s}" for s in selected)
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
        # Награда за использование глобальных знаний
        if "глобальной базы" in response or "сообщество" in response:
            score += 0.1
        return np.clip(score, -1.0, 1.0)

    def learn(self, query_emb: torch.Tensor, memory_emb: torch.Tensor,
              chosen_indices: List[int], reward: float):
        # REINFORCE: увеличиваем логарифм вероятности выбранных фраз, масштабируя на reward
        _, logits = self.forward(query_emb, memory_emb)
        probs = torch.softmax(logits.squeeze(), dim=-1)
        log_prob = 0.0
        for idx in chosen_indices:
            log_prob += torch.log(probs[idx] + 1e-8)
        loss = -log_prob * reward
        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.parameters(), 1.0)
        self.optimizer.step()
        self.total_updates += 1

        # Сохраняем в буфер воспроизведения
        self.replay_buffer.append((query_emb.detach().cpu().numpy(),
                                   memory_emb.detach().cpu().numpy(),
                                   chosen_indices, reward))

    def experience_replay(self):
        if len(self.replay_buffer) < REPLAY_BATCH_SIZE:
            return
        batch = random.sample(self.replay_buffer, REPLAY_BATCH_SIZE)
        total_loss = 0.0
        for q_np, m_np, indices, rew in batch:
            q = torch.tensor(q_np, dtype=torch.float32)
            m = torch.tensor(m_np, dtype=torch.float32)
            _, logits = self.forward(q, m)
            probs = torch.softmax(logits.squeeze(), dim=-1)
            log_prob = sum(torch.log(probs[i] + 1e-8) for i in indices)
            loss = -log_prob * rew
            total_loss += loss
        if total_loss != 0.0:
            self.optimizer.zero_grad()
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(self.parameters(), 1.0)
            self.optimizer.step()

    def save(self, path: Path):
        torch.save({
            'state_dict': self.state_dict(),
            'latent_state': self.latent_state,
            'total_updates': self.total_updates,
        }, path)

    def load(self, path: Path):
        if path.exists():
            data = torch.load(path, map_location='cpu')
            self.load_state_dict(data['state_dict'])
            self.latent_state = data['latent_state']
            self.total_updates = data['total_updates']

    def get_latent(self) -> np.ndarray:
        return self.latent_state.squeeze().detach().cpu().numpy()

    def apply_global_weights(self, global_net: 'Subconscious', alpha=GLOBAL_BLEND_ALPHA):
        """Смешивает веса локальной сети с глобальной (Federated Averaging)."""
        for local_param, global_param in zip(self.parameters(), global_net.parameters()):
            local_param.data = (1 - alpha) * local_param.data + alpha * global_param.data

# ==================================================================
# 🌍 Глобальная база коллективных знаний (обезличенная)
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
        self._global_subconscious: Optional[Subconscious] = None
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
        # Загрузка эпизодов
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

        # Загрузка глобальной подсознательной модели
        if GLOBAL_SUBCONSCIOUS_PATH.exists():
            try:
                self._global_subconscious = Subconscious()
                self._global_subconscious.load(GLOBAL_SUBCONSCIOUS_PATH)
            except Exception as e:
                logger.error(f"GlobalKB subconscious load error: {e}")

        # Загрузка глобального словаря
        if GLOBAL_VOCAB_PATH.exists():
            try:
                with gzip.open(GLOBAL_VOCAB_PATH, 'rb') as f:
                    s = pickle.load(f)
                self._global_embeddings = {k: np.array(v) for k, v in s['embeddings'].items()}
                self._global_word_counts = s['counts']
            except Exception as e:
                logger.error(f"GlobalKB vocab load error: {e}")

        # Статистика
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
            # Эпизоды
            raw = [{
                'content_hash': ep.content_hash,
                'embedding': ep.embedding.tolist(),
                'importance': ep.importance,
                'topic_tags': ep.topic_tags,
                'timestamp': ep.timestamp,
                'contributor_hash': ep.contributor_hash,
                'usage_count': ep.usage_count,
            } for ep in self._episodes]
            with gzip.open(GLOBAL_EPISODES_PATH, 'wb') as f:
                pickle.dump(raw, f)

            # Глобальная подсознательная модель
            if self._global_subconscious is not None:
                self._global_subconscious.save(GLOBAL_SUBCONSCIOUS_PATH)

            # Словарь
            with gzip.open(GLOBAL_VOCAB_PATH, 'wb') as f:
                pickle.dump({
                    'embeddings': {k: v.tolist() for k, v in self._global_embeddings.items()},
                    'counts': self._global_word_counts,
                }, f)

            # Статы
            with open(GLOBAL_STATS_PATH, 'w', encoding='utf-8') as f:
                json.dump({
                    'contributors': self.total_contributors,
                    'merges': self.total_merges,
                    'episodes_added': self.total_episodes_added,
                    'last_merge': self.last_merge_time,
                }, f, ensure_ascii=False, indent=2)
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
            ep = GlobalEpisode(
                content_hash=c_hash,
                embedding=embedding.copy(),
                importance=importance,
                topic_tags=topics,
                timestamp=time.time(),
                contributor_hash=u_hash,
            )
            self._episodes.append(ep)
            self._dirty = True
            self.total_episodes_added += 1

            # Обновляем глобальный словарь (running average)
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
                        self._global_embeddings[word] = local_emb.copy()
                        self._global_word_counts[word] = 1

            # Ограничиваем количество эпизодов
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
        if self._episodes:
            self._mat = np.vstack([ep.embedding for ep in self._episodes])
        else:
            self._mat = np.zeros((0, EMBEDDING_DIM))
        self._dirty = False

    async def merge_all(self, assistants: List['SelfImprovingAssistant']) -> Dict:
        async with self.get_lock():
            t0 = time.time()
            # 1. Сбор эпизодов от всех пользователей
            episodes_added = 0
            contributor_ids = set()
            for a in assistants:
                contributor_ids.add(a.user_id)
                top_eps = sorted(a.memory.episodic.items, key=lambda e: e.importance, reverse=True)[:MERGE_TOP_EPISODES_PER_USER]
                for ep in top_eps:
                    added = await self.contribute(a.user_id, ep.content, ep.embedding, ep.importance, a)
                    if added:
                        episodes_added += 1

            # 2. Федеративное усреднение подсознания
            if assistants and all(hasattr(a, 'subconscious') for a in assistants):
                # Усредняем веса всех локальных подсознаний в глобальную модель
                if self._global_subconscious is None:
                    self._global_subconscious = Subconscious()
                # Сбросить веса в ноль, потом накопить
                for param in self._global_subconscious.parameters():
                    param.data.zero_()
                total_weight = 0.0
                for a in assistants:
                    weight = a.subconscious.total_updates + 1
                    for global_param, local_param in zip(self._global_subconscious.parameters(), a.subconscious.parameters()):
                        global_param.data += weight * local_param.data
                    total_weight += weight
                if total_weight > 0:
                    for param in self._global_subconscious.parameters():
                        param.data /= total_weight

                # Применяем глобальную модель к каждому локальному ассистенту
                for a in assistants:
                    a.subconscious.apply_global_weights(self._global_subconscious, alpha=GLOBAL_BLEND_ALPHA)

            # 3. Применяем глобальный словарь к локальным
            for a in assistants:
                self.apply_global_vocab_to_local(a)

            self.total_contributors = max(self.total_contributors, len(contributor_ids))
            self.total_merges += 1
            self.last_merge_time = time.time()
            self._save()

            elapsed = time.time() - t0
            result = {
                'episodes_added': episodes_added,
                'total_episodes': len(self._episodes),
                'global_vocab': len(self._global_embeddings),
                'contributors': len(contributor_ids),
                'merge_time_s': round(elapsed, 2),
            }
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
        return {
            'total_episodes': len(self._episodes),
            'global_vocab_size': len(self._global_embeddings),
            'total_contributors': self.total_contributors,
            'total_merges': self.total_merges,
            'episodes_added': self.total_episodes_added,
            'last_merge': self.last_merge_time,
            'has_global_subconscious': self._global_subconscious is not None,
        }

# ==================================================================
# 🌐 Веб-поиск (без изменений)
# ==================================================================
class WebSearchTool:
    FETCH_TIMEOUT = 12
    MAX_PAGE_CHARS = 4000
    MAX_RESULTS = 6
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    }

    @classmethod
    def classify_query(cls, message: str) -> Tuple[str, str]:
        msg = message.lower().strip()
        if re.search(r'https?://[^\s]+', message):
            return 'url', re.search(r'https?://[^\s]+', message).group(0)
        if re.search(r'\bкурс\b|\bдолл[ао]р|\bевро\b|\busd\b|\bбитко[йи]н', msg):
            return 'currency', msg
        if re.search(r'\bпогод[аеу]\b|\bweather\b|\bтемператур', msg):
            return 'weather', msg
        if re.search(r'\bновост[иь]\b|\bnews\b|\bпоследн[иеяь]', msg):
            return 'news', msg
        if re.search(r'\bпоищи\b|\bнайди\b|\bчто такое\b|\bwho is\b|\bгде\b', msg):
            return 'general', msg
        return 'none', msg

    @classmethod
    async def get_currency_rates(cls) -> Optional[Dict]:
        try:
            async with aiohttp.ClientSession(headers=cls.HEADERS) as session:
                async with session.get("https://www.cbr.ru/scripts/XML_daily.asp", timeout=aiohttp.ClientTimeout(total=cls.FETCH_TIMEOUT)) as resp:
                    if resp.status == 200:
                        text = await resp.text(encoding='windows-1251', errors='replace')
                        rates = {}
                        for valute in re.finditer(r'<CharCode>(\w+)</CharCode>.*?<Name>(.*?)</Name>.*?<Nominal>(\d+)</Nominal>.*?<Value>([\d,]+)</Value>', text, re.DOTALL):
                            code, name, nominal, value = valute.groups()
                            val = float(value.replace(',', '.'))
                            nom = int(nominal)
                            rates[code] = {'name': name.strip(), 'rate': round(val,4), 'nominal': nom, 'per_unit': round(val/nom,4)}
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
            params = {"ids": "bitcoin,ethereum,tether,binancecoin,solana,ripple", "vs_currencies": "usd,rub", "include_24hr_change": "true"}
            async with aiohttp.ClientSession(headers=cls.HEADERS) as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=cls.FETCH_TIMEOUT)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        names = {'bitcoin':'Bitcoin (BTC)','ethereum':'Ethereum (ETH)','tether':'Tether (USDT)','binancecoin':'BNB','solana':'Solana (SOL)','ripple':'XRP'}
                        lines = ["=== КУРСЫ КРИПТОВАЛЮТ (CoinGecko) ==="]
                        for coin_id, info in data.items():
                            name = names.get(coin_id, coin_id)
                            usd = info.get('usd', '?')
                            rub = info.get('rub', '?')
                            change = info.get('usd_24h_change', 0)
                            sign = '+' if change and change>0 else ''
                            change_str = f" ({sign}{change:.1f}% за 24ч)" if change else ""
                            lines.append(f"  {name}: ${usd:,.2f} / ₽{rub:,.0f}{change_str}")
                        return '\n'.join(lines)
        except Exception as e:
            logger.warning(f"CoinGecko error: {e}")
        return None

    @classmethod
    async def _ddg_search(cls, query: str) -> List[Dict]:
        results = []
        try:
            def sync_search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=cls.MAX_RESULTS))
            search_results = await asyncio.to_thread(sync_search)
            for r in search_results:
                results.append({'title': r.get('title', '')[:120], 'url': r.get('href', ''), 'snippet': r.get('body', '')[:500]})
        except Exception as e:
            logger.warning(f"DDGS search error: {e}")
        return results

    @classmethod
    async def fetch_url(cls, url: str) -> str:
        if not url.startswith(('http://','https://')):
            return ""
        try:
            async with aiohttp.ClientSession(headers=cls.HEADERS) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=cls.FETCH_TIMEOUT), allow_redirects=True, ssl=False) as resp:
                    if resp.status != 200:
                        return f"[HTTP {resp.status}]"
                    ct = resp.headers.get("Content-Type", "")
                    if "text" not in ct and "json" not in ct:
                        return f"[Binary: {ct}]"
                    html = await resp.text(errors="replace")
                    text = re.sub(r'<[^>]+>', ' ', html)
                    text = re.sub(r'\s+', ' ', text).strip()
                    return text[:cls.MAX_PAGE_CHARS]
        except asyncio.TimeoutError:
            return "[Timeout]"
        except Exception as e:
            return f"[Ошибка: {e}]"

    @classmethod
    async def fetch_multiple_pages(cls, results: List[Dict], limit: int = MAX_PAGES_TO_FETCH) -> str:
        if not results:
            return ""
        to_fetch = [(r.get('title','Без названия'), r['url']) for r in results if r.get('url','').startswith(('http://','https://'))][:limit]
        if not to_fetch:
            return ""
        async def fetch_one(title, url):
            content = await cls.fetch_url(url)
            if len(content) > PAGE_CONTENT_MAX_CHARS:
                content = content[:PAGE_CONTENT_MAX_CHARS] + "\n[...обрезано]"
            return f"### {title}\nURL: {url}\n\n{content}\n\n"
        tasks = [fetch_one(t,u) for t,u in to_fetch]
        pages = await asyncio.gather(*tasks, return_exceptions=True)
        parts = ["\n=== ПОЛНОЕ СОДЕРЖИМОЕ СТРАНИЦ ===\n"]
        for i,res in enumerate(pages):
            if isinstance(res, Exception):
                parts.append(f"[Страница {i+1} не загружена: {res}]\n")
            else:
                parts.append(res)
        return ''.join(parts)

    @classmethod
    async def search(cls, query: str, query_type: str = 'general') -> Tuple[List[Dict], Optional[str]]:
        special = None
        if query_type == 'currency':
            if any(w in query.lower() for w in ['биткоин','bitcoin','btc','eth','крипт']):
                special = await cls.get_crypto_prices()
            else:
                rates = await cls.get_currency_rates()
                if rates:
                    lines = [f"=== ОФИЦИАЛЬНЫЕ КУРСЫ ЦБ РФ на {rates['date']} ==="]
                    for code in ['USD','EUR','CNY','GBP']:
                        if code in rates['rates']:
                            r = rates['rates'][code]
                            lines.append(f"  {code} ({r['name']}): {r['nominal']} {code} = {r['rate']} ₽ (1 {code} = {r['per_unit']} ₽)")
                    special = '\n'.join(lines)
        results = await cls._ddg_search(query)
        return results[:cls.MAX_RESULTS], special

    @classmethod
    def format_for_prompt(cls, results: List[Dict], special: Optional[str], full_pages: str, original_query: str) -> str:
        parts = []
        if special:
            parts.append(special)
        if results:
            parts.append(f"\n=== РЕЗУЛЬТАТЫ ПОИСКА (краткие сниппеты): «{original_query}» ===")
            for i,r in enumerate(results,1):
                parts.append(f"\n[{i}] {r.get('title','(без заголовка)')}")
                if r.get('url'):
                    parts.append(f"    Источник: {r['url']}")
                if r.get('snippet'):
                    parts.append(f"    {r['snippet']}")
        if full_pages:
            parts.append(full_pages)
        if not parts:
            return f"[ПОИСК НЕ ДАЛ РЕЗУЛЬТАТОВ для запроса: «{original_query}»]"
        parts.append("\n=== КОНЕЦ ДАННЫХ ===")
        return '\n'.join(parts)

# ==================================================================
# 🔤 Адаптивный словарь (без изменений, но с поддержкой обновлений)
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
        words = re.findall(r'\b\w+\b', text.lower())
        if not words:
            return np.zeros(self.dim)
        embs = [self.get_embedding(w) for w in words if len(w) > 2]
        return np.mean(embs, axis=0) if embs else np.zeros(self.dim)

    def update_embedding(self, word, grad, lr):
        w = word.lower()
        if w not in self.word2idx:
            return
        idx = self.word2idx[w]
        self.t += 1
        b1,b2,eps = 0.9,0.999,1e-8
        self.m[idx] = b1 * self.m[idx] + (1-b1) * grad
        self.v[idx] = b2 * self.v[idx] + (1-b2) * (grad**2)
        mh = self.m[idx] / (1 - b1**self.t)
        vh = self.v[idx] / (1 - b2**self.t)
        self.embeddings[idx] -= lr * mh / (np.sqrt(vh) + eps)

    def update_quality(self, word, quality):
        w = word.lower()
        if w in self.meta:
            self.meta[w].quality = self.meta[w].quality * 0.85 + quality * 0.15

    def stats(self):
        avg_q = np.mean([m.quality for m in self.meta.values()]) if self.meta else 0.0
        return {'size': self.next_idx, 'capacity': self.cur_size, 'avg_quality': round(float(avg_q),3)}

# ==================================================================
# 🧠 Память (без изменений)
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
                                  importance=importance, emotional_valence=emotional_valence, arousal=arousal))
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
        state = {
            'episodic': [ep_dict(e) for e in self.episodic.items],
            'semantic': [{'name': c.name, 'definition': c.definition, 'embedding': c.embedding.tolist(), 'confidence': c.confidence} for c in self.semantic.items],
            'working': list(self.working)
        }
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
# 🤖 Основной ассистент (с подсознанием и глобальным обучением)
# ==================================================================
class SelfImprovingAssistant:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.vocab = DynamicVocab()
        self.subconscious = Subconscious()
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

    @property
    def agent(self):
        if self._agent is None:
            try:
                from agent_core import AutonomousAgent
                self._agent = AutonomousAgent(self)
            except ImportError:
                logger.warning("agent_core не найден, агентный режим недоступен")
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
        # Обогащаем глобальными знаниями
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

    def _build_system_prompt(self, reasoning: bool, has_web: bool, query_type: str, sub_instruction: str = "") -> str:
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
                "3. Если данных НЕТ — честно сообщи: «Не удалось получить актуальные данные».\n"
            )
        if reasoning:
            prompt += (
                "\n\n🔍 РЕЖИМ РАССУЖДЕНИЙ:\n"
                "Перед ответом покажи цепочку мыслей.\n"
            )
        if sub_instruction:
            prompt += f"\n\n{sub_instruction}"
        return prompt

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
                            return data.get('choices', [{}])[0].get('text', '').strip()
                    else:
                        logger.error(f"LM Studio HTTP {resp.status}")
                        return ""
        except asyncio.TimeoutError:
            return "⏱️ Превышено время ожидания."
        except:
            logger.exception("LM Studio call failed")
            return ""

    async def get_response(self, message: str,
                           image_base64: Optional[str] = None,
                           image_mime: Optional[str] = None,
                           reasoning: bool = False,
                           web_search: bool = False,
                           url_to_fetch: Optional[str] = None) -> Tuple[str, Dict]:
        start = time.time()
        self.total_interactions += 1

        # Веб-поиск
        web_ctx, query_type, _ = await self._do_web_search(message, force=web_search, url_to_fetch=url_to_fetch)
        has_web = web_ctx is not None

        # Проверка кэша (без учёта подсознания)
        ck = self._cache_key(message, image_base64)
        store = self.image_cache if image_base64 else self.cache
        if ck in store and not has_web and not reasoning:
            cached, _ = store[ck]
            return cached, {'cached': True, 'response_time': time.time()-start}

        # Получение контекста памяти
        mem_ctx = self.memory.get_context(message)
        # Эмбеддинги для подсознания
        query_emb = torch.tensor(self.vocab.encode(message), dtype=torch.float32).unsqueeze(0)
        memory_emb = torch.tensor(self.vocab.encode(mem_ctx), dtype=torch.float32).unsqueeze(0) if mem_ctx else torch.zeros(1, EMBEDDING_DIM)
        latent, logits = self.subconscious.forward(query_emb, memory_emb)
        sub_instruction, chosen_indices = self.subconscious.generate_prompt_instruction(logits)

        # Собираем контент для LLM
        content_parts = []
        txt = message.strip()
        if web_ctx:
            txt += f"\n\n{web_ctx}"
        if mem_ctx:
            txt += f"\n\n{mem_ctx}"
        content_parts.append({"type": "text", "text": txt})
        if image_base64 and image_mime and len(image_base64) <= MAX_IMAGE_SIZE_BASE64:
            content_parts.append({"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_base64}"}})

        system_prompt = self._build_system_prompt(reasoning, has_web, query_type, sub_instruction)
        messages_llm = [{"role": "system", "content": system_prompt}, {"role": "user", "content": content_parts}]
        response = await self._call_llm(messages_llm)
        if not response:
            response = "⚠️ Не удалось получить ответ от модели."

        # Вычисляем награду и обучаем подсознание
        meta = {
            'complexity': min(1.0, len(message.split())/20),
            'web_search_used': has_web,
            'response_length': len(response.split())
        }
        reward = self.subconscious.compute_reward(response, meta)
        self.subconscious.learn(query_emb, memory_emb, chosen_indices, reward)

        # Периодический replay
        if self.total_interactions % REPLAY_FREQUENCY == 0:
            self.subconscious.experience_replay()

        # Сохраняем в память, если качество высокое
        quality = max(0.0, (reward + 1) / 2)  # превращаем reward [-1,1] в [0,1]
        if quality > MIN_QUALITY_SCORE:
            self.memory.add_episode(f"Q: {message}\nA: {response}", importance=quality)
            if not has_web and quality > 0.6:
                store[ck] = (response, time.time())
                if len(store) > 100:
                    oldest = min(store.items(), key=lambda x: x[1][1])[0]
                    del store[oldest]

        # Вклад в глобальную базу знаний
        if quality >= MIN_GLOBAL_QUALITY and not has_web:
            try:
                emb_contrib = self.vocab.encode(message + " " + response)
                asyncio.create_task(
                    GlobalKnowledgeBase.get_instance().contribute(
                        user_id=self.user_id,
                        content="Q: "+message+"\nA: "+response,
                        embedding=emb_contrib,
                        importance=quality,
                        assistant=self
                    )
                )
            except Exception as e:
                logger.debug(f"Global contribute failed: {e}")

        if self.total_interactions % SAVE_EVERY_N_INTERACTIONS == 0:
            self.memory.consolidate()
            self._save()

        return response, {'quality': round(quality,3), 'reward': round(reward,3), 'response_time': time.time()-start,
                          'memory_episodes': len(self.memory.episodic.items), 'web_search_used': has_web}

    async def _do_web_search(self, message: str, force: bool, url_to_fetch: Optional[str]) -> Tuple[Optional[str], str, List]:
        if url_to_fetch:
            content = await WebSearchTool.fetch_url(url_to_fetch)
            return f"=== СОДЕРЖИМОЕ СТРАНИЦЫ ({url_to_fetch}) ===\n{content}", 'url', []
        url_in_msg = re.search(r'https?://[^\s]+', message)
        if url_in_msg:
            url = url_in_msg.group(0)
            content = await WebSearchTool.fetch_url(url)
            return f"=== СОДЕРЖИМОЕ СТРАНИЦЫ ({url}) ===\n{content}", 'url', []
        query_type, clean_query = WebSearchTool.classify_query(message)
        if not force and query_type == 'none':
            return None, 'none', []
        cache_key = f"{query_type}:{clean_query}"
        now = time.time()
        if cache_key in _search_cache:
            cached_ctx, cached_ts = _search_cache[cache_key]
            if now - cached_ts < SEARCH_CACHE_TTL:
                return cached_ctx, query_type, []
        results, special = await WebSearchTool.search(clean_query, query_type)
        full_pages = await WebSearchTool.fetch_multiple_pages(results, limit=MAX_PAGES_TO_FETCH) if results else ""
        web_ctx = WebSearchTool.format_for_prompt(results, special, full_pages, message)
        _search_cache[cache_key] = (web_ctx, now)
        # очистка кэша
        for k in list(_search_cache.keys()):
            if now - _search_cache[k][1] > SEARCH_CACHE_TTL:
                del _search_cache[k]
        return web_ctx, query_type, results

    async def stream_response(self, message: str,
                              image_base64: Optional[str] = None,
                              image_mime: Optional[str] = None,
                              reasoning: bool = False,
                              web_search: bool = False,
                              url_to_fetch: Optional[str] = None):
        start = time.time()
        self.total_interactions += 1

        # Веб-поиск
        web_ctx, query_type, _ = await self._do_web_search(message, force=web_search, url_to_fetch=url_to_fetch)
        has_web = web_ctx is not None

        # Получение контекста памяти
        mem_ctx = self.memory.get_context(message)
        query_emb = torch.tensor(self.vocab.encode(message), dtype=torch.float32).unsqueeze(0)
        memory_emb = torch.tensor(self.vocab.encode(mem_ctx), dtype=torch.float32).unsqueeze(
            0) if mem_ctx else torch.zeros(1, EMBEDDING_DIM)
        latent, logits = self.subconscious.forward(query_emb, memory_emb)
        sub_instruction, chosen_indices = self.subconscious.generate_prompt_instruction(logits)

        # Собираем контент для LLM
        content_parts = []
        txt = message.strip()
        if web_ctx:
            txt += f"\n\n{web_ctx}"
        if mem_ctx:
            txt += f"\n\n{mem_ctx}"
        content_parts.append({"type": "text", "text": txt})
        if image_base64 and image_mime and len(image_base64) <= MAX_IMAGE_SIZE_BASE64:
            content_parts.append(
                {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_base64}"}})

        system_prompt = self._build_system_prompt(reasoning, has_web, query_type, sub_instruction)
        messages_llm = [{"role": "system", "content": system_prompt}, {"role": "user", "content": content_parts}]

        payload = {
            "messages": messages_llm,
            "temperature": 0.75,
            "max_tokens": 2500,
            "stream": True
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LM_STUDIO_API_KEY}"
        }

        full_response = ""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(LM_STUDIO_URL, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=LM_STUDIO_STREAM_TIMEOUT)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
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
            logger.exception("Streaming error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # После получения полного ответа – обучение подсознания и сохранение
        if full_response:
            meta = {
                'complexity': min(1.0, len(message.split()) / 20),
                'web_search_used': has_web,
                'response_length': len(full_response.split())
            }
            reward = self.subconscious.compute_reward(full_response, meta)
            self.subconscious.learn(query_emb, memory_emb, chosen_indices, reward)
            if self.total_interactions % REPLAY_FREQUENCY == 0:
                self.subconscious.experience_replay()
            quality = max(0.0, (reward + 1) / 2)
            if quality > MIN_QUALITY_SCORE:
                self.memory.add_episode(f"Q: {message}\nA: {full_response}", importance=quality)
                ck = self._cache_key(message, image_base64)
                store = self.image_cache if image_base64 else self.cache
                if not has_web and quality > 0.6:
                    store[ck] = (full_response, time.time())
                    if len(store) > 100:
                        oldest = min(store.items(), key=lambda x: x[1][1])[0]
                        del store[oldest]
            if quality >= MIN_GLOBAL_QUALITY and not has_web:
                try:
                    emb_contrib = self.vocab.encode(message + " " + full_response)
                    asyncio.create_task(
                        GlobalKnowledgeBase.get_instance().contribute(
                            user_id=self.user_id,
                            content="Q: " + message + "\nA: " + full_response,
                            embedding=emb_contrib,
                            importance=quality,
                            assistant=self
                        )
                    )
                except Exception as e:
                    logger.debug(f"Global contribute failed: {e}")
            if self.total_interactions % SAVE_EVERY_N_INTERACTIONS == 0:
                self.memory.consolidate()
                self._save()

        yield "data: [DONE]\n\n"

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

# Глобальная статистика
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

# Агентные эндпоинты (если agent_core доступен)
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
    # Используем метод research, если есть ResearchAgent
    if hasattr(assistant.agent, 'research'):
        result = await assistant.agent.research(body.goal)
        return result
    # fallback
    result = await assistant.agent.run_goal(body.goal)
    return {"answer": result}

# ==================================================================
# Завершение работы
# ==================================================================
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
        except Exception as e:
            logger.error(f"Save failed {uid}: {e}")

# ==================================================================
# Фоновая задача периодического глобального слияния
# ==================================================================
_merge_task: Optional[asyncio.Task] = None

async def _auto_merge_loop():
    """Запускает периодическое слияние глобальных знаний каждые GLOBAL_MERGE_INTERVAL секунд."""
    await asyncio.sleep(60)  # первый запуск через минуту после старта
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
    """Запускает фоновую задачу слияния (вызывается при старте приложения)."""
    global _merge_task
    if _merge_task is None:
        _merge_task = asyncio.create_task(_auto_merge_loop())
        logger.info("🌍 Global merge task started")


atexit.register(_shutdown_all)