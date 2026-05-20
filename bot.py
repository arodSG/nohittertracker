#!/usr/bin/python3

import datetime
import os
import pickle
import time
from pathlib import Path

import tweepy
from dotenv import load_dotenv

from nohittertracker import constants, util



import requests

class ApiEventBot:
    """Polls the no-hitter API and sends tweets for new events, but only when games are active."""

    SCHEDULER_INTERVAL_SECONDS = int(os.getenv('SCHEDULER_INTERVAL_SECONDS', 900))  # 15 min default
    GAME_SOON_WINDOW_MINUTES = int(os.getenv('GAME_SOON_WINDOW_MINUTES', 30))  # Consider 'soon' if within 30 min

    def __init__(self, api_base_url: str | None = None):
        self.api_base_url = api_base_url or os.getenv('API_BASE_URL', 'http://127.0.0.1:8001')
        self.interval_seconds = constants.INTERVAL_SECONDS
        self._today: str = datetime.date.today().isoformat()
        self.tweeted_event_ids: set[str] = set()
        self._load_tweeted_event_ids()

    def _tweeted_events_path(self) -> Path:
        """Path to persist tweeted event IDs."""
        preferred = Path('/data/tweeted_event_ids.pkl')
        if preferred.parent.exists():
            return preferred
        fallback = Path(__file__).resolve().parent / 'data' / 'tweeted_event_ids.pkl'
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return fallback

    def _load_tweeted_event_ids(self) -> None:
        """Load today's tweeted event IDs from file, pruning stale dates."""
        try:
            path = self._tweeted_events_path()
            if path.exists():
                with open(path, 'rb') as f:
                    while True:
                        games = self._get_today_games()
                        active, num_total, num_in_progress, next_start, next_minutes = self._any_game_in_progress_or_soon(games)
                        # Check if all games are final and none are scheduled (using offset logic)
                        if not games:
                            util.logger.info('Scheduler check: No games scheduled today.')
                            # Sleep until the next effective game day (after offset window passes)
                            now = datetime.datetime.now()
                            tomorrow = (now + datetime.timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)
                            if now.hour >= 5:
                                # Already past offset, so next day is tomorrow at 5am
                                sleep_seconds = (tomorrow - now).total_seconds()
                            else:
                                # Before 5am, so next day is today at 5am
                                today_5am = now.replace(hour=5, minute=0, second=0, microsecond=0)
                                sleep_seconds = (today_5am - now).total_seconds()
                            util.logger.info(f'All games final and none scheduled. Sleeping for {int(sleep_seconds // 3600)}h {int((sleep_seconds % 3600) // 60)}m until next effective game day.')
                            if sleep_seconds > 0:
                                time.sleep(sleep_seconds)
                            continue
                        log_msg = f"Scheduler check: {num_total} games scheduled, {num_in_progress} in progress"
                        if next_minutes is not None:
                            if next_minutes >= 60:
                                hours = int(next_minutes // 60)
                                minutes = int(next_minutes % 60)
                                if minutes > 0:
                                    log_msg += f", next game in {hours} hours {minutes} minutes"
                                else:
                                    log_msg += f", next game in {hours} hours"
                            else:
                                log_msg += f", next game in {int(next_minutes)} minutes"
                        util.logger.info(log_msg)

                        # If a game is in progress or about to start, enter high-frequency event polling
                        if active:
                            util.logger.info('No-hitter event check: polling for active games/events')
                            while True:
                                games = self._get_today_games()
                                active, _, num_in_progress, next_start, next_minutes = self._any_game_in_progress_or_soon(games)
                                if not active:
                                    util.logger.info('No active or upcoming games: returning to scheduler mode.')
                                    break
                                try:
                                    self.run_once()
                                except Exception as exc:
                                    util.logger.error(f'Error in run_once: {exc}')
                                time.sleep(EVENT_POLL_SECONDS)
                        # If the next game is within the pre-game window, poll every 15 minutes
                        elif next_minutes is not None and next_minutes <= PRE_GAME_WINDOW_MINUTES:
                            util.logger.info(f'Pre-game window: polling every {PRE_GAME_POLL_SECONDS // 60} minutes to catch late schedule changes.')
                            time.sleep(PRE_GAME_POLL_SECONDS)
                        # Otherwise, poll at the top of the next hour
                        else:
                            now = datetime.datetime.now()
                            next_hour = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                            sleep_seconds = (next_hour - now).total_seconds()
                            util.logger.info(f'No games soon. Sleeping until top of next hour ({int(sleep_seconds // 60)} min).')
                            time.sleep(sleep_seconds)
        try:
            if util.ENVIRONMENT == 'prod':
                client = self._twitter_client()
                response = client.create_tweet(text=tweet_text)
                tweet_url = f"https://twitter.com/NoHitterTracker/status/{response.data['id']}"
                util.logger.info(f'Tweet sent: {tweet_url}')
                util.arodsg_ntfy(tweet_text, tweet_url)
            else:
                util.logger.info(f'Test mode - would tweet: {tweet_text}')
                util.arodsg_ntfy(f'[TEST] {tweet_text}')
        except tweepy.TweepyException as exc:
            util.logger.error(f'Tweet failed: {exc}')
            util.arodsg_ntfy(f'Tweet failed: {exc}')

    def run_once(self, game_date: str | None = None) -> None:
        """Poll the API once and process new events."""
        today = datetime.date.today().isoformat()
        if today != self._today:
            util.logger.info(f'New day detected ({self._today} -> {today}), resetting tweeted event IDs')
            self._today = today
            self.tweeted_event_ids = set()

        events = self._fetch_events(game_date)
        if not events:
            util.logger.info('No events found')
            return

        for event in events:
            event_id = event.get('event_id')
            if event_id and event_id not in self.tweeted_event_ids:
                util.logger.info(f'Processing new event: {event_id}')
                self._send_tweet(event)
                self.tweeted_event_ids.add(event_id)
                self._save_tweeted_event_ids()


    def _get_today_games(self) -> list[dict]:
        """Fetch today's games from the MLB API schedule endpoint."""
        today = datetime.date.today().strftime('%m/%d/%Y')
        try:
            resp = requests.get('https://statsapi.mlb.com/api/v1/schedule', params={'sportId': 1, 'date': today})
            if resp.status_code == 200:
                data = resp.json()
                games = data.get('dates', [{}])[0].get('games', [])
                return games
        except Exception as exc:
            util.logger.error(f'Failed to fetch today\'s games: {exc}')
        return []
        def _get_effective_game_date(self) -> str:
            # Use the same 5-hour offset as service.py
            return (datetime.datetime.now() - datetime.timedelta(hours=5)).strftime('%m/%d/%Y')

        def _get_today_games(self) -> list[dict]:
            """Fetch games for the effective game date (with offset)."""
            game_date = self._get_effective_game_date()
            try:
                resp = requests.get('https://statsapi.mlb.com/api/v1/schedule', params={'sportId': 1, 'date': game_date})
                if resp.status_code == 200:
                    data = resp.json()
                    games = data.get('dates', [{}])[0].get('games', [])
                    return games
            except Exception as exc:
                util.logger.error(f'Failed to fetch games for {game_date}: {exc}')
            return []

    def _any_game_in_progress_or_soon(self, games: list[dict]) -> tuple[bool, int, int, str | None, float | None]:
        """Return (active, num_total, num_in_progress, next_game_str, next_game_minutes)"""
        now = datetime.datetime.now(datetime.timezone.utc)
        in_progress = 0
        next_start = None
        for g in games:
            status = g.get('status', {})
            code = status.get('abstractGameCode')
            if code == 'L':
                in_progress += 1
            elif code in {'P', 'S'}:
                # Scheduled or Pre-game: check if starting soon
                start_time = g.get('gameDate')
                if start_time:
                    try:
                        dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                        if dt > now:
                            if not next_start or dt < next_start:
                                next_start = dt
                    except Exception:
                        pass
        soon = False
        soon_str = None
        soon_minutes = None
        if next_start:
            delta = (next_start - now).total_seconds() / 60
            soon = 0 <= delta <= self.GAME_SOON_WINDOW_MINUTES
            soon_minutes = delta
            soon_str = next_start.strftime('%H:%M UTC')
        return (in_progress > 0 or soon, len(games), in_progress, soon_str, soon_minutes)

    def run_forever(self) -> None:
        """Adaptive scheduler: infrequent polls until close to first game, then more frequent, then high-frequency event polling."""
        util.logger.info(f'Bot started in adaptive scheduler mode. Scheduler interval: {self.SCHEDULER_INTERVAL_SECONDS}s, event poll interval: {self.interval_seconds}s')
        PRE_GAME_WINDOW_MINUTES = 60  # Start more frequent checks within 60 min of first game
        PRE_GAME_POLL_SECONDS = 120   # 2 min polling as game approaches
        while True:
            games = self._get_today_games()
            active, num_total, num_in_progress, next_start, next_minutes = self._any_game_in_progress_or_soon(games)
            if not games:
                util.logger.info('Scheduler check: No games scheduled today.')
                time.sleep(self.SCHEDULER_INTERVAL_SECONDS)
                continue
            log_msg = f"Scheduler check: {num_total} games scheduled, {num_in_progress} in progress"
            if next_minutes is not None:
                if next_minutes >= 60:
                    hours = int(next_minutes // 60)
                    minutes = int(next_minutes % 60)
                    if minutes > 0:
                        log_msg += f", next game in {hours} hours {minutes} minutes"
                    else:
                        log_msg += f", next game in {hours} hours"
                else:
                    log_msg += f", next game in {int(next_minutes)} minutes"
            util.logger.info(log_msg)

            # If a game is in progress or about to start, enter high-frequency event polling
            if active:
                util.logger.info('No-hitter event check: polling for active games/events')
                while True:
                    games = self._get_today_games()
                    active, _, num_in_progress, next_start, next_minutes = self._any_game_in_progress_or_soon(games)
                    if not active:
                        util.logger.info('No active or upcoming games: returning to scheduler mode.')
                        break
                    try:
                        self.run_once()
                    except Exception as exc:
                        util.logger.error(f'Error in run_once: {exc}')
                    time.sleep(self.interval_seconds)
            # If the next game is within the pre-game window, poll more frequently
            elif next_minutes is not None and next_minutes <= PRE_GAME_WINDOW_MINUTES:
                util.logger.info(f'Pre-game window: polling every {PRE_GAME_POLL_SECONDS} seconds to catch late schedule changes.')
                time.sleep(PRE_GAME_POLL_SECONDS)
            # Otherwise, poll at the normal scheduler interval
            else:
                time.sleep(self.SCHEDULER_INTERVAL_SECONDS)
                # Check if all games are final and none are scheduled (using offset logic)
                if not games:
                    util.logger.info('Scheduler check: No games scheduled today.')
                    # Sleep until the next effective game day (after offset window passes)
                    now = datetime.datetime.now()
                    tomorrow = (now + datetime.timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)
                    if now.hour >= 5:
                        # Already past offset, so next day is tomorrow at 5am
                        sleep_seconds = (tomorrow - now).total_seconds()
                    else:
                        # Before 5am, so next day is today at 5am
                        today_5am = now.replace(hour=5, minute=0, second=0, microsecond=0)
                        sleep_seconds = (today_5am - now).total_seconds()
                    util.logger.info(f'All games final and none scheduled. Sleeping for {int(sleep_seconds // 3600)}h {int((sleep_seconds % 3600) // 60)}m until next effective game day.')
                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)
                    continue


def main() -> None:
    load_dotenv()
    util.create_session()
        SCHEDULER_INTERVAL_SECONDS = 3600  # 1 hour
        PRE_GAME_WINDOW_MINUTES = 60  # Start 15-min checks within 60 min of first game
        PRE_GAME_POLL_SECONDS = 900   # 15 min polling as game approaches
        EVENT_POLL_SECONDS = 120      # 2 min polling when game is in progress or about to start
    bot.run_forever()


if __name__ == '__main__':
    main()
