#!/usr/bin/python3

import datetime
import math
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

    GAME_SOON_WINDOW_MINUTES = constants.GAME_SOON_WINDOW_MINUTES

    def __init__(self, api_base_url: str | None = None):
        self.api_base_url = api_base_url or os.getenv('API_BASE_URL', 'http://127.0.0.1:8001')
        self._today: str = (datetime.datetime.now() - datetime.timedelta(hours=10)).strftime('%Y-%m-%d')
        self.tweeted_event_ids: set[str] = set()
        self._warmed_up: bool = False
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
        """Send a tweet for an event. Raises on tweet failure so the caller can retry."""
        tweet_text = event.get('tweet_text', '')
        if not tweet_text:
            return

        if util.ENVIRONMENT == 'prod':
            client = self._twitter_client()
            response = client.create_tweet(text=tweet_text)
            tweet_url = f"https://twitter.com/NoHitterTracker/status/{response.data['id']}"
            util.logger.info(f'Tweet sent: {tweet_url}')
            try:
                util.arodsg_ntfy(tweet_text, tweet_url)
            except Exception as exc:
                util.logger.warning(f'Notification failed after tweet: {exc}')
        else:
            util.logger.info(f'Test mode - would tweet: {tweet_text}')
            try:
                util.arodsg_ntfy(f'[TEST] {tweet_text}')
            except Exception as exc:
                util.logger.warning(f'Notification failed in test mode: {exc}')

    def run_once(self, game_date: str | None = None) -> int:
        """Poll the API once and process new events. Returns count of active in-progress no-hitters."""
        today = (datetime.datetime.now() - datetime.timedelta(hours=10)).strftime('%Y-%m-%d')
        if today != self._today:
            util.logger.info(f'New day detected ({self._today} -> {today}), resetting tweeted event IDs')
            self._today = today
            self.tweeted_event_ids = set()

        payload = self._fetch_events(game_date)
        events = payload.get('activity', {}).get('events', [])
        active_no_hitters = payload.get('entities', {}).get('active_no_hitters_by_key', {})

        # Log sub-threshold no-hitters for games actually in progress
        in_progress_no_hitters = {k: v for k, v in active_no_hitters.items() if v.get('is_in_progress')}
        if in_progress_no_hitters:
            summaries = ', '.join(
                f'[{s.get("team_name")}: perfectGame={s.get("is_perfect_game")}, innings={s.get("innings_pitched")}]'
                for s in in_progress_no_hitters.values()
            )
            threshold = next(iter(in_progress_no_hitters.values())).get('alert_threshold')
            util.logger.info(f'no-hitters: {summaries}')

        if not self._warmed_up:
            # First poll after startup: silently absorb all existing events so the bot
            # is point-forward and won't re-tweet anything that already happened.
            event_ids = [e.get('event_id') for e in events if e.get('event_id')]
            self.tweeted_event_ids.update(event_ids)
            self._save_tweeted_event_ids()
            self._warmed_up = True
            util.logger.info(f'Warmup complete — marked {len(event_ids)} existing event(s) as seen, will only tweet new events from here')
            return len(in_progress_no_hitters)

        if not events:
            util.logger.info('No new events')
            return len(in_progress_no_hitters)

        for event in events:
            event_id = event.get('event_id')
            if event_id and event_id not in self.tweeted_event_ids:
                util.logger.info(f'Processing new event: {event_id}')
                try:
                    self._send_tweet(event)
                except Exception as exc:
                    util.logger.error(f'Tweet failed for {event_id}, will retry next poll: {exc}')
                    continue
                self.tweeted_event_ids.add(event_id)
                self._save_tweeted_event_ids()

        return len(in_progress_no_hitters)

    @staticmethod
    def _format_minutes(minutes: float) -> str:
        """Format a duration as 'X hour(s) Y minute(s)' with correct plurality."""
        total = math.ceil(minutes)
        h, m = divmod(total, 60)
        if h > 0 and m > 0:
            return f'{h} {"hour" if h == 1 else "hours"} {m} {"minute" if m == 1 else "minutes"}'
        elif h > 0:
            return f'{h} {"hour" if h == 1 else "hours"}'
        return f'{total} {"minute" if total == 1 else "minutes"}'

    def _get_effective_game_date(self) -> str:
        """Use a 10-hour offset so the game date rolls over at 5am CDT, safely past any late/extra-innings games."""
        return (datetime.datetime.now() - datetime.timedelta(hours=10)).strftime('%m/%d/%Y')

    def _get_today_games(self) -> list[dict]:
        """Fetch games for the effective game date (with 10-hour offset)."""
        game_date = self._get_effective_game_date()
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
            abstract = status.get('abstractGameCode')
            coded = status.get('codedGameState')
            if coded == 'I':
                in_progress += 1
            elif abstract in {'P', 'S'} or (abstract == 'L' and coded == 'P'):
                # Scheduled, pre-game, or warmup: check if starting soon
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

    def _is_mlb_season_over(self) -> bool:
        """Return True if today is past the current MLB season end date.

        Tries the current calendar year first. If the season hasn't started yet
        (e.g. January before opening day), falls back to the previous year so the
        offseason between seasons is correctly identified as 'over'.
        """
        today = datetime.date.today()
        for year in (today.year, today.year - 1):
            try:
                resp = requests.get(
                    f'https://statsapi.mlb.com/api/v1/seasons/{year}',
                    params={'sportId': 1},
                    timeout=10,
                )
                if resp.status_code != 200:
                    continue
                seasons = resp.json().get('seasons', [])
                if not seasons:
                    continue
                season = seasons[0]
                start_str = season.get('regularSeasonStartDate')
                end_str = season.get('seasonEndDate')
                if not start_str or not end_str:
                    continue
                if today < datetime.date.fromisoformat(start_str):
                    # This season hasn't started yet — check the previous year instead
                    continue
                return today > datetime.date.fromisoformat(end_str)
            except Exception as exc:
                util.logger.warning(f'Failed to check MLB {year} season dates: {exc}')
        return False

    def run_forever(self) -> None:
        """Unified adaptive scheduler loop.

        The same three-tier sleep logic applies in all phases:
          - 2 min  : active no-hitter, game about to start, or new game just entered in-progress
          - 15 min : within 60 minutes of the next scheduled game (or no more games today but still in progress)
          - 1 hour : no games active/near (or all in-progress no-hitters broken with next game > 60 min)

        Additionally sleeps until 8am EST when all games are final or none are scheduled.
        """
        PRE_GAME_WINDOW_MINUTES = 60
        PRE_GAME_POLL_SECONDS = 900
        EVENT_POLL_SECONDS = 120
        util.logger.info('Bot started. Adaptive scheduler: hourly → 15-min → 2-min event polling.')

        while True:
            games = self._get_today_games()
            active, num_total, num_in_progress, next_start, next_minutes = self._any_game_in_progress_or_soon(games)

            # ── All games final / no games scheduled ──────────────────────────────
            if not games or (not active and next_minutes is None):
                if not games and self._is_mlb_season_over():
                    util.logger.info('MLB season has ended and no games are scheduled. Shutting down.')
                    util.arodsg_ntfy('Bot: MLB season over — shutting down.')
                    return
                now = datetime.datetime.now()
                if now.hour >= 13:
                    resume = (now + datetime.timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
                else:
                    resume = now.replace(hour=13, minute=0, second=0, microsecond=0)
                sleep_seconds = (resume - now).total_seconds()
                reason = 'No games scheduled' if not games else 'All games final'
                util.logger.info(
                    f'{reason}. Sleeping for {int(sleep_seconds // 3600)}h '
                    f'{int((sleep_seconds % 3600) // 60)}m until 8am EST next effective game day.'
                )
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
                continue

            # ── No games active or starting very soon: pre-game dormant ───────────
            if not active:
                if next_minutes is not None and next_minutes <= PRE_GAME_WINDOW_MINUTES:
                    util.logger.info(
                        f'Pre-game: next game in {self._format_minutes(next_minutes)}. '
                        f'Polling every {PRE_GAME_POLL_SECONDS // 60} minutes.'
                    )
                    time.sleep(PRE_GAME_POLL_SECONDS)
                else:
                    now = datetime.datetime.now()
                    next_hour = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                    sleep_seconds = max(0, (next_hour - now).total_seconds())
                    sleep_minutes = -(-int(sleep_seconds) // 60)
                    sleep_display = '1 hour' if sleep_minutes >= 60 else f'{sleep_minutes} minutes'
                    suffix = f'next game in {self._format_minutes(next_minutes)}' if next_minutes is not None else 'no games today'
                    util.logger.info(f'Dormant ({suffix}). Sleeping for {sleep_display}.')
                    time.sleep(sleep_seconds)
                continue

            # ── Active: game in progress or starting very soon ────────────────────
            num_active_no_hitters = 1  # safe default on error
            try:
                num_active_no_hitters = self.run_once()
            except Exception as exc:
                util.logger.error(f'Error in run_once: {exc}')

            # Apply the same three-tier logic as pre-game dormant above.
            dormant = (
                num_active_no_hitters == 0
                and (next_minutes is None or next_minutes > self.GAME_SOON_WINDOW_MINUTES)
            )
            if not dormant:
                sleep_seconds = EVENT_POLL_SECONDS
            elif next_minutes is not None and next_minutes > PRE_GAME_WINDOW_MINUTES:
                now = datetime.datetime.now()
                next_hour = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                sleep_seconds = max(0, (next_hour - now).total_seconds())
                sleep_minutes = -(-int(sleep_seconds) // 60)
                sleep_display = '1 hour' if sleep_minutes >= 60 else f'{sleep_minutes} minutes'
                util.logger.info(
                    f'No active no-hitters; {num_in_progress} {"game" if num_in_progress == 1 else "games"} in progress. '
                    f'Next game in {self._format_minutes(next_minutes)}. Sleeping for {sleep_display}.'
                )
            else:
                if next_minutes is not None:
                    sleep_seconds = PRE_GAME_POLL_SECONDS
                    util.logger.info(
                        f'No active no-hitters; {num_in_progress} {"game" if num_in_progress == 1 else "games"} in progress. '
                        f'Next game in {self._format_minutes(next_minutes)}. '
                        f'Sleeping for {PRE_GAME_POLL_SECONDS // 60} minutes.'
                    )
                else:
                    now_utc = datetime.datetime.now(datetime.timezone.utc)
                    resume = now_utc.replace(hour=10, minute=0, second=0, microsecond=0)
                    if resume <= now_utc:
                        resume += datetime.timedelta(days=1)
                    sleep_seconds = (resume - now_utc).total_seconds()
                    sleep_hours = int(sleep_seconds // 3600)
                    sleep_mins = int((sleep_seconds % 3600) // 60)
                    sleep_display = f'{sleep_hours}h {sleep_mins}m' if sleep_hours > 0 else f'{sleep_mins} minutes'
                    util.logger.info(
                        f'No active no-hitters; {num_in_progress} {"game" if num_in_progress == 1 else "games"} in progress. '
                        f'No more games scheduled today. Sleeping {sleep_display} until effective game day ends (5am CDT).'
                    )

            time.sleep(sleep_seconds)


def main() -> None:
    load_dotenv()
    util.create_session()
    bot = ApiEventBot()
    bot.run_forever()


if __name__ == '__main__':
    main()
