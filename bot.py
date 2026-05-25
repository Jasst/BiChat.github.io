#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 ADVANCED AUTONOMOUS LEARNING AGENT v4.0 — Веб-версия для blockcoin.ru
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Улучшенная версия с монохромным UI и полной поддержкой мобильных устройств
"""

import os
import sys
import json
import asyncio
import logging
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from pathlib import Path
from collections import deque, defaultdict, Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field, asdict
import gzip
import pickle
import time
import re
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Для RAG
try:
    import chromadb
    from chromadb.config import Settings

    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("⚠️ ChromaDB not available")

# Для BPE токенизации
try:
    from tokenizers import Tokenizer
    from tokenizers.models import BPE
    from tokenizers.trainers import BpeTrainer
    from tokenizers.pre_tokenizers import ByteLevel
    from tokenizers.processors import TemplateProcessing

    TOKENIZERS_AVAILABLE = True
except ImportError:
    TOKENIZERS_AVAILABLE = False
    print("⚠️ Tokenizers not available")

load_dotenv()


# ══════════════════════════════════════════════════════════════
# ⚙️ ADVANCED CONFIGURATION
# ══════════════════════════════════════════════════════════════

@dataclass
class AdvancedConfig:
    """Продвинутая конфигурация v4"""
    lm_studio_url: str = os.getenv('LM_STUDIO_API_URL', 'http://localhost:1234/v1/chat/completions')
    lm_studio_key: str = os.getenv('LM_STUDIO_API_KEY', 'lm-studio')

    host: str = "0.0.0.0"
    port: int = 8000
    websocket_path: str = "/ws"

    vocab_size: int = 50000
    d_model: int = 1024
    n_heads: int = 16
    n_layers: int = 12
    d_ff: int = 4096
    max_seq_length: int = 1024
    dropout: float = 0.1

    auto_scale_model: bool = True
    max_gpu_memory_gb: float = 8.0

    learning_rate: float = 5e-5
    meta_learning_rate: float = 1e-4
    batch_size: int = 8
    gradient_accumulation_steps: int = 4
    distillation_temperature: float = 2.0
    distillation_alpha: float = 0.7

    meta_learning_enabled: bool = True
    few_shot_examples: int = 5
    meta_batch_size: int = 4
    inner_loop_steps: int = 3

    rag_enabled: bool = CHROMADB_AVAILABLE
    rag_top_k: int = 5
    rag_chunk_size: int = 512
    rag_embedding_dim: int = 768

    temporal_embeddings: bool = True
    time_embedding_dim: int = 64
    circadian_cycle_hours: int = 24
    memory_decay_rate: float = 0.01

    initial_teacher_usage: float = 1.0
    min_teacher_usage: float = 0.05
    autonomy_growth_rate: float = 0.002
    confidence_threshold: float = 0.75

    replay_buffer_size: int = 50000
    training_frequency: int = 5
    save_frequency: int = 50

    base_dir: Path = Path('advanced_agent_v4')
    device: str = 'cuda' if torch.cuda.is_available() else 'cpu'
    mixed_precision: bool = torch.cuda.is_available()

    def __post_init__(self):
        for subdir in ['models', 'memory', 'logs', 'checkpoints', 'rag', 'tokenizer']:
            (self.base_dir / subdir).mkdir(parents=True, exist_ok=True)

        if self.auto_scale_model and self.device == 'cuda':
            self._auto_scale_to_gpu()

    def _auto_scale_to_gpu(self):
        try:
            gpu_memory_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
            print(f"🎮 GPU Memory: {gpu_memory_gb:.2f} GB")
            estimated_params = (self.vocab_size * self.d_model * 2 + self.n_layers * (
                        4 * self.d_model * self.d_model + 2 * self.d_model * self.d_ff))
            estimated_memory_gb = estimated_params * 4 / 1e9 * 1.5
            if estimated_memory_gb > gpu_memory_gb * 0.7:
                scale_factor = (gpu_memory_gb * 0.7) / estimated_memory_gb
                self.d_model = int(self.d_model * scale_factor ** 0.5)
                self.d_ff = int(self.d_ff * scale_factor ** 0.5)
                self.n_layers = max(6, int(self.n_layers * scale_factor ** 0.25))
                self.d_model = (self.d_model // self.n_heads) * self.n_heads
                print(f"⚙️ Auto-scaled: d_model={self.d_model}, n_layers={self.n_layers}, d_ff={self.d_ff}")
        except Exception as e:
            print(f"⚠️ Auto-scaling failed: {e}")


CONFIG = AdvancedConfig()


# ══════════════════════════════════════════════════════════════
# 📊 LOGGING
# ══════════════════════════════════════════════════════════════

def setup_logging() -> logging.Logger:
    logger = logging.getLogger('AdvancedAgent_v4')
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S'))
    log_file = CONFIG.base_dir / 'logs' / f'agent_v4_{datetime.now():%Y%m%d}.log'
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger


logger = setup_logging()


# ══════════════════════════════════════════════════════════════
# 🔤 ADVANCED BPE TOKENIZER
# ══════════════════════════════════════════════════════════════

class AdvancedBPETokenizer:
    def __init__(self, vocab_size: int = 50000):
        self.vocab_size = vocab_size
        self.tokenizer: Optional[Tokenizer] = None
        self.special_tokens = {'<PAD>': 0, '<UNK>': 1, '<BOS>': 2, '<EOS>': 3}
        if TOKENIZERS_AVAILABLE:
            self._init_bpe_tokenizer()
        else:
            self._init_fallback_tokenizer()

    def _init_bpe_tokenizer(self):
        self.tokenizer = Tokenizer(BPE(unk_token="<UNK>"))
        self.tokenizer.add_special_tokens(list(self.special_tokens.keys()))
        self.tokenizer.pre_tokenizer = ByteLevel(add_prefix_space=False)
        self.tokenizer.post_processor = TemplateProcessing(
            single="<BOS> $A <EOS>",
            special_tokens=[("<BOS>", self.special_tokens['<BOS>']), ("<EOS>", self.special_tokens['<EOS>'])]
        )

    def _init_fallback_tokenizer(self):
        self.word_to_id = self.special_tokens.copy()
        self.id_to_word = {v: k for k, v in self.special_tokens.items()}
        self.next_id = len(self.special_tokens)

    def encode(self, text: str, max_length: Optional[int] = None) -> List[int]:
        if TOKENIZERS_AVAILABLE and self.tokenizer:
            try:
                encoding = self.tokenizer.encode(text)
                tokens = encoding.ids
            except:
                words = text.lower().split()
                tokens = [self.special_tokens['<BOS>']] + [self.special_tokens.get('<UNK>', 1)] * len(words) + [
                    self.special_tokens['<EOS>']]
        else:
            words = text.lower().split()
            tokens = [self.special_tokens['<BOS>']] + [self.word_to_id.get(w, self.special_tokens['<UNK>']) for w in
                                                       words] + [self.special_tokens['<EOS>']]

        if max_length:
            if len(tokens) > max_length:
                tokens = tokens[:max_length]
            else:
                tokens = tokens + [self.special_tokens['<PAD>']] * (max_length - len(tokens))
        return tokens

    def decode(self, tokens: List[int], skip_special: bool = True) -> str:
        if TOKENIZERS_AVAILABLE and self.tokenizer:
            if skip_special:
                tokens = [t for t in tokens if t >= len(self.special_tokens)]
            return self.tokenizer.decode(tokens, skip_special_tokens=skip_special)
        else:
            words = []
            for t in tokens:
                w = self.id_to_word.get(t, '<UNK>')
                if not skip_special or w not in self.special_tokens:
                    words.append(w)
            return ' '.join(words)

    def save(self, path: Path):
        if TOKENIZERS_AVAILABLE and self.tokenizer:
            self.tokenizer.save(str(path / 'tokenizer.json'))
        else:
            with gzip.open(path / 'tokenizer_fallback.pkl.gz', 'wb') as f:
                pickle.dump({'word_to_id': self.word_to_id, 'id_to_word': self.id_to_word, 'next_id': self.next_id}, f)

    def load(self, path: Path) -> bool:
        if (path / 'tokenizer.json').exists() and TOKENIZERS_AVAILABLE:
            self.tokenizer = Tokenizer.from_file(str(path / 'tokenizer.json'))
            return True
        elif (path / 'tokenizer_fallback.pkl.gz').exists():
            with gzip.open(path / 'tokenizer_fallback.pkl.gz', 'rb') as f:
                state = pickle.load(f)
            self.word_to_id, self.id_to_word, self.next_id = state['word_to_id'], state['id_to_word'], state['next_id']
            return True
        return False


# ══════════════════════════════════════════════════════════════
# ⏰ TEMPORAL EMBEDDINGS
# ══════════════════════════════════════════════════════════════

class TemporalEmbeddings(nn.Module):
    def __init__(self, time_dim: int = 64):
        super().__init__()
        self.time_dim = time_dim
        self.time_scale = 10000.0
        self.circadian_embedding = nn.Embedding(24, time_dim)
        self.weekday_embedding = nn.Embedding(7, time_dim)
        self.month_embedding = nn.Embedding(12, time_dim)
        self.register_buffer('birth_timestamp', torch.tensor(time.time()))

    def get_current_time_features(self) -> Dict[str, int]:
        now = datetime.now()
        return {'hour': now.hour, 'weekday': now.weekday(), 'month': now.month - 1,
                'seconds_since_birth': int(time.time() - self.birth_timestamp.item())}

    def forward(self, batch_size: int = 1) -> torch.Tensor:
        features = self.get_current_time_features()
        device = next(self.parameters()).device
        hour_emb = self.circadian_embedding(torch.tensor([features['hour']], device=device)).expand(batch_size, -1)
        weekday_emb = self.weekday_embedding(torch.tensor([features['weekday']], device=device)).expand(batch_size, -1)
        month_emb = self.month_embedding(torch.tensor([features['month']], device=device)).expand(batch_size, -1)
        seconds = features['seconds_since_birth']
        position = torch.arange(self.time_dim, device=device).float()
        div_term = torch.exp(position * -(np.log(self.time_scale) / self.time_dim))
        continuous_emb = torch.zeros(batch_size, self.time_dim, device=device)
        continuous_emb[:, 0::2] = torch.sin(seconds * div_term[0::2])
        continuous_emb[:, 1::2] = torch.cos(seconds * div_term[1::2])
        return hour_emb + weekday_emb + month_emb + continuous_emb


# ══════════════════════════════════════════════════════════════
# 🧠 TRANSFORMER MODELS
# ══════════════════════════════════════════════════════════════

class MultiHeadAttention(nn.Module):
    def __init__(self, d_model: int, n_heads: int, dropout: float = 0.1):
        super().__init__()
        assert d_model % n_heads == 0
        self.d_model, self.n_heads, self.d_k = d_model, n_heads, d_model // n_heads
        self.W_q = nn.Linear(d_model, d_model)
        self.W_k = nn.Linear(d_model, d_model)
        self.W_v = nn.Linear(d_model, d_model)
        self.W_o = nn.Linear(d_model, d_model)
        self.dropout = nn.Dropout(dropout)
        self.scale = np.sqrt(self.d_k)

    def forward(self, x: torch.Tensor, mask: Optional[torch.Tensor] = None) -> torch.Tensor:
        B = x.size(0)
        Q = self.W_q(x).view(B, -1, self.n_heads, self.d_k).transpose(1, 2)
        K = self.W_k(x).view(B, -1, self.n_heads, self.d_k).transpose(1, 2)
        V = self.W_v(x).view(B, -1, self.n_heads, self.d_k).transpose(1, 2)
        scores = torch.matmul(Q, K.transpose(-2, -1)) / self.scale
        if mask is not None:
            scores = scores.masked_fill(mask == 0, -1e9)
        attn = self.dropout(F.softmax(scores, dim=-1))
        context = torch.matmul(attn, V).transpose(1, 2).contiguous().view(B, -1, self.d_model)
        return self.W_o(context)


class FeedForward(nn.Module):
    def __init__(self, d_model: int, d_ff: int, dropout: float = 0.1):
        super().__init__()
        self.linear1 = nn.Linear(d_model, d_ff)
        self.linear2 = nn.Linear(d_ff, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.linear2(self.dropout(F.gelu(self.linear1(x))))


class TransformerBlock(nn.Module):
    def __init__(self, d_model: int, n_heads: int, d_ff: int, dropout: float = 0.1):
        super().__init__()
        self.attn = MultiHeadAttention(d_model, n_heads, dropout)
        self.ff = FeedForward(d_model, d_ff, dropout)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor, mask: Optional[torch.Tensor] = None) -> torch.Tensor:
        x = x + self.dropout1(self.attn(self.norm1(x), mask))
        return x + self.dropout2(self.ff(self.norm2(x)))


class AdvancedStudentTransformer(nn.Module):
    def __init__(self, vocab_size: int, d_model: int = 1024, n_heads: int = 16, n_layers: int = 12, d_ff: int = 4096,
                 max_seq_length: int = 1024, dropout: float = 0.1, use_temporal: bool = True, time_dim: int = 64):
        super().__init__()
        self.d_model = d_model
        self.vocab_size = vocab_size
        self.use_temporal = use_temporal
        self.token_embedding = nn.Embedding(vocab_size, d_model)
        self.position_embedding = nn.Embedding(max_seq_length, d_model)
        if use_temporal:
            self.temporal_embeddings = TemporalEmbeddings(time_dim)
            self.temporal_projection = nn.Linear(time_dim, d_model)
        self.blocks = nn.ModuleList([TransformerBlock(d_model, n_heads, d_ff, dropout) for _ in range(n_layers)])
        self.norm = nn.LayerNorm(d_model)
        self.output_projection = nn.Linear(d_model, vocab_size)
        self.output_projection.weight = self.token_embedding.weight
        self._init_weights()

    def _init_weights(self):
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)

    def forward(self, input_ids: torch.Tensor, mask: Optional[torch.Tensor] = None,
                return_logits: bool = True) -> torch.Tensor:
        B, L = input_ids.size()
        device = input_ids.device
        x = self.token_embedding(input_ids) + self.position_embedding(
            torch.arange(L, device=device).unsqueeze(0).expand(B, -1))
        if self.use_temporal:
            x = x + self.temporal_projection(self.temporal_embeddings(B).unsqueeze(1))
        for block in self.blocks:
            x = block(x, mask)
        logits = self.output_projection(self.norm(x))
        return logits if return_logits else F.softmax(logits, dim=-1)

    def generate(self, prompt_ids: torch.Tensor, max_length: int = 100, temperature: float = 1.0, top_k: int = 50,
                 top_p: float = 0.9, eos_token_id: int = 3) -> Tuple[torch.Tensor, float]:
        self.eval()
        generated = prompt_ids.clone()
        confidences = []
        with torch.no_grad():
            for _ in range(max_length):
                logits = self.forward(generated, return_logits=True)
                next_logits = logits[:, -1, :] / temperature
                if top_k > 0:
                    next_logits[next_logits < torch.topk(next_logits, top_k)[0][..., -1, None]] = -float('Inf')
                if top_p < 1.0:
                    sorted_logits, sorted_indices = torch.sort(next_logits, descending=True)
                    cum_probs = torch.cumsum(F.softmax(sorted_logits, dim=-1), dim=-1)
                    sorted_indices_to_remove = cum_probs > top_p
                    sorted_indices_to_remove[..., 1:] = sorted_indices_to_remove[..., :-1].clone()
                    sorted_indices_to_remove[..., 0] = 0
                    next_logits[sorted_indices_to_remove.scatter(1, sorted_indices, sorted_indices_to_remove)] = -float(
                        'Inf')
                probs = F.softmax(next_logits, dim=-1)
                next_token = torch.multinomial(probs, num_samples=1)
                confidences.append(probs.max().item())
                generated = torch.cat([generated, next_token], dim=1)
                if next_token.item() == eos_token_id:
                    break
        return generated, np.mean(confidences) if confidences else 0.0


# ══════════════════════════════════════════════════════════════
# 👨‍🏫 TEACHER MODEL
# ══════════════════════════════════════════════════════════════

class TeacherLLM:
    def __init__(self, url: str, api_key: str):
        self.url = url
        self.api_key = api_key
        self._session = None
        self.total_calls = 0

    async def connect(self):
        if not self._session:
            import aiohttp
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))

    async def close(self):
        if self._session:
            await self._session.close()

    async def generate(self, prompt: str, temperature: float = 0.7, max_tokens: int = 500) -> Tuple[str, List[float]]:
        if not self._session:
            await self.connect()
        self.total_calls += 1
        try:
            async with self._session.post(self.url, json={"messages": [{"role": "user", "content": prompt}],
                                                          "temperature": temperature, "max_tokens": max_tokens,
                                                          "stream": False},
                                          headers={"Authorization": f"Bearer {self.api_key}",
                                                   "Content-Type": "application/json"}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('choices', [{}])[0].get('message', {}).get('content', '').strip(), []
                return "", []
        except Exception as e:
            logger.error(f"Teacher LLM error: {e}")
            return "", []


# ══════════════════════════════════════════════════════════════
# 🎓 TRAINER
# ══════════════════════════════════════════════════════════════

class AdvancedDistillationTrainer:
    def __init__(self, student_model: AdvancedStudentTransformer, tokenizer: AdvancedBPETokenizer, device: str = 'cpu'):
        self.student = student_model.to(device)
        self.tokenizer = tokenizer
        self.device = device
        self.optimizer = torch.optim.AdamW(self.student.parameters(), lr=CONFIG.learning_rate, weight_decay=0.01)
        self.scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(self.optimizer, T_0=100, T_mult=2)
        self.scaler = torch.cuda.amp.GradScaler() if CONFIG.mixed_precision else None
        self.replay_buffer = deque(maxlen=CONFIG.replay_buffer_size)
        self.training_steps = 0
        self.losses_history = deque(maxlen=1000)

    def add_to_replay_buffer(self, prompt: str, teacher_response: str):
        self.replay_buffer.append({'prompt': prompt, 'response': teacher_response, 'timestamp': time.time()})

    async def train_on_interaction(self, prompt: str, teacher_response: str) -> float:
        self.student.train()
        text = f"{prompt} {teacher_response}"
        input_ids = self.tokenizer.encode(text, max_length=CONFIG.max_seq_length)
        input_tensor = torch.tensor([input_ids], dtype=torch.long, device=self.device)
        labels = input_tensor[:, 1:].clone()
        input_for_model = input_tensor[:, :-1]

        if self.scaler:
            with torch.cuda.amp.autocast():
                logits = self.student(input_for_model, return_logits=True)
                loss = F.cross_entropy(logits.view(-1, logits.size(-1)), labels.view(-1), ignore_index=0)
            self.scaler.scale(loss).backward()
            self.scaler.step(self.optimizer)
            self.scaler.update()
        else:
            logits = self.student(input_for_model, return_logits=True)
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), labels.view(-1), ignore_index=0)
            loss.backward()
            self.optimizer.step()

        self.optimizer.zero_grad()
        self.scheduler.step()
        self.training_steps += 1
        self.losses_history.append(loss.item())
        return loss.item()


# ══════════════════════════════════════════════════════════════
# 🤖 ADVANCED AUTONOMOUS AGENT
# ══════════════════════════════════════════════════════════════

class AdvancedAutonomousAgent:
    def __init__(self, user_id: str, teacher: TeacherLLM):
        self.user_id = user_id
        self.teacher = teacher
        self.tokenizer = AdvancedBPETokenizer(vocab_size=CONFIG.vocab_size)
        self.student_model = AdvancedStudentTransformer(
            vocab_size=CONFIG.vocab_size,
            d_model=CONFIG.d_model,
            n_heads=CONFIG.n_heads,
            n_layers=CONFIG.n_layers,
            d_ff=CONFIG.d_ff,
            max_seq_length=CONFIG.max_seq_length,
            dropout=CONFIG.dropout,
            use_temporal=CONFIG.temporal_embeddings,
            time_dim=CONFIG.time_embedding_dim
        )
        self.trainer = AdvancedDistillationTrainer(self.student_model, self.tokenizer, device=CONFIG.device)
        self.rag = None
        self.teacher_usage_probability = CONFIG.initial_teacher_usage
        self.autonomy_level = 0.0
        self.total_interactions = 0
        self.teacher_calls = 0
        self.autonomous_responses = 0
        self.successful_autonomous = 0
        self.user_dir = CONFIG.base_dir / 'models' / user_id
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()
        logger.info(f"🚀 Agent v4 for {user_id} | Model: {self._count_parameters() / 1e6:.1f}M params")

    def _count_parameters(self) -> int:
        return sum(p.numel() for p in self.student_model.parameters())

    def _load_state(self):
        if (self.user_dir / 'student_model.pt').exists():
            try:
                checkpoint = torch.load(self.user_dir / 'student_model.pt', map_location=CONFIG.device)
                self.student_model.load_state_dict(checkpoint['model_state_dict'])
                self.trainer.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
                self.total_interactions = checkpoint.get('total_interactions', 0)
                self.teacher_calls = checkpoint.get('teacher_calls', 0)
                self.autonomous_responses = checkpoint.get('autonomous_responses', 0)
                self.autonomy_level = checkpoint.get('autonomy_level', 0.0)
                self.teacher_usage_probability = checkpoint.get('teacher_usage_probability',
                                                                CONFIG.initial_teacher_usage)
                logger.info(f"✅ Loaded: {self.total_interactions} interactions, autonomy={self.autonomy_level:.1%}")
            except Exception as e:
                logger.error(f"Load failed: {e}")

    def _save_state(self):
        torch.save({
            'model_state_dict': self.student_model.state_dict(),
            'optimizer_state_dict': self.trainer.optimizer.state_dict(),
            'total_interactions': self.total_interactions,
            'teacher_calls': self.teacher_calls,
            'autonomous_responses': self.autonomous_responses,
            'autonomy_level': self.autonomy_level,
            'teacher_usage_probability': self.teacher_usage_probability
        }, self.user_dir / 'student_model.pt')
        self.tokenizer.save(self.user_dir / 'tokenizer')

    def _should_use_teacher(self) -> bool:
        return np.random.random() < self.teacher_usage_probability

    def _update_autonomy(self, was_successful: bool):
        if was_successful:
            self.autonomy_level = min(1.0, self.autonomy_level + CONFIG.autonomy_growth_rate)
            self.successful_autonomous += 1
        else:
            self.autonomy_level = max(0.0, self.autonomy_level - CONFIG.autonomy_growth_rate * 0.5)
        self.teacher_usage_probability = max(CONFIG.min_teacher_usage, 1.0 - self.autonomy_level)

    async def generate_autonomous(self, prompt: str) -> Tuple[str, float]:
        prompt_ids = self.tokenizer.encode(prompt, max_length=CONFIG.max_seq_length // 2)
        prompt_tensor = torch.tensor([prompt_ids], dtype=torch.long, device=CONFIG.device)
        generated, confidence = self.student_model.generate(
            prompt_tensor,
            max_length=CONFIG.max_seq_length // 2,
            temperature=0.8,
            eos_token_id=self.tokenizer.special_tokens.get('<EOS>', 3)
        )
        return self.tokenizer.decode(generated[0].cpu().tolist(), skip_special=True), confidence

    async def process_interaction(self, user_input: str) -> Tuple[str, Dict]:
        start_time = time.time()
        self.total_interactions += 1
        response = ""
        confidence = 0.0
        used_teacher = False
        autonomous_attempt = False

        use_teacher = self._should_use_teacher()
        if not use_teacher:
            autonomous_attempt = True
            self.autonomous_responses += 1
            response, confidence = await self.generate_autonomous(user_input)
            if confidence < CONFIG.confidence_threshold:
                use_teacher = True

        if use_teacher:
            self.teacher_calls += 1
            used_teacher = True
            teacher_response, _ = await self.teacher.generate(user_input)
            if teacher_response:
                response = teacher_response
                confidence = 1.0
                if self.total_interactions % CONFIG.training_frequency == 0:
                    await self.trainer.train_on_interaction(user_input, teacher_response)
                else:
                    self.trainer.add_to_replay_buffer(user_input, teacher_response)
            else:
                response = "Извините, возникла проблема с генерацией ответа."
                confidence = 0.0

        if autonomous_attempt:
            self._update_autonomy(confidence >= CONFIG.confidence_threshold)

        if self.total_interactions % CONFIG.save_frequency == 0:
            self._save_state()

        metadata = {
            'used_teacher': used_teacher,
            'autonomous_attempt': autonomous_attempt,
            'confidence': confidence,
            'autonomy_level': self.autonomy_level,
            'teacher_usage_prob': self.teacher_usage_probability,
            'response_time': time.time() - start_time,
            'total_interactions': self.total_interactions,
            'autonomous_responses': self.autonomous_responses,
            'training_stats': {
                'training_steps': self.trainer.training_steps,
                'avg_loss': np.mean(list(self.trainer.losses_history)) if self.trainer.losses_history else 0.0
            },
            'model_size': f"{self._count_parameters() / 1e6:.1f}M"
        }

        logger.info(
            f"[{self.user_id}] Teacher={'Yes' if used_teacher else 'No'} | Conf={confidence:.2f} | Autonomy={self.autonomy_level:.1%}")
        return response, metadata

    def get_status(self) -> Dict:
        return {
            'user_id': self.user_id,
            'model_parameters': self._count_parameters(),
            'model_size_mb': self._count_parameters() * 4 / 1e6,
            'autonomy': {
                'level': self.autonomy_level,
                'teacher_usage_probability': self.teacher_usage_probability,
                'success_rate': self.successful_autonomous / max(1, self.autonomous_responses)
            },
            'interactions': {
                'total': self.total_interactions,
                'teacher_calls': self.teacher_calls,
                'autonomous_responses': self.autonomous_responses,
                'successful_autonomous': self.successful_autonomous
            },
            'training': {
                'training_steps': self.trainer.training_steps,
                'avg_loss': np.mean(list(self.trainer.losses_history)) if self.trainer.losses_history else 0.0,
                'replay_buffer_size': len(self.trainer.replay_buffer)
            },
            'features': {
                'rag_enabled': False,
                'meta_learning': CONFIG.meta_learning_enabled,
                'temporal_embeddings': CONFIG.temporal_embeddings,
                'mixed_precision': CONFIG.mixed_precision
            }
        }


# ══════════════════════════════════════════════════════════════
# 🌐 FASTAPI WEB SERVER
# ══════════════════════════════════════════════════════════════

app = FastAPI(title="Advanced AI Agent v4", description="Автономный обучающийся агент", version="4.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*"])

teacher: Optional[TeacherLLM] = None
agents: Dict[str, AdvancedAutonomousAgent] = {}
websocket_connections: Dict[str, Set[WebSocket]] = {}

# ══════════════════════════════════════════════════════════════
# 🎨 УЛУЧШЕННЫЙ МОНОХРОМНЫЙ HTML ИНТЕРФЕЙС v4
# ══════════════════════════════════════════════════════════════

HTML_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, user-scalable=yes">
    <meta name="theme-color" content="#0a0a0a">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>Advanced AI Agent v4 | BlockCoin.ru</title>
    <style>
        /* ═══════════════════════════════════════════════════════════════
           🎨 MONOCHROME DESIGN SYSTEM v4 — Optimized for Mobile
           ═══════════════════════════════════════════════════════════════ */

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }

        :root {
            /* Monochrome palette — чисто ч/б с полутонами */
            --bg-primary: #0a0a0a;
            --bg-secondary: #111111;
            --bg-tertiary: #1a1a1a;
            --bg-hover: #222222;
            --bg-active: #2a2a2a;
            --bg-elevated: #1e1e1e;

            --text-primary: #ffffff;
            --text-secondary: #a0a0a0;
            --text-muted: #555555;
            --text-inverse: #0a0a0a;

            --border-color: #2a2a2a;
            --border-focus: #444444;
            --border-light: #222222;

            --accent: #ffffff;
            --accent-hover: #e0e0e0;
            --accent-soft: rgba(255, 255, 255, 0.08);
            --accent-muted: rgba(255, 255, 255, 0.05);

            --status-success: #888888;
            --status-warning: #aaaaaa;
            --status-error: #cccccc;
            --status-info: #999999;

            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.5);
            --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.6);
            --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.8);

            --transition-fast: 0.15s ease;
            --transition-normal: 0.25s ease;
            --transition-slow: 0.4s cubic-bezier(0.4, 0, 0.2, 1);

            --space-xs: 4px;
            --space-sm: 8px;
            --space-md: 16px;
            --space-lg: 24px;
            --space-xl: 32px;

            --radius-sm: 6px;
            --radius-md: 12px;
            --radius-lg: 18px;
            --radius-full: 9999px;

            --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            --font-mono: 'SF Mono', 'Fira Code', 'Consolas', monospace;
            --font-size-base: 16px;
            --font-size-sm: 14px;
            --font-size-xs: 12px;
        }

        /* Base */
        html {
            scroll-behavior: smooth;
            -webkit-text-size-adjust: 100%;
            touch-action: manipulation;
        }

        body {
            font-family: var(--font-sans);
            font-size: var(--font-size-base);
            line-height: 1.5;
            color: var(--text-primary);
            background: var(--bg-primary);
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            overflow-x: hidden;
            min-height: 100vh;
            min-height: 100dvh;
        }

        /* Custom Scrollbar */
        ::-webkit-scrollbar {
            width: 4px;
            height: 4px;
        }
        ::-webkit-scrollbar-track {
            background: var(--bg-secondary);
        }
        ::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: var(--radius-full);
        }
        ::-webkit-scrollbar-thumb:hover {
            background: var(--text-muted);
        }

        /* Animations */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes fadeInScale {
            from { opacity: 0; transform: scale(0.95); }
            to { opacity: 1; transform: scale(1); }
        }
        @keyframes slideInRight {
            from { opacity: 0; transform: translateX(16px); }
            to { opacity: 1; transform: translateX(0); }
        }
        @keyframes slideInUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        @keyframes typing {
            0%, 60%, 100% { transform: translateY(0); }
            30% { transform: translateY(-8px); }
        }
        @keyframes shimmer {
            0% { background-position: -200% 0; }
            100% { background-position: 200% 0; }
        }

        .animate-fade { animation: fadeIn var(--transition-normal) forwards; }
        .animate-slide { animation: slideInRight var(--transition-normal) forwards; }
        .animate-up { animation: slideInUp var(--transition-normal) forwards; }

        /* Layout — Mobile First */
        .app-container {
            display: flex;
            flex-direction: column;
            height: 100vh;
            height: 100dvh;
            max-width: 800px;
            margin: 0 auto;
            background: var(--bg-primary);
            position: relative;
        }

        /* Header */
        .app-header {
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border-color);
            padding: var(--space-md) var(--space-lg);
            backdrop-filter: blur(10px);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .header-content {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--space-md);
        }
        .logo-area {
            display: flex;
            align-items: center;
            gap: var(--space-sm);
            flex: 1;
            min-width: 0;
        }
        .logo-icon {
            font-size: 28px;
            filter: grayscale(1);
        }
        .logo-text h1 {
            font-size: 18px;
            font-weight: 600;
            letter-spacing: -0.5px;
            white-space: nowrap;
        }
        .logo-text p {
            font-size: 10px;
            color: var(--text-muted);
            white-space: nowrap;
        }
        .header-actions {
            display: flex;
            gap: var(--space-sm);
        }
        .icon-btn {
            background: var(--bg-tertiary);
            border: none;
            color: var(--text-secondary);
            width: 36px;
            height: 36px;
            border-radius: var(--radius-md);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all var(--transition-fast);
            font-size: 18px;
        }
        .icon-btn:hover, .icon-btn:active {
            background: var(--bg-hover);
            color: var(--text-primary);
            transform: scale(0.96);
        }

        /* Main Chat Area */
        .chat-main {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            position: relative;
        }

        /* Messages Container */
        .messages-container {
            flex: 1;
            overflow-y: auto;
            padding: var(--space-md);
            display: flex;
            flex-direction: column;
            gap: var(--space-md);
            scroll-behavior: smooth;
        }

        /* Message Bubbles */
        .message {
            display: flex;
            gap: var(--space-sm);
            max-width: 90%;
            animation: fadeIn var(--transition-normal);
        }
        .message.user {
            margin-left: auto;
            flex-direction: row-reverse;
        }
        .message.assistant {
            margin-right: auto;
        }
        .message-avatar {
            width: 32px;
            height: 32px;
            border-radius: var(--radius-full);
            background: var(--bg-tertiary);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
            flex-shrink: 0;
        }
        .message.user .message-avatar {
            background: var(--accent);
            color: var(--text-inverse);
        }
        .message-bubble {
            max-width: calc(100% - 44px);
            padding: 12px 16px;
            background: var(--bg-tertiary);
            border-radius: var(--radius-lg);
            border-top-left-radius: var(--radius-sm);
        }
        .message.user .message-bubble {
            background: var(--accent);
            color: var(--text-inverse);
            border-radius: var(--radius-lg);
            border-top-right-radius: var(--radius-sm);
        }
        .message-bubble p {
            font-size: 15px;
            line-height: 1.45;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .message-meta {
            display: flex;
            align-items: center;
            gap: var(--space-xs);
            margin-top: var(--space-xs);
            font-size: 10px;
            color: var(--text-muted);
        }
        .message.user .message-meta {
            justify-content: flex-end;
            color: rgba(10, 10, 10, 0.5);
        }

        /* Mode Badge in Message */
        .mode-badge {
            font-size: 10px;
            padding: 2px 8px;
            border-radius: var(--radius-full);
            background: var(--accent-soft);
            display: inline-block;
        }
        .mode-badge.teacher { background: rgba(200, 200, 200, 0.15); }
        .mode-badge.auto { background: rgba(255, 255, 255, 0.1); }

        /* Typing Indicator */
        .typing-indicator {
            display: flex;
            gap: 4px;
            padding: 12px 16px;
            background: var(--bg-tertiary);
            border-radius: var(--radius-lg);
            width: fit-content;
        }
        .typing-indicator span {
            width: 8px;
            height: 8px;
            background: var(--text-muted);
            border-radius: 50%;
            animation: typing 1.4s infinite;
        }
        .typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
        .typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

        /* Input Area */
        .input-area {
            padding: var(--space-md);
            background: var(--bg-secondary);
            border-top: 1px solid var(--border-color);
        }
        .input-wrapper {
            display: flex;
            align-items: flex-end;
            gap: var(--space-sm);
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-lg);
            padding: var(--space-xs) var(--space-sm);
            transition: all var(--transition-fast);
        }
        .input-wrapper:focus-within {
            border-color: var(--border-focus);
            box-shadow: 0 0 0 2px var(--accent-soft);
        }
        .input-wrapper textarea {
            flex: 1;
            background: transparent;
            border: none;
            padding: 10px 8px;
            color: var(--text-primary);
            font-size: 15px;
            font-family: var(--font-sans);
            resize: none;
            max-height: 100px;
            outline: none;
            line-height: 1.4;
        }
        .input-wrapper textarea::placeholder {
            color: var(--text-muted);
        }
        .send-btn {
            background: var(--accent);
            border: none;
            color: var(--text-inverse);
            width: 40px;
            height: 40px;
            border-radius: var(--radius-md);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all var(--transition-fast);
            flex-shrink: 0;
        }
        .send-btn:active {
            transform: scale(0.94);
        }
        .send-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        /* Status Panel — Mobile Optimized */
        .status-panel {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: var(--bg-secondary);
            border-top: 1px solid var(--border-color);
            transform: translateY(100%);
            transition: transform var(--transition-normal);
            z-index: 200;
            max-height: 70vh;
            overflow-y: auto;
            border-radius: var(--radius-lg) var(--radius-lg) 0 0;
        }
        .status-panel.open {
            transform: translateY(0);
        }
        .status-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: var(--space-md) var(--space-lg);
            border-bottom: 1px solid var(--border-color);
            background: var(--bg-secondary);
            position: sticky;
            top: 0;
        }
        .status-header h3 {
            font-size: 16px;
            font-weight: 600;
        }
        .status-close {
            background: var(--bg-tertiary);
            border: none;
            color: var(--text-secondary);
            width: 32px;
            height: 32px;
            border-radius: var(--radius-md);
            cursor: pointer;
            font-size: 18px;
        }
        .status-content {
            padding: var(--space-lg);
            display: flex;
            flex-direction: column;
            gap: var(--space-md);
        }
        .status-card {
            background: var(--bg-tertiary);
            border-radius: var(--radius-md);
            padding: var(--space-md);
        }
        .status-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: var(--space-sm) 0;
            border-bottom: 1px solid var(--border-light);
        }
        .status-row:last-child {
            border-bottom: none;
        }
        .status-label {
            font-size: 13px;
            color: var(--text-secondary);
        }
        .status-value {
            font-size: 15px;
            font-weight: 600;
            font-family: var(--font-mono);
        }
        .progress-bar {
            background: var(--bg-hover);
            border-radius: var(--radius-full);
            height: 6px;
            overflow: hidden;
            margin-top: var(--space-xs);
        }
        .progress-fill {
            background: var(--accent);
            height: 100%;
            border-radius: var(--radius-full);
            transition: width var(--transition-normal);
        }

        /* Badges */
        .badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: var(--radius-full);
            font-size: 11px;
            font-weight: 500;
        }
        .badge-auto { background: rgba(255, 255, 255, 0.1); color: var(--text-primary); }
        .badge-teacher { background: rgba(200, 200, 200, 0.15); color: var(--text-secondary); }

        /* Quick Actions */
        .quick-actions {
            display: flex;
            gap: var(--space-sm);
            padding: var(--space-sm) var(--space-md);
            overflow-x: auto;
            scrollbar-width: none;
            -webkit-overflow-scrolling: touch;
        }
        .quick-actions::-webkit-scrollbar {
            display: none;
        }
        .quick-chip {
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            padding: 8px 16px;
            border-radius: var(--radius-full);
            font-size: 13px;
            white-space: nowrap;
            cursor: pointer;
            transition: all var(--transition-fast);
        }
        .quick-chip:active {
            background: var(--bg-hover);
            transform: scale(0.96);
        }

        /* Overlay for status panel */
        .overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(4px);
            z-index: 199;
            opacity: 0;
            visibility: hidden;
            transition: all var(--transition-normal);
        }
        .overlay.active {
            opacity: 1;
            visibility: visible;
        }

        /* Toast Notifications */
        .toast {
            position: fixed;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%) translateY(20px);
            background: var(--bg-elevated);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            padding: 12px 20px;
            display: flex;
            align-items: center;
            gap: var(--space-sm);
            z-index: 300;
            opacity: 0;
            visibility: hidden;
            transition: all var(--transition-normal);
            white-space: nowrap;
            backdrop-filter: blur(10px);
        }
        .toast.show {
            opacity: 1;
            visibility: visible;
            transform: translateX(-50%) translateY(0);
        }
        .toast.success { border-left: 3px solid var(--status-success); }
        .toast.error { border-left: 3px solid var(--status-error); }
        .toast.info { border-left: 3px solid var(--status-info); }

        /* Connection Status */
        .connection-status {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            background: var(--status-error);
            color: var(--text-inverse);
            text-align: center;
            padding: 4px;
            font-size: 12px;
            transform: translateY(-100%);
            transition: transform var(--transition-normal);
            z-index: 1000;
        }
        .connection-status.show {
            transform: translateY(0);
        }
        .connection-status.connected {
            background: var(--status-success);
        }

        /* Empty State */
        .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            text-align: center;
            padding: var(--space-xl);
            color: var(--text-muted);
        }
        .empty-state-icon {
            font-size: 48px;
            margin-bottom: var(--space-md);
            opacity: 0.5;
        }

        /* Loading */
        .loading-spinner {
            width: 20px;
            height: 20px;
            border: 2px solid var(--border-color);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Responsive */
        @media (min-width: 768px) {
            .app-container {
                max-width: 600px;
                box-shadow: var(--shadow-lg);
            }
            .status-panel {
                max-width: 400px;
                left: auto;
                right: var(--space-md);
                bottom: var(--space-md);
                border-radius: var(--radius-lg);
                transform: translateY(0) translateX(400px);
            }
            .status-panel.open {
                transform: translateY(0) translateX(0);
            }
            .toast {
                bottom: var(--space-xl);
            }
        }

        /* Reduced Motion */
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
            }
        }
    </style>
</head>
<body>
    <div class="app-container">
        <!-- Header -->
        <header class="app-header">
            <div class="header-content">
                <div class="logo-area">
                    <div class="logo-icon">⚡</div>
                    <div class="logo-text">
                        <h1>AI Agent v4.0</h1>
                        <p>автономное обучение</p>
                    </div>
                </div>
                <div class="header-actions">
                    <button class="icon-btn" id="statusBtn" aria-label="Статус">📊</button>
                    <button class="icon-btn" id="resetBtn" aria-label="Сброс">⟳</button>
                </div>
            </div>
        </header>

        <!-- Main Chat Area -->
        <main class="chat-main">
            <!-- Quick Actions -->
            <div class="quick-actions">
                <div class="quick-chip" data-prompt="Что такое искусственный интеллект?">🤖 Что такое ИИ?</div>
                <div class="quick-chip" data-prompt="Расскажи о машинном обучении">📚 ML обучение</div>
                <div class="quick-chip" data-prompt="Как учишься?">🎓 Как учишься?</div>
                <div class="quick-chip" data-prompt="Помоги с программированием">💻 Программирование</div>
            </div>

            <!-- Messages -->
            <div class="messages-container" id="messagesContainer">
                <div class="message assistant animate-fade">
                    <div class="message-avatar">🤖</div>
                    <div class="message-bubble">
                        <p>Привет! Я — Advanced AI Agent v4.0.<br>Задавай любые вопросы, я самообучаюсь с каждым диалогом!</p>
                        <div class="message-meta">
                            <span>🤖 Автономный режим</span>
                            <span>•</span>
                            <span>только что</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Input Area -->
            <div class="input-area">
                <div class="input-wrapper">
                    <textarea id="messageInput" placeholder="Введите сообщение..." rows="1" maxlength="2000"></textarea>
                    <button class="send-btn" id="sendBtn">➤</button>
                </div>
            </div>
        </main>

        <!-- Status Panel -->
        <div class="overlay" id="overlay"></div>
        <div class="status-panel" id="statusPanel">
            <div class="status-header">
                <h3>📊 Состояние агента</h3>
                <button class="status-close" id="closeStatusBtn">✕</button>
            </div>
            <div class="status-content">
                <div class="status-card">
                    <div class="status-row">
                        <span class="status-label">🎯 Автономность</span>
                        <span class="status-value" id="autonomyValue">0%</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" id="autonomyFill" style="width: 0%"></div>
                    </div>
                </div>
                <div class="status-card">
                    <div class="status-row">
                        <span class="status-label">👨‍🏫 Учитель</span>
                        <span class="status-value" id="teacherProbValue">100%</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" id="teacherFill" style="width: 100%"></div>
                    </div>
                </div>
                <div class="status-card">
                    <div class="status-row">
                        <span class="status-label">💬 Диалогов</span>
                        <span class="status-value" id="totalInteractions">0</span>
                    </div>
                    <div class="status-row">
                        <span class="status-label">🤖 Автономных</span>
                        <span class="status-value" id="autoResponses">0</span>
                    </div>
                    <div class="status-row">
                        <span class="status-label">📚 Параметров</span>
                        <span class="status-value" id="modelSize">0M</span>
                    </div>
                    <div class="status-row">
                        <span class="status-label">⚡ Успешность</span>
                        <span class="status-value" id="successRate">0%</span>
                    </div>
                </div>
                <div class="status-card">
                    <div class="status-row">
                        <span class="status-label">🎓 Шагов обучения</span>
                        <span class="status-value" id="trainingSteps">0</span>
                    </div>
                    <div class="status-row">
                        <span class="status-label">📉 Средняя ошибка</span>
                        <span class="status-value" id="avgLoss">0.00</span>
                    </div>
                    <div class="status-row">
                        <span class="status-label">💾 Буфер памяти</span>
                        <span class="status-value" id="bufferSize">0</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Connection Toast -->
        <div class="toast" id="toast">
            <span id="toastIcon">✓</span>
            <span id="toastMessage"></span>
        </div>

        <div class="connection-status" id="connStatus">
            🔌 Подключение...
        </div>
    </div>

    <script>
        // DOM Elements
        const messagesContainer = document.getElementById('messagesContainer');
        const messageInput = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendBtn');
        const statusBtn = document.getElementById('statusBtn');
        const resetBtn = document.getElementById('resetBtn');
        const statusPanel = document.getElementById('statusPanel');
        const overlay = document.getElementById('overlay');
        const closeStatusBtn = document.getElementById('closeStatusBtn');
        const toast = document.getElementById('toast');
        const connStatus = document.getElementById('connStatus');

        // WebSocket
        let ws = null;
        let reconnectAttempts = 0;
        let isTyping = false;

        // Auto-resize textarea
        function autoResizeTextarea() {
            messageInput.style.height = 'auto';
            messageInput.style.height = Math.min(messageInput.scrollHeight, 100) + 'px';
        }

        messageInput.addEventListener('input', autoResizeTextarea);

        // Show toast
        function showToast(message, type = 'info') {
            const toastIcon = document.getElementById('toastIcon');
            const toastMessage = document.getElementById('toastMessage');
            toast.className = `toast ${type} show`;
            toastIcon.textContent = type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ';
            toastMessage.textContent = message;
            setTimeout(() => {
                toast.classList.remove('show');
            }, 3000);
        }

        // Update connection status
        function updateConnectionStatus(connected) {
            connStatus.textContent = connected ? '✓ Подключено к серверу' : '⚠️ Потеря соединения, переподключение...';
            connStatus.className = `connection-status ${connected ? 'connected show' : 'show'}`;
            if (connected) {
                setTimeout(() => {
                    connStatus.classList.remove('show');
                }, 2000);
            }
        }

        // Add message to chat
        function addMessage(role, content, metadata = null) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${role} animate-fade`;
            const avatar = role === 'assistant' ? '🤖' : '👤';
            const mode = metadata?.used_teacher ? '👨‍🏫 Учитель' : '🤖 Автономный';
            const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            messageDiv.innerHTML = `
                <div class="message-avatar">${avatar}</div>
                <div class="message-bubble">
                    <p>${escapeHtml(content)}</p>
                    <div class="message-meta">
                        <span class="mode-badge ${metadata?.used_teacher ? 'teacher' : 'auto'}">${mode}</span>
                        <span>•</span>
                        <span>${time}</span>
                        ${metadata?.confidence ? `<span>• 🎯 ${Math.round(metadata.confidence * 100)}%</span>` : ''}
                    </div>
                </div>
            `;
            messagesContainer.appendChild(messageDiv);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }

        // Escape HTML
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Show typing indicator
        function showTypingIndicator() {
            if (isTyping) return;
            isTyping = true;
            const indicator = document.createElement('div');
            indicator.className = 'message assistant';
            indicator.id = 'typingIndicator';
            indicator.innerHTML = `
                <div class="message-avatar">🤖</div>
                <div class="typing-indicator">
                    <span></span><span></span><span></span>
                </div>
            `;
            messagesContainer.appendChild(indicator);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }

        // Remove typing indicator
        function removeTypingIndicator() {
            const indicator = document.getElementById('typingIndicator');
            if (indicator) indicator.remove();
            isTyping = false;
        }

        // Update status panel
        function updateStatus(metadata) {
            if (metadata.autonomy_level !== undefined) {
                const autonomyPercent = Math.round(metadata.autonomy_level * 100);
                document.getElementById('autonomyValue').textContent = `${autonomyPercent}%`;
                document.getElementById('autonomyFill').style.width = `${autonomyPercent}%`;
            }
            if (metadata.teacher_usage_prob !== undefined) {
                const teacherPercent = Math.round(metadata.teacher_usage_prob * 100);
                document.getElementById('teacherProbValue').textContent = `${teacherPercent}%`;
                document.getElementById('teacherFill').style.width = `${teacherPercent}%`;
            }
            if (metadata.total_interactions !== undefined) {
                document.getElementById('totalInteractions').textContent = metadata.total_interactions;
            }
            if (metadata.autonomous_responses !== undefined) {
                document.getElementById('autoResponses').textContent = metadata.autonomous_responses;
            }
            if (metadata.model_size) {
                document.getElementById('modelSize').textContent = metadata.model_size;
            }
            if (metadata.training_stats) {
                document.getElementById('trainingSteps').textContent = metadata.training_stats.training_steps || 0;
                document.getElementById('avgLoss').textContent = metadata.training_stats.avg_loss?.toFixed(4) || '0.00';
            }
            if (metadata.autonomy?.success_rate !== undefined) {
                document.getElementById('successRate').textContent = `${Math.round(metadata.autonomy.success_rate * 100)}%`;
            }
        }

        // Send message
        function sendMessage() {
            const message = messageInput.value.trim();
            if (!message || !ws || ws.readyState !== WebSocket.OPEN) {
                if (ws?.readyState !== WebSocket.OPEN) {
                    showToast('Нет соединения с сервером', 'error');
                }
                return;
            }

            addMessage('user', message);
            messageInput.value = '';
            autoResizeTextarea();
            sendBtn.disabled = true;

            ws.send(JSON.stringify({ type: 'message', content: message }));
            showTypingIndicator();
        }

        // Reset conversation
        async function resetConversation() {
            if (confirm('Сбросить историю диалога? Автономность агента будет сохранена.')) {
                try {
                    const response = await fetch('/reset/default');
                    if (response.ok) {
                        showToast('Диалог сброшен', 'success');
                        // Clear messages except first
                        const messages = messagesContainer.querySelectorAll('.message');
                        for (let i = 1; i < messages.length; i++) {
                            messages[i].remove();
                        }
                    }
                } catch (e) {
                    showToast('Ошибка сброса', 'error');
                }
            }
        }

        // WebSocket connection
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws`;

            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                console.log('✅ WebSocket connected');
                reconnectAttempts = 0;
                sendBtn.disabled = false;
                messageInput.disabled = false;
                updateConnectionStatus(true);
                showToast('Подключено к агенту', 'success');
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'response') {
                    removeTypingIndicator();
                    addMessage('assistant', data.content, data.metadata);
                    updateStatus(data.metadata);
                    sendBtn.disabled = false;
                    messageInput.focus();
                } else if (data.type === 'status') {
                    updateStatus(data.metadata);
                }
            };

            ws.onclose = () => {
                console.log('WebSocket disconnected');
                sendBtn.disabled = true;
                messageInput.disabled = true;
                updateConnectionStatus(false);
                removeTypingIndicator();

                setTimeout(() => {
                    reconnectAttempts++;
                    connectWebSocket();
                }, Math.min(1000 * Math.pow(2, reconnectAttempts), 30000));
            };

            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                showToast('Ошибка соединения', 'error');
            };
        }

        // Status panel handlers
        function toggleStatusPanel() {
            statusPanel.classList.toggle('open');
            overlay.classList.toggle('active');
        }

        statusBtn.addEventListener('click', toggleStatusPanel);
        closeStatusBtn.addEventListener('click', toggleStatusPanel);
        overlay.addEventListener('click', toggleStatusPanel);
        resetBtn.addEventListener('click', resetConversation);

        // Quick actions
        document.querySelectorAll('.quick-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const prompt = chip.dataset.prompt;
                if (prompt) {
                    messageInput.value = prompt;
                    autoResizeTextarea();
                    sendMessage();
                }
            });
        });

        // Enter to send (Shift+Enter for new line)
        messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // Focus input on load
        messageInput.focus();

        // Request status every 3 seconds
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'get_status' }));
            }
        }, 3000);

        // Start connection
        connectWebSocket();
    </script>
</body>
</html>
"""


