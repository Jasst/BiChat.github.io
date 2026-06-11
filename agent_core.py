"""
agent_core.py — Автономный агентный слой для SelfImprovingAssistant
════════════════════════════════════════════════════════════════════

Подключается к ai_assistant.py как расширение — НЕ меняет существующий функционал.

Что добавляет:
  🧠 AgentPlanner   — декомпозиция цели на подзадачи (ReAct-петля)
  🛠  ToolRegistry   — реестр инструментов (search, memory, code, self-reflect)
  🔁 AgentLoop      — асинхронная петля Observe → Think → Act → Learn
  📈 SelfGoalEngine — автономная постановка целей из паттернов разговоров
  🪞 ReflectionLog  — журнал саморефлексии и качества решений
  💾 AgentMemory    — персистентная память агента (отдельно от CognitiveMemory)

Использование в ai_assistant.py:
    from agent_core import AgentMixin
    class SelfImprovingAssistant(AgentMixin, ...):
        ...

Или как standalone-вызов:
    agent = AutonomousAgent(assistant)
    result = await agent.run("Изучи тему X и составь краткое резюме")
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import pickle
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Конфигурация
# ──────────────────────────────────────────────────────────────────────────────

MAX_AGENT_STEPS      = 8       # макс. шагов в одной агентной петле
TOOL_TIMEOUT         = 30      # секунд на каждый вызов инструмента
REFLECTION_INTERVAL  = 20      # каждые N взаимодействий — рефлексия
GOAL_HORIZON         = 5       # сколько последних тем учитывать для авто-целей
MIN_GOAL_CONFIDENCE  = 0.55    # порог уверенности для создания авто-цели
AGENT_SAVE_INTERVAL  = 15      # сохранять состояние каждые N шагов
MAX_PAGES_TO_FETCH = 7   # должно совпадать со значением в ai_assistant
# Обучение из интернета
AUTO_LEARN_FROM_WEB = True          # автоматически извлекать факты после поиска
MIN_CONFIDENCE_TO_LEARN = 0.6       # порог уверенности для сохранения факта
MAX_FACTS_PER_SEARCH = 10           # ограничиваем количество фактов
ENABLE_QUERY_REWRITE = True         # рерайтинг перед поиском
SHARE_LEARNED_FACTS_GLOBALLY = True # анонимно делиться фактами
# ──────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AgentStep:
    step_id:    int
    thought:    str          # внутреннее рассуждение
    tool_name:  str          # какой инструмент вызван (или "final")
    tool_input: str          # аргумент инструмента
    tool_output: str         # результат
    timestamp:  float = field(default_factory=time.time)
    success:    bool  = True

@dataclass
class AgentGoal:
    goal_id:    str
    description: str
    priority:   float        # 0..1
    created_at: float        = field(default_factory=time.time)
    completed:  bool         = False
    result:     str          = ""
    source:     str          = "user"  # "user" | "auto" | "reflection"

@dataclass
class ReflectionEntry:
    interaction_id: int
    summary:        str
    weak_points:    List[str]
    improvements:   List[str]
    quality_score:  float
    timestamp:      float = field(default_factory=time.time)


# ──────────────────────────────────────────────────────────────────────────────
# Реестр инструментов
# ──────────────────────────────────────────────────────────────────────────────

class ToolRegistry:
    """
    Реестр инструментов агента.
    Каждый инструмент — async-функция(input: str) → str.
    Новые инструменты подключаются через register().
    """

    def __init__(self):
        self._tools: Dict[str, Dict] = {}

    def register(self, name: str, fn: Callable, description: str, examples: List[str] = None):
        self._tools[name] = {
            "fn": fn,
            "description": description,
            "examples": examples or [],
            "call_count": 0,
            "success_count": 0,
            "avg_latency": 0.0,
        }
        logger.debug(f"🛠 Tool registered: {name}")

    def list_tools(self) -> str:
        lines = []
        for name, meta in self._tools.items():
            lines.append(f"  [{name}] — {meta['description']}")
            if meta["examples"]:
                lines.append(f"    Пример: {meta['examples'][0]}")
        return "\n".join(lines)

    async def call(self, name: str, tool_input: str) -> Tuple[str, bool]:
        if name not in self._tools:
            return f"[Инструмент '{name}' не найден. Доступные: {', '.join(self._tools)}]", False
        meta = self._tools[name]
        t0 = time.time()
        try:
            result = await asyncio.wait_for(meta["fn"](tool_input), timeout=TOOL_TIMEOUT)
            meta["call_count"] += 1
            meta["success_count"] += 1
            lat = time.time() - t0
            meta["avg_latency"] = (meta["avg_latency"] * (meta["call_count"] - 1) + lat) / meta["call_count"]
            return str(result)[:3000], True
        except asyncio.TimeoutError:
            meta["call_count"] += 1
            return f"[Timeout: инструмент '{name}' не ответил за {TOOL_TIMEOUT}с]", False
        except Exception as e:
            meta["call_count"] += 1
            logger.warning(f"Tool '{name}' error: {e}")
            return f"[Ошибка инструмента '{name}': {e}]", False

    def stats(self) -> Dict:
        return {
            name: {
                "calls": m["call_count"],
                "success_rate": round(m["success_count"] / max(1, m["call_count"]), 2),
                "avg_latency_ms": round(m["avg_latency"] * 1000),
            }
            for name, m in self._tools.items()
        }

    # В AutonomousAgent, после других методов инструментов:



# ──────────────────────────────────────────────────────────────────────────────
# Планировщик задач
# ──────────────────────────────────────────────────────────────────────────────

class AgentPlanner:
    """
    Разбивает сложную цель на подзадачи через LLM-вызов.
    Реализует ReAct (Reason + Act) паттерн.
    """

    PLAN_SYSTEM_PROMPT = """Ты — автономный AI-агент. Твоя задача: разбить цель на конкретные шаги.

Доступные инструменты:
{tools}

