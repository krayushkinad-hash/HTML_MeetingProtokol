"""Speaker diarization service (US-007, ADR-005).

Эвристическая диаризация (E141, E142) — без pyannote.audio:
- Группируем sequence utterances в "speaker turns"
- Граница спикера: пауза > 2 сек ИЛИ смена speaker_id

Назначение speaker_id:
1. Идём по utterances, отсортированным по start_sec
2. При паузе > 2 сек закрываем текущий "turn"
3. Создаём Speaker для каждого уникального turn
4. Обновляем Utterance.speaker_id

AI cleanup (E142) учитывает speaker_id:
- Если у двух соседних utterances разный speaker_id → новая фраза
- Если тот же speaker_id + пауза < 2 сек → объединяем
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import DiarizationResult, Protocol, Speaker, Utterance

logger = get_logger(__name__)


class DiarizationService:
    """Simple heuristic speaker diarization (E141)."""

    # Граница спикера (turn boundary)
    PAUSE_THRESHOLD_SEC = 2.0  # секунд — если больше, считаем что спикер сменился

    async def diarize_protocol(
        self,
        db: AsyncSession,
        protocol_id: uuid.UUID,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> DiarizationResult:
        """Run diarization on all utterances of protocol.

        1. Получить все utterances, отсортированные по start_sec
        2. Сгруппировать в turns (по паузам > 2 сек)
        3. Создать Speaker для каждого turn
        4. Обновить Utterance.speaker_id
        5. Сохранить DiarizationResult
        """
        # 1. Utterances
        utterances_q = await db.execute(
            select(Utterance)
            .where(Utterance.protocol_id == protocol_id)
            .order_by(Utterance.start_sec.asc(), Utterance.created_at.asc())
        )
        utterances = utterances_q.scalars().all()
        if not utterances:
            raise ValueError(f"No utterances for protocol {protocol_id}")

        # E198: очищаем старые спикеры, отвязываем utterance, удаляем старый результат.
        # Это решает проблему с UniqueConstraint и dangling speakers.
        from sqlalchemy import delete as _del
        # Удаляем старый DiarizationResult (protocol_id unique)
        await db.execute(
            _del(DiarizationResult).where(
                DiarizationResult.protocol_id == protocol_id
            )
        )
        # Отвязываем utterance от старых спикеров
        await db.execute(
            sql_update(Utterance)
            .where(Utterance.protocol_id == protocol_id)
            .values(speaker_id=None)
        )
        # Удаляем старых спикеров (был UniqueConstraint на speaker_label)
        await db.execute(
            _del(Speaker).where(Speaker.protocol_id == protocol_id)
        )
        await db.flush()

        # 2. Group into turns
        turns = []  # [{start, end, texts: [...]}]
        current = None
        for u in utterances:
            if current is None:
                current = {"start": float(u.start_sec), "end": float(u.end_sec), "utt_ids": [u.id]}
            else:
                pause = float(u.start_sec) - current["end"]
                if pause <= self.PAUSE_THRESHOLD_SEC:
                    current["utt_ids"].append(u.id)
                    current["end"] = float(u.end_sec)
                else:
                    turns.append(current)
                    current = {"start": float(u.start_sec), "end": float(u.end_sec), "utt_ids": [u.id]}
        if current is not None:
            turns.append(current)

        # 3. Validate speaker range
        num_speakers_detected = len(turns)
        if min_speakers is not None and num_speakers_detected < min_speakers:
            logger.warning(
                "diarize_below_min_speakers",
                detected=num_speakers_detected,
                min_speakers=min_speakers,
            )
        if max_speakers is not None and num_speakers_detected > max_speakers:
            logger.warning(
                "diarize_above_max_speakers",
                detected=num_speakers_detected,
                max_speakers=max_speakers,
            )

        # 4. Создаём Speaker для каждого turn
        for idx, turn in enumerate(turns):
            # Проверяем, может уже есть speaker — не дублируем
            speaker = await self._get_or_create_speaker(
                db, protocol_id=protocol_id, turn_index=idx,
            )
            # 5. Обновляем utterance.speaker_id
            await db.execute(
                sql_update(Utterance)
                .where(Utterance.id.in_(turn["utt_ids"]))
                .values(speaker_id=speaker.id)
            )

        # 6. Сохраняем DiarizationResult
        diar_result = DiarizationResult(
            protocol_id=protocol_id,
            der_score=None,  # Эвристика без reference — DER неизвестен
            num_speakers_detected=num_speakers_detected,
            num_speakers_expected=None,
            pipeline_version="heuristic-v1",
            confidence_avg=None,
            segments_json=[
                {
                    "turn_index": i,
                    "start_sec": t["start"],
                    "end_sec": t["end"],
                    "utt_count": len(t["utt_ids"]),
                }
                for i, t in enumerate(turns)
            ],
        )
        db.add(diar_result)
        await db.commit()
        await db.refresh(diar_result)

        logger.info(
            "diarize_completed",
            protocol_id=str(protocol_id),
            num_speakers=num_speakers_detected,
            num_turns=len(turns),
            num_utterances=len(utterances),
        )
        return diar_result

    async def _get_or_create_speaker(
        self,
        db: AsyncSession,
        protocol_id: uuid.UUID,
        turn_index: int,
    ) -> Speaker:
        """Создать Speaker для turn.

        E198: после очистки старых спикеров в diarize_protocol, всегда создаём
        нового. Убрал SELECT-в-цикле (O(n²) → O(n)).

        Имя: Speaker 1, Speaker 2, ...
        Color: хэш turn_index → один из 6 цветов
        """
        COLORS = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"]
        color = COLORS[turn_index % len(COLORS)]
        speaker_label = f"Speaker {turn_index + 1}"
        # E189: voice_signature удалён — этого поля нет в модели Speaker
        speaker = Speaker(
            protocol_id=protocol_id,
            display_name=speaker_label,
            speaker_label=speaker_label,
            color=color,
        )
        db.add(speaker)
        await db.flush()  # нужен id для update Utterance.speaker_id
        return speaker
        return speaker


# Singleton
diarization_service = DiarizationService()
