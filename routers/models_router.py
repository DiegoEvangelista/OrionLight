import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import get_settings, update_env_config
from database import ModelConfig, ModelDownload, User, get_db
from routers.auth_router import get_current_user, require_admin
from services.hf_service import hf_service
from services.llm_service import llm_service

router = APIRouter(prefix="/v1/models", tags=["models"])


class DownloadRequest(BaseModel):
    repo_id: str
    filename: str


@router.get("", response_model=None)
@router.get("/", response_model=None)
async def list_models_openai(
    current_user: User = Depends(get_current_user),
):
    """Retorna todos os modelos disponíveis no formato padrão OpenAI (GET /v1/models).

    Agrega modelos do llama-server/ollama ativo, modelos .gguf locais em disco
    e provedores externos configurados (Claude, Gemini, OpenAI).
    """
    now_ts = int(time.time())
    data = []
    seen_ids = set()

    # 1. Modelos do backend de inferência local (llama-server / ollama)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{llm_service._base_url}/v1/models")
            if r.status_code == 200:
                resp_json = r.json()
                for m in resp_json.get("data", []):
                    m_id = m.get("id")
                    if m_id and m_id not in seen_ids:
                        seen_ids.add(m_id)
                        data.append({
                            "id": m_id,
                            "object": "model",
                            "created": m.get("created", now_ts),
                            "owned_by": "local",
                            "permission": [],
                            "root": m_id,
                            "parent": None,
                        })
    except Exception:
        pass

    # 2. Modelos .gguf locais no MODELS_DIR
    local_models = hf_service.list_local_models()
    for lm in local_models:
        name = lm["name"]
        if name not in seen_ids:
            seen_ids.add(name)
            data.append({
                "id": name,
                "object": "model",
                "created": now_ts,
                "owned_by": "local-disk",
                "permission": [],
                "root": name,
                "parent": None,
                "size_gb": lm.get("size_gb", 0),
            })

    # 3. Provedores externos configurados (.env)
    prov_status = llm_service.get_providers_status().get("providers", {})
    for p_name, p_info in prov_status.items():
        if p_name != "local" and p_info.get("configured"):
            m_id = p_info.get("model")
            if m_id and m_id not in seen_ids:
                seen_ids.add(m_id)
                data.append({
                    "id": m_id,
                    "object": "model",
                    "created": now_ts,
                    "owned_by": p_name,
                    "permission": [],
                    "root": m_id,
                    "parent": None,
                })

    return {
        "object": "list",
        "data": data,
    }


@router.get("/providers")
async def list_providers(current_user: User = Depends(get_current_user)):
    """Retorna os provedores configurados (local, claude, gemini, openai)."""
    return llm_service.get_providers_status()