Формат ОДНОГО шага (строго JSON, один объект):
{{"thought": "рассуждение", "tool": "имя_инструмента", "input": "аргумент"}}

Для финального ответа без инструмента:
{{"thought": "рассуждение", "tool": "final", "input": "готовый ответ"}}

Правила:
- Не более {max_steps} шагов
- Каждый шаг должен приближать к цели
- Используй memory_search перед web_search (быстрее и дешевле)
- Используй self_reflect для оценки своего прогресса
- Если цель простая — сразу "final"
"""

    def __init__(self, call_llm_fn: Callable):
        self._call_llm = call_llm_fn

    async def next_step(
        self,
        goal: str,
        history: List[AgentStep],
        tools: ToolRegistry,
        context: str = "",
    ) -> Optional[AgentStep]:
        """Возвращает следующий шаг или None если цель достигнута."""
        step_id = len(history) + 1

        history_text = ""
        for s in history[-4:]:  # последние 4 шага
            history_text += (
                f"\nШаг {s.step_id}:\n"
                f"  Мысль: {s.thought}\n"
                f"  Действие: {s.tool_name}({s.tool_input[:100]})\n"
                f"  Результат: {s.tool_output[:200]}\n"
            )

        user_msg = (
            f"Цель: {goal}\n"
            + (f"Контекст: {context[:500]}\n" if context else "")
            + (f"История шагов:{history_text}\n" if history_text else "")
            + f"\nШаг {step_id} из {MAX_AGENT_STEPS}. Что делаем?"
        )

        messages = [
            {
                "role": "system",
                "content": self.PLAN_SYSTEM_PROMPT.format(
                    tools=tools.list_tools(),
                    max_steps=MAX_AGENT_STEPS,
                ),
            },
            {"role": "user", "content": user_msg},
        ]

        raw = await self._call_llm(messages)
        if not raw:
            return None

        # Парсим JSON из ответа
        parsed = self._parse_json_step(raw)
        if not parsed:
            # Fallback: если LLM не вернул JSON, считаем final
            return AgentStep(
                step_id=step_id,
                thought=raw[:200],
                tool_name="final",
                tool_input=raw,
                tool_output="",
            )

        return AgentStep(
            step_id=step_id,
            thought=parsed.get("thought", ""),
            tool_name=parsed.get("tool", "final"),
            tool_input=parsed.get("input", ""),
            tool_output="",
        )

    @staticmethod
    def _parse_json_step(text: str) -> Optional[Dict]:
        # Ищем JSON объект в тексте
        match = re.search(r'\{[^{}]*"tool"[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        # Попытка распарсить весь текст
        text_clean = text.strip().strip("```json").strip("```").strip()
        try:
            return json.loads(text_clean)
        except Exception:
            return None


# ──────────────────────────────────────────────────────────────────────────────
# Движок авто-целей
# ──────────────────────────────────────────────────────────────────────────────

class SelfGoalEngine:
    """
    Анализирует паттерны разговоров и автономно ставит цели для саморазвития.
    Например: если часто спрашивают про Python → цель "углубить знания Python".
    """

    def __init__(self):
        self._topic_freq: Dict[str, int] = defaultdict(int)
        self._pending_goals: List[AgentGoal] = []
        self._completed_goals: List[AgentGoal] = []
        self._goal_hashes: set = set()  # дедупликация

    def observe_message(self, message: str):
        """Учитывает тему нового сообщения."""
        topics = self._extract_topics(message)
        for t in topics:
            self._topic_freq[t] += 1

    def _extract_topics(self, text: str) -> List[str]:
        stop = {
            'и','в','на','с','по','из','для','что','как','это','но','или','мне',
            'the','a','an','is','are','to','of','and','in','for','can','you',
        }
        words = re.findall(r'\b[а-яёa-z]{4,}\b', text.lower())
        return [w for w in words if w not in stop][:6]

    def generate_goals(self) -> List[AgentGoal]:
        """Создаёт новые авто-цели на основе частотных паттернов."""
        if not self._topic_freq:
            return []

        new_goals = []
        top_topics = sorted(self._topic_freq.items(), key=lambda x: -x[1])[:GOAL_HORIZON]

        for topic, count in top_topics:
            if count < 3:
                continue
            confidence = min(1.0, count / 15)
            if confidence < MIN_GOAL_CONFIDENCE:
                continue

            goal_desc = f"Углубить знания по теме: '{topic}' (упоминается {count} раз)"
            goal_hash = hashlib.md5(goal_desc.encode()).hexdigest()[:16]

            if goal_hash in self._goal_hashes:
                continue

            self._goal_hashes.add(goal_hash)
            goal = AgentGoal(
                goal_id=goal_hash,
                description=goal_desc,
                priority=confidence,
                source="auto",
            )
            new_goals.append(goal)
            self._pending_goals.append(goal)

        return new_goals

    def complete_goal(self, goal_id: str, result: str):
        for g in self._pending_goals:
            if g.goal_id == goal_id:
                g.completed = True
                g.result = result
                self._completed_goals.append(g)
                self._pending_goals.remove(g)
                break

    def get_pending(self, top_n: int = 3) -> List[AgentGoal]:
        return sorted(self._pending_goals, key=lambda g: -g.priority)[:top_n]

    def stats(self) -> Dict:
        return {
            "top_topics": dict(sorted(self._topic_freq.items(), key=lambda x: -x[1])[:10]),
            "pending_goals": len(self._pending_goals),
            "completed_goals": len(self._completed_goals),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Журнал рефлексии
# ──────────────────────────────────────────────────────────────────────────────

class ReflectionLog:
    """
    AI самоанализирует свои ответы, выявляет слабые места
    и формирует план улучшения.
    """

    REFLECTION_PROMPT = """Ты анализируешь качество последних ответов AI-ассистента.

Последние взаимодействия:
{interactions}

