"""Tests for RSSMonitor (memory protection, ADR-010)."""
import asyncio

import psutil
import pytest

from app.core.monitoring import RSSMonitor


@pytest.mark.asyncio
async def test_get_current_rss():
    """Test that RSS reading works."""
    monitor = RSSMonitor(limit_mb=4096, interval_sec=1)
    rss_mb = monitor.get_current_rss_mb()
    assert rss_mb > 0  # Process always uses some memory
    assert rss_mb < 100000  # Sanity check


@pytest.mark.asyncio
async def test_monitor_below_threshold_does_not_pause():
    """Below threshold, monitor should not pause."""
    monitor = RSSMonitor(limit_mb=100000, interval_sec=1)  # Very high limit
    assert monitor.is_paused() is False


@pytest.mark.asyncio
async def test_pause_and_resume():
    """Test pause/resume cycle."""
    monitor = RSSMonitor(limit_mb=100000, interval_sec=1)

    await monitor.pause()
    assert monitor.is_paused() is True

    await monitor.resume()
    assert monitor.is_paused() is False


@pytest.mark.asyncio
async def test_threshold_calculation():
    """80% threshold should be calculated correctly."""
    monitor = RSSMonitor(limit_mb=1000, interval_sec=1)
    assert monitor.threshold_mb == 800  # 80% of 1000


@pytest.mark.asyncio
async def test_monitor_lifecycle():
    """Test start/stop cycle doesn't raise."""
    monitor = RSSMonitor(limit_mb=4096, interval_sec=0.1)

    await monitor.start()
    await asyncio.sleep(0.3)  # Let it run a few iterations
    await monitor.stop()
