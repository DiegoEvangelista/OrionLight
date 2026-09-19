import asyncio
import base64
import io
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import get_settings
from database import Conversation, User, get_db
from routers.auth_router import get_current_user
from services.chat_service import chat_service
from services.llm_service import llm_service
from services.rag_service import rag_service

logger = logging.getLogger("orion_light.chat")
settings = get_settings()
router = APIRouter(prefix="/v1/chat", tags=["chat"])

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_TEXT_EXTS  = {".txt", ".md", ".csv", ".json", ".xml", ".html"}


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ChatCompletionMessage(BaseModel):
    role: str
    content: Any


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatCompletionMessage]
    max_tokens: Optional[int] = 1024
    temperature: Optional[float] = 0.5
    stream: Optional[bool] = False
    provider: Optional[str] = None
    enable_search: Optional[bool] = False


# ─── File processing ─────────────────────────────────────────────────────────

async def _process_upload(file: UploadFile) -> tuple[str, str, str]:
    """
    Returns (kind, content, display_name).
    kind = "image" | "text" | "unsupported"
    content = base64 data-URL (image) or extracted text (text)
    """
    import os
    content_bytes = await file.read()
    fname = file.filename or ""
    ext = os.path.splitext(fname)[1].lower()
    mime = file.content_type or ""

    if mime.startswith("image/") or ext in _IMAGE_EXTS:
        b64 = base64.b64encode(content_bytes).decode()
        mime_type = mime if mime.startswith("image/") else "image/jpeg"
        return "image", f"data:{mime_type};base64,{b64}", fname

    if fname.lower().endswith(".pdf") or mime == "application/pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content_bytes))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        return "text", text.strip(), fname

    if ext in _TEXT_EXTS or mime.startswith("text/"):
        text = content_bytes.decode("utf-8", errors="replace")
        return "text", text.strip(), fname

    return "unsupported", "", fname


def _build_user_message(query: str, file_kind: str, file_content: str, file_name: str) -> dict:
    if file_kind == "image":
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": query or "Analise este arquivo."},
                {"type": "image_url", "image_url": {"url": file_content}},
            ],
        }
    if file_kind == "text" and file_content:
        header = f"[Conteúdo do arquivo: {file_name}]\n{file_content}\n\n"
        return {"role": "user", "content": header + query}
    return {"role": "user", "content": query}


def _stored_content(query: str, file_kind: str, file_name: str) -> str:
    if file_kind in ("image", "text") and file_name:
        return f"[Arquivo: {file_name}]\n{query}" if query else f"[Arquivo: {file_name}]"
    return query


# ─── SSE stream ──────────────────────────────────────────────────────────────

