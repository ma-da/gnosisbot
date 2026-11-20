"""Public system status API."""

from fastapi import APIRouter
from app.services.system_health import system_status

router = APIRouter(prefix="/api/v1/system")


@router.get("/status")
async def get_system_status():
    return await system_status()