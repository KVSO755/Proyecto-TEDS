import json
from datetime import datetime
from azure.storage.blob import BlobServiceClient
from app.core.config import settings
from app.models.models import SessionModel


class StorageService:
    """Sincroniza el registro de una sesión a Azure Blob Storage."""

    def __init__(self):
        self._client: BlobServiceClient | None = None

    def _get_client(self) -> BlobServiceClient:
        if not self._client:
            self._client = BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING
            )
        return self._client

    async def upload_session_log(self, session: SessionModel) -> str:
        """
        Serializa los eventos de la sesión a JSON y los sube a Azure Blob.
        Devuelve la URL del blob.
        """
        if not settings.AZURE_STORAGE_CONNECTION_STRING:
            return ""

        payload = {
            "session_id": session.id,
            "user_id": str(session.user_id),
            "started_at": session.started_at.isoformat(),
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "events": [
                {
                    "type": e.type.value,
                    "timestamp": e.timestamp,
                    "duration_seconds": e.duration_seconds,
                }
                for e in session.events
            ],
        }

        blob_name = f"{session.user_id}/{session.id}.json"
        client = self._get_client()
        container = client.get_container_client(settings.AZURE_STORAGE_CONTAINER)

        # Crear contenedor si no existe
        try:
            await container.create_container()
        except Exception:
            pass  # Ya existe

        blob_client = container.get_blob_client(blob_name)
        blob_client.upload_blob(
            json.dumps(payload, ensure_ascii=False, indent=2),
            overwrite=True,
            content_settings={"content_type": "application/json"},
        )

        return blob_client.url


storage_service = StorageService()
