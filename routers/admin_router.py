import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import get_settings, get_version, update_env_config
from database import ModelConfig, User, get_db
from routers.auth_router import create_api_key_token, pwd_ctx, require_admin
from services.llm_service import llm_service

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class CreateUserBody(BaseModel):
    username: str
    password: str
    role: str = "user"


class ChangePasswordBody(BaseModel):
    password: str


# ─── Status ──────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    current_settings = get_settings()
    llm_ok = await llm_service.health()
    active_models = []
    if llm_ok:
        async with httpx.AsyncClient(timeout=3.0) as client:
            try:
                r = await client.get(f"{llm_service._base_url}/v1/models")
                if r.status_code == 200:
                    active_models = r.json().get("data", [])
            except Exception:
                pass

    active_cfg = db.query(ModelConfig).filter(ModelConfig.is_active == 1).first()
    active_name = active_cfg.name if (active_cfg and active_cfg.name) else (active_cfg.filename if active_cfg else None)

    return {
        "status": "ok",
        "version": get_version(),
        "llm_reachable": llm_ok,
        "model_url": current_settings.MODEL_URL,
        "parallel_slots": current_settings.PARALLEL_SLOTS,
        "active_slots": llm_service.active_slots,
        "models": active_models,
        "active_model": active_name or (active_models[0].get("id") if active_models else None),
        "active_filename": active_cfg.filename if active_cfg else None,
        "active_context": active_cfg.context_window if active_cfg else 8192,
    }


# ─── Models ──────────────────────────────────────────────────────────────────

@router.get("/models")
async def list_models(admin: User = Depends(require_admin)):
    current_settings = get_settings()
    active: list = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{llm_service._base_url}/v1/models")
            if r.status_code == 200:
                active = r.json().get("data", [])
        except Exception:
            pass

    available = []
    if os.path.isdir(current_settings.MODELS_DIR):
        for fname in sorted(os.listdir(current_settings.MODELS_DIR)):
            if fname.lower().endswith(".gguf"):
                fpath = os.path.join(current_settings.MODELS_DIR, fname)
                try:
                    size_gb = round(os.path.getsize(fpath) / 1e9, 1)
                except OSError:
                    size_gb = 0.0
                available.append({"name": fname, "size_gb": size_gb})

    return {
        "active": active,
        "available": available,
        "models_dir": current_settings.MODELS_DIR,
    }





class UpdateSettingsBody(BaseModel):
    DEFAULT_PROVIDER: Optional[str] = None
    MODEL_URL: Optional[str] = None
    CPU_THREADS: Optional[int] = None
    PARALLEL_SLOTS: Optional[int] = None
    MAX_CONTEXT_CHARS: Optional[int] = None
    SEARCH_MAX_RESULTS: Optional[int] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    CLAUDE_MODEL: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: Optional[str] = None


def _get_current_settings_dict():
    s = get_settings()
    return {
        "DEFAULT_PROVIDER": s.DEFAULT_PROVIDER,
        "MODEL_URL": s.MODEL_URL,
        "CPU_THREADS": s.CPU_THREADS,
        "PARALLEL_SLOTS": s.PARALLEL_SLOTS,
        "MAX_CONTEXT_CHARS": s.MAX_CONTEXT_CHARS,
        "SEARCH_MAX_RESULTS": s.SEARCH_MAX_RESULTS,
        "MODELS_DIR": s.MODELS_DIR,
        "DB_PATH": s.DB_PATH,
        "CHROMA_PATH": s.CHROMA_PATH,
        "ANTHROPIC_API_KEY": s.ANTHROPIC_API_KEY,
        "CLAUDE_MODEL": s.CLAUDE_MODEL,
        "GEMINI_API_KEY": s.GEMINI_API_KEY,
        "GEMINI_MODEL": s.GEMINI_MODEL,
        "OPENAI_API_KEY": s.OPENAI_API_KEY,
        "OPENAI_MODEL": s.OPENAI_MODEL,
    }


# ─── Settings ────────────────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings_view(admin: User = Depends(require_admin)):
    return _get_current_settings_dict()


@router.put("/settings")
async def update_settings_view(
    body: UpdateSettingsBody,
    admin: User = Depends(require_admin),
):
    updates = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            updates[k] = str(v).strip()
    if updates:
        update_env_config(updates)
    return {
        "status": "success",
        "message": "Configurações atualizadas com sucesso.",
        "settings": _get_current_settings_dict(),
    }


# ─── Users ───────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "has_api_key": bool(u.api_key_jti),
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if body.role not in ("admin", "user"):
        raise HTTPException(400, "Role deve ser 'admin' ou 'user'")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(400, "Usuário já existe")
    user = User(
        username=body.username,
        hashed_password=pwd_ctx.hash(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role}


@router.patch("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    user_id: int,
    body: ChangePasswordBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Usuário não encontrado")
    user.hashed_password = pwd_ctx.hash(body.password)
    db.commit()


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(400, "Não pode deletar a própria conta")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Usuário não encontrado")
    db.delete(user)
    db.commit()


@router.post("/users/{user_id}/api-key")
async def generate_api_key(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Usuário não encontrado")
    token, jti = create_api_key_token(user.id)
    user.api_key_jti = jti
    db.commit()
    return {"api_key": token, "username": user.username}


@router.delete("/users/{user_id}/api-key", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Usuário não encontrado")
    user.api_key_jti = None
    db.commit()
