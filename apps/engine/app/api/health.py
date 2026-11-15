from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    ai_configured: bool


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", ai_configured=get_settings().ai_configured)
