import argparse
import logging
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Main")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PC Build Guidance — FastAPI + WebSocket server"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Bind address (overrides API_HOST, default 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port (overrides API_PORT, default 8000)",
    )
    parser.add_argument(
        "--snapshot-interval",
        type=float,
        default=None,
        help="Seconds between model snapshots (sets SNAPSHOT_INTERVAL)",
    )
    args = parser.parse_args()

    if args.snapshot_interval is not None:
        os.environ["SNAPSHOT_INTERVAL"] = str(args.snapshot_interval)
    if args.host is not None:
        os.environ["API_HOST"] = args.host
    if args.port is not None:
        os.environ["API_PORT"] = str(args.port)

    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    logger.info("Starting Uvicorn on %s:%s (API)", host, port)
    uvicorn.run("api:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
