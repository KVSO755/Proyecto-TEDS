import uuid
from datetime import datetime
from sqlalchemy import String, Float, ForeignKey, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from app.core.database import Base
import enum


class DistractionType(str, enum.Enum):
    GAZE_AWAY   = "desvío de mirada"
    OUT_OF_FRAME = "fuera de encuadre"


# ---------------------------------------------------------------------------
# Usuario (FastAPI Users maneja toda la lógica de auth)
# ---------------------------------------------------------------------------

class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"

    full_name: Mapped[str] = mapped_column(String(120), nullable=True)
    sessions: Mapped[list["SessionModel"]] = relationship(back_populates="user")


# ---------------------------------------------------------------------------
# Sesión de estudio
# ---------------------------------------------------------------------------

class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    synced: Mapped[bool] = mapped_column(default=False)

    user: Mapped["User"] = relationship(back_populates="sessions")
    events: Mapped[list["DistractionEvent"]] = relationship(back_populates="session")


# ---------------------------------------------------------------------------
# Evento de distracción
# ---------------------------------------------------------------------------

class DistractionEvent(Base):
    __tablename__ = "distraction_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)

    # Formato: 2026-04-12|14:35:22
    timestamp: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[DistractionType] = mapped_column(
        SAEnum(DistractionType), nullable=False
    )

    session: Mapped["SessionModel"] = relationship(back_populates="events")
