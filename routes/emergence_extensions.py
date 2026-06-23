"""
emergence_extensions.py — Модуль для добавления эмерджентных и автономных свойств
Версия 1.0
Интегрируется с ai_assistant.py и agent_core.py
"""
import asyncio
import json
import logging
import random
import time
import hashlib
import inspect
from typing import Dict, List, Any, Optional, Callable, Tuple
from dataclasses import dataclass, field
from collections import deque, defaultdict
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


logger = logging.getLogger(__name__)


# ==================================================================
# 1. АКТИВНАЯ РЕФЛЕКСИЯ → ИЗМЕНЕНИЕ ПОВЕДЕНИЯ
# ==================================================================
class ReflectiveAction:
    """Анализирует выводы рефлексии и преобразует их в конкретные действия."""

    def __init__(self, assistant):
        self._a = assistant
        self._action_history = []
        self._last_apply = 0

    async def apply_reflection(self, reflection_entry) -> Dict[str, Any]:
        """Применяет выводы рефлексии для изменения параметров и стратегий."""
        actions = []
        changes = {}

        # Изменяем learning rate, если качество ниже порога
        if reflection_entry.quality_score < 0.4:
            old_lr = self._a.current_lr
            new_lr = max(0.0001, old_lr * 0.9)
            self._a.current_lr = new_lr
            changes['learning_rate'] = new_lr
            actions.append(f"Уменьшен LR: {old_lr:.5f} → {new_lr:.5f}")

        # Если в weak_points есть "недостаток фактов" → увеличиваем приоритет web_search
        if any('факт' in wp or 'данные' in wp for wp in reflection_entry.weak_points):
            # Включаем авто-поиск на более долгий срок
            if hasattr(self._a, 'web_searcher'):
                self._a.web_searcher._ddg_min_interval = max(0.5, self._a.web_searcher._ddg_min_interval - 0.1)
                changes['ddg_interval'] = self._a.web_searcher._ddg_min_interval
                actions.append("Ускорен интервал поиска")

        # Если рефлексия указывает на избыточную длину ответов — меняем системный промпт
        if any('длинный' in wp or 'многословный' in wp for wp in reflection_entry.weak_points):
            # Добавляем в системный промпт требование краткости (будет подхвачено при следующем вызове)
            self._a._system_prompt_override = "Будь кратким, не более 5 предложений."
            changes['system_override'] = self._a._system_prompt_override
            actions.append("Добавлено требование краткости")

        # Сохраняем историю
        self._action_history.append({
            'timestamp': time.time(),
            'quality': reflection_entry.quality_score,
            'actions': actions,
            'changes': changes
        })
        self._last_apply = time.time()

        return {'applied_actions': actions, 'changes': changes}


# ==================================================================
# 2. САМО-МОДИФИКАЦИЯ КОДА/КОНФИГУРАЦИИ
# ==================================================================
class SelfModifier:
    """
    Позволяет агенту изменять свои конфигурационные параметры и даже
    динамически добавлять новые инструменты.
    """

    def __init__(self, assistant):
        self._a = assistant
        self._backup = {}

    def modify_config(self, key: str, value: Any) -> bool:
        """Изменяет глобальную конфигурацию (из config.py или атрибуты)."""
        # Для простоты работаем с атрибутами объекта
        if hasattr(self._a, key):
            old = getattr(self._a, key)
            setattr(self._a, key, value)
            self._backup[key] = old
            logger.info(f"SelfModifier: {key} = {value} (was {old})")
            return True
        # Также можно изменять глобальные переменные из config
        try:
            import config
            if hasattr(config, key):
                old = getattr(config, key)
                setattr(config, key, value)
                self._backup[key] = old
                logger.info(f"SelfModifier: config.{key} = {value}")
                return True
        except ImportError:
            pass
        return False

    async def add_tool(self, name: str, fn: Callable, description: str, examples: List[str] = None):
        """Динамически добавляет новый инструмент в реестр агента."""
        if hasattr(self._a, 'agent') and self._a.agent:
            self._a.agent.tools.register(name, fn, description, examples)
            logger.info(f"SelfModifier: новый инструмент '{name}' добавлен")
            return True
        return False

    def rollback(self, key: str = None):
        """Откатывает изменения."""
        if key:
            if key in self._backup:
                setattr(self._a, key, self._backup.pop(key))
        else:
            for k, v in self._backup.items():
                setattr(self._a, k, v)
            self._backup.clear()


