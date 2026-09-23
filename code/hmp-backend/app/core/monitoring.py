"""RSS (memory) monitor — DEPRECATED (E193, E211).

Не вызывается нигде. Оставлен для совместимости.

Раньше использовался для auto-pause транскрибации при перерасходе RAM,
но wait_if_paused() нигде не вызывался — монитор только спамил
"rss_pause" / "rss_resume" в логах без реальной паузы.

Сейчас:
- rss_limit_mb = 8192 МБ в config.py — запаса хватает
- Если нужен реальный auto-pause — вызвать wait_if_paused() из _run_transcribe_eager
"""
import asyncio

import psutil

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class RSSMonitor:
    """Background task monitoring RSS memory usage.

    Auto-pauses transcription when RSS exceeds 80% of limit.
    """

    def __init__(self, limit_mb: int | None = None, interval_sec: int | None = None) -> None:
        self.limit_mb = limit_mb or settings.rss_limit_mb
        self.threshold_mb = int(self.limit_mb * 0.8)  # 80% trigger
        self.interval_sec = interval_sec or settings.rss_check_interval_sec
        self._task: asyncio.Task | None = None
        self._paused = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Initially not paused

    def get_current_rss_mb(self) -> float:
        """Get current process RSS in MB."""
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024

    def is_paused(self) -> bool:
        """Check if currently paused."""
        return self._paused

    async def pause(self) -> None:
        """Pause transcription (called when RSS too high)."""
        if not self._paused:
            logger.warning("rss_pause", rss_mb=self.get_current_rss_mb(), threshold_mb=self.threshold_mb)
            self._paused = True
            self._pause_event.clear()

    async def resume(self) -> None:
        """Resume transcription."""
        if self._paused:
            logger.info("rss_resume", rss_mb=self.get_current_rss_mb())
            self._paused = False
            self._pause_event.set()

    async def wait_if_paused(self) -> None:
        """Block until RSS is below threshold."""
        await self._pause_event.wait()

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        logger.info("rss_monitor_started", limit_mb=self.limit_mb, threshold_mb=self.threshold_mb)
        while True:
            try:
                rss_mb = self.get_current_rss_mb()
                if rss_mb > self.threshold_mb:
                    if not self._paused:
                        await self.pause()
                else:
                    if self._paused and rss_mb < self.threshold_mb * 0.7:
                        # Hysteresis: resume only when below 70% of threshold
                        await self.resume()

                logger.debug("rss_check", rss_mb=rss_mb, paused=self._paused)
            except Exception as e:
                logger.exception("rss_monitor_error", error=str(e))

            await asyncio.sleep(self.interval_sec)

    async def start(self) -> None:
        """Start the monitoring task."""
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop the monitoring task."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("rss_monitor_stopped")
