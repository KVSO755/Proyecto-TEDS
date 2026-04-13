import json
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.auth import current_active_user
from app.models.models import User, SessionModel, DistractionEvent, DistractionType
from app.schemas.schemas import (
    SessionOut, DistractionEventIn, DistractionEventOut, WSMessage
)
from app.services.storage import storage_service

router = APIRouter(prefix="/sessions", tags=["sessions"])

# ---------------------------------------------------------------------------
# TOAST messages por tipo de distracción
# ---------------------------------------------------------------------------

TOAST_MESSAGES = {
    DistractionType.GAZE_AWAY:    "Desvío de mirada detectado",
    DistractionType.OUT_OF_FRAME: "No se detecta tu rostro",
}


# ---------------------------------------------------------------------------
# REST: crear y consultar sesiones
# ---------------------------------------------------------------------------

@router.post("/", response_model=SessionOut, status_code=201)
async def create_session(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Inicia una nueva sesión de monitoreo para el usuario autenticado."""
    session = SessionModel(user_id=user.id)
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return _session_to_out(session, event_count=0)


@router.get("/", response_model=list[SessionOut])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    result = await db.execute(
        select(SessionModel).where(SessionModel.user_id == user.id)
        .order_by(SessionModel.started_at.desc())
    )
    sessions = result.scalars().all()
    return [_session_to_out(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    session = await _get_session_or_404(session_id, user.id, db)
    count = await _event_count(session_id, db)
    return _session_to_out(session, event_count=count)


@router.get("/{session_id}/events", response_model=list[DistractionEventOut])
async def get_session_events(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    await _get_session_or_404(session_id, user.id, db)
    result = await db.execute(
        select(DistractionEvent).where(DistractionEvent.session_id == session_id)
    )
    return result.scalars().all()


@router.post("/{session_id}/end", response_model=SessionOut)
async def end_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """Cierra la sesión, sincroniza a Azure Blob y marca como synced."""
    session = await _get_session_or_404(session_id, user.id, db)

    if session.ended_at:
        raise HTTPException(400, "La sesión ya fue cerrada.")

    # Cargar eventos para la sincronización
    result = await db.execute(
        select(DistractionEvent).where(DistractionEvent.session_id == session_id)
    )
    session.events = result.scalars().all()
    session.ended_at = datetime.utcnow()

    # Sincronizar a Azure Blob Storage
    blob_url = await storage_service.upload_session_log(session)
    if blob_url:
        session.synced = True

    await db.flush()
    count = len(session.events)
    return _session_to_out(session, event_count=count)


# ---------------------------------------------------------------------------
# WebSocket: recibe eventos de distracción en tiempo real
# ---------------------------------------------------------------------------

@router.websocket("/{session_id}/ws")
async def session_websocket(
    websocket: WebSocket,
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint WebSocket para recibir eventos de distracción del frontend.

    Flujo:
      1. Cliente envía: { "token": "<JWT>" } para autenticarse
      2. Cliente envía eventos: DistractionEventIn JSON
      3. Servidor responde con confirmación y datos del toast
    """
    await websocket.accept()

    # --- Autenticación vía primer mensaje ---
    try:
        auth_data = await websocket.receive_json()
        token = auth_data.get("token", "")
        user = await _authenticate_ws(token, db)
        if not user:
            await websocket.send_json({"action": "error", "payload": {"detail": "Token inválido"}})
            await websocket.close(code=4001)
            return
    except Exception:
        await websocket.close(code=4001)
        return

    # --- Verificar que la sesión pertenece al usuario ---
    session = await _get_session_or_none(session_id, user.id, db)
    if not session or session.ended_at:
        await websocket.send_json({"action": "error", "payload": {"detail": "Sesión no válida o ya cerrada"}})
        await websocket.close(code=4003)
        return

    await websocket.send_json({"action": "connected", "payload": {"session_id": session_id}})

    # --- Bucle de recepción ---
    try:
        while True:
            raw = await websocket.receive_json()
            event_in = DistractionEventIn(**raw)

            # Persistir evento
            event = DistractionEvent(
                session_id=session_id,
                type=event_in.type,
                timestamp=event_in.timestamp,
                duration_seconds=event_in.duration_seconds,
            )
            db.add(event)
            await db.flush()
            await db.refresh(event)

            # Responder con confirmación + datos del toast
            await websocket.send_json({
                "action": "event_saved",
                "payload": {
                    "event_id": event.id,
                    "toast": {
                        "type": event.type.value,
                        "message": TOAST_MESSAGES[event.type],
                    },
                },
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"action": "error", "payload": {"detail": str(e)}})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _authenticate_ws(token: str, db: AsyncSession) -> User | None:
    """Valida el JWT y devuelve el usuario, o None si es inválido."""
    from app.core.auth import get_jwt_strategy, get_user_db
    from fastapi_users.exceptions import UserNotExists
    try:
        strategy = get_jwt_strategy()
        async for user_db in get_user_db(db):
            from app.core.auth import UserManager
            manager = UserManager(user_db)
            user = await strategy.read_token(token, manager)
            return user
    except Exception:
        return None


async def _get_session_or_404(session_id: str, user_id, db: AsyncSession) -> SessionModel:
    result = await db.execute(
        select(SessionModel).where(
            SessionModel.id == session_id,
            SessionModel.user_id == user_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Sesión no encontrada.")
    return session


async def _get_session_or_none(session_id: str, user_id, db: AsyncSession) -> SessionModel | None:
    result = await db.execute(
        select(SessionModel).where(
            SessionModel.id == session_id,
            SessionModel.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def _event_count(session_id: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).where(DistractionEvent.session_id == session_id)
    )
    return result.scalar() or 0


def _session_to_out(session: SessionModel, event_count: int = 0) -> SessionOut:
    return SessionOut(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        synced=session.synced,
        event_count=event_count,
    )
