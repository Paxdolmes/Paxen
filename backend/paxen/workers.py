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


def _init_trackernet():
    from .trackernet import from_env

    return from_env()


_TRACKERNET = _init_trackernet()


def recorder_tick() -> dict:
    provider = get_provider()
    with SessionLocal() as s:
        extra = PILOT_STOPS_SIM if isinstance(provider, SimProvider) else []
        out = record_once(s, provider, utcnow(), extra, modes=settings.record_modes)
        if _TRACKERNET is not None and settings.provider == "tfl":
            from .recorder import record_trackernet

            out["trackernet"] = record_trackernet(s, _TRACKERNET, utcnow())
        return out


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


def context_tick() -> dict:
    from .context import record_context

    with SessionLocal() as s:
        return record_context(s, get_provider(), utcnow(), settings.context_interval_s)


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
        fresh = feed_health(s, now, counts=False)["fresh"]
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
    """Model selection by the pre-registered rolling-day protocol (docs/model-evaluation.md)."""
    from .evaluate import run

    with SessionLocal() as s:
        provider = get_provider()
        if isinstance(provider, SimProvider):
            res = train_and_maybe_promote(s, provider.name)  # the simulator keeps the quick demo behaviour
        else:
            rep = run(s, provider.name)
            res = {"status": rep["status"], "winner": rep.get("winner"), "days": rep["days"],
                   "ground_truth": rep.get("ground_truth"), "message": rep.get("message")}
        prune(s, utcnow())
        return res


TRAIN_FIRST_DELAY_S = 600  # let the recorder run for a while after a (re)start before the first training run


def _peak_mb() -> int | None:
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024  # KB on Linux
    except Exception:
        return None


def train_isolated() -> dict:
    """Run train_tick in a child process. Training holds weeks of history in memory; if it is ever killed for
    running out of memory, only the child dies and the recorder keeps recording (before this, an out-of-memory
    kill took the whole worker down every 30 s, silently)."""
    import subprocess
    import sys

    import os

    # One thread for the model libraries (OpenMP). By default they start one thread per CPU the host has, which
    # in a container is far more than it may use; with the recorder also running, the threads spin waiting for
    # each other and a 3-second model fit took over 10 minutes in testing.
    env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    proc = subprocess.run([sys.executable, "-m", "paxen.worker", "--train-once"], env=env)
    if proc.returncode == 0:
        return {"exit": 0}
    if proc.returncode in (-9, 137):
        log.error("training process was killed (signal 9, usually out of memory); recording continues")
    else:
        log.error("training process exited with code %s; recording continues", proc.returncode)
    return {"exit": proc.returncode}


async def _loop(fn, interval: int, name: str, first_delay: int = 0):
    if first_delay:
        await asyncio.sleep(first_delay)
    while True:
        try:
            res = await asyncio.to_thread(fn)
            log.info("%s: %s | peak memory %s MB", name, res, _peak_mb())
        except Exception:
            log.exception("%s failed", name)
        await asyncio.sleep(interval)


def start(loop_tasks: list) -> None:
    loop_tasks.append(asyncio.create_task(_loop(recorder_tick, settings.poll_interval_s, "recorder")))
    loop_tasks.append(asyncio.create_task(_loop(monitor_tick, settings.monitor_interval_s, "monitor")))
    if settings.provider == "tfl" and settings.context_interval_s > 0:
        loop_tasks.append(asyncio.create_task(_loop(context_tick, settings.context_interval_s, "context",
                                                    first_delay=60)))
    delay = 0 if settings.provider == "sim" else TRAIN_FIRST_DELAY_S
    loop_tasks.append(asyncio.create_task(_loop(train_isolated, settings.train_interval_s, "train", first_delay=delay)))
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
