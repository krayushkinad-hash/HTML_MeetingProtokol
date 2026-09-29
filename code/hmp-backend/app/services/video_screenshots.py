"""
US-019: Скриншоты из видео во время транскрибации.

Алгоритм:
1. После успешной транскрибации берём utterances с start_sec
2. Выбираем N таймкодов (равномерно или по важным/решениям)
3. Для каждого таймкода извлекаем кадр через ffmpeg
4. Сохраняем PNG в папку протокола + запись в БД
"""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Protocol, Screenshot, Utterance
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def extract_frame(
    video_path: Path,
    timestamp_sec: float,
    output_path: Path,
    width: Optional[int] = None,
) -> bool:
    """Извлекает кадр из видео в указанный момент.

    Args:
        video_path: путь к видео (m4a/webm/mp4)
        timestamp_sec: момент в секундах
        output_path: куда сохранить PNG
        width: целевая ширина (None = как есть)
    """
    if not video_path.exists():
        logger.error(f"Video not found: {video_path}")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Сначала проверяем что в видео вообще есть видеопоток (а не только аудио)
    probe = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "v",
        "-show_entries", "stream=index", "-of", "csv=p=0",
        str(video_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    probe_stdout, _ = await probe.communicate()
    has_video_stream = bool(probe_stdout.decode("utf-8", errors="replace").strip())
    if not has_video_stream:
        logger.warning(f"No video stream in {video_path} — это аудио, скриншоты невозможны")
        return False

    # Пробуем 2 стратегии: быстрая (без перекодирования) и fallback
    for cmd in [
        # Быстрая: copy codec, без перекодирования (мгновенно)
        ["ffmpeg", "-y", "-ss", str(timestamp_sec), "-i", str(video_path),
         "-frames:v", "1", "-c:v", "copy", str(output_path)],
        # Fallback: с перекодированием (если первый не сработал)
        ["ffmpeg", "-y", "-ss", str(timestamp_sec), "-i", str(video_path)]
        + (["-vf", f"scale={width}:-1"] if width else [])
        + ["-frames:v", "1", "-q:v", "2", str(output_path)],
    ]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return True
            # Логируем первую попытку если упала
            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace")[-300:]
                logger.warning(f"ffmpeg attempt failed: ...{err_msg}")
        except FileNotFoundError:
            logger.error("ffmpeg not found in PATH")
            return False
        except Exception as e:
            logger.warning(f"ffmpeg exception: {e}")
    return False


async def generate_screenshots_for_protocol(
    protocol_id: UUID,
    video_path: Path,
    output_dir: Path,
    max_screenshots: int = 10,
    strategy: str = "uniform",
    db: Optional[AsyncSession] = None,
) -> list[Screenshot]:
    """US-019: автоматическое создание скриншотов по таймкодам реплик.

    Args:
        protocol_id: UUID протокола
        video_path: путь к видеофайлу
        output_dir: куда сохранять PNG
        max_screenshots: максимум скриншотов
        strategy: "uniform" (равномерно) | "important" (важные) | "decisions" (решения)
        db: AsyncSession (если None — создаётся сама)
    """
    own_session = db is None
    if own_session:
        db = AsyncSessionLocal()

    try:
        proto = await db.get(Protocol, protocol_id)
        if not proto:
            logger.error(f"Protocol not found: {protocol_id}")
            return []

        # Получаем реплики
        utterances_q = (
            select(Utterance)
            .where(Utterance.protocol_id == protocol_id)
            .order_by(Utterance.start_sec)
        )
        result = await db.execute(utterances_q)
        utterances = result.scalars().all()
        if not utterances:
            logger.info(f"No utterances for {protocol_id}, skipping screenshots")
            return []

        # Выбираем таймкоды по стратегии
        if strategy == "important":
            timestamps = [u.start_sec for u in utterances if u.important][:max_screenshots]
        elif strategy == "decisions":
            timestamps = [u.start_sec for u in utterances if u.is_decision][:max_screenshots]
        else:  # uniform
            n = min(max_screenshots, len(utterances))
            if n == 0:
                timestamps = []
            else:
                step_idx = len(utterances) / n
                timestamps = [utterances[int(i * step_idx)].start_sec for i in range(n)]

        if not timestamps:
            logger.warning(f"No timestamps selected for screenshots (strategy={strategy})")
            return []

        # Извлекаем кадры
        screenshots = []
        for ts in timestamps:
            out_path = output_dir / f"shot_{int(ts*1000):010d}.png"
            ok = await extract_frame(video_path, ts, out_path, width=1280)
            if not ok:
                logger.warning(f"Failed to extract frame at {ts}s")
                continue

            # Создаём запись в БД
            file_size = out_path.stat().st_size
            shot = Screenshot(
                protocol_id=protocol_id,
                timestamp_sec=round(ts, 3),
                file_path=str(out_path),
                file_size=file_size,
                mime_type="image/png",
                source=f"auto_{strategy}",
                captured_at=datetime.now(timezone.utc),
            )
            db.add(shot)
            screenshots.append(shot)

        await db.commit()
        for s in screenshots:
            await db.refresh(s)

        logger.info(
            f"US-019: created {len(screenshots)} screenshots for protocol {protocol_id} "
            f"(strategy={strategy}, total duration={proto.duration_sec}s)"
        )
        return screenshots

    except Exception as e:
        logger.error(f"generate_screenshots_for_protocol failed for {protocol_id}: {e}")
        logger.error(tb_mod.format_exc())
        await db.rollback()
        return []
    finally:
        if own_session:
            await db.close()


# Синхронная версия для удобного вызова
async def synthesize_screenshots_for_protocol(
    protocol_id: UUID,
    db: AsyncSession,
) -> int:
    """Entry point из роутера: после успешной транскрибации.

    Returns: количество созданных скриншотов
    """
    proto = await db.get(Protocol, protocol_id)
    if not proto or not proto.audio_file_id:
        return 0

    from app.db.models import AudioFile
    audio = await db.get(AudioFile, proto.audio_file_id)
    if not audio or not audio.file_path:
        return 0

    video_path = Path(audio.file_path)
    # Папка скриншотов: рядом с видео
    output_dir = video_path.parent / "screenshots"

    # Стратегия по умолчанию: важные реплики + uniform
    important = await generate_screenshots_for_protocol(
        protocol_id=protocol_id,
        video_path=video_path,
        output_dir=output_dir,
        max_screenshots=5,
        strategy="important",
        db=db,
    )
    uniform = await generate_screenshots_for_protocol(
        protocol_id=protocol_id,
        video_path=video_path,
        output_dir=output_dir,
        max_screenshots=5,
        strategy="uniform",
        db=db,
    )
    return len(important) + len(uniform)

# US-019: стратегия change_detection — сравниваем perceptual hash с предыдущим
async def generate_screenshots_change_detection(
    protocol_id: UUID,
    video_path: Path,
    output_dir: Path,
    max_screenshots: int = 30,
    sample_interval_sec: float = 5.0,
    threshold: int = 8,
    db: Optional[AsyncSession] = None,
) -> list[Screenshot]:
    """US-019: скриншот только при существенном изменении кадра."""
    logger.info(
        f"US-019 change_detection START: protocol={protocol_id}, "
        f"video={video_path}, output_dir={output_dir}, max={max_screenshots}, "
        f"interval={sample_interval_sec}s, threshold={threshold}"
    )
    try:
        from PIL import Image
        import imagehash
        logger.info(f"US-019 imagehash={imagehash.__version__}, PIL={Image.__version__}")
    except ImportError as ie:
        logger.error(f"PIL/imagehash not installed — change_detection unavailable: {ie}")
        return []

    own_session = db is None
    if own_session:
        db = AsyncSessionLocal()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Узнаём длительность видео
        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        probe_stdout, _ = await probe.communicate()
        try:
            duration = float(probe_stdout.decode().strip())
        except ValueError:
            duration = 0.0

        if duration <= 0:
            logger.warning(f"Could not determine video duration: {video_path}")
            return []

        timestamps = []
        t = 0.0
        while t < duration and len(timestamps) < max_screenshots * 3:  # берём с запасом
            timestamps.append(t)
            t += sample_interval_sec

        # Извлекаем кадры и проверяем хеши
        prev_hash = None
        screenshots = []
        for ts in timestamps:
            out_path = output_dir / f"shot_{int(ts*1000):010d}.png"
            ok = await extract_frame(video_path, ts, out_path, width=1280)
            if not ok:
                continue

            # Считаем pHash
            try:
                img = Image.open(out_path)
                cur_hash = imagehash.phash(img)
            except Exception as e:
                logger.warning(f"phash failed at {ts}s: {e}")
                continue

            is_change = False
            if prev_hash is None:
                # Первый кадр всегда сохраняем как baseline
                is_change = True
            else:
                # Hamming distance
                dist = prev_hash - cur_hash
                if dist >= threshold:
                    is_change = True

            if is_change and len(screenshots) < max_screenshots:
                shot = Screenshot(
                    protocol_id=protocol_id,
                    timestamp_sec=round(ts, 3),
                    file_path=str(out_path),
                    file_size=out_path.stat().st_size,
                    mime_type="image/png",
                    source="auto_change_detection",
                    captured_at=datetime.now(timezone.utc),
                )
                db.add(shot)
                screenshots.append(shot)

            prev_hash = cur_hash

        await db.commit()
        for s in screenshots:
            await db.refresh(s)

        logger.info(
            f"US-019 change_detection: created {len(screenshots)}/{len(timestamps)} screenshots "
            f"for {protocol_id} (threshold={threshold})"
        )
        return screenshots
    except Exception as e:
        logger.error(f"change_detection failed: {e}")
        await db.rollback()
        return []
    finally:
        if own_session:
            await db.close()