async def _sse_stream(
    query: str,
    conv_id: str,
    max_tokens: int,
    db: Session,
    user: User,
    enable_search: bool = False,
    file_kind: str = "",
    file_content: str = "",
    file_name: str = "",
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.5,
) -> AsyncIterator[str]:
    t_start = time.time()
    ttft_ms = 0
    req_status = "success"
    error_detail = None

    s = get_settings()

    # 1. RAG retrieval (context documents)
    rag_context = ""
    try:
        rag_results = rag_service.query(query, n_results=3)
        if rag_results:
            rag_context = "\n\n".join(r.get("text", "") for r in rag_results if isinstance(r, dict) and r.get("text"))
    except Exception as e:
        logger.warning("RAG search failed: %s", e)

    # 2. Web search (DuckDuckGo)
    search_context = ""
    if enable_search:
        try:
            from services.search_service import search_service
            results = search_service.search(query, max_results=s.SEARCH_MAX_RESULTS)
            search_context = search_service.format_for_context(results)
        except Exception as e:
            logger.warning("Web search failed: %s", e)

    # 3. Build augmented query
    augmented_query = query
    if rag_context:
        augmented_query += f"\n\n---\nContexto da base de conhecimento:\n{rag_context}"
    if search_context:
        augmented_query += f"\n\n---\n{search_context}"

    # 4. System message (Orion identity) + history + new message
    system_msg = chat_service.build_orion_system_message(
        rag_context=rag_context,
        web_context=search_context,
    )

    # Sessão segura dedicada para leitura de histórico dentro do generator
    history = []
    try:
        from database import SessionLocal
        with SessionLocal() as sdb:
            history = chat_service.get_history(sdb, conv_id, max_chars=s.MAX_CONTEXT_CHARS)
    except Exception as e:
        logger.warning("History fetch failed: %s", e)

    user_msg = _build_user_message(augmented_query, file_kind, file_content, file_name)
    messages = [system_msg] + history + [user_msg]

    # Estima tokens de prompt (~4 chars por token)
    prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
    prompt_tokens_est = max(1, prompt_chars // 4)

    # 5. Stream from LLM com garantia de entrega e proteção contra corte de conexão
    collected: list[str] = []
    try:
        async for token in llm_service.stream_chat(messages, max_tokens=max_tokens, temperature=temperature, provider=provider, model=model):
            if not collected:
                ttft_ms = int((time.time() - t_start) * 1000)
            collected.append(token)
            payload = json.dumps({"token": token}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
    except Exception as exc:
        req_status = "error"
        error_detail = str(exc)
        logger.error("LLM stream error: %s", exc)
        err_token = f"\n\n[Erro na inferência: {exc}]"
        collected.append(err_token)
        payload = json.dumps({"token": err_token}, ensure_ascii=False)
        yield f"data: {payload}\n\n"
    finally:
        # Garante SEMPRE o envio do marcador [DONE] para evitar que o Nginx/navegador aborte com 'network error'
        yield "data: [DONE]\n\n"

    full_reply = "".join(collected)
    completion_tokens_est = max(1, len(full_reply) // 4)
    latency_ms = int((time.time() - t_start) * 1000)

    # 6. Persistir mensagem com nova sessão de banco independente (nunca reutiliza sessão fechada da rota)
    try:
        from database import SessionLocal
        with SessionLocal() as sdb:
            clean_user_content = _stored_content(query, file_kind, file_name)
            chat_service.save_turn(sdb, conv_id, clean_user_content, full_reply)
    except Exception as e:
        logger.error("Failed to save turn: %s", e)

    # 7. Gravar log de métricas (fire-and-forget)
    try:
        from database import RequestLog as _RL, SessionLocal as _SL
        active_provider = provider or s.DEFAULT_PROVIDER
        with _SL() as log_db:
            log_db.add(_RL(
                user_id=user.id,
                username=user.username,
                conv_id=conv_id,
                provider=active_provider,
                model_name=model,
                endpoint="/v1/chat",
                prompt_tokens=prompt_tokens_est,
                completion_tokens=completion_tokens_est,
                total_tokens=prompt_tokens_est + completion_tokens_est,
                latency_ms=latency_ms,
                ttft_ms=ttft_ms,
                status=req_status,
                error_detail=error_detail,
            ))
            log_db.commit()
    except Exception as log_exc:
        logger.debug("Metrics log failed (non-fatal): %s", log_exc)



# ─── Chat endpoints ──────────────────────────────────────────────────────────

@router.post("")
async def chat(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Endpoint unificado de chat: aceita application/json ou multipart/form-data com upload."""
    content_type = request.headers.get("content-type", "").lower()

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "JSON inválido")
        query = str(body.get("query", ""))
        conv_id = body.get("conv_id")
        max_tokens = int(body.get("max_tokens", 1024))
        temperature = float(body.get("temperature", 0.5))
        enable_search = bool(body.get("enable_search", False))
        provider = body.get("provider")
        model = body.get("model")
        file_kind = file_content = file_name = ""
    else:
        form = await request.form()
        query = str(form.get("query", ""))
        conv_id = form.get("conv_id")
        max_tokens = int(form.get("max_tokens", 1024))
        temperature = float(form.get("temperature", 0.5))
        enable_search = str(form.get("enable_search", "false")).lower() in ("true", "1")
        provider = form.get("provider")
        model = form.get("model")
        file_obj = form.get("file")
        file_kind = file_content = file_name = ""
        if file_obj and hasattr(file_obj, "read"):
            file_kind, file_content, file_name = await _process_upload(file_obj)
            if file_kind == "unsupported":
                raise HTTPException(
                    status_code=415,
                    detail=f"Tipo de arquivo não suportado: {file_name}. Use imagens (JPG, PNG, WebP) ou documentos (PDF, TXT).",
                )

    if not query.strip() and not file_kind:
        raise HTTPException(status_code=400, detail="Envie uma mensagem ou um arquivo.")

    conv = chat_service.get_or_create_conversation(db, current_user.id, conv_id)

    return StreamingResponse(
        _sse_stream(query, conv.id, max_tokens, db, current_user,
                    enable_search, file_kind, file_content, file_name,
                    provider=provider, model=model, temperature=temperature),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Conv-Id": conv.id,
        },
    )


@router.post("/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Endpoint compatível com OpenAI Chat Completions (POST /v1/chat/completions).

    Permite conexão plug-and-play de agentes de IA, LangChain, AutoGen, CrewAI,
    n8n, Dify, LiteLLM e o SDK oficial da OpenAI.
    """
    req_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created_ts = int(time.time())
    model_name = req.model or "orion-light"
    t_start = time.time()

    has_system = any(m.role == "system" for m in req.messages)
    messages_payload = []
    if not has_system:
        messages_payload.append(chat_service.build_orion_system_message())
        for m in req.messages:
            messages_payload.append({"role": m.role, "content": m.content})
    else:
        # Se o cliente (ex: backend/EHR externo) ja passou system prompt, injeta o guardrail de veracidade
        guardrail = (
            "\n\n[DIRETRIZ DE VERACIDADE: Nunca invente dados, métricas, agendamentos, números de pacientes "
            "ou faturamento de clínicas. Se não houver dados reais presentes no contexto ou prompt, informe categoricamente "
            "que não há dados ou registros disponíveis no momento e oriente a consulta diretamente no prontuário eletrônico (EHR) ou sistema de gestão correspondente.]"
        )
        for m in req.messages:
            if m.role == "system":
                messages_payload.append({"role": "system", "content": str(m.content) + guardrail})
            else:
                messages_payload.append({"role": m.role, "content": m.content})

    prompt_chars = sum(len(str(m.get("content", ""))) for m in messages_payload)
    prompt_tokens_est = max(1, prompt_chars // 4)

    token_gen = llm_service.stream_chat(
        messages=messages_payload,
        max_tokens=req.max_tokens or 1024,
        temperature=req.temperature if req.temperature is not None else 0.5,
        provider=req.provider,
        model=req.model,
    )

    if req.stream:
        async def sse_openai_generator():
            collected = []
            ttft_ms = 0
            req_status = "success"
            err_detail = None
            try:
                async for token in token_gen:
                    if not collected:
                        ttft_ms = int((time.time() - t_start) * 1000)
                    collected.append(token)
                    chunk = {
                        "id": req_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": model_name,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": token},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            except Exception as exc:
                req_status = "error"
                err_detail = str(exc)
                logger.error("OpenAI stream error: %s", exc)

            stop_chunk = {
                "id": req_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(stop_chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

            # Log metrics
            try:
                from database import RequestLog as _RL, SessionLocal as _SL
                active_provider = req.provider or settings.DEFAULT_PROVIDER
                full_rep = "".join(collected)
                compl_tokens = max(1, len(full_rep) // 4) if full_rep else 0
                tot_latency = int((time.time() - t_start) * 1000)
                log_db = _SL()
                log_db.add(_RL(
                    user_id=current_user.id,
                    username=current_user.username,
                    conv_id=None,
                    provider=active_provider,
                    model_name=model_name,
                    endpoint="/v1/chat/completions",
                    prompt_tokens=prompt_tokens_est,
                    completion_tokens=compl_tokens,
                    total_tokens=prompt_tokens_est + compl_tokens,
                    latency_ms=tot_latency,
                    ttft_ms=ttft_ms,
                    status=req_status,
                    error_detail=err_detail,
                ))
                log_db.commit()
                log_db.close()
            except Exception as log_exc:
                logger.debug("Metrics log error (completions stream): %s", log_exc)

        return StreamingResponse(
            sse_openai_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        collected = []
        ttft_ms = 0
        req_status = "success"
        err_detail = None
        try:
            async for token in token_gen:
                if not collected:
                    ttft_ms = int((time.time() - t_start) * 1000)
                collected.append(token)
        except Exception as exc:
            req_status = "error"
            err_detail = str(exc)
            logger.error("OpenAI sync completion error: %s", exc)

        full_reply = "".join(collected)
        completion_chars = len(full_reply)
        compl_tokens = max(1, completion_chars // 4)
        tot_latency = int((time.time() - t_start) * 1000)

        # Log metrics
        try:
            from database import RequestLog as _RL, SessionLocal as _SL
            active_provider = req.provider or settings.DEFAULT_PROVIDER
            log_db = _SL()
            log_db.add(_RL(
                user_id=current_user.id,
                username=current_user.username,
                conv_id=None,
                provider=active_provider,
                model_name=model_name,
                endpoint="/v1/chat/completions",
                prompt_tokens=prompt_tokens_est,
                completion_tokens=compl_tokens,
                total_tokens=prompt_tokens_est + compl_tokens,
                latency_ms=tot_latency,
                ttft_ms=ttft_ms,
                status=req_status,
                error_detail=err_detail,
            ))
            log_db.commit()
            log_db.close()
        except Exception as log_exc:
            logger.debug("Metrics log error (completions sync): %s", log_exc)

        return {
            "id": req_id,
            "object": "chat.completion",
            "created": created_ts,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full_reply,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens_est,
                "completion_tokens": compl_tokens,
                "total_tokens": prompt_tokens_est + compl_tokens,
            },
        }



# ─── Conversations ────────────────────────────────────────────────────────────

@router.get("/conversations")
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
        }
        for c in convs
    ]


@router.delete("/conversations/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    db.delete(conv)
    db.commit()


# ─── WebSocket (text-only) ────────────────────────────────────────────────────

@router.websocket("/ws/chat")
async def ws_chat(
    websocket: WebSocket,
    db: Session = Depends(get_db),
):
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        msg = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await websocket.close(code=1008)
        return

    from jose import JWTError, jwt
    from routers.auth_router import ALGORITHM
    from database import User as UserModel

    token = msg.get("token", "")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        await websocket.send_text(json.dumps({"error": "Token inválido"}))
        await websocket.close(code=1008)
        return

    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        await websocket.send_text(json.dumps({"error": "Usuário não encontrado"}))
        await websocket.close(code=1008)
        return

    # API keys must have a valid JTI (enables revocation).
    if payload.get("type") == "api_key":
        jti = payload.get("jti")
        if not jti or user.api_key_jti != jti:
            await websocket.send_text(json.dumps({"error": "API Key revogada ou inválida"}))
            await websocket.close(code=1008)
            return

    query      = msg.get("query", "")
    conv_id    = msg.get("conv_id")
    max_tokens = int(msg.get("max_tokens", 2048))
    provider   = msg.get("provider")
    model      = msg.get("model")

    if not query.strip():
        await websocket.send_text(json.dumps({"error": "Query vazia"}))
        await websocket.close(code=1003)
        return

    conv = chat_service.get_or_create_conversation(db, user.id, conv_id)
    await websocket.send_text(json.dumps({"conv_id": conv.id}))

    try:
        async for chunk in _sse_stream(query, conv.id, max_tokens, db, user, provider=provider, model=model):

            if chunk.startswith("data: "):
                await websocket.send_text(chunk[len("data: "):].strip())
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()

