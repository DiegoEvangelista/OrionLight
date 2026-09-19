import asyncio
import json
import logging
from typing import AsyncIterator, Optional, Dict, Any

import httpx

from config import get_settings
from services.external_llm_service import external_llm_service

logger = logging.getLogger("orion_light.llm")


class LightLLMService:
    def __init__(self):
        self._sem: asyncio.Semaphore | None = None
        self._sem_slots: int = 0

    @property
    def settings(self):
        return get_settings()

    @property
    def _base_url(self) -> str:
        url = self.settings.MODEL_URL.rstrip("/")
        if "llama-server" in url:
            try:
                import socket
                socket.gethostbyname("llama-server")
            except Exception:
                url = url.replace("llama-server", "127.0.0.1")
        elif "localhost" in url:
            url = url.replace("localhost", "127.0.0.1")
        return url

    def _get_sem(self) -> asyncio.Semaphore:
        # Lazy init e detecção de mudança em PARALLEL_SLOTS em runtime.
        # Se o usuário alterar via Settings, recria o semaphore com o novo valor.
        current_slots = self.settings.PARALLEL_SLOTS
        if self._sem is None or self._sem_slots != current_slots:
            self._sem = asyncio.Semaphore(current_slots)
            self._sem_slots = current_slots
        return self._sem

    def _get_active_model_name(self) -> Optional[str]:
        """Recupera o nome do modelo ativo registrado no banco ou .env."""
        try:
            from database import ModelConfig, SessionLocal
            with SessionLocal() as db:
                cfg = db.query(ModelConfig).filter(ModelConfig.is_active == 1).first()
                if cfg:
                    return cfg.filename or cfg.name
        except Exception:
            pass
        import os
        return os.environ.get("MODEL_FILE")

    async def stream_chat(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: Optional[float] = 0.5,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        chosen_provider = (provider or self.settings.DEFAULT_PROVIDER or "local").strip().lower()

        # Roteamento para APIs externas
        if chosen_provider == "claude":
            async for token in external_llm_service.stream_claude(messages, model=model, max_tokens=max_tokens):
                yield token
            return
        elif chosen_provider == "gemini":
            async for token in external_llm_service.stream_gemini(messages, model=model, max_tokens=max_tokens):
                yield token
            return
        elif chosen_provider == "openai":
            async for token in external_llm_service.stream_openai(messages, model=model, max_tokens=max_tokens):
                yield token
            return

        # Roteamento padrão: Servidor local OpenAI-compatible (llama.cpp router mode, Ollama, vLLM)
        active_model = model or self._get_active_model_name()
        if not active_model:
            yield "[Aviso: Nenhum modelo local está ativo. Acesse 'Central de Modelos' e clique em 'Iniciar' no modelo desejado.]"
            return
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature if temperature is not None else 0.5,
            "repeat_penalty": 1.15,
            "presence_penalty": 0.1,
            "stream": True,
        }
        if active_model:
            payload["model"] = active_model

        url = f"{self._base_url}/v1/chat/completions"
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)

        async with self._get_sem():
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", url, json=payload) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line[len("data: "):]
                            if data.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                token = chunk["choices"][0]["delta"].get("content", "")
                                if token:
                                    yield token
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue
            except httpx.ConnectError as exc:
                logger.error("LLM server unreachable at %s: %s", self._base_url, exc)
                yield f"[Erro: Servidor LLM indisponível em {self._base_url}. Certifique-se de iniciar o modelo na 'Central de Modelos'.]"
            except httpx.HTTPStatusError as exc:
                logger.error("LLM server returned %s: %s", exc.response.status_code, exc)
                try:
                    err_msg = exc.response.text
                except Exception:
                    err_msg = ""
                yield f"[Erro do modelo: {exc.response.status_code} - {err_msg}]"

    async def health(self) -> bool:
        base = self._base_url
        candidates = [base]
        if "localhost" in base or "127.0.0.1" in base:
            candidates.append(base.replace("localhost", "llama-server").replace("127.0.0.1", "llama-server"))

        for target in candidates:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    # 1. Checa endpoint /health (llama.cpp retorna 200 ok ou 503 loading model)
                    try:
                        resp = await client.get(f"{target}/health")
                        if resp.status_code in (200, 503):
                            return True
                    except Exception:
                        pass
                    # 2. Checa endpoint /v1/models (OpenAI compatível)
                    try:
                        resp = await client.get(f"{target}/v1/models")
                        if resp.status_code == 200:
                            return True
                    except Exception:
                        pass
                    # 3. Checa raiz /
                    try:
                        resp = await client.get(f"{target}/")
                        if resp.status_code == 200:
                            return True
                    except Exception:
                        pass
            except Exception:
                continue
        return False

    def get_providers_status(self) -> Dict[str, Any]:
        s = self.settings
        return {
            "default_provider": s.DEFAULT_PROVIDER,
            "providers": {
                "local": {
                    "configured": bool(s.MODEL_URL),
                    "target": s.MODEL_URL,
                },
                "claude": {
                    "configured": bool(s.ANTHROPIC_API_KEY),
                    "model": s.CLAUDE_MODEL,
                },
                "gemini": {
                    "configured": bool(s.GEMINI_API_KEY),
                    "model": s.GEMINI_MODEL,
                },
                "openai": {
                    "configured": bool(s.OPENAI_API_KEY),
                    "model": s.OPENAI_MODEL,
                },
            }
        }

    @property
    def active_slots(self) -> int:
        if self._sem is None:
            return 0
        # Usa _sem_slots (slots com que o semaphore foi criado) para evitar leitura stale
        return self._sem_slots - self._sem._value


llm_service = LightLLMService()
