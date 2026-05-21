from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .service import NoHitterTracker


class NoHitterAPIServer(ThreadingHTTPServer):
    def __init__(self, server_address, tracker: NoHitterTracker):
        self.tracker = tracker
        super().__init__(server_address, NoHitterAPIHandler)


class NoHitterAPIHandler(BaseHTTPRequestHandler):
    server: NoHitterAPIServer

    def _set_common_headers(self, body_len: int) -> None:
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(body_len))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _write_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode('utf-8')
        self.send_response(status.value)
        self._set_common_headers(len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT.value)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == '/health':
            self._write_json({'status': 'ok'})
            return

        # Extract query parameters
        params = parse_qs(parsed.query)
        game_date = params.get('date', [None])[0]
        include_events = params.get('include_events', ['true'])[0].lower() != 'false'
        include_all_plays = params.get('include_all_plays', ['false'])[0].lower() == 'true'
        include_event_snapshot = params.get('include_event_snapshot', ['false'])[0].lower() == 'true'
        include_legacy = params.get('include_legacy', ['true'])[0].lower() != 'false'

        # Different default for include_games based on endpoint
        if parsed.path == '/api/games':
            include_games = params.get('include_games', ['true'])[0].lower() != 'false'
        elif parsed.path == '/api/no-hitters':
            include_games = params.get('include_games', ['false'])[0].lower() != 'false'
        elif parsed.path == '/':
            include_games = params.get('include_games', ['true'])[0].lower() != 'false'
        else:
            self._write_json({'error': 'Not found'}, status=HTTPStatus.NOT_FOUND)
            return

        result = self.server.tracker.scan(
            game_date=game_date,
            include_game_feed=include_games,
            include_all_plays=include_all_plays,
            include_event_snapshot=include_event_snapshot,
            include_legacy=include_legacy,
        )
        if not include_events:
            if 'events' in result:
                result.pop('events', None)
            if 'activity' in result and isinstance(result['activity'], dict):
                result['activity']['events'] = []
        self._write_json(result)

    def log_message(self, format: str, *args) -> None:
        return