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
                    data = pickle.load(f)
                if isinstance(data, dict):
                    # New format: {date_str: set(event_ids)} — keep only today
                    self.tweeted_event_ids = set(data.get(self._today, set()))
                elif isinstance(data, (set, list, tuple)):
                    # Legacy flat-set format written before date-keyed format
                    self.tweeted_event_ids = set()
        except Exception as exc:
            util.logger.warning(f'Failed to load tweeted event IDs: {exc}')

    def _save_tweeted_event_ids(self) -> None:
        """Persist today's tweeted event IDs to file, discarding past dates."""
        try:
            path = self._tweeted_events_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'wb') as f:
                pickle.dump({self._today: self.tweeted_event_ids}, f)
        except Exception as exc:
            util.logger.warning(f'Failed to save tweeted event IDs: {exc}')

    def _twitter_client(self) -> tweepy.Client:
        return tweepy.Client(
            consumer_key=os.getenv('TWITTER_CONSUMER_KEY'),
            consumer_secret=os.getenv('TWITTER_CONSUMER_SECRET'),
            access_token=os.getenv('TWITTER_ACCESS_TOKEN'),
            access_token_secret=os.getenv('TWITTER_ACCESS_TOKEN_SECRET'),
        )

    def _fetch_events(self, game_date: str | None = None) -> dict:
        """Fetch the full no-hitter API payload."""
        params = {
            'include_events': True,
            'include_event_snapshot': True,
        }
        if game_date:
            params['date'] = game_date

        try:
            response = util.session.get(f'{self.api_base_url}/api/no-hitters', params=params)
            if response.status_code == 200:
                return response.json()
        except Exception as exc:
            util.logger.error(f'Failed to fetch events: {exc}')
            util.arodsg_ntfy(f'Bot: Failed to fetch events: {exc}')

        return {}

    def _send_tweet(self, event: dict) -> None:
        """Send a tweet for an event."""
        tweet_text = event.get('tweet_text', '')
        if not tweet_text:
            return

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

        payload = self._fetch_events(game_date)
        events = payload.get('activity', {}).get('events', [])
        active_no_hitters = payload.get('entities', {}).get('active_no_hitters_by_key', {})

        # Log sub-threshold no-hitters regardless of whether events exist
        if active_no_hitters:
            summaries = ', '.join(
                f'[{s.get("team_name")}: isNoHitter={s.get("is_no_hitter")}, isPerfectGame={s.get("is_perfect_game")}, innings={s.get("innings_pitched")}]'
                for s in active_no_hitters.values()
            )
            threshold = next(iter(active_no_hitters.values())).get('alert_threshold')
            util.logger.info(f'{len(active_no_hitters)} active no-hitter(s) below threshold ({threshold} inn): {summaries}')

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

    def _get_effective_game_date(self) -> str:
        """Use the same 5-hour offset as service.py to determine the current game date."""
        return (datetime.datetime.now() - datetime.timedelta(hours=5)).strftime('%m/%d/%Y')

    def _get_today_games(self) -> list[dict]:
        """Fetch games for the effective game date (with 5-hour offset)."""
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
        """Adaptive scheduler loop:
        - Polls at the top of every hour when no games are near.
        - Polls every 15 minutes when within 60 minutes of the first game.
        - Polls every 2 minutes when games are in progress or about to start.
        - Stops polling for the rest of the effective day when all games are final.
        """
        SCHEDULER_INTERVAL_SECONDS = 3600  # 1 hour, aligned to top of hour
        PRE_GAME_WINDOW_MINUTES = 60        # Start 15-min checks within 60 min of first game
        PRE_GAME_POLL_SECONDS = 900         # 15 min polling as game approaches
        EVENT_POLL_SECONDS = 120            # 2 min polling when game is in progress or about to start
        util.logger.info('Bot started in adaptive scheduler mode. Hourly checks -> 15-min pre-game -> 2-min event polling.')

        while True:
            games = self._get_today_games()
            active, num_total, num_in_progress, next_start, next_minutes = self._any_game_in_progress_or_soon(games)

            # All games final and none scheduled for the effective day: sleep until next effective game day (5am offset)
            if not games:
                now = datetime.datetime.now()
                if now.hour >= 5:
                    next_day = (now + datetime.timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)
                else:
                    next_day = now.replace(hour=5, minute=0, second=0, microsecond=0)
                sleep_seconds = (next_day - now).total_seconds()
                util.logger.info(f'All games final and none scheduled. Sleeping for {int(sleep_seconds // 3600)}h {int((sleep_seconds % 3600) // 60)}m until next effective game day.')
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
                continue

            log_msg = f'Scheduler check: {num_total} games scheduled, {num_in_progress} in progress'
            if next_minutes is not None:
                if next_minutes >= 60:
                    hours = int(next_minutes // 60)
                    minutes = int(next_minutes % 60)
                    if minutes > 0:
                        log_msg += f', next game in {hours} hours {minutes} minutes'
                    else:
                        log_msg += f', next game in {hours} hours'
                else:
                    log_msg += f', next game in {int(next_minutes)} minutes'
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
            # Within 60 minutes of first game: poll every 15 minutes to catch late schedule changes
            elif next_minutes is not None and next_minutes <= PRE_GAME_WINDOW_MINUTES:
                util.logger.info(f'Pre-game window: polling every {PRE_GAME_POLL_SECONDS // 60} minutes to catch late schedule changes.')
                time.sleep(PRE_GAME_POLL_SECONDS)
            # Otherwise: sleep until the top of the next hour
            else:
                now = datetime.datetime.now()
                next_hour = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                sleep_seconds = (next_hour - now).total_seconds()
                util.logger.info(f'No games soon. Sleeping until top of next hour ({int(sleep_seconds // 60)} min).')
                time.sleep(sleep_seconds)


def main() -> None:
    load_dotenv()
    util.create_session()
    bot = ApiEventBot()
    bot.run_forever()


if __name__ == '__main__':
    main()