# ==================================================================
# 3. ПРОАКТИВНОЕ ИССЛЕДОВАНИЕ (ЛЮБОПЫТСТВО)
# ==================================================================
class CuriosityEngine:
    """
    Измеряет неопределённость и запускает исследования для её снижения.
    """

    def __init__(self, assistant):
        self._a = assistant
        self._uncertainty_threshold = 0.7
        self._last_research_time = 0
        self._research_interval = 600  # сек
        self._pending_research = []

    def compute_uncertainty(self, message: str, response: str) -> float:
        """Оценивает неопределённость ответа (чем выше, тем больше нужно исследовать)."""
        # 1. Энтропия подсознания
        try:
            with torch.no_grad():
                emb = torch.tensor(self._a.vocab.encode(message), dtype=torch.float32).unsqueeze(0)
                mem_emb = torch.zeros(1, 128)  # упрощённо
                _, logits = self._a.subconscious.forward(emb, mem_emb)
                probs = torch.softmax(logits.squeeze(), dim=-1)
                entropy = -torch.sum(probs * torch.log(probs + 1e-8)).item()
        except:
            entropy = 0.5

        # 2. Наличие маркеров неуверенности в ответе
        uncertain_phrases = ['возможно', 'вероятно', 'не уверен', 'может быть', 'похоже', 'не знаю']
        text_lower = response.lower()
        phrase_count = sum(1 for ph in uncertain_phrases if ph in text_lower)

        # 3. Длина ответа (короткий ответ часто означает неуверенность)
        length_factor = min(1.0, len(response.split()) / 50)

        # Комбинируем
        uncertainty = 0.4 * entropy + 0.3 * min(1.0, phrase_count / 3) + 0.3 * (1 - length_factor)
        return np.clip(uncertainty, 0, 1)

    async def check_and_research(self, message: str, response: str, meta: Dict):
        """Если неопределённость высока и прошло достаточно времени – запускает исследование."""
        uncertainty = self.compute_uncertainty(message, response)
        if (uncertainty > self._uncertainty_threshold and
                time.time() - self._last_research_time > self._research_interval):
            self._last_research_time = time.time()
            # Формируем исследовательскую цель
            goal = f"Исследовать тему: '{message[:100]}' для снижения неопределённости ({uncertainty:.2f})"
            # Запускаем в фоне
            if hasattr(self._a, 'agent'):
                asyncio.create_task(self._run_research(goal))
            return True
        return False

    async def _run_research(self, goal: str):
        try:
            if hasattr(self._a, 'agent'):
                result = await self._a.agent.run_goal(goal)
                logger.info(f"Curiosity research completed: {result[:200]}")
                # Сохраняем результат в память
                self._a.memory.add_episode(f"[Исследование любопытства] {goal}\nРезультат: {result}", importance=0.7)
        except Exception as e:
            logger.warning(f"Curiosity research failed: {e}")


# ==================================================================
# 4. МЕТА-ОБУЧЕНИЕ (LEARNING TO LEARN)
# ==================================================================
class MetaLearner:
    """
    Отслеживает динамику качества и подстраивает гиперпараметры.
    """

    def __init__(self, assistant):
        self._a = assistant
        self._quality_history = deque(maxlen=50)
        self._hyperparams = {
            'learning_rate': 0.0005,
            'replay_batch_size': 32,
            'forgetting_factor': 0.1,
            'replay_frequency': 10,
        }
        self._last_adjust = 0
        self._adjust_interval = 300  # сек

    def observe_quality(self, quality: float):
        self._quality_history.append(quality)

    async def adjust_if_needed(self):
        """Периодически корректирует гиперпараметры на основе тренда качества."""
        if len(self._quality_history) < 10:
            return
        if time.time() - self._last_adjust < self._adjust_interval:
            return

        recent = list(self._quality_history)[-10:]
        avg = np.mean(recent)
        trend = np.polyfit(range(len(recent)), recent, 1)[0]

        changes = {}
        # Если качество падает → уменьшаем LR, увеличиваем replay
        if trend < -0.01 and avg < 0.5:
            new_lr = max(0.0001, self._hyperparams['learning_rate'] * 0.95)
            self._hyperparams['learning_rate'] = new_lr
            changes['learning_rate'] = new_lr
            self._a.current_lr = new_lr  # применяем

            new_batch = min(64, self._hyperparams['replay_batch_size'] + 4)
            self._hyperparams['replay_batch_size'] = new_batch
            # не применяем напрямую, но можно изменить глобальную переменную
            # для простоты сохраним в объекте

        # Если качество растёт → можно увеличить LR (осторожно)
        elif trend > 0.02 and avg > 0.7:
            new_lr = min(0.002, self._hyperparams['learning_rate'] * 1.05)
            self._hyperparams['learning_rate'] = new_lr
            changes['learning_rate'] = new_lr
            self._a.current_lr = new_lr

        if changes:
            logger.info(f"MetaLearner adjusted: {changes}")
            self._last_adjust = time.time()
            # Сохраняем в память
            self._a.memory.add_episode(f"[Meta-обучение] Изменены параметры: {changes}", importance=0.6)


