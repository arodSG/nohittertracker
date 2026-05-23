#!/usr/bin/python3

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from nohittertracker import util
from nohittertracker.api_server import NoHitterAPIServer
from nohittertracker.service import NoHitterTracker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run the NoHitterTracker API server.')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', 8001)))
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    tracker = NoHitterTracker()
    tracker.initialize()
    server = NoHitterAPIServer((args.host, args.port), tracker)
    util.logger.info(f'Starting No-Hitter Tracker API on http://{args.host}:{args.port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
