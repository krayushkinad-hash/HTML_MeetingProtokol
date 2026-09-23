"""Cross-dialect типы для совместимости PostgreSQL и SQLite.

В SQLite PostgreSQL-специфичные типы (UUID, JSONB, BYTEA) не работают напрямую.
Этот модуль предоставляет TypeDecorator-обёртки, которые прозрачно работают
в обоих диалектах.

Использование:
    from app.db.types import GUID, JSONType, BYTEAType

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, ...)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    data: Mapped[bytes | None] = mapped_column(BYTEAType)
"""
import uuid

from sqlalchemy import CHAR, JSON, LargeBinary, TypeDecorator
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID as PG_UUID


class GUID(TypeDecorator):
    """UUID, который работает в PostgreSQL и SQLite.

    PostgreSQL: native UUID тип (16 байт + индексы).
    SQLite: CHAR(36) с str(uuid) хранимым форматом.
    """
    impl = CHAR
    cache_ok = True

    # E212: параметр as_uuid убран — он не использовался.
    # (process_bind_param/process_result_value всегда возвращали uuid.UUID)
    def __init__(self, length=36, **kwargs):
        super().__init__(length=length, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value) if isinstance(value, uuid.UUID) else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return uuid.UUID(str(value)) if not isinstance(value, uuid.UUID) else value


class JSONType(TypeDecorator):
    """JSON: PostgreSQL JSONB (с индексами) / SQLite JSON."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class BYTEAType(TypeDecorator):
    """BYTEA: PostgreSQL BYTEA / SQLite LargeBinary (BLOB)."""
    impl = LargeBinary
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(BYTEA())
        return dialect.type_descriptor(LargeBinary())
