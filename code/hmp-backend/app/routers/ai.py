"""AI text-processing endpoints (US-045, US-046, US-049, API §12).

Endpoints (all currently stubs — wire to app.services.llm_client.llm_router
when ready; the placeholder implementation returns the input untouched so
the contract is stable and tests can run):

    POST /ai/cleanup-text        — fix typos (US-045)
    POST /ai/restore-punctuation — restore punctuation (US-046)
    POST /ai/review-transcript   — review transcript quality (US-049)
    POST /ai/semantic-search     — semantic search (TODO: embeddings)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.db.models import Protocol
from app.db.session import get_db

logger = get_logger(__name__)
router = APIRouter()


# ============================================================================
# Request / Response schemas
# ============================================================================


class AITextRequest(BaseModel):
    """Common request shape for AI text endpoints."""

    text: str = Field(..., min_length=1, max_length=20000, description="Input text")
    protocol_id: uuid.UUID | None = Field(
        None, description="Optional protocol context for the operation"
    )


class AITextResponse(BaseModel):
    """Common response shape."""

    text: str
    changed: bool
    notes: str | None = None
    provider: str = "mock"


class TranscriptReviewItem(BaseModel):
    """Single issue reported by /ai/review-transcript."""

    start: int = Field(..., description="0-based char offset of the issue")
    end: int = Field(..., description="0-based char offset (exclusive)")
    severity: str = Field(..., description="low | medium | high")
    message: str
    suggestion: str | None = None


class TranscriptReviewResponse(BaseModel):
    """Review output (US-049)."""

    reviewed_text: str
    issues: list[TranscriptReviewItem]
    quality_score: float = Field(..., ge=0.0, le=1.0)
    provider: str = "mock"


class SemanticSearchRequest(BaseModel):
    """Request body for /ai/semantic-search."""

    query: str = Field(..., min_length=1, max_length=1000)
    protocol_id: uuid.UUID | None = None
    top_k: int = Field(default=10, ge=1, le=50)


class SemanticSearchHit(BaseModel):
    """Single hit returned by /ai/semantic-search."""

    utterance_id: uuid.UUID | None = None
    start_sec: float
    end_sec: float
    text: str
    score: float = Field(..., ge=0.0, le=1.0)


class SemanticSearchResponse(BaseModel):
    """Search response (US-049)."""

    query: str
    hits: list[SemanticSearchHit]
    provider: str = "mock"


# ============================================================================
# Internal helpers
# ============================================================================


async def _ensure_protocol(protocol_id: uuid.UUID | None, db: AsyncSession) -> None:
    """If protocol_id provided, 404 if missing/deleted."""
    if protocol_id is None:
        return
    protocol = await db.get(Protocol, protocol_id)
    if not protocol or protocol.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )


# ============================================================================
# POST /ai/cleanup-text — US-045
# ============================================================================


@router.post(
    "/ai/cleanup-text",
    response_model=AITextResponse,
    summary="Fix typos / clean text (MOCK)",
)
async def cleanup_text(
    req: AITextRequest,
    db: AsyncSession = Depends(get_db),
) -> AITextResponse:
    """US-045 — remove common ASR artifacts.

    TODO: replace with `llm_router.generate(prompt=CLEANUP_PROMPT, ...)`.
    Currently echoes the input; the `changed=False` flag signals to the
    client that nothing happened, so the UI can decide whether to retry.
    """
    await _ensure_protocol(req.protocol_id, db)

    logger.info(
        "ai_cleanup_text",
        protocol_id=str(req.protocol_id) if req.protocol_id else None,
        text_len=len(req.text),
    )
    return AITextResponse(
        text=req.text,
        changed=False,
        notes="MOCK — реальная модель не подключена",
        provider="mock",
    )


# ============================================================================
# POST /ai/restore-punctuation — US-046
# ============================================================================


@router.post(
    "/ai/restore-punctuation",
    response_model=AITextResponse,
    summary="Restore punctuation (MOCK)",
)
async def restore_punctuation(
    req: AITextRequest,
    db: AsyncSession = Depends(get_db),
) -> AITextResponse:
    """US-046 — restore punctuation/capitalization for ASR output.

    TODO: integrate llm_router.generate() with RESTORE_PUNCT_PROMPT.
    """
    await _ensure_protocol(req.protocol_id, db)

    logger.info(
        "ai_restore_punctuation",
        protocol_id=str(req.protocol_id) if req.protocol_id else None,
        text_len=len(req.text),
    )
    return AITextResponse(
        text=req.text,
        changed=False,
        notes="MOCK — реальная модель не подключена",
        provider="mock",
    )


# ============================================================================
# POST /ai/review-transcript — US-049
# ============================================================================


@router.post(
    "/ai/review-transcript",
    response_model=TranscriptReviewResponse,
    summary="Review transcript quality (MOCK)",
)
async def review_transcript(
    req: AITextRequest,
    db: AsyncSession = Depends(get_db),
) -> TranscriptReviewResponse:
    """US-049 — flag low-confidence spans and grammar issues.

    TODO: combine `Utterance.low_confidence` flags with LLM-driven grammar
    checks via llm_router.generate().
    """
    await _ensure_protocol(req.protocol_id, db)

    logger.info(
        "ai_review_transcript",
        protocol_id=str(req.protocol_id) if req.protocol_id else None,
        text_len=len(req.text),
    )

    # Stub: no issues, perfect score
    return TranscriptReviewResponse(
        reviewed_text=req.text,
        issues=[],
        quality_score=1.0,
        provider="mock",
    )


# ============================================================================



# ============================================================================
# POST /ai/extract-decisions — US-083, E147
# ============================================================================
# E147: AI-извлечение решений из транскрипта.
# Автоматически создаёт Decision записи для фраз которые являются решениями.
# Сейчас MOCK — возвращает одно решение если есть ключевые слова.
# Реальный LLM будет искать патерны: "договорились", "решили", "принято решение".


class ExtractDecisionsRequest(BaseModel):
    """POST /ai/extract-decisions body."""
    protocol_id: uuid.UUID
    text: str | None = None  # полный текст; если None — загрузим из БД
    min_confidence: float = 0.5


class ExtractedDecision(BaseModel):
    text: str
    timestamp_sec: float | None = None
    source_utterance_id: uuid.UUID | None = None
    confidence: float
    priority: str = "medium"
    rationale: str | None = None


class ExtractDecisionsResponse(BaseModel):
    decisions: list[ExtractedDecision]
    total_found: int
    provider: str  # "mock" или "gigachat" и т.п.


@router.post(
    "/ai/extract-decisions",
    response_model=ExtractDecisionsResponse,
    summary="Auto-extract decisions from transcript (US-083)",
)
async def extract_decisions(
    req: ExtractDecisionsRequest,
    db: AsyncSession = Depends(get_db),
) -> ExtractDecisionsResponse:
    """E147: AI finds 'решили / договорились / принято' паттерны в транскрипте.

    MOCK: эвристика по ключевым словам.
    Production: LLM промпт "extract decisions from meeting text".
    """
    from app.db.models import Utterance
    from sqlalchemy import select as _select

    # E147: загружаем utterances если текст не передан
    utterances = []
    if req.text is None:
        # Загрузим из БД
        rows = await db.execute(
            _select(Utterance)
            .where(Utterance.protocol_id == req.protocol_id)
            .order_by(Utterance.start_sec.asc())
        )
        utterances = list(rows.scalars().all())
        text_combined = "\n".join(u.text or "" for u in utterances if u.text)
    else:
        text_combined = req.text

    # E147: MOCK эвристика — ищем русские ключевые слова решений
    DECISION_KEYWORDS = [
        "решили", "договорились", "принято решение", "принято",
        "подтвердили", "согласовали", "утвердили", "одобрили",
        "обязуется", "берёт на себя", "постановили",
    ]

    decisions = []
    lines = text_combined.split("\n")
    for idx, line in enumerate(lines):
        line_lower = line.lower().strip()
        if not line_lower or len(line_lower) < 5:
            continue
        # Простая проверка ключевых слов
        matched = [kw for kw in DECISION_KEYWORDS if kw in line_lower]
        if matched:
            confidence = min(0.95, 0.5 + 0.1 * len(matched))
            if confidence < req.min_confidence:
                continue
            # E147: находим timestamp из utterance если есть
            timestamp_sec = float(utterances[idx].start_sec) if idx < len(utterances) else None
            source_utt_id = utterances[idx].id if idx < len(utterances) else None
            decisions.append(
                ExtractedDecision(
                    text=line.strip()[:500],
                    timestamp_sec=timestamp_sec,
                    source_utterance_id=source_utt_id,
                    confidence=confidence,
                    priority="medium",
                    rationale=f"Ключевые слова: {', '.join(matched)}",
                )
            )

    logger.info(
        "ai_extract_decisions",
        protocol_id=str(req.protocol_id),
        found=len(decisions),
        text_len=len(text_combined),
    )

    return ExtractDecisionsResponse(
        decisions=decisions[:50],  # лимит
        total_found=len(decisions),
        provider="mock",
    )


# POST /ai/semantic-search — US-049
# ============================================================================


@router.post(
    "/ai/semantic-search",
    response_model=SemanticSearchResponse,
    summary="Semantic search across utterances (MOCK)",
)
async def semantic_search(
    req: SemanticSearchRequest,
    db: AsyncSession = Depends(get_db),
) -> SemanticSearchResponse:
    """US-049 — semantic search using vector embeddings.

    TODO:
      1. Compute embedding for `req.query` via local model (e.g. E5/GTE).
      2. Compare against pre-computed utterance embeddings stored alongside
         Utterance (column TBD; add JSONB column in a future migration).
      3. Return top_k matches.

    For now returns an empty hit list so the contract is stable.
    """
    await _ensure_protocol(req.protocol_id, db)

    logger.info(
        "ai_semantic_search",
        protocol_id=str(req.protocol_id) if req.protocol_id else None,
        query=req.query,
        top_k=req.top_k,
    )
    return SemanticSearchResponse(
        query=req.query,
        hits=[],
        provider="mock",
    )


# ============================================================================
# POST /ai/translate — US-083 (E149)
# ============================================================================
# E149: Перевод utterances на другой язык.
# Если translation_language уже установлен на protocol → возвращает
# закэшированный translation_text.
# MOCK: возвращает "[MOCK en] <text>" — для теста UI.


class TranslateRequest(BaseModel):
    """POST /ai/translate body."""
    protocol_id: UUID
    target_language: str = Field(..., min_length=2, max_length=10)
    # E149: если указано — переводят только эти utterance.id
    utterance_ids: list[UUID] | None = None


class TranslatedUtterance(BaseModel):
    id: UUID
    text: str  # оригинал
    translation_text: str
    translation_language: str


class TranslateResponse(BaseModel):
    translations: list[TranslatedUtterance]
    cached: int  # сколько взято из кэша
    new: int  # сколько новых переведено
    total: int
    target_language: str
    provider: str = "mock"


@router.post(
    "/ai/translate",
    response_model=TranslateResponse,
    summary="Translate utterances (MOCK)",
)
async def translate_utterances(
    req: TranslateRequest,
    db: AsyncSession = Depends(get_db),
) -> TranslateResponse:
    """E149: MOCK-перевод utterances на target_language.

    Production: LLM через llm_router.generate() с target_language.
    """
    from app.db.models import Protocol, Utterance
    from sqlalchemy import select as _select, update as _update

    # Проверяем protocol
    proto = await db.get(Protocol, req.protocol_id)
    if not proto:
        raise HTTPException(404, detail="Протокол не найден")

    # Получаем utterances
    query = _select(Utterance).where(Utterance.protocol_id == req.protocol_id)
    if req.utterance_ids:
        query = query.where(Utterance.id.in_(req.utterance_ids))
    query = query.order_by(Utterance.start_sec.asc()).limit(500)
    rows = await db.execute(query)
    utterances = list(rows.scalars().all())

    if not utterances:
        return TranslateResponse(
            translations=[], cached=0, new=0,
            total=0, target_language=req.target_language,
        )

    translations = []
    cached = 0
    new = 0
    for u in utterances:
        # Если уже переведено на нужный язык — используем кэш
        if u.translation_text and u.translation_language == req.target_language:
            translations.append(TranslatedUtterance(
                id=u.id,
                text=u.text,
                translation_text=u.translation_text,
                translation_language=u.translation_language,
            ))
            cached += 1
            continue
        # MOCK: новый перевод — префикс + оригинал
        mock_translation = f"[{req.target_language}] {u.text}"
        translations.append(TranslatedUtterance(
            id=u.id,
            text=u.text,
            translation_text=mock_translation,
            translation_language=req.target_language,
        ))
        # Сохраняем в БД
        await db.execute(
            _update(Utterance)
            .where(Utterance.id == u.id)
            .values(translation_text=mock_translation,
                    translation_language=req.target_language)
        )
        new += 1

    # Обновляем protocol.translation_language (целевой язык)
    await db.execute(
        _update(Protocol)
        .where(Protocol.id == req.protocol_id)
        .values(translation_language=req.target_language)
    )
    await db.commit()

    logger.info(
        "ai_translate",
        protocol_id=str(req.protocol_id),
        target=req.target_language,
        cached=cached,
        new=new,
    )

    return TranslateResponse(
        translations=translations,
        cached=cached,
        new=new,
        total=len(translations),
        target_language=req.target_language,
    )


# ============================================================================
# POST /ai/check-grammar — US-085, E154
# ============================================================================
# E154: Grammar/spelling check для одной реплики или batch.
# MOCK: простая эвристика (regex, length, capitals, double spaces).
# Production: LLM через llm_router.generate() или language_tool_python.


class GrammarIssue(BaseModel):
    """Один issue найденный grammar checker."""
    start: int  # offset в text
    end: int
    original: str
    suggestion: str
    rule_id: str  # "SPELLING", "GRAMMAR", "PUNCTUATION"
    description: str
    confidence: float = 1.0


class GrammarCheckRequest(BaseModel):
    """POST /ai/check-grammar body."""
    text: str
    language: str = "ru"
    utterance_id: uuid.UUID | None = None  # если указан — для inline-edit


class GrammarCheckResponse(BaseModel):
    text: str
    corrected: str  # текст с применёнными исправлениями
    issues: list[GrammarIssue]
    issue_count: int
    language: str
    provider: str = "mock"


@router.post(
    "/ai/check-grammar",
    response_model=GrammarCheckResponse,
    summary="Check grammar/spelling (MOCK)",
)
async def check_grammar(req: GrammarCheckRequest) -> GrammarCheckResponse:
    """E154: MOCK grammar checker.

    Эвристика:
    - Двойные пробелы
    - Заглавная в середине предложения
    - Точка без пробела после
    - "ё" → "е" (опционально для русского)
    - Английские сокращения типа "т.к." → "так как"
    """
    import re
    text = req.text
    issues = []

    # 1. Двойные пробелы
    for m in re.finditer(r"  +", text):
        issues.append(GrammarIssue(
            start=m.start(),
            end=m.end(),
            original=m.group(),
            suggestion=" ",
            rule_id="DOUBLE_SPACE",
            description="Двойной пробел",
            confidence=1.0,
        ))

    # 2. Пробел перед знаком препинания
    for m in re.finditer(r" +([,.!?:;])", text):
        issues.append(GrammarIssue(
            start=m.start(),
            end=m.end(),
            original=m.group(),
            suggestion=m.group(1),
            rule_id="SPACE_BEFORE_PUNCT",
            description="Лишний пробел перед знаком препинания",
            confidence=1.0,
        ))

    # 3. Отсутствие пробела после знака препинания
    for m in re.finditer(r"([,.!?:;])([А-Яа-яA-Za-z])", text):
        if m.start() == 0:
            continue  # в начале строки норм
        issues.append(GrammarIssue(
            start=m.start(),
            end=m.end(),
            original=m.group(),
            suggestion=f"{m.group(1)} {m.group(2)}",
            rule_id="NO_SPACE_AFTER_PUNCT",
            description="Нет пробела после знака препинания",
            confidence=0.95,
        ))

    # 4. Заглавная в середине предложения
    for m in re.finditer(r"(\.\s*[а-яё])", text):
        issues.append(GrammarIssue(
            start=m.start(1) + len(m.group(1)) - 1,
            end=m.start(1) + len(m.group(1)),
            original=m.group()[0].lower(),
            suggestion=m.group()[0].upper(),
            rule_id="CAPITAL_AFTER_DOT",
            description="Строчная буква после точки",
            confidence=0.9,
        ))

    # 5. Типичные опечатки RU (базовый словарь)
    COMMON_TYPOS = {
        "координально": "кардинально",
        "прийдти": "прийти",
        "прейдти": "перейти",
        "что-бы": "чтобы",
        "за то что": "зато что",
        "незнаю": "не знаю",
        "низнаю": "не знаю",
        "и так же": "и так же",  # placeholder
        "кое что": "кое-что",
        "кое кто": "кое-кто",
        "в течении дня": "в течение дня",
        "в продолжении": "в продолжение",
        "в заключении": "в заключение",
    }

    for typo, correct in COMMON_TYPOS.items():
        if typo in text:
            idx = text.find(typo)
            issues.append(GrammarIssue(
                start=idx,
                end=idx + len(typo),
                original=typo,
                suggestion=correct,
                rule_id="TYPO",
                description=f"Возможная опечатка: '{typo}' → '{correct}'",
                confidence=0.7,
            ))

    # Применяем исправления (с конца строки, чтобы не сбивать offsets)
    corrected = text
    for issue in sorted(issues, key=lambda x: -x.start):
        corrected = corrected[:issue.start] + issue.suggestion + corrected[issue.end:]

    logger.info(
        "ai_check_grammar",
        text_len=len(text),
        issues_found=len(issues),
        language=req.language,
    )

    return GrammarCheckResponse(
        text=text,
        corrected=corrected,
        issues=issues,
        issue_count=len(issues),
        language=req.language,
        provider="mock",
    )
