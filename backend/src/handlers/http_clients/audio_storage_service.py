"""Persistent shared storage for short-lived synthesized voice audio."""
import asyncio
import time
from pathlib import Path
from uuid import UUID, uuid4

from src.config.settings import settings


class AudioStorageService:
    def __init__(self) -> None:
        self.directory = Path(settings.AUDIO_STORAGE_DIR)
        self.ttl_seconds = max(60, settings.AUDIO_CACHE_TTL_SECONDS)

    def _path(self, audio_id: str) -> Path:
        return self.directory / f"{UUID(audio_id).hex}.wav"

    def _store(self, audio: bytes) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        expires_before = time.time() - self.ttl_seconds
        for old_file in self.directory.glob("*.wav"):
            try:
                if old_file.stat().st_mtime < expires_before:
                    old_file.unlink(missing_ok=True)
            except OSError:
                continue
        audio_id = uuid4().hex
        final_path = self._path(audio_id)
        temp_path = final_path.with_suffix(".tmp")
        temp_path.write_bytes(audio)
        temp_path.replace(final_path)
        return audio_id

    def _get(self, audio_id: str) -> bytes | None:
        try:
            path = self._path(audio_id)
            if not path.is_file():
                return None
            if time.time() - path.stat().st_mtime > self.ttl_seconds:
                path.unlink(missing_ok=True)
                return None
            return path.read_bytes()
        except (ValueError, OSError):
            return None

    async def store(self, audio: bytes) -> str:
        return await asyncio.to_thread(self._store, audio)

    async def get(self, audio_id: str) -> bytes | None:
        return await asyncio.to_thread(self._get, audio_id)


audio_storage_service = AudioStorageService()
