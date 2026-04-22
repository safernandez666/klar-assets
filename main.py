from __future__ import annotations

import argparse
import os

import structlog
import uvicorn
from dotenv import load_dotenv

from src.storage.schema import init_db
from src.sync_engine import SyncEngine

load_dotenv()

logger = structlog.get_logger(__name__)
DB_PATH = os.getenv("DB_PATH", "data/devices.db")


def main() -> None:
    parser = argparse.ArgumentParser(description="Klar Device Normalizer")
    parser.add_argument("--sync-only", action="store_true", help="Run sync without web server")
    args = parser.parse_args()

    # Initialize database
    init_db(DB_PATH)
    logger.info("db_initialized", path=DB_PATH)

    if args.sync_only:
        logger.info("running_sync_only")
        engine = SyncEngine(DB_PATH)
        result = engine.run()
        logger.info("sync_finished", result=result)
    else:
        # Sync on startup if configured and data is stale (>2h)
        sync_on_startup = os.getenv("SYNC_ON_STARTUP", "true").lower() == "true"
        if sync_on_startup:
            if SyncEngine.should_skip_startup_sync(DB_PATH):
                logger.info("startup_sync_skipped", reason="last_sync_within_2h")
            else:
                logger.info("running_startup_sync")
                engine = SyncEngine(DB_PATH)
                try:
                    engine.run()
                except Exception as exc:
                    logger.error("startup_sync_failed", error=str(exc))

        host = os.getenv("WEB_HOST", "0.0.0.0")
        port = int(os.getenv("WEB_PORT", "8080"))
        logger.info("starting_server", host=host, port=port)
        uvicorn.run("src.web.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
