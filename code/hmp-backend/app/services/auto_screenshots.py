"""
US-092: Автоматические скриншоты при существенном изменении кадра (Live Mode).

Использует perceptual hash (imagehash) для детекции изменений.
При смене слайда / UI — сохраняет PNG в папку протокола + записывает в БД с таймкодом.

Workflow:
1. Раз в N секунд захватываем кадр (через ffmpeg из видеопотока / либо с веб-камеры).
2. Сравниваем perceptual hash с предыдущим.
3. Если hamming distance > threshold — это существенное изменение → сохраняем.
4. Debounce: не чаще чем 1 скриншот в 10 секунд.
"""
import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Protocol, Screenshot
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

try:
    import imagehash
    from PIL import Image
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False


# Порог Hamming distance для perceptual hash (8-bit). > 8 = значительное изменение.
CHANGE_THRESHOLD = 8
DEBOUNCE_SECONDS = 10.0


async def _compute_phash(image_path: Path) -> Optional[str]:
    """Считает perceptual hash изображения. Возвращает hex-строку или None."""
    if not HAS_IMAGEHASH:
        return None
    try:
        img = Image.open(image_path)
        return str(imagehash.phash(img))
    except Exception as e:
        logger.warning(f"phash failed for {image_path}: {e}")
        return None


async def _hamming_distance(hash1: str, hash2: str) -> int:
    """Считает Hamming distance между двумя hex-хешами (imagehash format)."""
    if not HAS_IMAGEHASH:
        return 999
    try:
        h1 = imagehash.hex_to_hash(hash1)
        h2 = imagehash.hex_to_hash(hash2)
        return h1 - h2  # imagehash ImageHash supports subtraction
    except Exception:
        return 999


def _save_screenshot_to_db_sync(
    db: AsyncSession,
    protocol_id: UUID,
    timestamp_sec: float,
    file_path: Path,
    mime_type: str = "image/png",
    source: str = "live_auto",
) -> Screenshot:
    """Сохраняет запись о скриншоте в БД."""
    file_size = file_path.stat().st_size if file_path.exists() else 0
    shot = Screenshot(
        protocol_id=protocol_id,
        timestamp_sec=round(timestamp_sec, 3),
        file_path=str(file_path),
        file_size_kb=file_size // 1024 if file_size else None,
    )
    db.add(shot)
    return shot


async def capture_and_save_screenshot(
    protocol_id: UUID,
    frame_image_path: Path,
    timestamp_sec: float,
    db: Optional[AsyncSession] = None,
) -> Optional[Screenshot]:
    """US-092: вызывается из Live Mode при существенном изменении кадра.

    Args:
        protocol_id: UUID протокола
        frame_image_path: путь к уже сохранённому кадру (PNG)
        timestamp_sec: таймкод совещания
        db: AsyncSession (если None — создаётся сама)

    Returns:
        Screenshot или None при ошибке
    """
    if not frame_image_path.exists():
        logger.error(f"Frame not found: {frame_image_path}")
        return None

    own_session = db is None
    if own_session:
        db = AsyncSessionLocal()

    try:
        # Получаем протокол для проверки папки хранения
        proto = await db.get(Protocol, protocol_id)
        if not proto:
            logger.error(f"Protocol not found: {protocol_id}")
            return None

        # Создаём запись в БД
        shot = _save_screenshot_to_db_sync(
            db=db,
            protocol_id=protocol_id,
            timestamp_sec=timestamp_sec,
            file_path=frame_image_path,
            source="live_auto",
        )
        await db.commit()
        await db.refresh(shot)

        logger.info(
            f"US-092 screenshot saved: protocol={protocol_id}, "
            f"timestamp={timestamp_sec}s, path={frame_image_path}"
        )
        return shot
    except Exception as e:
        logger.error(f"Failed to save screenshot: {e}")
        await db.rollback()
        return None
    finally:
        if own_session:
            await db.close()


class ScreenshotWatcher:
    """Background watcher: раз в N секунд сравнивает кадры и сохраняет скриншоты."""

    def __init__(
        self,
        protocol_id: UUID,
        source_media_path: Path,
        output_dir: Path,
        interval_seconds: float = 5.0,
    ):
        self.protocol_id = protocol_id
        self.source_media_path = Path(source_media_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.interval_seconds = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._last_phash: Optional[str] = None
        self._last_screenshot_time: float = 0.0
        self._is_running = False

    async def _capture_frame(self, timestamp_sec: float) -> Optional[Path]:
        """Захватывает кадр из видео через ffmpeg."""
        out_path = self.output_dir / f"auto_{int(timestamp_sec*1000):010d}.png"
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-ss", str(timestamp_sec),
                "-i", str(self.source_media_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(out_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if out_path.exists() and out_path.stat().st_size > 0:
                return out_path
        except Exception as e:
            logger.error(f"ffmpeg capture failed: {e}")
        return None

    async def _tick(self):
        """Один проход watcher."""
        timestamp_sec = asyncio.get_event_loop().time() % 36000  # base
        frame_path = await self._capture_frame(timestamp_sec)
        if not frame_path:
            return

        new_phash = await _compute_phash(frame_path)
        if new_phash is None:
            return

        should_save = False
        if self._last_phash is None:
            should_save = True
        else:
            distance = await _hamming_distance(self._last_phash, new_phash)
            if distance >= CHANGE_THRESHOLD:
                should_save = True

        if should_save:
            now = asyncio.get_event_loop().time()
            if now - self._last_screenshot_time >= DEBOUNCE_SECONDS:
                await capture_and_save_screenshot(
                    protocol_id=self.protocol_id,
                    frame_image_path=frame_path,
                    timestamp_sec=timestamp_sec,
                )
                self._last_screenshot_time = now

        self._last_phash = new_phash

    async def _run(self):
        self._is_running = True
        logger.info(f"US-092 watcher started for {self.protocol_id}")
        while self._is_running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"watcher tick error: {e}")
            await asyncio.sleep(self.interval_seconds)
        logger.info(f"US-092 watcher stopped for {self.protocol_id}")

    def start(self) -> asyncio.Task:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        return self._task

    def stop(self):
        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
