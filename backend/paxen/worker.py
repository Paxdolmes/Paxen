"""Standalone background process: data recorder, commute monitor and model training.

Run alongside the API in production (with PAXEN_RUN_WORKERS=0 on the API):

    python -m paxen.worker
"""
from __future__ import annotations

import asyncio
import logging
import signal

from .db import init_db
from . import workers


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # Request URLs carry the TfL app_key: never log them.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    init_db()
    tasks: list[asyncio.Task] = []
    workers.start(tasks)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    import os

    from .config import settings

    log = logging.getLogger("paxen.worker")
    if os.getenv("RAILWAY_ENVIRONMENT") and settings.provider == "sim":
        log.error("PAXEN_PROVIDER is %r on Railway: recording SIMULATED data, not TfL. Set PAXEN_PROVIDER=tfl.",
                  os.getenv("PAXEN_PROVIDER"))
    if settings.provider == "tfl":
        from .db import SessionLocal
        from .recorder import purge_source

        with SessionLocal() as s:
            purged = purge_source(s, "sim")
        if any(purged.values()):
            log.warning("removed simulator data from the live database: %s", purged)
        from .darwin import start as start_darwin

        if not start_darwin(SessionLocal):
            log.info("darwin: not configured (DARWIN_* variables): Overground/Elizabeth line truth stays inferred")
    log.info(
        "worker started: recorder, monitor, training | code %s | provider %s | modes %s | region %s",
        (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "local")[:7], settings.provider, ",".join(settings.record_modes),
        os.getenv("RAILWAY_REPLICA_REGION") or "?")
    await stop.wait()
    for t in tasks:
        t.cancel()


def train_once() -> None:
    """One training run, in its own process (started by the worker; see workers.train_isolated)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    log = logging.getLogger("paxen.train")
    init_db()
    res = workers.train_tick()
    import resource

    log.info("train: %s | peak memory %s MB", res, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)


if __name__ == "__main__":
    import sys

    if "--train-once" in sys.argv:
        train_once()
    else:
        asyncio.run(main())
