from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
from threading import Lock
import time
from typing import Any

from . import constants, util
from .game_details import GameDetails

from .formatter import TweetFormatter
from .models import (
    BattingStats,
    Boxscore,
    BoxscoreTeam,
    BoxscoreTeams,
    FieldingStats,
    GameData,
    GameDatetime,
    GameFeedApiError,
    GameFlags,
    GamePayload,
    GameStatus,
    GameTeams,
    InningHalf,
    InningLine,
    LineScore,
    LiveData,
    PitchingLine,
    PitchingStats,
    Play,
    PlayAbout,
    Plays,
    PlayResult,
    Runner,
    RunnerMovement,
    Team,
    TeamStats,
    TrackerEvent,
    TeamSnapshot,
)


def get_game_info_by_date(date: str) -> dict[int, dict[str, Any]]:
    games: dict[int, dict[str, Any]] = {}
    params = {'sportId': 1, 'date': date}
    request_endpoint = 'https://statsapi.mlb.com/api/v1/schedule/games/'
    util.logger.info(f'Getting game info for {date}...', extra={'url': request_endpoint, 'params': params})

    try:
        response = util.make_request(request_endpoint, params)
        if response.status_code == 200 and response.json()['dates']:
            games_json = response.json()['dates'][0]['games']
            for game_json in games_json:
                game_pk = game_json['gamePk']
                games[game_pk] = {
                    'status': GameDetails.get_game_status(game_json['status']),
                    'status_detailed': game_json['status']['detailedState'],
                    'start_time': game_json.get('gameDate'),
                    'home_team_id': game_json['teams']['home']['team']['id'],
                    'away_team_id': game_json['teams']['away']['team']['id'],
                    'home_team_name': game_json['teams']['home']['team']['name'],
                    'away_team_name': game_json['teams']['away']['team']['name'],
                }
    except Exception as exc:
        util.arodsg_ntfy(str(exc))

    return games


