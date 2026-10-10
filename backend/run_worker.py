"""Standalone video worker for hosts where the web process can't run background tasks (cPanel/Passenger).
  python run_worker.py          # run forever (VPS / systemd / supervisor)
  python run_worker.py --once   # process all pending jobs then exit (cron every minute; file lock prevents overlap)"""
import asyncio
import fcntl
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bootstrap import bootstrap_sync  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


async def drain():
    import worker
    while True:
        while len(worker._running) < worker.MAX_CONCURRENT:
            j = await worker._claim()
            if not j:
                break
            worker._running.add(j["id"])
            asyncio.create_task(worker._run(j["id"]))
        if not worker._running:
            return
        await asyncio.sleep(3)


def main():
    lock = open(Path(__file__).parent / ".worker.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another worker is already running; exiting.")
        return
    bootstrap_sync()
    from core import init_storage
    init_storage()
    import worker
    asyncio.run(drain() if "--once" in sys.argv else worker.worker_loop())


if __name__ == "__main__":
    main()
