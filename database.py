import os
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from config import get_settings

settings = get_settings()

_db_dir = os.path.dirname(settings.DB_PATH)
_db_file = settings.DB_PATH
if _db_dir:
    try:
        os.makedirs(_db_dir, exist_ok=True)
    except OSError:
        _fallback_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db")
        os.makedirs(_fallback_dir, exist_ok=True)
        _db_file = os.path.join(_fallback_dir, "orion_light.db")

DATABASE_URL = f"sqlite:///{_db_file}"


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-32000")
    cursor.close()


# NullPool: SQLite is local-file, open/close costs microseconds.
# Avoids pool exhaustion under concurrent async requests.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    poolclass=NullPool,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user")  # "admin" | "user"
    api_key_jti = Column(String, nullable=True, default=None)
    created_at = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, index=True)  # UUID
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String, default="Nova conversa")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    messages = Column(Text, default="[]")  # JSON list of {role, content}


class ModelDownload(Base):
    __tablename__ = "model_downloads"

    id = Column(Integer, primary_key=True, index=True)
    repo_id = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending, downloading, completed, failed, cancelled
    progress = Column(Float, default=0.0)
    downloaded_bytes = Column(Integer, default=0)
    total_bytes = Column(Integer, default=0)
    speed = Column(String, nullable=True)
    eta = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    context_window = Column(Integer, default=8192)
    gpu_layers = Column(Integer, default=-1)  # -1 = auto offload
    cpu_threads = Column(Integer, default=0)  # 0 = auto / herda de CPU_THREADS global
    loading_strategy = Column(String, default="keep_warm")  # keep_warm | on_demand
    is_active = Column(Integer, default=0)  # 1 = active, 0 = inactive
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class RequestLog(Base):
    """Registro de cada requisição de inferência — base do sistema de métricas."""
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, index=True)
    # Identificação
    user_id = Column(Integer, nullable=True, index=True)   # NULL = API anônima
    username = Column(String, nullable=True)
    conv_id = Column(String, nullable=True)                 # UUID da conversa
    # Roteamento
    provider = Column(String, nullable=False, default="local")  # local|claude|gemini|openai
    model_name = Column(String, nullable=True)
    endpoint = Column(String, nullable=True)                # /v1/chat | /v1/chat/completions | ws
    # Métricas de throughput
    prompt_tokens = Column(Integer, default=0)    # tokens de entrada (estimado)
    completion_tokens = Column(Integer, default=0)  # tokens de saída (estimado)
    total_tokens = Column(Integer, default=0)
    # Métricas de performance
    latency_ms = Column(Integer, default=0)       # tempo total até [DONE] em ms
    ttft_ms = Column(Integer, default=0)          # time to first token em ms (0 = não medido)
    # Status
    status = Column(String, default="success")    # success | error | cancelled
    error_detail = Column(Text, nullable=True)
    # Temporal (com índice para filtros por data)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)



def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()
    _seed_admin()


def _migrate_add_columns():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN api_key_jti VARCHAR"))
            conn.commit()
        except Exception:
            pass  # column already exists
        try:
            conn.execute(text("ALTER TABLE model_configs ADD COLUMN cpu_threads INTEGER DEFAULT 0"))
            conn.commit()
        except Exception:
            pass  # column already exists


def _seed_admin():
    from routers.auth_router import pwd_ctx

    # Obter configuração atual e fresca
    current_settings = get_settings()
    admin_pass = current_settings.ADMIN_PASSWORD
    if not admin_pass:
        return

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            db.add(User(
                username="admin",
                hashed_password=pwd_ctx.hash(admin_pass),
                role="admin",
            ))
            db.commit()
        else:
            # Garante que a senha no banco sempre respeite o .env se houver divergência
            if not pwd_ctx.verify(admin_pass, admin.hashed_password):
                admin.hashed_password = pwd_ctx.hash(admin_pass)
                db.commit()
    finally:
        db.close()




def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
