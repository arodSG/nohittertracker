#!/usr/bin/python3

import datetime
import os
import pickle
import time
from pathlib import Path

import tweepy
from dotenv import load_dotenv

from nohittertracker import constants, util


class ApiEventBot:
    """Polls the no-hitter API and sends tweets for new events."""

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

    def _fetch_events(self, game_date: str | None = None) -> list[dict]:
        """Fetch events from the API."""
        params = {
            'include_events': True,
            'include_event_snapshot': True,
        }
        if game_date:
            params['date'] = game_date

        try:
            response = util.session.get(f'{self.api_base_url}/api/no-hitters', params=params)
            if response.status_code == 200:
                payload = response.json()
                return payload.get('activity', {}).get('events', [])
        except Exception as exc:
            util.logger.error(f'Failed to fetch events: {exc}')
            util.arodsg_ntfy(f'Bot: Failed to fetch events: {exc}')

        return []

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

    def run_forever(self) -> None:
        """Continuously poll the API and process events."""
        util.logger.info(f'Bot started, polling every {self.interval_seconds} seconds')
        while True:
            try:
                self.run_once()
            except Exception as exc:
                util.logger.error(f'Error in run_once: {exc}')
            time.sleep(self.interval_seconds)


def main() -> None:
    load_dotenv()
    util.create_session()
    util.load_config(constants.CONFIG_FILE_PATH)
    bot = ApiEventBot()
    bot.run_forever()


if __name__ == '__main__':
    main()