Задача:
1. Выяви 2-3 слабых места (конкретно)
2. Предложи 2-3 конкретных улучшения
3. Оцени общее качество от 0 до 1
4. Напиши краткое резюме (1-2 предложения)

Ответь строго в JSON:
{{"summary": "...", "weak_points": ["...", "..."], "improvements": ["...", "..."], "quality": 0.7}}
"""

    def __init__(self):
        self._entries: deque = deque(maxlen=50)
        self._interaction_buffer: List[str] = []

    def log_interaction(self, message: str, response: str, quality: float):
        self._interaction_buffer.append(
            f"Q: {message[:150]}\nA: {response[:200]}\nQuality: {quality:.2f}"
        )
        if len(self._interaction_buffer) > 20:
            self._interaction_buffer = self._interaction_buffer[-10:]

    async def reflect(self, interaction_id: int, call_llm_fn: Callable) -> Optional[ReflectionEntry]:
        if len(self._interaction_buffer) < 5:
            return None

        interactions_text = "\n---\n".join(self._interaction_buffer[-8:])
        messages = [
            {"role": "system", "content": "Ты аналитик качества AI-систем. Отвечай только JSON."},
            {"role": "user", "content": self.REFLECTION_PROMPT.format(interactions=interactions_text)},
        ]

        raw = await call_llm_fn(messages)
        if not raw:
            return None

        try:
            text_clean = raw.strip().strip("```json").strip("```").strip()
            data = json.loads(text_clean)
        except Exception:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if not match:
                return None
            try:
                data = json.loads(match.group(0))
            except Exception:
                return None

        entry = ReflectionEntry(
            interaction_id=interaction_id,
            summary=data.get("summary", ""),
            weak_points=data.get("weak_points", []),
            improvements=data.get("improvements", []),
            quality_score=float(data.get("quality", 0.5)),
        )
        self._entries.append(entry)
        logger.info(f"🪞 Reflection #{interaction_id}: quality={entry.quality_score:.2f}, "
                    f"weak={len(entry.weak_points)}")
        return entry

    def get_improvement_context(self) -> str:
        """Возвращает контекст из последних рефлексий для системного промпта."""
        if not self._entries:
            return ""
        last = list(self._entries)[-3:]
        parts = ["=== Журнал саморефлексии ==="]
        for e in last:
            parts.append(f"[{time.strftime('%H:%M', time.localtime(e.timestamp))}] "
                         f"Q={e.quality_score:.2f}: {e.summary}")
            if e.improvements:
                parts.append(f"  Улучшения: {'; '.join(e.improvements[:2])}")
        return "\n".join(parts)

    def latest_quality(self) -> float:
        if self._entries:
            return self._entries[-1].quality_score
        return 0.5


# ──────────────────────────────────────────────────────────────────────────────
# Персистентная память агента
# ──────────────────────────────────────────────────────────────────────────────

class AgentMemory:
    """
    Хранит долгосрочные знания агента:
    - Факты, извлечённые из разговоров
    - Предпочтения пользователя
    - Шаблоны успешных решений
    """

    def __init__(self, save_path: Path):
        self._save_path = save_path
        self._facts: Dict[str, Dict] = {}          # key → {value, confidence, ts}
        self._patterns: List[Dict] = []             # успешные паттерны решений
        self._user_prefs: Dict[str, Any] = {}       # предпочтения пользователя
        self._load()

    def store_fact(self, key: str, value: str, confidence: float = 0.8):
        self._facts[key] = {"value": value, "confidence": confidence, "ts": time.time()}

    def recall_fact(self, key: str) -> Optional[str]:
        f = self._facts.get(key)
        return f["value"] if f else None

    def search_facts(self, query: str, top_k: int = 5) -> List[Tuple[str, str, float]]:
        """Простой поиск по ключам фактов (fuzzy match)."""
        q = query.lower()
        results = []
        for key, meta in self._facts.items():
            score = sum(1 for w in q.split() if w in key.lower()) / max(1, len(q.split()))
            if score > 0.2:
                results.append((key, meta["value"], score * meta["confidence"]))
        return sorted(results, key=lambda x: -x[2])[:top_k]

    def store_pattern(self, goal_type: str, steps: List[str], success: bool, quality: float):
        if quality > 0.6 and success:
            self._patterns.append({
                "goal_type": goal_type,
                "steps": steps[:5],
                "quality": quality,
                "ts": time.time(),
            })
            if len(self._patterns) > 200:
                # Оставляем только лучшие
                self._patterns.sort(key=lambda x: -x["quality"])
                self._patterns = self._patterns[:150]

    def get_best_pattern(self, goal_type: str) -> Optional[Dict]:
        candidates = [p for p in self._patterns if p["goal_type"] == goal_type]
        return max(candidates, key=lambda x: x["quality"]) if candidates else None

    def set_user_pref(self, key: str, value: Any):
        self._user_prefs[key] = value

    def get_user_pref(self, key: str, default=None) -> Any:
        return self._user_prefs.get(key, default)

    def _load(self):
        if self._save_path.exists():
            try:
                with gzip.open(self._save_path, 'rb') as f:
                    state = pickle.load(f)
                self._facts       = state.get("facts", {})
                self._patterns    = state.get("patterns", [])
                self._user_prefs  = state.get("user_prefs", {})
                logger.debug(f"AgentMemory loaded: {len(self._facts)} facts, {len(self._patterns)} patterns")
            except Exception as e:
                logger.warning(f"AgentMemory load error: {e}")

    def save(self):
        try:
            with gzip.open(self._save_path, 'wb') as f:
                pickle.dump({
                    "facts":      self._facts,
                    "patterns":   self._patterns,
                    "user_prefs": self._user_prefs,
                }, f)
        except Exception as e:
            logger.error(f"AgentMemory save error: {e}")

    def stats(self) -> Dict:
        return {
            "facts": len(self._facts),
            "patterns": len(self._patterns),
            "user_prefs": len(self._user_prefs),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Главный агент
# ──────────────────────────────────────────────────────────────────────────────

class AutonomousAgent:
    """
    Автономный агент-обёртка над SelfImprovingAssistant.

    Добавляет поверх существующего ассистента:
    - Многошаговую ReAct петлю
    - Набор инструментов (search, memory, code_eval, self_reflect)
    - Авто-постановку целей
    - Журнал рефлексии
    - Персистентную агентную память

    Использование:
        agent = AutonomousAgent(assistant)
        # Простой вопрос → обычный ответ (без overhead)
        response = await agent.chat(message, **kwargs)
        # Сложная задача → агентная петля
        response = await agent.run_goal("Исследуй тему X и напиши резюме")
    """

    COMPLEXITY_THRESHOLD = 50   # слов — выше этого порога включаем агентную петлю

    def __init__(self, assistant):
        """
        assistant: экземпляр SelfImprovingAssistant
        """
        self._a = assistant
        self._user_id = assistant.user_id
        self._agent_dir = assistant.user_dir / "agent"
        self._agent_dir.mkdir(exist_ok=True)

        self.tools   = ToolRegistry()
        self.planner = AgentPlanner(self._call_llm_direct)
        self.goals   = SelfGoalEngine()
        self.reflect = ReflectionLog()
        self.memory  = AgentMemory(self._agent_dir / "agent_memory.pkl.gz")

        self._step_counter = 0
        self._active_goals: List[AgentGoal] = []

        # Регистрируем встроенные инструменты
        self._register_builtin_tools()
        logger.info(f"🤖 AutonomousAgent ready for {self._user_id[:8]}")

    # ── Встроенные инструменты ──────────────────────────────────────

    def _register_builtin_tools(self):

        self.tools.register(
            "rewrite_query",
            self._tool_rewrite_query,
            "Оптимизирует запрос для поиска в интернете",
            ["rewrite_query: погода в москве сегодня"]
        )
        self.tools.register(
            "learn_from_web",
            self._tool_learn_from_web,
            "Извлекает и сохраняет факты из веб-результатов в долговременную память",
            ["learn_from_web: [текст страницы]"]
        )

        self.tools.register(
            "web_search",
            self._tool_web_search,
            "Поиск информации в интернете",
            ["web_search: последние новости о Python 3.13"],
        )
        self.tools.register(
            "memory_search",
            self._tool_memory_search,
            "Поиск в долгосрочной памяти и фактах",
            ["memory_search: предпочтения пользователя по языкам"],
        )
        self.tools.register(
            "store_fact",
            self._tool_store_fact,
            "Сохранить факт: 'ключ=значение'",
            ["store_fact: любимый_язык=Python"],
        )
        self.tools.register(
            "self_reflect",
            self._tool_self_reflect,
            "Оценить свой прогресс и скорректировать план",
            ["self_reflect: Как хорошо я справляюсь с задачей?"],
        )
        self.tools.register(
            "summarize",
            self._tool_summarize,
            "Сжать длинный текст до ключевых пунктов",
            ["summarize: [длинный текст...]"],
        )
        self.tools.register(
            "extract_facts",
            self._tool_extract_facts,
            "Извлечь структурированные факты из текста",
            ["extract_facts: [текст для анализа]"],
        )
        self.tools.register(
            "generate_hypothesis",
            self._tool_generate_hypothesis,
            "Создаёт 3 проверяемые гипотезы по вопросу"
        )
        self.tools.register(
            "verify_information",
            self._tool_verify_information,
            "Анализирует текст на подтверждения и противоречия"
        )

    # ── Инструменты ────────────────────────────────────────────────

    async def _tool_web_search(self, query: str) -> str:
        # Получаем глобальные знания по теме запроса
        try:
            from routes.ai_assistant import GlobalKnowledgeBase, WebSearchTool
            gkb = GlobalKnowledgeBase.get_instance()
            query_emb = self._a.vocab.encode(query)
            global_ctx = gkb.get_global_context(query_emb, top_k=2)
            if global_ctx:
                logger.debug(f"Global context for '{query}': {global_ctx[:200]}")
                # Можно добавить глобальный контекст в запрос для рерайтинга, но оставим пока в логе
        except Exception as e:
            logger.debug(f"Global KB not available: {e}")
        # 1. Рерайтинг запроса
        if ENABLE_QUERY_REWRITE:
            optimized_query = await self._tool_rewrite_query(query)
        else:
            optimized_query = query

        # 2. Выполнение поиска через существующий инструмент ассистента
        try:
            from routes.ai_assistant import GlobalKnowledgeBase
            qt, _ = WebSearchTool.classify_query(optimized_query)
            results, special = await WebSearchTool.search(optimized_query, qt)
            pages = ""
            if results:
                pages = await WebSearchTool.fetch_multiple_pages(results, limit=MAX_PAGES_TO_FETCH)
            web_ctx = WebSearchTool.format_for_prompt(results, special, pages, optimized_query)

            # 3. Асинхронное извлечение фактов (обучение)
            if AUTO_LEARN_FROM_WEB and web_ctx and len(web_ctx) > 500:
                asyncio.create_task(self._learn_from_search_result(web_ctx))

            return web_ctx
        except ImportError:
            return f"[web_search недоступен для: {query}]"

    async def _learn_from_search_result(self, context: str):
        """Фоновое извлечение фактов из результатов поиска."""
        try:
            result = await self._tool_learn_from_web(context)
            logger.debug(f"Auto-learning result: {result}")
        except Exception as e:
            logger.warning(f"Auto-learning failed: {e}")

    async def _tool_memory_search(self, query: str) -> str:
        # Поиск в агентной памяти (факты)
        facts = self.memory.search_facts(query, top_k=5)
        parts = []
        if facts:
            parts.append("Факты из памяти агента:")
            for key, val, score in facts:
                parts.append(f"  [{score:.2f}] {key}: {val}")

        # Поиск в когнитивной памяти ассистента
        episodes = self._a.memory.recall(query, top_k=3)
        if episodes:
            parts.append("\nЭпизоды из долгосрочной памяти:")
            for ep, score in episodes:
                parts.append(f"  [{score:.2f}] {ep.content[:200]}")

        return "\n".join(parts) if parts else "Ничего не найдено в памяти"

    async def _tool_store_fact(self, fact_str: str) -> str:
        if "=" in fact_str:
            key, _, val = fact_str.partition("=")
            self.memory.store_fact(key.strip(), val.strip())
            return f"✅ Факт сохранён: {key.strip()} = {val.strip()}"
        return "❌ Формат: ключ=значение"

    async def _tool_self_reflect(self, question: str) -> str:
        ctx = self.reflect.get_improvement_context()
        if not ctx:
            return "Рефлексия пока недоступна (мало данных)"
        return f"Текущий контекст саморефлексии:\n{ctx}\n\nВопрос: {question}"

    async def _tool_summarize(self, text: str) -> str:
        if len(text) < 100:
            return text
        messages = [
            {"role": "system", "content": "Сожми текст до 5 ключевых пунктов. Отвечай на языке текста."},
            {"role": "user", "content": text[:4000]},
        ]
        result = await self._call_llm_direct(messages)
        return result or "[Не удалось сжать]"

    async def _tool_extract_facts(self, text: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "Извлеки структурированные факты из текста. "
                    "Формат: одна строка на факт, начиная с '•'. "
                    "Только конкретные, проверяемые факты."
                ),
            },
            {"role": "user", "content": text[:3000]},
        ]
        result = await self._call_llm_direct(messages)
        return result or "[Не удалось извлечь факты]"

    # ── LLM-вызов (делегирует к ассистенту) ────────────────────────

    async def _call_llm_direct(self, messages: List[Dict]) -> str:
        """Прямой вызов LLM через метод ассистента."""
        return await self._a._call_llm(messages)

    # ── Основные публичные методы ───────────────────────────────────

    async def chat(
        self,
        message: str,
        image_base64=None,
        image_mime=None,
        reasoning=False,
        web_search=False,
        url_to_fetch=None,
    ) -> Tuple[str, Dict]:
        """
        Главная точка входа.
        Для простых запросов — делегирует к get_response ассистента.
        Для сложных — включает агентную петлю.
        """
        # Наблюдаем тему для авто-целей
        self.goals.observe_message(message)
        self._step_counter += 1

        # Генерируем авто-цели (если накопились паттерны)
        new_goals = self.goals.generate_goals()
        if new_goals:
            logger.info(f"🎯 Auto-goals generated: {[g.description[:50] for g in new_goals]}")

        # Проверяем сложность запроса
        is_complex = self._is_complex_task(message)

        if is_complex and not image_base64:
            # Агентная петля
            result = await self._run_agent_loop(message, context="")
            response = result["final_answer"]
            meta = {
                "agent_mode": True,
                "steps_taken": result["steps_taken"],
                "tools_used": result["tools_used"],
            }
        else:
            # Стандартный путь через ассистента
            # Дополняем системный промпт данными рефлексии
            response, meta = await self._a.get_response(
                message=message,
                image_base64=image_base64,
                image_mime=image_mime,
                reasoning=reasoning,
                web_search=web_search,
                url_to_fetch=url_to_fetch,
            )
            meta["agent_mode"] = False

        # Логируем для рефлексии
        quality = meta.get("quality", 0.5)
        self.reflect.log_interaction(message, response, quality)

        # Периодическая рефлексия
        if self._step_counter % REFLECTION_INTERVAL == 0:
            asyncio.create_task(self._background_reflect())

        # Периодическое сохранение
        if self._step_counter % AGENT_SAVE_INTERVAL == 0:
            self.memory.save()

        return response, meta

    async def run_goal(self, goal_description: str) -> str:
        """
        Запускает автономное выполнение цели.
        Используется для фоновых задач и авто-целей.
        """
        goal = AgentGoal(
            goal_id=hashlib.md5(goal_description.encode()).hexdigest()[:16],
            description=goal_description,
            priority=0.8,
            source="user",
        )
        result = await self._run_agent_loop(goal_description, context="")
        goal.completed = True
        goal.result = result["final_answer"]
        self.goals.complete_goal(goal.goal_id, goal.result)
        return result["final_answer"]

    # ── Агентная петля ──────────────────────────────────────────────

    async def _run_agent_loop(self, goal: str, context: str) -> Dict:
        """
        ReAct петля: Observe → Think → Act → Learn
        Возвращает финальный ответ и метаданные.
        """
        history: List[AgentStep] = []
        tools_used: List[str] = []

        # Проверяем кэш паттернов
        goal_type = self._classify_goal(goal)
        best_pattern = self.memory.get_best_pattern(goal_type)
        if best_pattern:
            context += f"\n[Успешный паттерн для похожей задачи: {', '.join(best_pattern['steps'])}]"

        for step_num in range(MAX_AGENT_STEPS):
            # Планировщик решает следующий шаг
            step = await self.planner.next_step(goal, history, self.tools, context)
            if not step:
                break

            if step.tool_name == "final":
                # Цель достигнута
                step.tool_output = step.tool_input
                history.append(step)
                break

            # Выполняем инструмент
            output, success = await self.tools.call(step.tool_name, step.tool_input)
            step.tool_output = output
            step.success = success
            history.append(step)

            if step.tool_name not in tools_used:
                tools_used.append(step.tool_name)

            # ---- Принудительное обучение после web_search ----
            if step.tool_name == "web_search" and success and len(output) > 500 and AUTO_LEARN_FROM_WEB:
                learn_step = AgentStep(
                    step_id=step_num + 1,
                    thought="Извлекаю факты из веб-страниц для долговременной памяти",
                    tool_name="learn_from_web",
                    tool_input=output[:3000],
                    tool_output=""
                )
                learn_out, learn_ok = await self.tools.call("learn_from_web", learn_step.tool_input)
                learn_step.tool_output = learn_out
                learn_step.success = learn_ok
                history.append(learn_step)
                if "learn_from_web" not in tools_used:
                    tools_used.append("learn_from_web")
            # ------------------------------------------------

            # Если получили достаточно данных — можно завершить досрочно
            if self._has_sufficient_data(history):
                break

        # Формируем финальный ответ
        final_answer = await self._synthesize_answer(goal, history)

        # Сохраняем паттерн если успешно
        step_names = [s.tool_name for s in history]
        quality = self.reflect.latest_quality()
        self.memory.store_pattern(goal_type, step_names, True, quality)

        return {
            "final_answer": final_answer,
            "steps_taken": len(history),
            "tools_used": tools_used,
            "history": history,
        }

    async def _synthesize_answer(self, goal: str, history: List[AgentStep]) -> str:
        """Синтезирует финальный ответ из истории шагов."""
        # Если последний шаг — финальный, используем его напрямую
        if history and history[-1].tool_name == "final":
            return history[-1].tool_output

        # Иначе просим LLM сформулировать ответ
        steps_summary = ""
        for s in history:
            if s.tool_output and s.tool_name != "final":
                steps_summary += f"\n[{s.tool_name}] {s.tool_output[:400]}\n"

        messages = [
            {
                "role": "system",
                "content": (
                    "Ты AI-агент, который завершил исследование. "
                    "Синтезируй собранные данные в чёткий, полезный ответ. "
                    "Будь конкретным, ссылайся на найденные факты."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Цель: {goal}\n\n"
                    f"Собранные данные:{steps_summary}\n\n"
                    "Дай финальный ответ:"
                ),
            },
        ]

        result = await self._call_llm_direct(messages)
        return result or "Не удалось синтезировать ответ."

    # ── Вспомогательные методы ──────────────────────────────────────

    def _is_complex_task(self, message: str) -> bool:
        """Определяет, нужна ли агентная петля для этого запроса.

        Логика: включаем агент если:
          - есть ключевое слово (даже короткий запрос типа "исследуй X"), ИЛИ
          - длинный запрос (> порога) — скорее всего сложная задача.
        """
        complex_keywords = [
            'исследуй', 'проанализируй', 'составь план', 'найди и сравни',
            'подготовь отчёт', 'изучи', 'research', 'analyze', 'compare',
            'summarize multiple', 'найди несколько', 'сделай обзор',
        ]
        research_keywords = ['правда ли', 'докажи', 'опровергни', 'исследуй', 'проверь', 'действительно ли']
        if any(kw in message.lower() for kw in research_keywords):
            return True  # включить агентный режим (и ResearchAgent)
        msg_lower = message.lower()
        has_keyword = any(kw in msg_lower for kw in complex_keywords)

        # Ключевое слово → агент всегда, даже для короткого запроса
        if has_keyword:
            return True

        # Без ключевого слова — только если запрос очень длинный
        return len(message.split()) >= self.COMPLEXITY_THRESHOLD

    def _classify_goal(self, goal: str) -> str:
        """Определяет тип цели для поиска паттернов."""
        gl = goal.lower()
        if any(w in gl for w in ['search', 'найди', 'поищи', 'find']):
            return "search"
        if any(w in gl for w in ['анализ', 'analyze', 'сравни', 'compare']):
            return "analysis"
        if any(w in gl for w in ['напиши', 'write', 'составь', 'create']):
            return "creation"
        if any(w in gl for w in ['объясни', 'explain', 'что такое', 'what is']):
            return "explanation"
        return "general"

    def _has_sufficient_data(self, history: List[AgentStep]) -> bool:
        """Проверяет, достаточно ли данных для ответа."""
        successful_steps = [s for s in history if s.success and s.tool_output]
        total_data = sum(len(s.tool_output) for s in successful_steps)
        return len(successful_steps) >= 2 and total_data > 1000

    async def _background_reflect(self):
        """Фоновая рефлексия (не блокирует ответ)."""
        try:
            entry = await self.reflect.reflect(self._step_counter, self._call_llm_direct)
            if entry and entry.weak_points:
                # Сохраняем слабые места как факты для улучшения
                for i, wp in enumerate(entry.weak_points[:2]):
                    self.memory.store_fact(
                        f"weak_point_{self._step_counter}_{i}",
                        wp,
                        confidence=0.9,
                    )
        except Exception as e:
            logger.debug(f"Background reflection error: {e}")

    # ── Стриминг с агентными событиями ─────────────────────────────

    async def stream_with_agent(
        self,
        message: str,
        image_base64=None,
        image_mime=None,
        reasoning=False,
        web_search=False,
        url_to_fetch=None,
    ):
        """
        Генератор стриминговых событий с поддержкой агентной петли.
        Формат событий совместим с существующим stream_response.
        """
        self.goals.observe_message(message)
        self._step_counter += 1

        is_complex = self._is_complex_task(message)

        if is_complex and not image_base64:
            # Агентный режим — стримим шаги
            yield f"data: {json.dumps({'status': 'agent_start', 'text': '🤖 Агентный режим...'})}\n\n"

            goal_type = self._classify_goal(message)
            history: List[AgentStep] = []
            tools_used: List[str] = []

            for step_num in range(MAX_AGENT_STEPS):
                step = await self.planner.next_step(message, history, self.tools, "")
                if not step:
                    break

                # Стримим мысль агента
                if step.thought:
                    yield f"data: {json.dumps({'status': 'agent_thinking', 'text': f'💭 {step.thought[:100]}'})}\n\n"

                if step.tool_name == "final":
                    step.tool_output = step.tool_input
                    history.append(step)
                    break

                # Стримим действие
                tool_emoji = {
                    "web_search": "🔍",
                    "memory_search": "🧠",
                    "store_fact": "💾",
                    "self_reflect": "🪞",
                    "summarize": "📝",
                    "extract_facts": "🔬",
                }.get(step.tool_name, "🛠")
                yield f"data: {json.dumps({'status': 'agent_action', 'text': f'{tool_emoji} {step.tool_name}: {step.tool_input[:60]}'})}\n\n"

                output, success = await self.tools.call(step.tool_name, step.tool_input)
                step.tool_output = output
                step.success = success
                history.append(step)

                if step.tool_name not in tools_used:
                    tools_used.append(step.tool_name)

                if self._has_sufficient_data(history):
                    break

            # Синтез ответа
            yield f"data: {json.dumps({'status': 'agent_synthesizing', 'text': '✍️ Формулирую ответ...'})}\n\n"
            final = await self._synthesize_answer(message, history)

            # Стримим токены финального ответа
            words = final.split(" ")
            chunk = ""
            for word in words:
                chunk += word + " "
                if len(chunk) > 20:
                    yield f"data: {json.dumps({'token': chunk})}\n\n"
                    chunk = ""
                    await asyncio.sleep(0.01)
            if chunk:
                yield f"data: {json.dumps({'token': chunk})}\n\n"

            # Мета-информация
            yield f"data: {json.dumps({'agent_meta': {'steps': len(history), 'tools': tools_used}})}\n\n"

            # Обучение
            quality = min(1.0, len(final) / 300)
            self.reflect.log_interaction(message, final, quality)
            self.memory.store_pattern(goal_type, [s.tool_name for s in history], True, quality)

        else:
            # Стандартный стриминг через ассистента.
            # stream_response уже завершается своим [DONE] — не дублируем.
            async for chunk in self._a.stream_response(
                message=message,
                image_base64=image_base64,
                image_mime=image_mime,
                reasoning=reasoning,
                web_search=web_search,
                url_to_fetch=url_to_fetch,
            ):
                yield chunk

            # Фоновые задачи и ранний выход (без второго [DONE])
            if self._step_counter % REFLECTION_INTERVAL == 0:
                asyncio.create_task(self._background_reflect())
            if self._step_counter % AGENT_SAVE_INTERVAL == 0:
                self.memory.save()
            return

        # Только для агентного пути (is_complex=True)
        if self._step_counter % REFLECTION_INTERVAL == 0:
            asyncio.create_task(self._background_reflect())
        if self._step_counter % AGENT_SAVE_INTERVAL == 0:
            self.memory.save()

        yield "data: [DONE]\n\n"

    async def _tool_generate_hypothesis(self, query: str) -> str:
        messages = [
            {"role": "system", "content": "Ты — методолог. Генерируй краткие, чёткие, проверяемые гипотезы."},
            {"role": "user", "content": f"Сформулируй 3 гипотезы для вопроса: {query}"}
        ]
        return await self._call_llm_direct(messages)

    async def _tool_verify_information(self, text: str) -> str:
        messages = [
            {"role": "system", "content": (
                "Ты — критический анализатор. Для данного текста определи:\n"
                "1. Какие утверждения подтверждают исходную гипотезу?\n"
                "2. Какие утверждения противоречат ей?\n"
                "3. Общий уровень достоверности (0-100%).\n"
                "Ответ дай в формате:\n"
                "ПОДТВЕРЖДЕНИЯ: ...\n"
                "ПРОТИВОРЕЧИЯ: ...\n"
                "УВЕРЕННОСТЬ: ..."
            )},
            {"role": "user", "content": text[:3000]}
        ]
        return await self._call_llm_direct(messages)



    # ── Статистика ──────────────────────────────────────────────────

    def stats(self) -> Dict:
        return {
            "steps_total":    self._step_counter,
            "tools":          self.tools.stats(),
            "goals":          self.goals.stats(),
            "agent_memory":   self.memory.stats(),
            "reflection_quality": round(self.reflect.latest_quality(), 3),
            "pending_goals":  [
                {"id": g.goal_id, "desc": g.description[:60], "priority": round(g.priority, 2)}
                for g in self.goals.get_pending(5)
            ],
        }

    async def _tool_rewrite_query(self, raw_query: str) -> str:
        """Превращает разговорный запрос в эффективный поисковый запрос."""
        if not ENABLE_QUERY_REWRITE:
            return raw_query
        messages = [
            {"role": "system", "content": (
                "Ты — эксперт по поисковым системам. Перепиши запрос пользователя в несколько ключевых слов "
                "или короткую фразу для поиска в Google/Yandex. Убери лишние слова, добавь важные сущности. "
                "Если запрос уже короткий и точный — оставь как есть. Отвечай только готовым поисковым запросом."
            )},
            {"role": "user", "content": raw_query[:500]}
        ]
        try:
            rewritten = await self._call_llm_direct(messages)
            rewritten = rewritten.strip()
            if len(rewritten) < 3:
                rewritten = raw_query
            logger.debug(f"Query rewrite: '{raw_query}' -> '{rewritten}'")
            return rewritten
        except Exception as e:
            logger.warning(f"Rewrite failed: {e}")
            return raw_query

    async def _tool_learn_from_web(self, search_result_context: str) -> str:
        """
        Принимает контекст, полученный из web_search (страницы + сниппеты),
        извлекает новые факты и сохраняет в память агента.
        """
        if not AUTO_LEARN_FROM_WEB:
            return "Автоматическое обучение отключено."

        context = search_result_context[:8000]
        messages = [
            {"role": "system", "content": (
                "Извлеки из текста все проверяемые, конкретные факты. "
                "Каждый факт должен быть кратким, содержать суть и источник (если есть). "
                f"Максимум {MAX_FACTS_PER_SEARCH} фактов. "
                "Формат: 'факт: ... | источник: ...' (источник может быть URL или названием сайта)."
            )},
            {"role": "user", "content": context}
        ]
        facts_text = await self._call_llm_direct(messages)
        saved = 0
        for line in facts_text.split('\n'):
            line = line.strip()
            if line.startswith('факт:'):
                parts = line.split('|')
                fact = parts[0].replace('факт:', '').strip()
                source = parts[1].replace('источник:', '').strip() if len(parts) > 1 else "web"
                key = hashlib.md5(fact.encode()).hexdigest()[:16]
                self.memory.store_fact(key, f"{fact} (src: {source})", confidence=MIN_CONFIDENCE_TO_LEARN)
                saved += 1
                if saved >= MAX_FACTS_PER_SEARCH:
                    break
        if saved:
            logger.info(f"📚 Learned {saved} facts from web")
            if SHARE_LEARNED_FACTS_GLOBALLY:
                from routes.ai_assistant import GlobalKnowledgeBase
                for line in facts_text.split('\n'):
                    if line.startswith('факт:'):
                        fact = line.split('|')[0].replace('факт:', '').strip()
                        asyncio.create_task(
                            GlobalKnowledgeBase.get_instance().contribute(
                                user_id=self._user_id,
                                content=fact,
                                embedding=self._a.vocab.encode(fact),
                                importance=MIN_CONFIDENCE_TO_LEARN,
                                assistant=self._a
                            )
                        )
        return f"✅ Сохранено {saved} новых фактов в память агента (уверенность > {MIN_CONFIDENCE_TO_LEARN})."

# agent_core.py — добавить после AutonomousAgent

class ResearchAgent(AutonomousAgent):
    """
    Агент, специализирующийся на фактологических исследованиях.
    Цикл: Гипотеза → Поиск → Верификация → Синтез + Уверенность.
    """

    async def research(self, query: str) -> Dict[str, Any]:
        # 1. Генерация гипотез
        hypotheses = await self._generate_hypotheses(query)

        # 2. Сбор свидетельств по каждой гипотезе
        evidence = []
        for hyp in hypotheses:
            evidence.append(await self._gather_evidence(hyp))

        # 3. Верификация и выявление противоречий
        verified = await self._verify_evidence(evidence)

        # 4. Оценка уверенности
        confidence = self._compute_confidence(verified)

        # 5. Финальный ответ с указанием уверенности
        answer = await self._synthesize_research(query, verified, confidence)

        return {
            "answer": answer,
            "confidence": confidence,
            "hypotheses": hypotheses,
            "evidence": verified,
        }

    async def _synthesize_research(self, query: str, verified: List[Dict], confidence: float) -> str:
        prompt = f"""
    Ты исследователь. На основе собранных свидетельств и гипотез сформулируй итоговый ответ на вопрос: "{query}".

    Уверенность в ответе: {confidence:.0%}

    Свидетельства:
    {json.dumps(verified, ensure_ascii=False, indent=2)}

    Ответ должен быть чётким, опираться на факты, указывать уровень уверенности.
    """
        messages = [{"role": "user", "content": prompt}]
        return await self._call_llm_direct(messages)
    async def _generate_hypotheses(self, query: str) -> List[str]:
        # используем LLM, можно через planner, но проще прямой вызов
        prompt = f"""Ты исследователь. По запросу: "{query}" сгенерируй 3 проверяемые гипотезы.
