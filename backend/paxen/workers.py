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
        from . import recorder

        if not recorder.recording_allowed(s, utcnow()):
            # Disk nearly full (PAXEN_DB_PAUSE_MB). Line statuses are tiny and alerts need them; train data still
            # goes to the raw archive, so nothing is lost and these hours can be rebuilt; only the database copy
            # is skipped.
            now = utcnow()
            recorder.record_statuses(s, provider, now)
            out = {"paused": recorder.PAUSED,
                   "archived": [recorder.archive_network(s, provider, m, now) for m in settings.record_modes or []]}
            if _TRACKERNET is not None and settings.provider == "tfl":
                out["trackernet"] = recorder.record_trackernet(s, _TRACKERNET, now, store=False)
            s.commit()
            return out
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
        try:
            from .notify import note_worker

            note_worker(s, now)  # lets /v1/health show whether this process can send iPhone pushes
        except Exception:
            log.exception("worker status not recorded")
            s.rollback()
        try:
            from .briefing import send_due

            sent += send_due(s, provider, now, fresh, deliver)  # daily briefings at the times users chose
        except Exception:
            log.exception("briefings failed")
            s.rollback()
        try:
            from .activity import push_all
            from .live import live_status

            push_all(s, provider, now, live_status)  # trips showing on a lock screen
        except Exception:
            log.exception("live activity updates failed")
            s.rollback()
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


THIN_STATUS = "thin_status"  # AppSecret: where the latest storage/history run is (shown on /v1/journeys/report)


class Progress:
    """Where a long background run is, saved as it goes: the run takes an hour or more in a child process and its
    log is only on the host, so this is how anyone can see what it is doing, how long each step took, and what
    failed. Writes use their own session, so they never mix with the run's own transactions."""

    def __init__(self, name: str = THIN_STATUS):
        import time

        self.name, self._clock = name, time.monotonic
        self.state: dict = {"started_at": utcnow().isoformat(), "step": None, "steps": {}, "errors": {},
                            "finished_at": None}
        self._t = self._clock()
        self.previous = self._load()
        self._save()

    def _load(self):
        import json

        from .db import AppSecret

        try:
            with SessionLocal() as s:
                row = s.get(AppSecret, self.name)
                return json.loads(row.value).get("run") if row else None
        except Exception:
            return None

    def _save(self) -> None:
        import json

        from .db import AppSecret

        value = json.dumps({"run": self.state, "previous": self.previous}, default=str)
        try:
            with SessionLocal() as s:
                row = s.get(AppSecret, self.name)
                if row:
                    row.value = value
                else:
                    s.add(AppSecret(name=self.name, value=value))
                s.commit()
        except Exception:
            log.exception("could not save progress")

    def step(self, name: str | None) -> None:
        now = self._clock()
        if self.state["step"]:
            self.state["steps"][self.state["step"]] = round(now - self._t, 1)
        self.state["step"], self._t = name, now
        self._save()

    def failed(self, e: Exception) -> None:
        import re

        msg = re.sub(r"\w+://\S+", "<url>", str(e))[:300]  # no hostnames or bucket addresses
        self.state["errors"][self.state["step"] or "run"] = f"{type(e).__name__}: {msg}"
        self._save()

    def finish(self, result: dict) -> None:
        self.step(None)
        self.state["finished_at"], self.state["result"] = utcnow().isoformat(), result
        self._save()


