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


import subprocess as _sp_local

def _sp_run(cmd, timeout=30):
    """Синхронный subprocess.run. E271: для обхода проблем с asyncio.create_subprocess_exec на Windows."""
    import subprocess as sp
    try:
        r = sp.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=sp.CREATE_NO_WINDOW if hasattr(sp, "CREATE_NO_WINDOW") else 0,
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -1, "", f"command not found: {cmd[0]}"
    except sp.TimeoutExpired:
        return -2, "", f"timeout after {timeout}s"
    except Exception as e:
        return -3, "", str(e)


async def _sp_run_async(cmd, timeout=30):
    """Async wrapper через asyncio.to_thread."""
    import asyncio
    return await asyncio.to_thread(_sp_run, cmd, timeout)

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
    rc, probe_stdout, probe_stderr = await _sp_run_async([
        "ffprobe", "-v", "error", "-select_streams", "v",
        "-show_entries", "stream=index", "-of", "csv=p=0",
        str(video_path),
    ], timeout=10)
    has_video_stream = bool(probe_stdout.strip())
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
            rc, stdout, stderr = await _sp_run_async(cmd, timeout=30)
            if rc == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return True
            # Логируем первую попытку если упала
            if rc != 0:
                err_msg = (stderr or "")[-300:]
                logger.warning(f"ffmpeg attempt failed rc={rc}: ...{err_msg}")
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
            file_size_bytes = out_path.stat().st_size
            shot = Screenshot(
                protocol_id=protocol_id,
                timestamp_sec=round(ts, 3),
                file_path=str(out_path),
                file_size_kb=file_size_bytes // 1024 if file_size_bytes else None,
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
        import traceback as _tb_cd2
        tb_text2 = _tb_cd2.format_exc()
        logger.error(
            f"generate_screenshots_for_protocol failed for {protocol_id}: "
            f"{type(e).__name__}: {e}"
        )
        logger.error("FULL TRACEBACK:\n" + tb_text2)
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
    """US-019: change_detection — КАЖДЫЙ ШАГ ЛОГИРУЕТСЯ ОТДЕЛЬНО."""
    logger.info(f"[CD] START protocol={protocol_id} video={video_path.name} max={max_screenshots} thr={threshold}")

    # ШАГ 1: импорт модулей
    try:
        from PIL import Image
        import imagehash
        logger.info(f"[CD] modules OK: imagehash={imagehash.__version__} PIL={Image.__version__}")
    except ImportError as ie:
        logger.error(f"[CD] MODULE MISSING: {type(ie).__name__}: {ie}")
        return []

    own_session = db is None
    if own_session:
        db = AsyncSessionLocal()

    # ШАГ 3: создать папку
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[CD] output_dir={output_dir}")
    except Exception as e:
        logger.error(f"[CD] MKDIR FAILED: {type(e).__name__}: {e}")
        return []

    # ШАГ 4: ffprobe
    try:
        rc, stdout, stderr = await _sp_run_async([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
        ], timeout=10)
        probe_stdout = stdout or ""
        probe_stderr = stderr or ""
        duration_str = probe_stdout.strip()
        duration = float(duration_str) if duration_str else 0.0
        stderr_text = probe_stderr
        logger.info(f"[CD] ffprobe duration={duration:.2f}s stderr={stderr_text[:100]}")
        if duration <= 0:
            logger.error(f"[CD] INVALID DURATION={duration} (видео повреждено или не имеет видеопотока)")
            return []
    except (ValueError, OSError) as e:
        logger.error(f"[CD] FFPROBE FAILED: {type(e).__name__}: {e}")
        return []
    except Exception as e:
        logger.error(f"[CD] FFPROBE UNEXPECTED: {type(e).__name__}: {e}")
        return []

    # ШАГ 5: timestamps
    timestamps = []
    t = 0.0
    while t < duration and len(timestamps) < max_screenshots * 3:
        timestamps.append(t)
        t += sample_interval_sec
    logger.info(f"[CD] generated {len(timestamps)} timestamps (sample={timestamps[:3]})")

    if not timestamps:
        logger.error("[CD] NO TIMESTAMPS")
        return []

    # ШАГ 6: extract + phash
    prev_hash = None
    screenshots = []
    attempts = 0
    successes = 0

    for ts in timestamps:
        attempts += 1
        out_path = output_dir / f"shot_{int(ts*1000):010d}.png"
        extract_ok = await extract_frame(video_path, ts, out_path, width=1280)
        if not extract_ok:
            if attempts <= 3:
                logger.warning(f"[CD] EXTRACT FAILED at ts={ts:.2f}s (attempts={attempts}/{len(timestamps)})")
            continue
        try:
            img = Image.open(out_path)
            cur_hash = imagehash.phash(img)
            successes += 1
        except Exception as e:
            logger.warning(f"[CD] PHASH FAILED at ts={ts}: {type(e).__name__}: {e}")
            continue
        is_change = False
        if prev_hash is None:
            is_change = True
            logger.info(f"[CD] baseline ts={ts:.2f}s")
        else:
            dist = prev_hash - cur_hash
            if dist >= threshold:
                is_change = True
                logger.info(f"[CD] change detected ts={ts:.2f}s dist={dist}")
        if is_change and len(screenshots) < max_screenshots:
            try:
                file_size_bytes = out_path.stat().st_size
                shot = Screenshot(
                    protocol_id=protocol_id,
                    timestamp_sec=round(ts, 3),
                    file_path=str(out_path),
                    file_size_kb=file_size_bytes // 1024 if file_size_bytes else None,
                )
                db.add(shot)
                screenshots.append(shot)
            except Exception as e:
                logger.error(f"[CD] DB ADD FAILED: {type(e).__name__}: {e}")
        prev_hash = cur_hash

    logger.info(f"[CD] EXTRACT STATS: attempts={attempts}, successes={successes}, saved={len(screenshots)}/{len(timestamps)}")

    # ШАГ 7: commit
    try:
        await db.commit()
        for s in screenshots:
            await db.refresh(s)
        logger.info(f"[CD] DONE: created {len(screenshots)} screenshots")
    except Exception as e:
        logger.error(f"[CD] DB COMMIT FAILED: {type(e).__name__}: {e}")
        await db.rollback()
        return []
    finally:
        if own_session:
            await db.close()

    return screenshots
