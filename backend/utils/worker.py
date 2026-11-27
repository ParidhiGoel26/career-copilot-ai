"""RQ worker entrypoint: python -m utils.worker"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

load_dotenv(ROOT / ".env")

from redis import Redis
from rq import Worker

from utils.jobs import QUEUE_NAME
from utils.observability import configure_logging

configure_logging()
logger = logging.getLogger("careerai.worker")


def main() -> int:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    logger.info("starting RQ worker queue=%s redis=%s", QUEUE_NAME, redis_url)
    conn = Redis.from_url(redis_url)
    worker = Worker([QUEUE_NAME], connection=conn)
    worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
