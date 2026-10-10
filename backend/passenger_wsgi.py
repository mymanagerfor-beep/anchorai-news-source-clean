"""cPanel "Setup Python App" (Passenger) entry point. Startup file: passenger_wsgi.py, entry point: application.
The video worker does NOT run inside Passenger; schedule `run_worker.py --once` with cron (see DEPLOYMENT.md)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("RUN_WORKER", "0")

from bootstrap import bootstrap_sync  # noqa: E402

bootstrap_sync()

from a2wsgi import ASGIMiddleware  # noqa: E402
from server import app  # noqa: E402

application = ASGIMiddleware(app)
