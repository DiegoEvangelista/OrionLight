import uuid
from datetime import datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import get_settings
from database import User, get_db

settings = get_settings()

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
API_KEY_EXPIRE_DAYS = 365


class SafePwdContext:
    @staticmethod
    def hash(secret: str) -> str:
        pwd_bytes = secret.encode("utf-8")[:72]
        return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify(secret: str, hashed: str) -> bool:
        try:
            pwd_bytes = secret.encode("utf-8")[:72]
            hash_bytes = hashed.encode("utf-8")
            return bcrypt.checkpw(pwd_bytes, hash_bytes)
        except Exception:
            return False


pwd_ctx = SafePwdContext()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login", auto_error=False)


router = APIRouter(prefix="/v1/auth", tags=["auth"])


class Token(BaseModel):
    access_token: str
    token_type: str


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    has_api_key: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


def _create_token(data: dict, expire_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(minutes=expire_minutes)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_api_key_token(user_id: int) -> tuple[str, str]:
    """Gera um JWT de API key com validade de 365 dias e identificador único JTI."""
    jti = str(uuid.uuid4())
    token = _create_token(
        {"sub": str(user_id), "type": "api_key", "jti": jti},
        expire_minutes=API_KEY_EXPIRE_DAYS * 24 * 60,
    )
    return token, jti


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def get_current_user(
    request: Request,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    db: Session = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autenticação necessária. Forneça a chave via 'Authorization: Bearer <key>', header 'x-api-key' ou 'api-key'.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = bearer_token
    if not token:
        auth_header = request.headers.get("Authorization", "").strip()
        if auth_header:
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()
            else:
                token = auth_header
        if not token:
            token = request.headers.get("x-api-key") or request.headers.get("api-key")
        if not token:
            token = request.query_params.get("api_key") or request.query_params.get("token")

    if not token:
        raise credentials_exc

    # Suporte a Master Key se configurada
    if settings.SECRET_KEY and settings.SECRET_KEY != "change-me-in-production" and token == settings.SECRET_KEY:
        admin_user = db.query(User).filter(User.role == "admin").first()
        if admin_user:
            return admin_user

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exc

    # Validação rigorosa de JTI para chaves de API: permite revogação instantânea
    if payload.get("type") == "api_key":
        jti = payload.get("jti")
        if not jti or user.api_key_jti != jti:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Chave de API revogada ou inválida.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado: privilégios de administrador necessários")
    return current_user


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not _verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = _create_token({"sub": str(user.id), "role": user.role})
    return Token(access_token=token, token_type="bearer")


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "has_api_key": bool(current_user.api_key_jti),
        "created_at": current_user.created_at.isoformat(),
    }


@router.post("/api-key")
async def generate_my_api_key(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Gera uma nova chave de API (365 dias) para a conta do usuário ou serviço atual."""
    token, jti = create_api_key_token(current_user.id)
    current_user.api_key_jti = jti
    db.commit()
    return {
        "api_key": token,
        "username": current_user.username,
        "role": current_user.role,
        "expires_in_days": API_KEY_EXPIRE_DAYS,
        "header_example": f"Authorization: Bearer {token}",
    }


@router.delete("/api-key", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_api_key(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoga a chave de API ativa da conta atual."""
    current_user.api_key_jti = None
    db.commit()
