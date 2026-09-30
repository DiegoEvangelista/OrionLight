import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

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

    async def complete_with_tools_openai(
        self,
        messages: List[Dict],
        tools: List[Any],
        tool_choice: Any = "auto",
        model: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("OPENAI_API_KEY não configurada no servidor")

        model_name = model or settings.OPENAI_MODEL or "gpt-4o-mini"
        payload = {
            "model": model_name,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        url = "https://api.openai.com/v1/chat/completions"
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    def _openai_msgs_to_anthropic(self, messages: List[Dict]) -> tuple[str, List[Dict]]:
        """Converte lista de mensagens no formato OpenAI para o formato Anthropic."""
        system_parts: List[str] = []
        anthropic_msgs: List[Dict] = []
        i = 0
        while i < len(messages):
            m = messages[i]
            role = m.get("role", "")
            content = m.get("content")

            if role == "system":
                if isinstance(content, str) and content:
                    system_parts.append(content)
                i += 1
                continue

            if role == "assistant":
                tool_calls = m.get("tool_calls")
                if tool_calls:
                    blocks: List[Dict] = []
                    if content:
                        blocks.append({"type": "text", "text": str(content)})
                    for tc in tool_calls:
                        fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                        args_raw = fn.get("arguments", "{}")
                        try:
                            args_obj = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                        except Exception:
                            args_obj = {}
                        blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id", f"tool_{i}") if isinstance(tc, dict) else f"tool_{i}",
                            "name": fn.get("name", ""),
                            "input": args_obj,
                        })
                    anthropic_msgs.append({"role": "assistant", "content": blocks})
                else:
                    anthropic_msgs.append({"role": "assistant", "content": content or ""})
                i += 1
                continue

            if role == "tool":
                tool_results: List[Dict] = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    t = messages[i]
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": t.get("tool_call_id", ""),
                        "content": str(t.get("content", "")),
                    })
                    i += 1
                anthropic_msgs.append({"role": "user", "content": tool_results})
                continue

            # user
            if isinstance(content, list):
                parts: List[Dict] = []
                for part in content:
                    if part.get("type") == "text":
                        parts.append({"type": "text", "text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        url_val = part.get("image_url", {}).get("url", "")
                        if url_val.startswith("data:"):
                            header, data = url_val.split(",", 1)
                            media_type = header.split(";")[0].split(":")[1]
                            parts.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
                anthropic_msgs.append({"role": "user", "content": parts})
            else:
                anthropic_msgs.append({"role": "user", "content": content or ""})
            i += 1

        return "\n\n".join(system_parts), anthropic_msgs

    async def complete_with_tools_claude(
        self,
        messages: List[Dict],
        tools: List[Any],
        tool_choice: Any = "auto",
        model: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """Chama Anthropic com tools e retorna resposta no formato OpenAI-compatible."""
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY não configurada no servidor")

        model_name = model or settings.CLAUDE_MODEL or "claude-3-5-sonnet-20241022"
        system_prompt, anthropic_msgs = self._openai_msgs_to_anthropic(messages)

        # Converte ferramentas do formato OpenAI para Anthropic
        anthropic_tools = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            fn = t.get("function", {})
            anthropic_tools.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })

        # Converte tool_choice
        if tool_choice == "required":
            anthropic_tc: Dict = {"type": "any"}
        elif isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
            anthropic_tc = {"type": "tool", "name": tool_choice["function"]["name"]}
        else:
            anthropic_tc = {"type": "auto"}

        payload: Dict[str, Any] = {
            "model": model_name,
            "max_tokens": max_tokens,
            "messages": anthropic_msgs,
            "tools": anthropic_tools,
            "tool_choice": anthropic_tc,
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

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            anthropic_resp = resp.json()

        # Converte resposta Anthropic → OpenAI format
        content_blocks = anthropic_resp.get("content", [])
        tool_calls_out: List[Dict] = []
        text_parts_out: List[str] = []
        for block in content_blocks:
            if block.get("type") == "tool_use":
                tool_calls_out.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    },
                })
            elif block.get("type") == "text":
                text_parts_out.append(block.get("text", ""))

        message_out: Dict[str, Any] = {
            "role": "assistant",
            "content": "".join(text_parts_out) or None,
        }
        if tool_calls_out:
            message_out["tool_calls"] = tool_calls_out

        usage = anthropic_resp.get("usage", {})
        return {
            "id": f"chatcmpl-{anthropic_resp.get('id', '')}",
            "object": "chat.completion",
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": message_out,
                    "finish_reason": "tool_calls" if tool_calls_out else "stop",
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        }


external_llm_service = ExternalLLMService()
