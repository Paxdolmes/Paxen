"""Background loops: data recorder, commute monitor, model training."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from .config import settings
from .db import Commute, SessionLocal
from .engine import evaluate_commute, is_active_window, maybe_alert
from .forecast import train_and_maybe_promote
from .notify import deliver
from .providers import get_provider
from .providers.sim import SimProvider
from .recorder import feed_health, prune, record_once
from .timeutil import utcnow

log = logging.getLogger("paxen.workers")

# Pilot corridor: always recorded, so there is history before the first user arrives.
PILOT_STOPS_SIM = ["walthamstow-central", "liverpool-street", "oxford-circus", "highbury-islington", "stratford",
                   "hoe-street", "bakers-arms"]


def recorder_tick() -> dict:
    provider = get_provider()
    with SessionLocal() as s:
        extra = PILOT_STOPS_SIM if isinstance(provider, SimProvider) else []
        return record_once(s, provider, utcnow(), extra, modes=settings.record_modes)


def archive_tick() -> list[dict]:
    """Whole-network archive of modes too big for the database (buses)."""
    from .archive import get_archive
    from .recorder import archive_network

    provider = get_provider()
    try:
        archive = get_archive()
    except Exception as e:
        log.error("archive disabled: %s", e)
        return []
    if archive is None or not hasattr(provider, "mode_arrivals_raw"):
        return []
    with SessionLocal() as s:
        return [archive_network(s, provider, m, utcnow()) for m in settings.archive_only_modes]


_aq_day: str | None = None


def monitor_tick() -> int:
    """Evaluate every commute in its alert window and raise alerts where warranted."""
    global _aq_day
    provider = get_provider()
    now = utcnow()
    sent = 0
    with SessionLocal() as s:
        today = now.strftime("%Y-%m-%d %H")[:10]
        if _aq_day != today and now.hour >= 8:  # TfL publishes the day's forecast in the morning
            try:
                from .conditions import record_air_quality

                if record_air_quality(s, provider, now):
                    _aq_day = today
            except Exception:
                log.exception("air quality recording failed")
        fresh = feed_health(s, now)["fresh"]
        try:
            from .live import close_stale

            close_stale(s, now)
        except Exception:
            log.exception("closing stale trips failed")
        for c in s.scalars(select(Commute).where(Commute.alerts_enabled.is_(True))):
            if c.user.monitoring_paused or not is_active_window(c, now):
                continue
            try:
                ev = evaluate_commute(s, provider, c, now, feed_fresh=fresh)
                alert = maybe_alert(s, ev, now)
                if alert:
                    deliver(c.user, alert)
                    sent += 1
                s.commit()
            except Exception:
                log.exception("monitor failed for commute %s", c.id)
                s.rollback()
    return sent


def train_tick() -> dict:
    with SessionLocal() as s:
        res = train_and_maybe_promote(s, get_provider().name)
        prune(s, utcnow())
        return res


async def _loop(fn, interval: int, name: str):
    while True:
        try:
            res = await asyncio.to_thread(fn)
            log.info("%s: %s", name, res)
        except Exception:
            log.exception("%s failed", name)
        await asyncio.sleep(interval)


def start(loop_tasks: list) -> None:
    loop_tasks.append(asyncio.create_task(_loop(recorder_tick, settings.poll_interval_s, "recorder")))
    loop_tasks.append(asyncio.create_task(_loop(monitor_tick, settings.monitor_interval_s, "monitor")))
    loop_tasks.append(asyncio.create_task(_loop(train_tick, settings.train_interval_s, "train")))
    from .archive import get_archive

    try:
        archive_ok = get_archive() is not None
    except Exception as e:
        log.error("archive misconfigured (%s): recording continues without the raw archive", e)
        archive_ok = False
    if settings.archive_only_modes:
        if not archive_ok:
            log.warning("PAXEN_ARCHIVE_ONLY_MODES=%s set but PAXEN_ARCHIVE_URL is not: skipping the bus archive",
                        settings.archive_only_modes)
        else:
            loop_tasks.append(asyncio.create_task(_loop(archive_tick, settings.archive_only_interval_s, "archive")))