Каждая гипотеза должна быть краткой и конкретной. Формат: список.
"""
        resp = await self._call_llm_direct([{"role": "user", "content": prompt}])
        # парсим список
        return [h.strip("-• ") for h in resp.split("\n") if h.strip()]

    async def _gather_evidence(self, hypothesis: str) -> Dict:
        # Рерайтинг гипотезы в поисковый запрос
        search_query = await self._tool_rewrite_query(hypothesis)
        # Ищем в памяти
        mem_result = await self._tool_memory_search(search_query)
        # Ищем в интернете
        web_result = await self._tool_web_search(search_query)
        # Извлекаем факты
        facts = await self._tool_learn_from_web(web_result[:3000])
        return {
            "hypothesis": hypothesis,
            "memory_evidence": mem_result,
            "web_evidence": web_result,
            "extracted_facts": facts,
        }

    async def _verify_evidence(self, evidence_list: List[Dict]) -> List[Dict]:
        # вызываем LLM для верификации каждого блока
        verified = []
        for ev in evidence_list:
            # используем _tool_verify_information (создадим ниже)
            verification = await self._tool_verify_information(
                f"Гипотеза: {ev['hypothesis']}\nДанные:\n{ev['web_evidence']}"
            )
            verified.append({**ev, "verification": verification})
        return verified

    def _compute_confidence(self, verified: List[Dict]) -> float:
        # простая метрика: кол-во подтверждений, отсутствие противоречий
        confirmations = 0
        contradictions = 0
        for v in verified:
            if "подтверждает" in v.get("verification", "").lower():
                confirmations += 1
            if "противоречит" in v.get("verification", "").lower():
                contradictions += 1
        base = min(1.0, confirmations / max(1, len(verified)))
        penalty = contradictions * 0.2
        return max(0.0, min(1.0, base - penalty))
# ──────────────────────────────────────────────────────────────────────────────
# Mixin для встраивания в SelfImprovingAssistant
# ──────────────────────────────────────────────────────────────────────────────

class AgentMixin:
    """
    Mixin для добавления агентных возможностей в SelfImprovingAssistant.

    Использование:
        class SelfImprovingAssistant(AgentMixin, ...):
            def __init__(self, user_id):
                super().__init__(user_id)
                self._init_agent()  # вызвать в конце __init__
    """

    def _init_agent(self):
        """Вызвать в конце __init__ SelfImprovingAssistant."""
        self._autonomous_agent = AutonomousAgent(self)

    @property
    def agent(self) -> AutonomousAgent:
        if not hasattr(self, '_autonomous_agent'):
            self._init_agent()
        return self._autonomous_agent

    def agent_stats(self) -> Dict:
        return self.agent.stats()

    async def run_goal(self, goal: str) -> str:
        return await self.agent.run_goal(goal)

    def register_tool(self, name: str, fn: Callable, description: str):
        """Регистрирует кастомный инструмент в агенте."""
        self.agent.tools.register(name, fn, description)