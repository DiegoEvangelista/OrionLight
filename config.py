import os
from functools import lru_cache
from pydantic_settings import BaseSettings

_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


class Settings(BaseSettings):
    MODEL_URL: str = "http://127.0.0.1:8085"
    PARALLEL_SLOTS: int = 4
    DB_PATH: str = "/data/db/orion_light.db"
    CHROMA_PATH: str = "/data/chroma"
    SECRET_KEY: str = "4f47fe7873c00769b94c6b18e3a5734c26e7ffa49ea40013cca0a852f379db"
    MAX_CONTEXT_CHARS: int = 12000
    SEARCH_MAX_RESULTS: int = 5
    ADMIN_PASSWORD: str = "orion2026"
    MODELS_DIR: str = "/data/models"

    # Threads de inferência em CPU (0 = automático pelo llama.cpp)
    CPU_THREADS: int = 4

    # Bootstrap automático de modelo inicial
    AUTO_DOWNLOAD_MODEL: str = "bartowski/Qwen2.5-7B-Instruct-GGUF"
    AUTO_DOWNLOAD_FILE: str = "Qwen2.5-7B-Instruct-Q4_K_M.gguf"

    # Provedores Externos e Roteamento
    DEFAULT_PROVIDER: str = "local"  # 'local', 'claude', 'gemini', 'openai'
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-3-5-sonnet-20241022"
    GEMINI_MODEL: str = "gemini-1.5-flash"
    OPENAI_MODEL: str = "gpt-4o-mini"

    class Config:
        env_file = _env_path
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def get_version() -> str:
    """Lê a versão exata do compilado a partir do arquivo VERSION."""
    version_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
    if os.path.isfile(version_file):
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                ver = f.read().strip()
                if ver:
                    return ver
        except Exception:
            pass
    return "0.0.1"


def update_env_config(updates: dict[str, str]) -> None:
    """Atualiza variáveis no arquivo .env, sincroniza os.environ e recarrega Settings."""
    env_lines = []
    keys_updated = set()
    if os.path.exists(_env_path):
        try:
            with open(_env_path, "r", encoding="utf-8") as f:
                env_lines = f.readlines()
        except Exception:
            env_lines = []

    new_lines = []
    for line in env_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                keys_updated.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in keys_updated:
            new_lines.append(f"{key}={val}\n")

    with open(_env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    for key, val in updates.items():
        os.environ[key] = str(val)

    get_settings.cache_clear()

