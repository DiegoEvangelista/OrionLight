import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import get_settings, get_version
from database import init_db
from routers.admin_router import router as admin_router
from routers.auth_router import router as auth_router
from routers.chat_router import router as chat_router
from routers.metrics_router import router as metrics_router
from routers.models_router import router as models_router
from routers.rag_router import router as rag_router
from routers.transcription_router import router as transcription_router

settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("orion_light.main")

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    version = get_version()
    logger.info("Orion Light v%s starting", version)
    init_db()
    logger.info("Database ready at %s", settings.DB_PATH)
    try:
        from services.llama_process_service import llama_process_service
        llama_process_service.auto_start_from_db()
    except Exception as e:
        logger.warning("Falha ao auto-iniciar modelo ativo: %s", e)
    try:
        from services.hf_service import hf_service
        hf_service.ensure_default_model_bootstrap()
    except Exception as e:
        logger.warning("Falha ao executar auto-bootstrap de modelo: %s", e)
    yield
    try:
        from services.llama_process_service import llama_process_service
        llama_process_service.stop_model()
    except Exception:
        pass
    logger.info("Orion Light shutdown")


app = FastAPI(
    title="Orion Light",
    description="Sovereign Lightweight AI Gateway & Medical Copilot",
    version=get_version(),
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(rag_router)
app.include_router(transcription_router)
app.include_router(models_router)
app.include_router(admin_router)
app.include_router(metrics_router)


if os.path.isdir(_STATIC_DIR):
    app.mount("/dashboard", StaticFiles(directory=_STATIC_DIR, html=True), name="dashboard")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/dashboard")


@app.get("/health")
async def health():
    from services.llm_service import llm_service
    llm_ok = await llm_service.health()
    return {
        "status": "ok",
        "version": get_version(),
        "llm_reachable": llm_ok,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
