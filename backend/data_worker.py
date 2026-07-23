from __future__ import annotations

import logging
import signal
import threading

from dotenv import load_dotenv

load_dotenv()

from services.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lineuplab.data_worker")


def main() -> None:
    stopped = threading.Event()

    def stop(signum: int, _frame: object) -> None:
        logger.info("received signal %s; stopping data refresh worker", signum)
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    scheduler = start_scheduler()
    logger.info("data refresh worker is ready")
    stopped.wait()
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