@router.get("/hf/search")
async def search_huggingface(
    q: str = Query(default="", description="Termo de busca"),
    limit: int = Query(default=18, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    """Busca modelos GGUF no Hugging Face."""
    try:
        return hf_service.search_models(query=q, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro na busca HuggingFace: {e}")


@router.get("/hf/files")
async def list_hf_files(
    repo_id: str = Query(..., description="ID do repositório no HF"),
    current_user: User = Depends(get_current_user),
):
    """Lista arquivos .gguf de um repositório com tamanho e quantização."""
    try:
        return hf_service.list_repo_files(repo_id=repo_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao listar arquivos do HuggingFace: {e}")


@router.post("/hf/download", status_code=status.HTTP_202_ACCEPTED)
async def start_hf_download(
    req: DownloadRequest,
    admin: User = Depends(require_admin),
):
    """Inicia o download de um modelo GGUF do Hugging Face em background."""
    try:
        res = hf_service.start_download(req.repo_id, req.filename)
        return res
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Falha ao iniciar download: {e}")


@router.get("/downloads")
async def list_downloads(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Lista o histórico e progresso dos downloads."""
    downloads = db.query(ModelDownload).order_by(ModelDownload.id.desc()).limit(30).all()
    return [
        {
            "id": d.id,
            "repo_id": d.repo_id,
            "filename": d.filename,
            "status": d.status,
            "progress": d.progress,
            "downloaded_bytes": d.downloaded_bytes,
            "total_bytes": d.total_bytes,
            "speed": d.speed,
            "eta": d.eta,
            "error_message": d.error_message,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in downloads
    ]


@router.delete("/downloads/{download_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_or_delete_download(
    download_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Cancela um download ativo ou remove seu registro."""
    hf_service.cancel_download(download_id)
    rec = db.query(ModelDownload).filter(ModelDownload.id == download_id).first()
    if rec:
        db.delete(rec)
        db.commit()



class ModelConfigUpdate(BaseModel):
    name: Optional[str] = None
    context_window: Optional[int] = 8192
    gpu_layers: Optional[int] = -1
    cpu_threads: Optional[int] = None
    loading_strategy: Optional[str] = "keep_warm"


@router.get("/local")
async def list_local_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista todos os modelos .gguf armazenados localmente com seus parâmetros e status."""
    files = hf_service.list_local_models()
    active_symlink = hf_service.get_active_model_filename()

    configs = {c.filename: c for c in db.query(ModelConfig).all()}

    result = []
    for f in files:
        fname = f["name"]
        cfg = configs.get(fname)
        is_active = False
        if cfg:
            is_active = bool(cfg.is_active)
        elif not configs and active_symlink and active_symlink == fname:
            is_active = True

        result.append({
            "name": fname,
            "display_name": cfg.name if cfg and cfg.name else fname,
            "size_gb": f["size_gb"],
            "size_mb": f["size_mb"],
            "modified_at": f["modified_at"],
            "path": f["path"],
            "context_window": cfg.context_window if cfg else 8192,
            "gpu_layers": cfg.gpu_layers if cfg else -1,
            "cpu_threads": cfg.cpu_threads if cfg else 0,
            "loading_strategy": cfg.loading_strategy if cfg else "keep_warm",
            "is_active": is_active,
            "is_chat_compatible": f.get("is_chat_compatible", True),
            "model_type": f.get("model_type", "chat"),
        })
    return result


@router.put("/local/{filename}/config")
async def update_local_model_config(
    filename: str,
    body: ModelConfigUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Configura os parâmetros de execução do modelo (contexto, gpu layers, estratégia)."""
    cfg = db.query(ModelConfig).filter(ModelConfig.filename == filename).first()
    if not cfg:
        cfg = ModelConfig(filename=filename)
        db.add(cfg)

    if body.name is not None:
        cfg.name = body.name
    if body.context_window is not None:
        cfg.context_window = body.context_window
    if body.gpu_layers is not None:
        cfg.gpu_layers = body.gpu_layers
    if body.cpu_threads is not None:
        cfg.cpu_threads = body.cpu_threads
    if body.loading_strategy is not None:
        cfg.loading_strategy = body.loading_strategy

    db.commit()
    db.refresh(cfg)
    return {
        "filename": cfg.filename,
        "name": cfg.name,
        "context_window": cfg.context_window,
        "gpu_layers": cfg.gpu_layers,
        "cpu_threads": cfg.cpu_threads,
        "loading_strategy": cfg.loading_strategy,
        "is_active": bool(cfg.is_active),
    }


@router.post("/local/{filename}/activate")
async def activate_local_model(
    filename: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Ativa o modelo especificado para execução imediata no backend local."""
    try:
        hf_service.activate_local_model(filename)
    except FileNotFoundError:
        raise HTTPException(404, f"Arquivo {filename} não encontrado no diretório de modelos.")
    except Exception as e:
        raise HTTPException(500, f"Falha ao ativar modelo: {e}")

    # Desativa os outros no banco e ativa este
    db.query(ModelConfig).update({ModelConfig.is_active: 0})
    cfg = db.query(ModelConfig).filter(ModelConfig.filename == filename).first()
    if not cfg:
        cfg = ModelConfig(filename=filename, is_active=1)
        db.add(cfg)
    else:
        cfg.is_active = 1
    db.commit()

    # Garante que o cfg tem valores padrão se for novo
    ctx_window = cfg.context_window if cfg.context_window else 8192
    gpu_l = cfg.gpu_layers if cfg.gpu_layers is not None else -1
    settings = get_settings()
    cpu_t = cfg.cpu_threads if (cfg.cpu_threads and cfg.cpu_threads > 0) else getattr(settings, "CPU_THREADS", 0)

    # Inicia o servidor local de inferência llama-server
    started = False
    start_msg = ""
    try:
        from services.llama_process_service import llama_process_service
        started, start_msg = await llama_process_service.start_model(filename, ctx_size=ctx_window, gpu_layers=gpu_l, threads=cpu_t)
    except Exception as e:
        logger.error("Falha ao iniciar processo do modelo: %s", e)
        start_msg = str(e)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{llm_service._base_url}/models/load",
                json={"model": filename, "ctx_size": ctx_window, "n_gpu_layers": gpu_l},
            )
    except Exception:
        pass

    update_env_config({
        "MODEL_FILE": filename,
        "CTX_SIZE": str(ctx_window),
        "MODEL_URL": f"http://127.0.0.1:{llama_process_service.port}",
    })

    llm_reachable = await llm_service.health()

    return {
        "status": "activated",
        "filename": filename,
        "context_window": ctx_window,
        "gpu_layers": gpu_l,
        "cpu_threads": cpu_t,
        "llm_reachable": llm_reachable,
        "message": f"Modelo {filename} ativado com sucesso." if started else f"Modelo {filename} selecionado ({start_msg}).",
    }


@router.post("/local/{filename}/deactivate")
async def deactivate_local_model(
    filename: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Desativa o modelo local e encerra o processo de inferência."""
    # 1. Encerra o processo de inferência do llama-server
    try:
        from services.llama_process_service import llama_process_service
        llama_process_service.stop_model()
    except Exception as e:
        logger.warning("Erro ao parar processo llama-server: %s", e)

    # 2. Desativa no banco de dados
    db.query(ModelConfig).filter(ModelConfig.filename == filename).update({ModelConfig.is_active: 0})
    db.commit()

    # 3. Remove o link simbólico model.gguf
    hf_service.deactivate_local_model(filename)

    # 4. Limpa as variáveis de ambiente no .env e os.environ
    update_env_config({
        "MODEL_FILE": "",
    })

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{llm_service._base_url}/models/unload",
                json={"model": filename},
            )
    except Exception:
        pass

    return {"status": "deactivated", "filename": filename, "message": f"Modelo {filename} desativado com sucesso."}


@router.delete("/local/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_local_model(
    filename: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Deleta um arquivo de modelo .gguf local e sua configuração."""
    try:
        deleted = hf_service.delete_local_model(filename)
        if not deleted:
            raise HTTPException(404, "Arquivo não encontrado.")
        db.query(ModelConfig).filter(ModelConfig.filename == filename).delete()
        db.commit()
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/llama-logs")
async def get_llama_logs(admin: User = Depends(require_admin)):
    """Retorna os logs completos da última execução do llama-server."""
    log_path = "/data/logs/llama_server.log" if os.path.exists("/data/logs/llama_server.log") else "/tmp/llama_server.log"
    if not os.path.exists(log_path):
        return {"exists": False, "message": "Arquivo de log não encontrado."}
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {
            "exists": True,
            "path": log_path,
            "lines_count": len(content.splitlines()),
            "logs": content[-8000:],
        }
    except Exception as e:
        return {"exists": False, "error": str(e)}