def thin_tick() -> dict:
    """Storage and history, every 2 hours. In order:
      1. export every finished day to the history store (paxen/history.py); nothing below runs if this fails;
      2. replay the journey panel on the newly exported days (paxen/replay.py): real journey times, quick;
      3. thin old days of predictions to the sample the evaluation reads (evaluate.thin_history) and drop arrivals
         no remaining prediction can pair with (evaluate.trim_arrivals); neither changes what training reads;
      4. with PAXEN_DB_KEEP_DAYS set, drop the database copy of old days already safely in the store;
      5. rebuild days thinned before the store existed from the raw archive (slow: thousands of responses a day),
         then replay those too."""
    from .evaluate import thin_history, trim_arrivals

    prog = Progress()
    with SessionLocal() as s:
        source = get_provider().name
        out: dict = {}
        exported = archive = None
        try:
            from .archive import get_archive
            from .history import export_pending, exported_days

            archive = get_archive()
            if archive is not None:
                # every finished day goes to the history store first; only then is it thinned or dropped
                prog.step("export")
                out["history"] = export_pending(s, source, utcnow(), archive,
                                                on_table=lambda day, table: prog.step(f"export {day} {table}"))
                exported = exported_days(s, source)
        except Exception as e:
            log.exception("history export failed: nothing is thinned or dropped until it works")
            prog.failed(e)
            s.rollback()
            prog.finish({"history": "failed"})
            return {"history": "failed"}

        def guarded(name: str, fn):
            prog.step(name)
            try:
                return fn()
            except Exception as e:
                log.exception("%s failed", name)
                prog.failed(e)
                s.rollback()
                return "failed"

        def replay():
            from .replay import replay_pending

            return replay_pending(s, source, archive, max_days=4,
                                  on_day=lambda day: prog.step(f"replay {day}"))

        if exported is not None:
            out["replay"] = guarded("replay", replay)  # real journey times for the journey model
        thinned = guarded("thin", lambda: thin_history(s, source, utcnow(), exported=exported))
        out.update(thinned if isinstance(thinned, dict) else {"thin": thinned})
        out["arrivals"] = guarded("trim arrivals", lambda: trim_arrivals(s, source))
        if exported is not None:
            from .history import drop_exported, rebuild_pending
            from .trackernet import from_env

            out["dropped"] = guarded("drop", lambda: drop_exported(s, source, utcnow()))
            # days thinned before the store existed: every measured Tube arrival, rebuilt from the raw archive
            out["rebuilt"] = guarded("rebuild", lambda: rebuild_pending(
                s, source, archive, from_env(), max_days=2, on_day=lambda day: prog.step(f"rebuild {day}")))
            if isinstance(out["rebuilt"], dict) and out["rebuilt"]["days"]:
                out["replay_rebuilt"] = guarded("replay rebuilt", replay)
        prog.finish(out)
        return out


def journeys_tick() -> dict:
    """The journey model's pre-registered evaluation on the replayed days (paxen/journey_eval.py)."""
    from .archive import get_archive
    from .journey_eval import run

    with SessionLocal() as s:
        return run(s, get_provider().name, get_archive())


TRAIN_FIRST_DELAY_S = 600  # let the recorder run for a while after a (re)start before the first training run


def _peak_mb() -> int | None:
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024  # KB on Linux
    except Exception:
        return None


def train_isolated(flag: str = "--train-once") -> dict:
    """Run train_tick (or, with --thin-once, thin_tick) in a child process. Training holds weeks of history in
    memory; if it is ever killed for running out of memory, only the child dies and the recorder keeps recording
    (before this, an out-of-memory kill took the whole worker down every 30 s, silently). The model libraries are
    only ever loaded in the child, never in the long-running worker."""
    import os
    import subprocess
    import sys

    # One thread for the model libraries (OpenMP). By default they start one thread per CPU the host has, which
    # in a container is far more than it may use; with the recorder also running, the threads spin waiting for
    # each other and a 3-second model fit took over 10 minutes in testing.
    env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    proc = subprocess.run([sys.executable, "-m", "paxen.worker", flag], env=env)
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
    if settings.provider != "sim":  # the journey model's evaluation, daily, an hour after training
        loop_tasks.append(asyncio.create_task(_loop(lambda: train_isolated("--journeys-once"), settings.train_interval_s,
                                                    "journeys", first_delay=TRAIN_FIRST_DELAY_S + 3600)))
    if settings.provider != "sim" and settings.thin_interval_s > 0:
        loop_tasks.append(asyncio.create_task(_loop(lambda: train_isolated("--thin-once"), settings.thin_interval_s,
                                                    "thin", first_delay=300)))
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
