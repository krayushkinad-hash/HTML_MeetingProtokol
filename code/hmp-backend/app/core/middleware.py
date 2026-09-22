"""Custom middleware: Correlation IDs and RFC 7807 Problem Details.

NFR: §5.4 (RFC 7807), §5.9 (X-Correlation-Id).
"""
import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Adds X-Correlation-Id to every request/response (NFR §5.9)."""

    HEADER_NAME = "X-Correlation-Id"

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Get or generate correlation ID
        correlation_id = request.headers.get(self.HEADER_NAME) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        # Process request
        response = await call_next(request)

        # Add to response headers
        response.headers[self.HEADER_NAME] = correlation_id
        return response


class ProblemDetailsMiddleware(BaseHTTPMiddleware):
    """Converts exceptions to RFC 7807 Problem Details (NFR §5.4)."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            correlation_id = getattr(request.state, "correlation_id", None)
            logger.exception(
                "unhandled_error",
                path=request.url.path,
                method=request.method,
                correlation_id=correlation_id,
            )

            # Return RFC 7807 problem details
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=500,
                content={
                    "type": f"{settings.api_prefix}/errors/internal-error",
                    "title": "Internal Server Error",
                    "status": 500,
                    "code": "INTERNAL_ERROR",
                    "message": "Внутренняя ошибка сервера",
                    "correlation_id": correlation_id,
                    "timestamp": "PLACEHOLDER",  # TODO: real timestamp
                },
            )
