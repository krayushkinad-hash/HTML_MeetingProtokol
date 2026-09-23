FROM python:3.11-slim AS base

# System dependencies for Whisper, pyannote, OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    gcc \
    g++ \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Install Python dependencies
COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

# Copy application
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Create data directory
RUN mkdir -p /root/.html_mp/protocols /root/.html_mp/backup

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

# Run as non-root (best practice, but PostgreSQL connection from root is simpler)
# USER appuser

EXPOSE 8000

# Run with uvicorn (single worker per ADR-009)
CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1"]
