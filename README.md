# NoHitterTracker
NoHitterTracker is a Twitter bot that checks for no-hitters and perfect games in live MLB games.

The script retrieves the list of games for the current day and checks various game/player stats from the MLB Stats API to determine if there is currently a no-hitter or perfect game, and whether or not it's combined. Tweeted game information is stored in a serialized pickle file, `team_ids_tweeted.pkl` - `{team_id: {is_combined: False, is_perfect_game: False, is_finished: False}}`. Tweets are sent if there's a no-hitter or perfect game after `num_innings_to_alert`. For previously tweeted games, additional tweets are sent if a perfect game is downgraded to a no-hitter, if the starting pitcher is replaced (making it a combined no-hitter), if a no-hitter is broken up, and if a no-hitter is completed.

## How to Run
Run the bot with `python3 nohittertracker/main.py`

Use crontab to run the bot on a schedule. Ex: `*/3 10-23,0-3 * 3-10 * python3 nohittertracker/main.py` will check for no-hitters every 3 minutes between 10:00 AM and 3:59 AM from March through October.

## Dependencies
NoHitterTracker requires the following modules:
- dotenv
- requests
- tweepy

`pip3 install dotenv requests tweepy`

## .env
`.env.example` is a template file that must be replaced with `.env` and filled in with details for the bot's Twitter account. To get this info, a new application must be created in [Twitter's Developer Portal](https://developer.twitter.com/en/portal/projects-and-apps) while logged into the bot account.

`TWITTER_CONSUMER_KEY` and `TWITTER_CONSUMER_SECRET` correspond to the API Key and Secret under the Consumer Keys section of your Twitter application.

`TWITTER_ACCESS_TOKEN` and `TWITTER_ACCESS_TOKEN_SECRET` correspond to the Access Token and Secret under the Authentication Tokens section of your Twitter application. The access token must be created with read+write permissions.

## config.json
`config.json.example` is a template file that must be replaced with `config.json`.

- `num_innings_to_alert` - decimal
  - Number of no-hit innings that must be pitched by a team before sending a tweet.
  - This should be in "baseball" format, ex: 6.0 for 6 full innings pitched, 6.1 for 6 innings + 1 out, 6.2 for 6 innings + 2 outs.
- `debug_mode` - boolean
  - Flag for running in debug mode. If set to true, the script will run but no tweets will be sent.
- `ntfy_alert` - boolean
  - Will be deleted.
- `ntfy_settings`
  - `enabled` - boolean
    - Flag for sending Ntfy push notifications. If set to true, notifications will be sent.
  - `topic` - string
    - Topic to use when sending Ntfy push notifications. Ex: `"topic": "arodsg-nohittertracker"`
  - `title` - string
    - Title to use when sending Ntfy push notifications. Ex: `"title": "NoHitterTracker"`
- `last_game_date` - string
  - Used to determine if the next day's games should be retrieved. The script compares this value to the current date every time the script runs, and updates this value to the current date after checking for no-hitters.
  - Ex: `"last_game_date": "09/09/2024"`
- `team_hashtags`
  - Hastags to use in tweets for each team when involved in a no-hitter.
  - Ex: `"CWS": "WhiteSox"`