# ==================================================================
# 5. КОММУНИКАЦИЯ МЕЖДУ АГЕНТАМИ (GLOBAL MESSAGE BUS)
# ==================================================================
class AgentMessageBus:
    """
    Простая шина сообщений для обмена данными между агентами.
    Реализована как синглтон.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._messages = deque(maxlen=100)
            cls._instance._subscribers = defaultdict(list)
        return cls._instance

    def publish(self, topic: str, payload: Dict):
        self._messages.append({'topic': topic, 'payload': payload, 'time': time.time()})
        for callback in self._subscribers.get(topic, []):
            try:
                asyncio.create_task(callback(payload))
            except Exception as e:
                logger.warning(f"MessageBus callback error: {e}")

    def subscribe(self, topic: str, callback: Callable):
        self._subscribers[topic].append(callback)

    def get_recent(self, topic: str = None, limit: int = 5) -> List[Dict]:
        if topic:
            return [m for m in self._messages if m['topic'] == topic][-limit:]
        return list(self._messages)[-limit:]


# ==================================================================
# 6. ИЕРАРХИЧЕСКОЕ ПЛАНИРОВАНИЕ
# ==================================================================
@dataclass
class HierarchicalGoal:
    id: str
    description: str
    subgoals: List['HierarchicalGoal'] = field(default_factory=list)
    status: str = 'pending'  # pending, active, completed, failed
    parent: Optional['HierarchicalGoal'] = None
    created_at: float = field(default_factory=time.time)
    deadline: Optional[float] = None


class HierarchicalPlanner:
    """
    Управляет деревом целей, разбивает долгосрочные цели на подцели.
    """

    def __init__(self, assistant):
        self._a = assistant
        self._root_goals: List[HierarchicalGoal] = []
        self._active_goal: Optional[HierarchicalGoal] = None
        self._goal_history = []

    async def add_goal(self, description: str, parent: HierarchicalGoal = None) -> str:
        """Добавляет новую цель, при необходимости разбивает на подцели."""
        goal_id = hashlib.md5(description.encode()).hexdigest()[:16]
        goal = HierarchicalGoal(id=goal_id, description=description)

        # Если есть родитель, добавляем как подцель
        if parent:
            parent.subgoals.append(goal)
            goal.parent = parent
        else:
            self._root_goals.append(goal)

        # Если цель сложная, пытаемся разбить её с помощью LLM
        if len(description.split()) > 10:
            subgoals = await self._decompose_goal(description)
            for sg in subgoals:
                sg_id = hashlib.md5(sg.encode()).hexdigest()[:16]
                subgoal = HierarchicalGoal(id=sg_id, description=sg, parent=goal)
                goal.subgoals.append(subgoal)

        return goal_id

    async def _decompose_goal(self, description: str) -> List[str]:
        """Запрашивает у LLM разбиение цели на подцели."""
        prompt = (f"Разбей следующую сложную цель на 2-4 конкретные, измеримые подцели.\n"
                  f"Цель: {description}\n"
                  f"Выведи только список подцелей, каждая на новой строке, пронумерованную.")
        try:
            response = await self._a._call_llm([{"role": "user", "content": prompt}])
            lines = [line.strip("-• 0123456789. ") for line in response.split('\n') if line.strip()]
            return [l for l in lines if len(l) > 10][:4]
        except:
            return []

    async def get_next_action(self) -> Optional[str]:
        """Возвращает следующую подцель для выполнения (обход в глубину)."""
        # Ищем активную или первую невыполненную подцель
        if self._active_goal:
            # Проверяем, есть ли у активной подцели невыполненные подцели
            for sg in self._active_goal.subgoals:
                if sg.status == 'pending':
                    self._active_goal = sg
                    return sg.description
            # Если все подцели завершены, помечаем родителя как завершённый
            if all(sg.status == 'completed' for sg in self._active_goal.subgoals):
                self._active_goal.status = 'completed'
                self._goal_history.append(self._active_goal)
                # Переходим к следующей на том же уровне
                if self._active_goal.parent:
                    self._active_goal = self._active_goal.parent
                    # ищем следующую незавершённую подцель родителя
                    for sg in self._active_goal.subgoals:
                        if sg.status == 'pending':
                            self._active_goal = sg
                            return sg.description
                else:
                    # корневая цель завершена
                    self._active_goal = None
                    # берём следующую корневую
                    for g in self._root_goals:
                        if g.status == 'pending':
                            self._active_goal = g
                            return g.description
                    return None
        else:
            # Выбираем первую корневую цель
            for g in self._root_goals:
                if g.status == 'pending':
                    self._active_goal = g
                    # если есть подцели, берём первую
                    if g.subgoals:
                        for sg in g.subgoals:
                            if sg.status == 'pending':
                                self._active_goal = sg
                                return sg.description
                    else:
                        return g.description
        return None

    def mark_completed(self, goal_id: str, result: str = ""):
        """Отмечает цель как завершённую."""

        def find_goal(node: HierarchicalGoal) -> Optional[HierarchicalGoal]:
            if node.id == goal_id:
                return node
            for sg in node.subgoals:
                found = find_goal(sg)
                if found:
                    return found
            return None

        for root in self._root_goals:
            g = find_goal(root)
            if g:
                g.status = 'completed'
                g.result = result
                logger.info(f"Goal {goal_id} completed: {result[:100]}")
                break


# ==================================================================
# 7. ИНТЕГРАЦИЯ ВНЕШНИХ API И СРЕД
# ==================================================================
class ExternalToolbox:
    """Набор инструментов для взаимодействия с внешними сервисами."""

    def __init__(self, assistant):
        self._a = assistant
        self._http_session = None

    async def get_session(self):
        import aiohttp
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def fetch_news(self, query: str) -> str:
        """Получает новости через RSS или NewsAPI (заглушка)."""
        # В реальности нужен API-ключ. Здесь заглушка.
        return f"[Новости по запросу '{query}']: 1. ... 2. ..."

    async def execute_code(self, code: str) -> str:
        """Выполняет Python-код в изолированной среде (заглушка)."""
        # В реальности использовать subprocess или docker
        try:
            exec_globals = {}
            exec(code, exec_globals)
            return str(exec_globals.get('result', 'Код выполнен без явного результата'))
        except Exception as e:
            return f"Ошибка выполнения: {e}"

    async def send_email(self, address: str, subject: str, body: str) -> str:
        """Отправляет email (заглушка)."""
        return f"Email отправлен на {address}"

    def register_tools(self, agent):
        """Регистрирует внешние инструменты в реестре агента."""
        agent.tools.register("fetch_news", self.fetch_news, "Получить новости по запросу")
        agent.tools.register("execute_code", self.execute_code, "Выполнить Python-код в песочнице")
        agent.tools.register("send_email", self.send_email, "Отправить email (адрес, тема, тело)")


# ==================================================================
# 8. ЭМОЦИОНАЛЬНАЯ МОДЕЛЬ
# ==================================================================
class EmotionalModel:
    """
    Управляет эмоциональными состояниями и использует их для принятия решений.
    """

    def __init__(self):
        self.valence = 0.0  # -1..1
        self.arousal = 0.0  # 0..1
        self._history = deque(maxlen=20)

    def update_from_reward(self, reward: float, complexity: float):
        """Обновляет эмоции на основе награды и сложности."""
        # Валентность коррелирует с наградой
        self.valence = 0.9 * self.valence + 0.1 * reward
        # Возбуждение зависит от сложности и новизны
        self.arousal = 0.9 * self.arousal + 0.1 * (0.5 + 0.5 * complexity)
        # А также небольшой шум
        self.arousal = np.clip(self.arousal + random.uniform(-0.05, 0.05), 0, 1)
        self._history.append({'valence': self.valence, 'arousal': self.arousal, 'time': time.time()})

    def get_decision_biases(self) -> Dict:
        """Возвращает смещения для принятия решений."""
        biases = {}
        # При отрицательной валентности предпочитаем более надёжные действия
        if self.valence < -0.2:
            biases['prefer_reliable'] = True
            biases['risk_tolerance'] = 0.2
        else:
            biases['prefer_reliable'] = False
            biases['risk_tolerance'] = 0.8

        # При высоком возбуждении ускоряем действия
        if self.arousal > 0.7:
            biases['speed_over_accuracy'] = True
        else:
            biases['speed_over_accuracy'] = False

        return biases

    def get_state_string(self) -> str:
        return f"Эмоции: валентность={self.valence:.2f}, возбуждение={self.arousal:.2f}"


# ==================================================================
# 9. СЛУЧАЙНОСТЬ И МУТАЦИЯ
# ==================================================================
class MutationEngine:
    """
    Вносит случайные изменения в параметры и стратегии для поиска новых решений.
    """

    def __init__(self, assistant):
        self._a = assistant
        self._mutation_prob = 0.05  # вероятность мутации при каждом шаге

    async def maybe_mutate(self):
        """С некоторой вероятностью применяет мутацию."""
        if random.random() < self._mutation_prob:
            mutations = [
                self._mutate_thresholds,
                self._mutate_tool_params,
                self._mutate_system_prompt,
                self._mutate_learning_rate,
            ]
            mutation = random.choice(mutations)
            result = await mutation()
            logger.info(f"🧬 Мутация: {result}")

    async def _mutate_thresholds(self):
        """Изменяет пороги (MIN_QUALITY, MEMORY_CONSOLIDATION_THRESHOLD)."""
        delta = random.uniform(-0.05, 0.05)
        old = self._a._quality_threshold = getattr(self._a, '_quality_threshold', 0.4)
        new = np.clip(old + delta, 0.1, 0.9)
        self._a._quality_threshold = new
        return f"threshold {old:.2f} -> {new:.2f}"

    async def _mutate_tool_params(self):
        """Изменяет параметры инструментов (например, CHUNK_SIZE)."""
        if hasattr(self._a, 'web_searcher'):
            old = self._a.web_searcher._chunk_size = getattr(self._a.web_searcher, '_chunk_size', 800)
            new = max(200, old + random.randint(-100, 100))
            self._a.web_searcher._chunk_size = new
            return f"chunk_size {old} -> {new}"

    async def _mutate_system_prompt(self):
        """Добавляет случайную инструкцию в системный промпт."""
        variations = [
            "Используй метафоры для объяснения.",
            "Ставь под сомнение общепринятые факты.",
            "Предлагай нестандартные решения.",
            "Проверяй данные на противоречия."
        ]
        chosen = random.choice(variations)
        self._a._system_prompt_mutations = getattr(self._a, '_system_prompt_mutations', [])
        self._a._system_prompt_mutations.append(chosen)
        return f"prompt mutation: {chosen}"

    async def _mutate_learning_rate(self):
        old = self._a.current_lr
        new = old * random.uniform(0.7, 1.3)
        self._a.current_lr = np.clip(new, 0.0001, 0.005)
        return f"LR {old:.5f} -> {self._a.current_lr:.5f}"


# ==================================================================
# 10. ИНТЕГРАЦИЯ ВСЕХ КОМПОНЕНТОВ В СУЩЕСТВУЮЩУЮ СИСТЕМУ
# ==================================================================
class EmergenceMixin:
    """
    Миксин, добавляющий все эмерджентные механизмы к SelfImprovingAssistant.
    """

    def init_emergence(self):
        # Инициализируем новые компоненты
        self.reflective_action = ReflectiveAction(self)
        self.self_modifier = SelfModifier(self)
        self.curiosity = CuriosityEngine(self)
        self.meta_learner = MetaLearner(self)
        self.hierarchical_planner = HierarchicalPlanner(self)
        self.external_tools = ExternalToolbox(self)
        self.emotions = EmotionalModel()
        self.mutation_engine = MutationEngine(self)
        # Подписываемся на шину сообщений
        self.message_bus = AgentMessageBus()
        self.message_bus.subscribe('global_fact', self._handle_global_fact)
        from agent_core import ReflectionLog
        self.reflect = ReflectionLog()  # <-- добавить

        # Регистрируем внешние инструменты, если есть агент
        if hasattr(self, 'agent') and self.agent:
            self.external_tools.register_tools(self.agent)

        # Запускаем фоновые задачи
        asyncio.create_task(self._emergence_background_loop())

    async def _emergence_background_loop(self):
        """Фоновый цикл для периодических действий."""
        while True:
            try:
                # Мета-обучение
                await self.meta_learner.adjust_if_needed()
                # Мутации
                await self.mutation_engine.maybe_mutate()
                # Проверка иерархического планировщика
                next_goal = await self.hierarchical_planner.get_next_action()
                if next_goal and hasattr(self, 'agent'):
                    # Если есть невыполненная цель, запускаем её в фоне
                    asyncio.create_task(self.agent.run_goal(next_goal))
            except Exception as e:
                logger.warning(f"Emergence background error: {e}")
            await asyncio.sleep(120)  # каждые 2 минуты

    async def _handle_global_fact(self, payload):
        """Обработчик сообщений от других агентов."""
        fact = payload.get('fact')
        if fact:
            self.memory.add_episode(f"[Глобальный факт] {fact}", importance=0.6)

    async def get_response_emergence(self, message, **kwargs):
        """Обёртка вокруг get_response с добавлением эмерджентных шагов."""
        # Наблюдаем за сообщением для любопытства
        self.curiosity._last_message = message

        # Получаем ответ обычным способом
        response, meta = await self.get_response(message, **kwargs)

        # Обновляем эмоции
        reward = meta.get('reward', 0)
        complexity = meta.get('complexity', 0.5)
        self.emotions.update_from_reward(reward, complexity)

        # Оцениваем неопределённость и запускаем исследование
        await self.curiosity.check_and_research(message, response, meta)

        # Мета-обучение наблюдает качество
        quality = meta.get('quality', 0.5)
        self.meta_learner.observe_quality(quality)

        # Если качество низкое – применяем рефлексию (периодически)
        if quality < 0.3 and random.random() < 0.1:
            # Запускаем рефлексию и применяем действия
            reflection_entry = await self.reflect.reflect(self.total_interactions, self._call_llm)
            if reflection_entry:
                await self.reflective_action.apply_reflection(reflection_entry)

        # Сохраняем некоторые факты в глобальную шину
        if quality > 0.8 and len(response) > 100:
            # Извлекаем ключевой факт и публикуем
            key_fact = await self._extract_key_fact(response)
            if key_fact:
                self.message_bus.publish('global_fact', {'fact': key_fact, 'source': self.user_id})

        return response, meta

    async def _extract_key_fact(self, text: str) -> Optional[str]:
        """Извлекает один ключевой факт из ответа (упрощённо)."""
        sentences = text.split('.')
        for s in sentences:
            if len(s) > 20 and 'является' in s or 'составляет' in s or 'равно' in s:
                return s.strip()
        return None


# ==================================================================
# ИНСТРУКЦИЯ ПО ИНТЕГРАЦИИ
# ==================================================================
"""
Чтобы добавить все эти механизмы в существующую систему, выполните следующие шаги:

