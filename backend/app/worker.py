"""Background job worker (production mode).

Run alongside the API with JOB_MODE=worker:

    python -m app.worker

It claims pending audits and visibility runs from the database one at a time
(`FOR UPDATE SKIP LOCKED`, so several workers can run safely) and executes them.
Jobs survive API restarts because they live in the database, not in the API process.
"""

from __future__ import annotations

import logging
import signal
import time

from app.db import session_scope
from app.main import configure_logging
from app.services.jobs import claim_next_job, recover_interrupted_jobs

logger = logging.getLogger("app.worker")
POLL_SECONDS = 2.0
_stop = False


def _request_stop(signum, _frame) -> None:
    global _stop
    logger.info("received signal %s, finishing current job then stopping", signum)
    _stop = True


def run_once() -> bool:
    """Claim and run one job. Returns True if a job was run."""
    with session_scope() as db:
        claimed = claim_next_job(db)
    if claimed is None:
        return False
    job, job_id = claimed
    logger.info("running %s(%s)", job.__name__, job_id)
    job(job_id)
    return True


def main() -> None:
    configure_logging()
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    # Jobs marked running belonged to a worker that died; pending jobs stay queued.
    with session_scope() as db:
        recover_interrupted_jobs(db, statuses=("running",))
    logger.info("worker started, polling every %ss", POLL_SECONDS)
    while not _stop:
        try:
            if not run_once():
                time.sleep(POLL_SECONDS)
        except Exception:  # noqa: BLE001 - keep the worker alive; the job records its own failure
            logger.exception("worker loop error")
            time.sleep(POLL_SECONDS)
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
