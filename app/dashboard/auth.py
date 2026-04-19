from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import DashboardUser

settings = get_settings()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_signer = URLSafeTimedSerializer(settings.DASHBOARD_SECRET_KEY, salt="session")

SESSION_MAX_AGE = 60 * 60 * 8  # 8 hours


def hash_password(pw: str) -> str:
    return pwd_ctx.hash(pw)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def make_session_token(user_id: int) -> str:
    return _signer.dumps(user_id)


def decode_session_token(token: str) -> int | None:
    try:
        return _signer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(
    request: Request,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> DashboardUser:
    user_id = decode_session_token(session) if session else None
    if user_id:
        user = db.get(DashboardUser, user_id)
        if user and user.is_active:
            return user
    raise HTTPException(
        status_code=status.HTTP_302_FOUND,
        headers={"Location": f"/login?next={request.url.path}"},
    )


def require_admin(user: DashboardUser = Depends(get_current_user)) -> DashboardUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
