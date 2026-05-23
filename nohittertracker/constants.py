import os


PACKAGE_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)
CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, 'config.json')

# --- Tuning ---
SCHEDULE_CACHE_TTL_SECONDS: float = 60.0
GAME_FEED_FINAL_CACHE_TTL_SECONDS: float = 300.0
GAME_FEED_SCHEDULED_CACHE_TTL_SECONDS: float = 3600.0
GAME_FEED_NEAR_START_CACHE_TTL_SECONDS: float = 60.0
GAME_FEED_NEAR_START_WINDOW_SECONDS: float = 1800.0
GAME_SOON_WINDOW_MINUTES: int = 5

PITCHER_STATS = '{num_strikeouts} K, {num_walks} BB, {num_runs} R, {num_pitches} PC'
PITCHER_STATS_HBP = '{num_strikeouts} K, {num_walks} BB, {num_hit_by_pitch} HBP, {num_runs} R, {num_pitches} PC'
PITCHER_STATS_INNINGS = '{num_innings} IP, {pitcher_stats}'

REG_CURRENT = '⚠️ {pitcher_name} ({team_abbrv}) currently has a {game_status} against the {opposing_team} through {innings_pitched} innings.\n\n{pitcher_stats_message}'
COMBINED_CURRENT = '⚠️ The {team_name} currently have a combined {game_status} against the {opposing_team} through {innings_pitched} innings.'

REG_DOWNGRADE = '🔽 {pitcher_name} ({team_abbrv}) no longer has a perfect game against the {opposing_team}. No-hitter is still active through {innings_pitched} innings.'
COMBINED_DOWNGRADE = '🔽 The {team_name} no longer have a combined perfect game against the {opposing_team}. Combined no-hitter is still active through {innings_pitched} innings.'

REG_TO_COMBINED = '🔀 {pitcher_name} ({team_abbrv}) has been replaced by {new_pitcher_name}. Combined {game_status} is still active through {innings_pitched} innings.\n\nFinal line for {pitcher_name}:\n{pitcher_stats_message}'

REG_BROKEN = '❌ {pitcher_name} ({team_abbrv}) no longer has a no-hitter against the {opposing_team}.\n\n{broken_by_message}'
COMBINED_BROKEN = '❌ The {team_name} no longer have a combined no-hitter against the {opposing_team}.\n\n{broken_by_message}'

BROKEN_BY = 'Broken up on a {play_event} by {batter_name} after {inning}.{outs} innings.'

REG_FINAL = '🎉 {pitcher_name} ({team_abbrv}) has thrown a {game_status} against the {opposing_team}!\n\n{pitcher_stats_message}'
COMBINED_FINAL = '🎉 The {team_name} have thrown a combined {game_status} against the {opposing_team}!\n\n{pitcher_stats_message}'
COMBINED_FINAL_PITCHER_STATS = '{pitcher_name}: ' + PITCHER_STATS_INNINGS

TWEET = '{message}\n\n#{home_team_hashtag} | #{away_team_hashtag}'