class NoHitterTracker:
    def __init__(self, *, config_path: str = constants.CONFIG_FILE_PATH):
        self.config_path = config_path
        self._initialize_lock = Lock()
        self._schedule_cache_lock = Lock()
        self._game_feed_cache_lock = Lock()
        self._config_loaded = False
        self._session_ready = False
        self._session_pool_size = 0
        self._schedule_cache: dict[str, tuple[float, dict[int, dict[str, Any]]]] = {}
        self._game_feed_cache: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}
        self.formatter: TweetFormatter | None = None

    def _set_session_pool_size(self, pool_size: int) -> None:
        adapter = util.HTTPAdapter(
            max_retries=util.Retry(total=5, backoff_factor=1),
            pool_connections=pool_size,
            pool_maxsize=pool_size,
            pool_block=True,
        )
        util.session.mount('https://', adapter)
        self._session_pool_size = pool_size

    def _ensure_session_pool_size(self, pool_size: int) -> None:
        with self._initialize_lock:
            if self._session_pool_size != pool_size:
                self._set_session_pool_size(pool_size)

    def _start_cache_pruner(self) -> None:
        """Start a background daemon thread that prunes expired cache entries every 60 seconds."""
        def _prune_loop() -> None:
            while True:
                time.sleep(60)
                now = time.monotonic()
                with self._game_feed_cache_lock:
                    self._prune_expired_cache_entries(self._game_feed_cache, now)
                with self._schedule_cache_lock:
                    self._prune_expired_cache_entries(self._schedule_cache, now)
        t = threading.Thread(target=_prune_loop, daemon=True, name='cache-pruner')
        t.start()

    def initialize(self) -> None:
        with self._initialize_lock:
            if not self._config_loaded:
                util.load_config(self.config_path)
                self.formatter = TweetFormatter(util.config)
                self._config_loaded = True
            if not self._session_ready:
                util.create_session()
                self._set_session_pool_size(1)
                self._session_ready = True
                self._start_cache_pruner()

    def default_game_date(self) -> str:
        return (datetime.now() - timedelta(hours=10)).strftime('%m/%d/%Y')

    @staticmethod
    def _parse_mlb_datetime(date_time_str: str | None) -> datetime | None:
        if not date_time_str:
            return None

        normalized = date_time_str.replace('Z', '+00:00')
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    def _team_should_be_checked(self, status: str) -> bool:
        return status in {'I', 'F'}

    @staticmethod
    def _is_live_or_final(game_status: str) -> bool:
        return game_status in {'I', 'F'}

    def _team_no_hitter_status(self, team_boxscore: dict[str, Any], game_status: str) -> str:
        if not self._is_live_or_final(game_status):
            return 'none'

        team_stats = team_boxscore.get('teamStats', {}).get('pitching', {})
        num_hits = team_stats.get('hits', 0)
        num_pitchers = len(team_boxscore.get('pitchers', []))
        minimum_batters_faced = team_stats.get('outs', 0) == team_stats.get('battersFaced', 0)
        num_walks = team_stats.get('baseOnBalls', 0) + team_stats.get('intentionalWalks', 0)
        num_hit_by_pitch = team_stats.get('hitByPitch', 0)

        if num_hits == 0:
            no_hitter_string = 'combined no-hitter' if num_pitchers > 1 else 'no-hitter'
            perfect_game_string = 'combined perfect game' if num_pitchers > 1 else 'perfect game'
            return perfect_game_string if minimum_batters_faced and num_walks + num_hit_by_pitch == 0 else no_hitter_string

        return 'none'

    @staticmethod
    def _game_flags(home_status: str, away_status: str) -> dict[str, bool]:
        home_no_hitter = home_status in {'no-hitter', 'combined no-hitter', 'perfect game', 'combined perfect game'}
        away_no_hitter = away_status in {'no-hitter', 'combined no-hitter', 'perfect game', 'combined perfect game'}
        home_perfect_game = home_status in {'perfect game', 'combined perfect game'}
        away_perfect_game = away_status in {'perfect game', 'combined perfect game'}
        return {
            'noHitter': home_no_hitter or away_no_hitter,
            'perfectGame': home_perfect_game or away_perfect_game,
            'homeTeamNoHitter': home_no_hitter,
            'homeTeamPerfectGame': home_perfect_game,
            'awayTeamNoHitter': away_no_hitter,
            'awayTeamPerfectGame': away_perfect_game,
        }

    def _fetch_game_feed_response(self, game_id: int) -> dict[str, Any]:
        request_endpoint = f'https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live'
        response = util.make_request(request_endpoint)
        if response.status_code != 200:
            raise RuntimeError(f'Failed to fetch game feed: {response.status_code}')
        return response.json()

    def _game_feed_payload(
        self,
        game_id: int,
        game_status: str,
        *,
        include_all_plays: bool,
        response_json: dict[str, Any],
        schedule_status_detailed: str | None = None,
    ) -> dict[str, Any]:
        game_data = response_json.get('gameData', {})
        live_data = response_json.get('liveData', {})
        linescore = live_data.get('linescore', {})
        boxscore = live_data.get('boxscore', {})
        plays = live_data.get('plays', {})
        current_play = plays.get('currentPlay', {})
        current_play_matchup = current_play.get('matchup', {})

        teams = game_data.get('teams', {})
        home_team = teams.get('home', {})
        away_team = teams.get('away', {})

        boxscore_teams = boxscore.get('teams', {})
        home_boxscore = boxscore_teams.get('home', {})
        away_boxscore = boxscore_teams.get('away', {})

        home_status = self._team_no_hitter_status(home_boxscore, game_status)
        away_status = self._team_no_hitter_status(away_boxscore, game_status)
        flags = self._game_flags(home_status, away_status)

        status = game_data.get('status', {})
        datetime_info = game_data.get('datetime', {})

        def status_payload(status_data: dict[str, Any]) -> GameStatus:
            if game_status in GameDetails._SPECIAL_STATUSES:
                return GameStatus(
                    abstractGameCode=status_data.get('abstractGameCode'),
                    codedGameState=status_data.get('codedGameState'),
                    statusCode=game_status,
                    detailedState=schedule_status_detailed or status_data.get('detailedState'),
                )
            return GameStatus(
                abstractGameCode=status_data.get('abstractGameCode'),
                codedGameState=status_data.get('codedGameState'),
                statusCode=status_data.get('statusCode'),
                detailedState=status_data.get('detailedState'),
            )

        def datetime_payload(datetime_data: dict[str, Any]) -> GameDatetime:
            return GameDatetime(dateTime=datetime_data.get('dateTime'))

        def team_payload(team_data: dict[str, Any]) -> Team:
            return Team(
                id=team_data.get('id'),
                name=team_data.get('name'),
                abbreviation=team_data.get('abbreviation'),
            )

        def _player_from_boxscore(player_id: int | None) -> dict[str, Any]:
            if player_id is None:
                return {}

            player_key = f'ID{player_id}'
            home_player = home_boxscore.get('players', {}).get(player_key, {})
            if home_player:
                return home_player

            away_player = away_boxscore.get('players', {}).get(player_key, {})
            if away_player:
                return away_player

            return {}

        def _batter_stats_payload(player_data: dict[str, Any]) -> dict[str, Any]:
            batting_stats = player_data.get('stats', {}).get('batting', {})
            season_batting_stats = player_data.get('seasonStats', {}).get('batting', {})

            return {
                'hits': batting_stats.get('hits'),
                'atBats': batting_stats.get('atBats'),
                'avg': season_batting_stats.get('avg', batting_stats.get('avg')),
                'obp': season_batting_stats.get('obp', batting_stats.get('obp')),
                'slg': season_batting_stats.get('slg', batting_stats.get('slg')),
            }

        def linescore_offense_payload(offense_data: dict[str, Any], current_matchup: dict[str, Any]) -> dict[str, Any]:
            payload: dict[str, Any] = {}
            for base in ('first', 'second', 'third'):
                if base in offense_data:
                    payload[base] = {}

            offense_team = offense_data.get('team', {})
            matchup_batter = current_matchup.get('batter', {})

            if offense_team.get('id') is not None:
                payload['team'] = {
                    'id': offense_team.get('id'),
                }

            batter_source = offense_data.get('batter', {}) if isinstance(offense_data.get('batter', {}), dict) else {}
            if not batter_source:
                batter_source = matchup_batter if isinstance(matchup_batter, dict) else {}

            batter_player_id = batter_source.get('id')
            batter_player = _player_from_boxscore(batter_player_id)

            if batter_source.get('id') is not None or batter_source.get('fullName'):
                payload['batter'] = {
                    'id': batter_source.get('id'),
                    'fullName': batter_source.get('fullName'),
                    'stats': _batter_stats_payload(batter_player),
                }

            return payload

        def linescore_defense_payload(defense_data: dict[str, Any], current_matchup: dict[str, Any]) -> dict[str, Any]:
            payload: dict[str, Any] = {}

            defense_team = defense_data.get('team', {})
            matchup_pitcher = current_matchup.get('pitcher', {})

            if defense_team.get('id') is not None:
                payload['team'] = {
                    'id': defense_team.get('id'),
                }

            pitcher_source = defense_data.get('pitcher', {}) if isinstance(defense_data.get('pitcher', {}), dict) else {}
            if not pitcher_source:
                pitcher_source = matchup_pitcher if isinstance(matchup_pitcher, dict) else {}

            if pitcher_source.get('id') is not None or pitcher_source.get('fullName'):
                payload['pitcher'] = {
                    'id': pitcher_source.get('id'),
                    'fullName': pitcher_source.get('fullName'),
                }

            return payload

        def inning_half_payload(inning_half_data: dict[str, Any]) -> InningHalf:
            return InningHalf(
                runs=inning_half_data.get('runs'),
                hits=inning_half_data.get('hits'),
                errors=inning_half_data.get('errors'),
            )

        def inning_payload(inning_data: dict[str, Any]) -> InningLine:
            return InningLine(
                num=inning_data.get('num'),
                home=inning_half_payload(inning_data.get('home', {})) if 'home' in inning_data else None,
                away=inning_half_payload(inning_data.get('away', {})) if 'away' in inning_data else None,
            )

        def pitching_stats_payload(team_stats_data: dict[str, Any]) -> PitchingStats:
            pitching_data = team_stats_data.get('pitching', {})
            return PitchingStats(
                hits=pitching_data.get('hits', 0),
                outs=pitching_data.get('outs', 0),
                battersFaced=pitching_data.get('battersFaced', 0),
                baseOnBalls=pitching_data.get('baseOnBalls', 0),
                intentionalWalks=pitching_data.get('intentionalWalks', 0),
                hitByPitch=pitching_data.get('hitByPitch', 0),
            )

        def batting_stats_payload(team_stats_data: dict[str, Any]) -> BattingStats:
            batting_data = team_stats_data.get('batting', {})
            return BattingStats(
                runs=batting_data.get('runs', 0),
                hits=batting_data.get('hits', 0),
                baseOnBalls=batting_data.get('baseOnBalls', 0),
                hitByPitch=batting_data.get('hitByPitch', 0),
            )

        def fielding_stats_payload(team_stats_data: dict[str, Any]) -> FieldingStats:
            fielding_data = team_stats_data.get('fielding', {})
            return FieldingStats(errors=fielding_data.get('errors', 0))

        def ui_pitcher_stats_with_innings(pitching_stats: dict[str, Any]) -> str:
            # UI-only format requested by user: IP, H, R, BB, HBP, K, PC
            return (
                f"{pitching_stats.get('inningsPitched', '0.0')} IP, "
                f"{pitching_stats.get('hits', 0)} H, "
                f"{pitching_stats.get('runs', 0)} R, "
                f"{pitching_stats.get('baseOnBalls', 0)} BB, "
                f"{pitching_stats.get('hitByPitch', 0)} HBP, "
                f"{pitching_stats.get('strikeOuts', 0)} K, "
                f"{pitching_stats.get('pitchesThrown', 0)} PC"
            )

        def team_boxscore_payload(team_boxscore: dict[str, Any]) -> BoxscoreTeam:
            team_stats = team_boxscore.get('teamStats', {})
            pitchers = team_boxscore.get('pitchers', [])
            current_pitcher_name = ''
            current_pitcher_stats = '0.0 IP, 0 H, 0 R, 0 BB, 0 HBP, 0 K, 0 PC'
            pitcher_lines: list[dict[str, Any]] = []
            for pitcher_id in pitchers:
                pitcher = team_boxscore.get('players', {}).get(f'ID{pitcher_id}', {})
                pitcher_name = pitcher.get('person', {}).get('fullName', '')
                pitching_stats = pitcher.get('stats', {}).get('pitching', {})
                num_hit_by_pitch = pitching_stats.get('hitByPitch', 0)
                stat_line = ui_pitcher_stats_with_innings(pitching_stats)
                pitcher_lines.append(PitchingLine(
                    player_id=pitcher_id,
                    full_name=pitcher_name,
                    last_name=pitcher_name.split(' ')[-1] if pitcher_name else '',
                    innings_pitched=pitching_stats.get('inningsPitched', '0.0'),
                    strikeouts=pitching_stats.get('strikeOuts', 0),
                    walks=pitching_stats.get('baseOnBalls', 0),
                    intentional_walks=pitching_stats.get('intentionalWalks', 0),
                    hit_by_pitch=num_hit_by_pitch,
                    runs=pitching_stats.get('runs', 0),
                    pitches_thrown=pitching_stats.get('pitchesThrown', 0),
                    stat_line=stat_line,
                    final_line=stat_line,
                ).to_dict())
            if pitchers:
                current_pitcher_id = pitchers[-1]
                current_pitcher = team_boxscore.get('players', {}).get(f'ID{current_pitcher_id}', {})
                current_pitcher_name = current_pitcher.get('person', {}).get('fullName', '')
                pitching_stats = current_pitcher.get('stats', {}).get('pitching', {})
                current_pitcher_stats = ui_pitcher_stats_with_innings(pitching_stats)
            return BoxscoreTeam(
                pitchers=pitchers,
                pitcherName=current_pitcher_name,
                pitcherStats=current_pitcher_stats,
                pitcherLines=pitcher_lines,
                teamStats=TeamStats(
                    batting=batting_stats_payload(team_stats),
                    fielding=fielding_stats_payload(team_stats),
                    pitching=pitching_stats_payload(team_stats),
                ),
            )

        def play_payload(play_data: dict[str, Any]) -> Play:
            play_result = play_data.get('result', {})
            play_about = play_data.get('about', {})
            play_runners = play_data.get('runners', [])
            return Play(
                result=PlayResult(
                    type=play_result.get('type'),
                    eventType=play_result.get('eventType'),
                    description=play_result.get('description'),
                ),
                about=PlayAbout(isTopInning=play_about.get('isTopInning')),
                runners=[
                    Runner(
                        movement=RunnerMovement(
                            start=runner.get('movement', {}).get('start'),
                            end=runner.get('movement', {}).get('end'),
                        )
                    )
                    for runner in play_runners
                ],
            )

        game_payload = GamePayload(
            gamePk=game_id,
            gameData=GameData(
                status=status_payload(status),
                datetime=datetime_payload(datetime_info),
                teams=GameTeams(home=team_payload(home_team), away=team_payload(away_team)),
                flags=GameFlags(
                    noHitter=flags['noHitter'],
                    perfectGame=flags['perfectGame'],
                    homeTeamNoHitter=flags['homeTeamNoHitter'],
                    homeTeamPerfectGame=flags['homeTeamPerfectGame'],
                    awayTeamNoHitter=flags['awayTeamNoHitter'],
                    awayTeamPerfectGame=flags['awayTeamPerfectGame'],
                    homeTeamNoHitterStatus=home_status,
                    awayTeamNoHitterStatus=away_status,
                ),
            ),
            liveData=LiveData(
                linescore=LineScore(
                    currentInning=linescore.get('currentInning'),
                    isTopInning=linescore.get('isTopInning'),
                    innings=[inning_payload(inning) for inning in linescore.get('innings', [])],
                    scheduledInnings=linescore.get('scheduledInnings'),
                    balls=linescore.get('balls'),
                    strikes=linescore.get('strikes'),
                    outs=linescore.get('outs'),
                    offense=linescore_offense_payload(linescore.get('offense', {}), current_play_matchup),
                    defense=linescore_defense_payload(linescore.get('defense', {}), current_play_matchup),
                ),
                boxscore=Boxscore(
                    teams=BoxscoreTeams(
                        home=team_boxscore_payload(home_boxscore),
                        away=team_boxscore_payload(away_boxscore),
                    )
                ),
                plays=Plays(
                    allPlays=[play_payload(play) for play in plays.get('allPlays', [])] if include_all_plays else []
                ),
            ),
        )

        return game_payload.to_dict()

    def _pitching_totals(self, game_details, team_id: int) -> dict[str, Any]:
        stats = game_details.get_team_pitching_stats(team_id)
        return {
            'innings_pitched': float(stats['inningsPitched']),
            'hits': stats['hits'],
            'runs': stats['runs'],
            'earned_runs': stats['earnedRuns'],
            'strikeouts': stats['strikeOuts'],
            'walks': stats['baseOnBalls'],
            'intentional_walks': stats['intentionalWalks'],
            'hit_by_pitch': stats['hitByPitch'],
            'home_runs': stats['homeRuns'],
            'batters_faced': stats['battersFaced'],
            'outs': stats['outs'],
        }

    def _build_snapshot(self, game_details, team_id: int, game_status_detailed: str) -> dict[str, Any]:
        assert self.formatter is not None
        try:
            game_details.set_broken_details()
        except KeyError:
            pass

        is_no_hitter = game_details.is_no_hitter(team_id)
        is_perfect_game = game_details.is_perfect_game(team_id) if is_no_hitter else False
        is_combined = game_details.is_combined(team_id)
        team_boxscore = game_details.get_team_boxscore(team_id)
        pitcher_lines = [line.to_dict() for line in self.formatter.build_team_pitching_lines(game_details, team_id)]
        starting_pitcher_name = game_details.get_starting_pitcher_name(team_id) if team_boxscore['pitchers'] else None
        replacing_pitcher_name = game_details.get_replacing_pitcher_name(team_id) if len(team_boxscore['pitchers']) > 1 else None
        starting_pitcher_line = pitcher_lines[0] if pitcher_lines else None
        downgrade_play = self.formatter.play_snapshot(game_details.get_downgrade_play_details(team_id))
        broken_play = self.formatter.play_snapshot(game_details.get_broken_play_details(team_id))
        innings_pitched = game_details.get_innings_pitched(team_id)
        snapshot = TeamSnapshot(
            game_id=game_details.game_id,
            game_status=game_details.game_status,
            game_status_detailed=game_status_detailed,
            is_in_progress=game_details.game_status == 'I',
            is_final=game_details.is_final(),
            is_home_team=team_id == game_details.home_team_id,
            team_id=team_id,
            team_name=game_details.get_team_name(team_id),
            team_abbrv=game_details.get_team_abbrv(team_id),
            opposing_team=game_details.get_opposing_team(team_id),
            opposing_team_id=game_details.away_team_id if team_id == game_details.home_team_id else game_details.home_team_id,
            home_team_id=game_details.home_team_id,
            home_team_name=game_details.home_team_name,
            home_team_abbrv=game_details.home_team_abbrv,
            away_team_id=game_details.away_team_id,
            away_team_name=game_details.away_team_name,
            away_team_abbrv=game_details.away_team_abbrv,
            home_team_hashtag=self.formatter.get_team_hashtag(game_details.home_team_abbrv),
            away_team_hashtag=self.formatter.get_team_hashtag(game_details.away_team_abbrv),
            innings_pitched=innings_pitched,
            alert_threshold=util.config['num_innings_to_alert'],
            alert_eligible=innings_pitched >= util.config['num_innings_to_alert'],
            is_no_hitter=is_no_hitter,
            is_perfect_game=is_perfect_game,
            is_combined=is_combined,
            status_label='perfect_game' if is_perfect_game else ('no_hitter' if is_no_hitter else 'none'),
            starting_pitcher_name=starting_pitcher_name,
            replacing_pitcher_name=replacing_pitcher_name,
            starting_pitcher_line=starting_pitcher_line,
            pitching_team_totals=self._pitching_totals(game_details, team_id),
            pitcher_lines=pitcher_lines,
            downgrade_play=downgrade_play.to_dict() if downgrade_play is not None else None,
            broken_play=broken_play.to_dict() if broken_play is not None else None,
            tweet_variants=self.formatter.build_tweet_variants(game_details, team_id).to_dict(),
        )
        return snapshot.to_dict()

    def _event(self, event_type: str, game_details, team_id: int, message: str, is_finished: bool, snapshot: dict[str, Any]) -> TrackerEvent:
        assert self.formatter is not None
        return TrackerEvent(
            event_type=event_type,
            game_id=game_details.game_id,
            team_id=team_id,
            is_finished=is_finished,
            is_combined=game_details.is_combined(team_id),
            is_perfect_game=game_details.is_perfect_game(team_id) if snapshot['is_no_hitter'] else False,
            message=message,
            tweet_text=self.formatter.build_tweet(message, game_details),
            snapshot=snapshot,
        )

    def _inspect_team(
        self,
        game_details,
        team_id: int,
        game_status_detailed: str,
    ) -> tuple[dict[str, Any] | None, list[TrackerEvent]]:
        snapshot = self._build_snapshot(game_details, team_id, game_status_detailed)
        innings_pitched = snapshot['innings_pitched']
        alert_threshold = snapshot['alert_threshold']

        active_snapshot = snapshot if snapshot['is_in_progress'] and snapshot['is_no_hitter'] else None

        if innings_pitched < alert_threshold:
            return active_snapshot, []

        try:
            if snapshot['is_no_hitter']:
                is_final = snapshot['is_final']
                downgrade_play = snapshot.get('downgrade_play')
                is_perfect_game = snapshot['is_perfect_game']
                is_combined = snapshot['is_combined']
                starter_ip = float((snapshot.get('starting_pitcher_line') or {}).get('innings_pitched', 0))
                is_pitching_change = is_combined and snapshot.get('replacing_pitcher_name') is not None and starter_ip >= alert_threshold

                if downgrade_play is not None and not is_perfect_game:
                    if downgrade_play.get('completed_innings', 0) >= alert_threshold:
                        message = self.formatter.build_downgrade_message(game_details, team_id)
                        if message is not None:
                            return active_snapshot, [self._event('perfect_game_downgrade', game_details, team_id, message, False, snapshot)]
                if is_pitching_change:
                    message = self.formatter.build_pitching_change_message(game_details, team_id)
                    if message is not None:
                        return active_snapshot, [self._event('pitching_change', game_details, team_id, message, False, snapshot)]

                message = self.formatter.build_no_hitter_message(game_details, team_id, is_final=is_final, innings_pitched=None if is_final else alert_threshold)
                return active_snapshot, [self._event('no_hitter_update', game_details, team_id, message, is_final, snapshot)]
            broken_play = snapshot.get('broken_play')
            if broken_play is not None and broken_play.get('completed_innings', 0) >= alert_threshold:
                broken_message = self.formatter.build_broken_message(game_details, team_id)
                if broken_message is not None:
                    update_message = self.formatter.build_no_hitter_message(game_details, team_id, is_final=False, innings_pitched=alert_threshold)
                    return None, [
                        self._event('no_hitter_update', game_details, team_id, update_message, False, snapshot),
                        self._event('no_hitter_broken', game_details, team_id, broken_message, True, snapshot),
                    ]
        except KeyError:
            return active_snapshot, []

        return active_snapshot, []

    @staticmethod
    def _pool_size_for_num_games(num_games: int) -> int:
        return max(1, num_games)

    @staticmethod
    def _prune_expired_cache_entries(cache: dict[Any, tuple[float, Any]], now: float) -> None:
        expired_keys = [cache_key for cache_key, (expires_at, _) in cache.items() if expires_at <= now]
        for cache_key in expired_keys:
            del cache[cache_key]

    def _game_feed_cache_ttl_seconds(self, game_status: str, game_start_time: str | None) -> float:
        if game_status in {'F'} | GameDetails._SPECIAL_STATUSES:
            return constants.GAME_FEED_FINAL_CACHE_TTL_SECONDS

        if game_status in {'S', 'P'}:
            if game_status == 'P':
                return constants.GAME_FEED_NEAR_START_CACHE_TTL_SECONDS

            start_time = self._parse_mlb_datetime(game_start_time)
            if start_time is None:
                return constants.GAME_FEED_SCHEDULED_CACHE_TTL_SECONDS

            seconds_until_first_pitch = (start_time - datetime.now(timezone.utc)).total_seconds()
            if seconds_until_first_pitch <= constants.GAME_FEED_NEAR_START_WINDOW_SECONDS:
                return constants.GAME_FEED_NEAR_START_CACHE_TTL_SECONDS

            return constants.GAME_FEED_SCHEDULED_CACHE_TTL_SECONDS

        return 0.0

    def _get_game_feed_response_cached(
        self,
        game_id: int,
        game_status: str,
        *,
        game_start_time: str | None,
    ) -> dict[str, Any]:
        ttl_seconds = self._game_feed_cache_ttl_seconds(game_status, game_start_time)
        if ttl_seconds <= 0:
            return self._fetch_game_feed_response(game_id)

        cache_key = (game_id, game_status)
        now = time.monotonic()

        with self._game_feed_cache_lock:
            self._prune_expired_cache_entries(self._game_feed_cache, now)
            cached = self._game_feed_cache.get(cache_key)
            if cached is not None:
                expires_at, cached_payload = cached
                if now < expires_at:
                    return cached_payload

        payload = self._fetch_game_feed_response(game_id)

        # If the schedule says the game is Final but the live feed hasn't caught
        # up yet (MLB API lag), don't cache with the long Final TTL — use a short
        # TTL so we re-fetch shortly and get the correct Final state.
        effective_ttl = ttl_seconds
        if game_status == 'F':
            feed_abstract_code = payload.get('gameData', {}).get('status', {}).get('abstractGameCode', 'F')
            if feed_abstract_code != 'F':
                effective_ttl = constants.GAME_FEED_NEAR_START_CACHE_TTL_SECONDS

        with self._game_feed_cache_lock:
            self._game_feed_cache[cache_key] = (now + effective_ttl, payload)

        return payload

    def _get_game_info_by_date_cached(self, game_date: str) -> dict[int, dict[str, Any]]:
        ttl_seconds = constants.SCHEDULE_CACHE_TTL_SECONDS
        now = time.monotonic()

        with self._schedule_cache_lock:
            self._prune_expired_cache_entries(self._schedule_cache, now)
            cached = self._schedule_cache.get(game_date)
            if cached is not None:
                expires_at, cached_payload = cached
                if now < expires_at:
                    return cached_payload

        game_info = get_game_info_by_date(game_date)

        with self._schedule_cache_lock:
            self._schedule_cache[game_date] = (now + ttl_seconds, game_info)

        return game_info

    @staticmethod
    def _max_workers(num_games: int, pool_size: int) -> int:
        return max(1, min(pool_size, num_games))

    @staticmethod
    def _game_start_sort_key(game: dict[str, Any]) -> str:
        return str(game.get('gameData', {}).get('datetime', {}).get('dateTime') or '9999-12-31T23:59:59Z')

    def _sort_games_by_start_time(self, games: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(games, key=self._game_start_sort_key)

    @staticmethod
    def _event_lifecycle_status(event_type: str) -> str:
        if event_type == 'perfect_game_downgrade':
            return 'downgraded'
        if event_type == 'no_hitter_broken':
            return 'broken'
        return 'active'

    @staticmethod
    def _snapshot_key(snapshot: dict[str, Any]) -> str:
        return f"{snapshot['game_id']}:{snapshot['team_id']}"

    @staticmethod
    def _snapshot_id(snapshot: dict[str, Any]) -> str:
        version = int(round(float(snapshot.get('innings_pitched', 0)) * 10))
        return f"{snapshot['game_id']}:{snapshot['team_id']}:{version}"

    def _normalize_response(
        self,
        *,
        game_date: str,
        generated_at: str,
        game_info: dict[int, dict[str, Any]],
        games: list[dict[str, Any]],
        active_no_hitters: list[dict[str, Any]],
        events: list[dict[str, Any]],
        failed_game_pks: list[int],
        include_event_snapshot: bool,
        include_legacy: bool,
    ) -> dict[str, Any]:
        ordered_games = self._sort_games_by_start_time(games)
        games_by_id: dict[str, dict[str, Any]] = {}
        game_ids_in_order: list[str] = []
        for game in ordered_games:
            game_pk = game.get('gamePk')
            if game_pk is not None:
                game_id = str(game_pk)
                games_by_id[game_id] = game
                game_ids_in_order.append(game_id)

        active_no_hitters_by_key: dict[str, dict[str, Any]] = {}
        legacy_refs: list[dict[str, Any]] = []
        for snapshot in active_no_hitters:
            key = self._snapshot_key(snapshot)
            snapshot_id = self._snapshot_id(snapshot)
            normalized_snapshot = dict(snapshot)
            normalized_snapshot['snapshot_id'] = snapshot_id
            normalized_snapshot['snapshot_version'] = int(snapshot_id.split(':')[-1])
            normalized_snapshot['lifecycle_status'] = 'active'
            active_no_hitters_by_key[key] = normalized_snapshot
            legacy_refs.append(
                {
                    'game_id': snapshot['game_id'],
                    'team_id': snapshot['team_id'],
                    'snapshot_ref': {
                        'key': key,
                        'snapshot_id': snapshot_id,
                        'snapshot_version': normalized_snapshot['snapshot_version'],
                    },
                }
            )

        activity_events: list[dict[str, Any]] = []
        for i, event in enumerate(events, 1):
            snapshot = event.get('snapshot', {})
            key = self._snapshot_key(snapshot)
            snapshot_id = self._snapshot_id(snapshot)
            snapshot_version = int(snapshot_id.split(':')[-1])
            alert_threshold = float(snapshot.get('alert_threshold', 0))
            event_type = event['event_type']
            broken_play = snapshot.get('broken_play') if event_type == 'no_hitter_broken' else None
            downgrade_play = snapshot.get('downgrade_play') if event_type == 'perfect_game_downgrade' else None
            play = broken_play if broken_play is not None else downgrade_play
            play_alert_eligible = bool(play and play.get('completed_innings', 0) >= alert_threshold)
            if event_type == 'no_hitter_update':
                event_id = f"evt_{event['game_id']}_{event['team_id']}_no_hitter_update_{'final' if event['is_finished'] else 'active'}"
            elif event_type in ('no_hitter_broken', 'perfect_game_downgrade', 'pitching_change'):
                event_id = f"evt_{event['game_id']}_{event['team_id']}_{event_type}"
            else:
                event_id = f"evt_{event['game_id']}_{event['team_id']}_{generated_at.replace(':', '').replace('-', '')}_{i:02d}"
            normalized_event = {
                'event_id': event_id,
                'event_ts': generated_at,
                'event_type': event_type,
                'game_id': event['game_id'],
                'team_id': event['team_id'],
                'lifecycle_status': self._event_lifecycle_status(event_type),
                'is_finished': event['is_finished'],
                'is_combined': event['is_combined'],
                'is_perfect_game': event['is_perfect_game'],
                'innings_pitched': snapshot.get('innings_pitched', 0),
                'alert_threshold': alert_threshold,
                'alert_eligible': snapshot.get('alert_eligible', False),
                'play_alert_eligible': play_alert_eligible,
                'broken_play': broken_play,
                'downgrade_play': downgrade_play,
                'message': event['message'],
                'tweet_text': event['tweet_text'],
                'snapshot_ref': {
                    'key': key,
                    'snapshot_id': snapshot_id,
                    'snapshot_version': snapshot_version,
                },
            }
            if include_event_snapshot:
                normalized_event['snapshot'] = snapshot
            activity_events.append(normalized_event)

        response: dict[str, Any] = {
            'response_version': '2.1',
            'meta': {
                'date': game_date,
                'generated_at': generated_at,
                'num_games': len(game_info),
                'num_in_progress_no_hitters': len(active_no_hitters),
                'failed_game_pks': failed_game_pks,
            },
            'entities': {
                'games_by_id': games_by_id,
                'game_ids_in_order': game_ids_in_order,
                'active_no_hitters_by_key': active_no_hitters_by_key,
            },
            'activity': {
                'events': activity_events,
            },
            'options': {
                'include_event_snapshot': include_event_snapshot,
            },
        }

        if include_legacy:
            response.update(
                {
                    'date': game_date,
                    'generated_at': generated_at,
                    'num_games': len(game_info),
                    'num_in_progress_no_hitters': len(active_no_hitters),
                    'in_progress_no_hitters': legacy_refs,
                    'events': [
                        {
                            'event_id': event['event_id'],
                            'event_type': event['event_type'],
                            'game_id': event['game_id'],
                            'team_id': event['team_id'],
                            'snapshot_ref': event['snapshot_ref'],
                        }
                        for event in activity_events
                    ],
                    'games': ordered_games,
                }
            )

        return response

    def _process_game(
        self,
        game_id: int,
        current_game_info: dict[str, Any],
        *,
        include_game_feed: bool,
        include_all_plays: bool,
    ) -> dict[str, Any]:
        game_status = current_game_info['status']
        game_payload: dict[str, Any] | None = None
        game_feed_response: dict[str, Any] | None = None

        check_home_team = self._team_should_be_checked(game_status)
        check_away_team = self._team_should_be_checked(game_status)

        if include_game_feed or check_home_team or check_away_team:
            try:
                game_feed_response = self._get_game_feed_response_cached(
                    game_id,
                    game_status,
                    game_start_time=current_game_info.get('start_time'),
                )
                if include_game_feed:
                    game_payload = self._game_feed_payload(
                        game_id,
                        game_status,
                        include_all_plays=include_all_plays,
                        response_json=game_feed_response,
                        schedule_status_detailed=current_game_info.get('status_detailed'),
                    )
            except Exception as exc:
                if include_game_feed:
                    game_payload = GameFeedApiError(gamePk=game_id, error=str(exc)).to_dict()
                game_feed_response = None

        util.logger.info(
            f"{game_id} - {current_game_info['home_team_name']} ({current_game_info['home_team_id']}) vs. {current_game_info['away_team_name']} ({current_game_info['away_team_id']}) - {current_game_info['status_detailed']}",
            extra={
                'check_home_team': check_home_team,
                'check_away_team': check_away_team,
            },
        )

        if not (check_home_team or check_away_team):
            return {
                'game_id': game_id,
                'game_payload': game_payload,
                'active_no_hitters': [],
                'events': [],
            }

        if game_feed_response is None:
            return {
                'game_id': game_id,
                'game_payload': game_payload,
                'active_no_hitters': [],
                'events': [],
            }

        active_no_hitters: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        game_details = GameDetails(game_id, response_json=game_feed_response)
        for team_id in (current_game_info['home_team_id'], current_game_info['away_team_id']):
            active_snapshot, team_events = self._inspect_team(game_details, team_id, current_game_info['status_detailed'])
            if active_snapshot is not None:
                active_no_hitters.append(active_snapshot)
            events.extend(e.to_dict() for e in team_events)

        return {
            'game_id': game_id,
            'game_payload': game_payload,
            'active_no_hitters': active_no_hitters,
            'events': events,
        }

    def scan(
        self,
        *,
        game_date: str | None = None,
        include_game_feed: bool = False,
        include_all_plays: bool = False,
        include_event_snapshot: bool = False,
        include_legacy: bool = True,
    ) -> dict[str, Any]:
        self.initialize()
        game_date = game_date or self.default_game_date()
        game_info = self._get_game_info_by_date_cached(game_date)
        pool_size = self._pool_size_for_num_games(len(game_info))
        self._ensure_session_pool_size(pool_size)
        active_no_hitters: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        games: list[dict[str, Any]] = []
        failed_game_pks: list[int] = []

        game_ids = list(game_info.keys())
        game_results: dict[int, dict[str, Any]] = {}

        if game_ids:
            max_workers = self._max_workers(len(game_ids), pool_size)
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='nohitter-tracker') as executor:
                futures = {
                    game_id: executor.submit(
                        self._process_game,
                        game_id,
                        game_info[game_id],
                        include_game_feed=include_game_feed,
                        include_all_plays=include_all_plays,
                    )
                    for game_id in game_ids
                }

                for game_id in game_ids:
                    try:
                        game_results[game_id] = futures[game_id].result()
                    except Exception as exc:
                        util.logger.error(f'Failed to process game {game_id}: {exc}')
                        failed_game_pks.append(game_id)
                        game_results[game_id] = {
                            'game_id': game_id,
                            'game_payload': GameFeedApiError(gamePk=game_id, error=str(exc)).to_dict() if include_game_feed else None,
                            'active_no_hitters': [],
                            'events': [],
                        }

        for game_id in game_ids:
            game_result = game_results[game_id]
            if include_game_feed and game_result['game_payload'] is not None:
                # Only include valid game payloads (exclude error objects)
                payload = game_result['game_payload']
                if 'error' not in payload:
                    games.append(payload)
            active_no_hitters.extend(game_result['active_no_hitters'])
            events.extend(game_result['events'])

        games = self._sort_games_by_start_time(games)
        generated_at = datetime.now(timezone.utc).isoformat()
        return self._normalize_response(
            game_date=game_date,
            generated_at=generated_at,
            game_info=game_info,
            games=games,
            active_no_hitters=active_no_hitters,
            events=events,
            failed_game_pks=failed_game_pks,
            include_event_snapshot=include_event_snapshot,
            include_legacy=include_legacy,
        )