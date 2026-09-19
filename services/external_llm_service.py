import json
import logging
from typing import AsyncIterator, List, Dict, Optional

import httpx

from config import get_settings

logger = logging.getLogger("orion_light.external_llm")
settings = get_settings()


class ExternalLLMService:
    @staticmethod
    def _separate_system_prompt(messages: List[Dict[str, str]]) -> tuple[str, List[Dict[str, str]]]:
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        chat_msgs = [m for m in messages if m.get("role") != "system"]
        system_text = "\n\n".join(system_parts)
        return system_text, chat_msgs

    async def stream_claude(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            yield "[Erro: ANTHROPIC_API_KEY não configurada no servidor]"
            return

        model_name = model or settings.CLAUDE_MODEL or "claude-3-5-sonnet-20241022"
        system_prompt, chat_msgs = self._separate_system_prompt(messages)

        # Anthropic aceita roles: 'user', 'assistant'
        anthropic_msgs = []
        for m in chat_msgs:
            role = "assistant" if m["role"] == "assistant" else "user"
            anthropic_msgs.append({"role": role, "content": m["content"]})

        payload = {
            "model": model_name,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": anthropic_msgs,
        }
        if system_prompt:
            payload["system"] = system_prompt

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        url = "https://api.anthropic.com/v1/messages"
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        err_text = await resp.aread()
                        logger.error("Claude API error %s: %s", resp.status_code, err_text.decode("utf-8", errors="ignore"))
                        yield f"[Erro Claude: HTTP {resp.status_code}]"
                        return

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[len("data: "):].strip()
                        if not data_str:
                            continue
                        try:
                            ev = json.loads(data_str)
                            ev_type = ev.get("type")
                            if ev_type == "content_block_delta":
                                delta = ev.get("delta", {})
                                text = delta.get("text", "")
                                if text:
                                    yield text
                            elif ev_type == "message_stop":
                                break
                        except Exception:
                            continue
        except Exception as e:
            logger.error("Erro na chamada do Claude: %s", e)
            yield f"[Erro de conexão com Claude: {e}]"

    async def stream_gemini(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            yield "[Erro: GEMINI_API_KEY não configurada no servidor]"
            return

        model_name = model or settings.GEMINI_MODEL or "gemini-1.5-flash"
        system_prompt, chat_msgs = self._separate_system_prompt(messages)

        contents = []
        for m in chat_msgs:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({
                "role": role,
                "parts": [{"text": m["content"]}],
            })

        payload: Dict[str, any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
            },
        }
        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}],
            }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:streamGenerateContent?alt=sse&key={api_key}"
        headers = {"content-type": "application/json"}
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        err_text = await resp.aread()
                        logger.error("Gemini API error %s: %s", resp.status_code, err_text.decode("utf-8", errors="ignore"))
                        yield f"[Erro Gemini: HTTP {resp.status_code}]"
                        return

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[len("data: "):].strip()
                        if not data_str:
                            continue
                        try:
                            ev = json.loads(data_str)
                            candidates = ev.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for p in parts:
                                    t = p.get("text", "")
                                    if t:
                                        yield t
                        except Exception:
                            continue
        except Exception as e:
            logger.error("Erro na chamada do Gemini: %s", e)
            yield f"[Erro de conexão com Gemini: {e}]"

    async def stream_openai(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            yield "[Erro: OPENAI_API_KEY não configurada no servidor]"
            return

        model_name = model or settings.OPENAI_MODEL or "gpt-4o-mini"
        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        url = "https://api.openai.com/v1/chat/completions"
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        err_text = await resp.aread()
                        logger.error("OpenAI API error %s: %s", resp.status_code, err_text.decode("utf-8", errors="ignore"))
                        yield f"[Erro OpenAI: HTTP {resp.status_code}]"
                        return

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[len("data: "):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            token = chunk["choices"][0]["delta"].get("content", "")
                            if token:
                                yield token
                        except Exception:
                            continue
        except Exception as e:
            logger.error("Erro na chamada OpenAI: %s", e)
            yield f"[Erro de conexão com OpenAI: {e}]"


external_llm_service = ExternalLLMService()