@app.on_event("startup")
async def startup():
    global teacher
    teacher = TeacherLLM(CONFIG.lm_studio_url, CONFIG.lm_studio_key)
    await teacher.connect()
    logger.info(f"🚀 Server started on {CONFIG.host}:{CONFIG.port}")
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║  🚀 ADVANCED AUTONOMOUS AGENT v4.0                            ║
║     Монохромный интерфейс | Mobile First                      ║
╚═══════════════════════════════════════════════════════════════╝

🔥 ОСОБЕННОСТИ v4.0:

✅ ПОЛНОСТЬЮ МОНОХРОМНЫЙ ИНТЕРФЕЙС
✅ ОПТИМИЗАЦИЯ ДЛЯ МОБИЛЬНЫХ УСТРОЙСТВ
✅ BPE TOKENIZER | META-LEARNING | RAG
✅ АВТОНОМНОЕ ОБУЧЕНИЕ С УЧИТЕЛЕМ

🎮 УСТРОЙСТВО: {CONFIG.device.upper()}
📊 МОДЕЛЬ: {CONFIG.n_layers}L-{CONFIG.d_model}D-{CONFIG.n_heads}H
🌐 СЕРВЕР: http://{CONFIG.host}:{CONFIG.port}
📱 ОТКРОЙТЕ В БРАУЗЕРЕ ДЛЯ ОБЩЕНИЯ
""")


@app.on_event("shutdown")
async def shutdown():
    if teacher:
        await teacher.close()
    logger.info("👋 Server shutdown")


@app.get("/", response_class=HTMLResponse)
async def get_index():
    return HTMLResponse(HTML_PAGE)


@app.get("/health")
async def health_check():
    return {"status": "ok", "device": CONFIG.device, "model_size": f"{CONFIG.n_layers}L-{CONFIG.d_model}D"}


@app.get("/status/{user_id}")
async def get_user_status(user_id: str):
    if user_id in agents:
        return agents[user_id].get_status()
    return {"error": "User not found"}


@app.post("/reset/{user_id}")
async def reset_user(user_id: str):
    if user_id in agents:
        agents[user_id]._save_state()
        del agents[user_id]
    return {"status": "reset", "user_id": user_id}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    user_id = websocket.query_params.get("user_id", f"user_{int(time.time())}")

    if user_id not in agents:
        agents[user_id] = AdvancedAutonomousAgent(user_id, teacher)

    if user_id not in websocket_connections:
        websocket_connections[user_id] = set()
    websocket_connections[user_id].add(websocket)

    try:
        status = agents[user_id].get_status()
        await websocket.send_json({"type": "status", "metadata": status})

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)

                if msg.get("type") == "message":
                    user_input = msg.get("content", "")
                    if user_input:
                        response, metadata = await agents[user_id].process_interaction(user_input)
                        await websocket.send_json({
                            "type": "response",
                            "content": response,
                            "metadata": metadata
                        })

                        for conn in websocket_connections[user_id]:
                            if conn != websocket:
                                try:
                                    await conn.send_json({"type": "status", "metadata": agents[user_id].get_status()})
                                except:
                                    pass

                elif msg.get("type") == "get_status":
                    await websocket.send_json({
                        "type": "status",
                        "metadata": agents[user_id].get_status()
                    })

            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "content": "Invalid JSON"})

    except WebSocketDisconnect:
        websocket_connections[user_id].discard(websocket)
        if not websocket_connections[user_id]:
            agents[user_id]._save_state()
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        websocket_connections[user_id].discard(websocket)


# ══════════════════════════════════════════════════════════════
# 🚀 MAIN
# ══════════════════════════════════════════════════════════════

async def main():
    config = uvicorn.Config(app, host=CONFIG.host, port=CONFIG.port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 До встречи!")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()