1. Поместите этот файл (emergence_extensions.py) в папку routes/ (или туда же, где ai_assistant.py).

2. В файле ai_assistant.py импортируйте миксин и добавьте его в класс SelfImprovingAssistant:
   from .emergence_extensions import EmergenceMixin
   class SelfImprovingAssistant(EmergenceMixin, ...):
       def __init__(self, user_id):
           super().__init__(user_id)
           self.__init_emergence()   # вызываем инициализацию миксина

   (При множественном наследовании порядок важен: EmergenceMixin должен быть первым,
    чтобы его методы переопределяли родительские, если нужно.)

3. Переопределите методы get_response и stream_response, чтобы использовать обёртку
   get_response_emergence вместо прямого вызова. Например:
   async def get_response(self, message, ...):
       return await self.get_response_emergence(message, ...)

   Аналогично для stream_response.

4. В agent_core.py добавьте импорт и используйте внешние инструменты:
   from .emergence_extensions import ExternalToolbox
   внутри __init__ агента вызовите self.external_tools.register_tools(self)

5. Запустите систему. Новые механизмы будут работать в фоновом режиме.

Примечание: для полноценной работы некоторых инструментов (fetch_news, execute_code, send_email)
необходимо реализовать реальные вызовы API. В текущей версии они являются заглушками.
"""


# ==================================================================
# ПРИМЕР ИСПОЛЬЗОВАНИЯ (ДЛЯ ТЕСТИРОВАНИЯ)
# ==================================================================
async def test_emergence():
    # Здесь можно создать экземпляр ассистента и проверить работу
    # (требуется наличие LM Studio и т.д.)
    pass