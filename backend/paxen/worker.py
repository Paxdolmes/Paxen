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
    init_db()
    tasks: list[asyncio.Task] = []
    workers.start(tasks)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    import os

    from .config import settings

    logging.getLogger("paxen.worker").info(
        "worker started: recorder, monitor, training | code %s | provider %s | modes %s | region %s",
        (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "local")[:7], settings.provider, ",".join(settings.record_modes),
        os.getenv("RAILWAY_REPLICA_REGION") or "?")
    await stop.wait()
    for t in tasks:
        t.cancel()


if __name__ == "__main__":
    asyncio.run(main())
