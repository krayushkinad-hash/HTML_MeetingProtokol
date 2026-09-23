"""Admin endpoints (US-067, US-072)."""

from fastapi import APIRouter, Depends
from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.db.models import (
    Protocol, Utterance, Speaker, Tag, ActionItem, Decision,
    Summary, TranscriptionTask, Screenshot, AudioFile, Folder,
    ProtocolVersion, UserSetting,
)
from app.db.session import get_db

logger = logging.getLogger("hmp")

router = APIRouter()


@router.delete(
    "/admin/clear-data",
    summary="US-072: Clear ALL application data",
)
async def clear_all_data(db: AsyncSession = Depends(get_db)) -> dict:
    """Delete all data: protocols, files, settings.

    US-072: One-click cleanup for the entire app.

    Deletes from DB:
    - protocols, utterances, speakers, tags
    - action_items, decisions, summaries
    - transcription_tasks, screenshots
    - audio_files, folders, protocol_versions
    - user_settings (reset to defaults)

    Deletes from disk:
    - All files in ~/.html_mp/protocols/
    """
    from pathlib import Path as PathLib
    from shutil import rmtree
    from app.core.config import settings

    deleted_counts = {}

    # Список таблиц для очистки (порядок важен из-за FK)
    tables_to_clear = [
        "utterances", "speakers", "tags", "action_items",
        "decisions", "summaries", "transcription_tasks",
        "screenshots", "audio_files", "protocols",
        "protocol_versions", "folders",
    ]

    # Удаляем записи из всех таблиц
    try:
        # Utterances
        result = await db.execute(select(func.count(Utterance.id)))
        deleted_counts["utterances"] = result.scalar() or 0
        await db.execute(sql_delete(Utterance))

        # Speakers
        result = await db.execute(select(func.count(Speaker.id)))
        deleted_counts["speakers"] = result.scalar() or 0
        await db.execute(sql_delete(Speaker))

        # Tags
        result = await db.execute(select(func.count(Tag.id)))
        deleted_counts["tags"] = result.scalar() or 0
        await db.execute(sql_delete(Tag))

        # ActionItems
        result = await db.execute(select(func.count(ActionItem.id)))
        deleted_counts["action_items"] = result.scalar() or 0
        await db.execute(sql_delete(ActionItem))

        # Decisions
        result = await db.execute(select(func.count(Decision.id)))
        deleted_counts["decisions"] = result.scalar() or 0
        await db.execute(sql_delete(Decision))

        # Summaries
        result = await db.execute(select(func.count(Summary.id)))
        deleted_counts["summaries"] = result.scalar() or 0
        await db.execute(sql_delete(Summary))

        # TranscriptionTasks
        result = await db.execute(select(func.count(TranscriptionTask.id)))
        deleted_counts["transcription_tasks"] = result.scalar() or 0
        await db.execute(sql_delete(TranscriptionTask))

        # Screenshots
        result = await db.execute(select(func.count(Screenshot.id)))
        deleted_counts["screenshots"] = result.scalar() or 0
        await db.execute(sql_delete(Screenshot))

        # AudioFiles
        result = await db.execute(select(func.count(AudioFile.id)))
        deleted_counts["audio_files"] = result.scalar() or 0
        await db.execute(sql_delete(AudioFile))

        # Folders
        result = await db.execute(select(func.count(Folder.id)))
        deleted_counts["folders"] = result.scalar() or 0
        await db.execute(sql_delete(Folder))

        # ProtocolVersions
        result = await db.execute(select(func.count(ProtocolVersion.id)))
        deleted_counts["protocol_versions"] = result.scalar() or 0
        await db.execute(sql_delete(ProtocolVersion))

        # Protocols (последним — все ссылки уже удалены)
        result = await db.execute(select(func.count(Protocol.id)))
        deleted_counts["protocols"] = result.scalar() or 0
        await db.execute(sql_delete(Protocol))

        # Reset UserSettings
        await db.execute(sql_delete(UserSetting))

        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("clear_data_db_failed", error=str(e), exc_info=True)
        raise

    # Удаляем файлы с диска
    files_deleted = 0
    protocols_path = PathLib(settings.protocols_path)
    if protocols_path.exists():
        try:
            for protocol_dir in protocols_path.iterdir():
                if protocol_dir.is_dir():
                    try:
                        rmtree(protocol_dir)
                        files_deleted += 1
                    except Exception as e:
                        logger.warning(
                            "folder_delete_failed",
                            path=str(protocol_dir),
                            error=str(e),
                        )
                else:
                    try:
                        protocol_dir.unlink()
                        files_deleted += 1
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("clear_data_disk_error", error=str(e))

    # Создаём новую пустую UserSetting
    db.add(UserSetting())
    await db.commit()

    logger.info(
        "all_data_cleared",
        deleted_counts=deleted_counts,
        files_deleted=files_deleted,
    )

    return {
        "status": "cleared",
        "deleted_counts": deleted_counts,
        "files_deleted": files_deleted,
        "message": "Все данные удалены. Приложение сброшено к начальному состоянию.",
    }


@router.get(
    "/admin/stats",
    summary="US-072: Get counts of all data (for confirmation dialog)",
)
async def get_admin_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """Return counts for confirmation dialog."""
    result = {
        "protocols": (await db.execute(select(func.count(Protocol.id)))).scalar() or 0,
        "audio_files": (await db.execute(select(func.count(AudioFile.id)))).scalar() or 0,
        "utterances": (await db.execute(select(func.count(Utterance.id)))).scalar() or 0,
        "screenshots": (await db.execute(select(func.count(Screenshot.id)))).scalar() or 0,
        "folders": (await db.execute(select(func.count(Folder.id)))).scalar() or 0,
    }
    return result
