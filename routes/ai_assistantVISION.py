"""
routes/ai_assistant.py — AI‑чат через LM Studio с поддержкой streaming и изображений
"""
import logging
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dependencies import require_auth
import aiohttp
import asyncio

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/ai', tags=['ai'])

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_STUDIO_API_KEY = "lm-studio"

class AIRequest(BaseModel):
    message: str
    image_base64: Optional[str] = None
    image_mime: Optional[str] = None
    stream: bool = True

@router.post("/chat")
async def chat_with_ai(body: AIRequest, address: str = Depends(require_auth)):
    try:
        content = []
        if body.message and body.message.strip():
            content.append({"type": "text", "text": body.message.strip()})
        if body.image_base64 and body.image_mime:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{body.image_mime};base64,{body.image_base64}"}
            })
            logger.debug(
                f"Received image MIME: {body.image_mime}, base64 length: {len(body.image_base64) if body.image_base64 else 0}")
        if not content:
            raise HTTPException(400, "No content provided")

        messages = [{"role": "user", "content": content}]

        payload = {
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1000,
            "stream": body.stream
        }
        headers = {"Content-Type": "application/json"}
        if LM_STUDIO_API_KEY:
            headers["Authorization"] = f"Bearer {LM_STUDIO_API_KEY}"

        if body.stream:
            return StreamingResponse(
                stream_lm_studio(payload, headers),
                media_type="text/event-stream"
            )
        else:
            async with aiohttp.ClientSession() as session:
                async with session.post(LM_STUDIO_URL, json=payload, headers=headers, timeout=60) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"LM Studio error {resp.status}: {error_text}")
                        raise HTTPException(500, "AI service unavailable")
                    data = await resp.json()
                    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    if not reply:
                        reply = "🤖 Извините, не удалось сгенерировать ответ."
                    return {"reply": reply}
    except asyncio.TimeoutError:
        logger.error("LM Studio request timeout")
        raise HTTPException(504, "AI service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("AI request failed")
        raise HTTPException(500, str(e))

async def stream_lm_studio(payload: dict, headers: dict):
    """Потоковый парсер с улучшенным извлечением токенов."""
    timeout = aiohttp.ClientTimeout(total=None, sock_read=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(LM_STUDIO_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"LM Studio stream error {resp.status}: {error_text}")
                yield f"data: {json.dumps({'error': 'AI service unavailable'})}\n\n"
                return

            buffer = ""
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
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        data = json.loads(data_str)
                        token = None
                        if 'choices' in data and data['choices']:
                            choice = data['choices'][0]
                            if 'delta' in choice and 'content' in choice['delta']:
                                token = choice['delta'].get('content', '')
                            elif 'text' in choice:
                                token = choice.get('text', '')
                            elif 'message' in choice and 'content' in choice['message']:
                                token = choice['message'].get('content', '')
                            elif 'delta' in choice and isinstance(choice['delta'], dict):
                                token = choice['delta'].get('content', '')
                        if token:
                            yield f"data: {json.dumps({'token': token})}\n\n"
                        else:
                            # Отладочный лог (один раз)
                            if not hasattr(stream_lm_studio, '_logged'):
                                logger.debug(f"Unrecognized chunk: {data}")
                                stream_lm_studio._logged = True
                    except json.JSONDecodeError:
                        continue
            yield "data: [DONE]\n\n"