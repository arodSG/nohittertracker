import requests

from . import util
from .play_details import PlayDetails


class GameDetails:
    game_id = 0
    game_status = ''
    player_info = {}

    home_team_id = 0
    home_team_name = ''
    home_team_abbrv = ''
    home_team_boxscore = {}
    home_pitching_details = {}

    away_team_id = 0
    away_team_name = ''
    away_team_abbrv = ''
    away_team_boxscore = {}
    away_pitching_details = {}

    all_plays = []
    home_pitcher_broken_play = None
    home_pitcher_downgrade_play = None
    away_pitcher_broken_play = None
    away_pitcher_downgrade_play = None

    def __init__(self, game_pk, response_json=None):
        self.game_id = game_pk
        if response_json is None:
            self.set_live_game_details()
        else:
            self.set_live_game_details(response_json=response_json)

    _SPECIAL_STATUSES = frozenset({'PPD', 'DR', 'DI', 'DO', 'DS', 'IR'})

    @classmethod
    def get_game_status(cls, status_obj):
        if status_obj.get('statusCode') in cls._SPECIAL_STATUSES:
            return status_obj['statusCode']
        game_code_live = status_obj['abstractGameCode'] == 'L'
        if game_code_live and status_obj['codedGameState'] == 'I':
            return 'I'
        elif game_code_live and status_obj['codedGameState'] == 'P':
            return 'P'
        return status_obj['abstractGameCode']

    def set_live_game_details(self, response_json=None):
        request_endpoint = 'https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live'.format(game_id=str(self.game_id))

        try:
            if response_json is None:
                response = util.make_request(request_endpoint)
                if response.status_code != 200:
                    return
                response_json = response.json()

            game_data = response_json['gameData']
            status = game_data['status']
            home_team_details = game_data['teams']['home']
            away_team_details = game_data['teams']['away']

            live_data = response_json['liveData']
            boxscore = live_data['boxscore']

            self.player_info = game_data['players']
            self.game_status = self.get_game_status(status)
            self.all_plays = live_data['plays']['allPlays']

            self.home_team_id = home_team_details['id']
            self.home_team_name = home_team_details['name']
            self.home_team_abbrv = home_team_details['abbreviation']
            self.home_team_boxscore = boxscore['teams']['home']
            self.away_team_boxscore = boxscore['teams']['away']
            self.home_pitching_details = self.home_team_boxscore['teamStats']['pitching']

            self.away_team_id = away_team_details['id']
            self.away_team_name = away_team_details['name']
            self.away_team_abbrv = away_team_details['abbreviation']
            self.away_pitching_details = self.away_team_boxscore['teamStats']['pitching']
        except (ConnectionError, KeyError, requests.exceptions.RequestException) as e:
            util.arodsg_ntfy(str(e))

    def set_broken_details(self):
        if self.home_pitcher_broken_play is None or self.away_pitcher_broken_play is None:
            for play_details in self.all_plays:
                play_info = play_details['about']
                play_complete = play_info['isComplete']
                play_result = play_details['result']

                if play_complete:
                    play_type = play_result['type']
                    play_event_type = play_result['eventType']
                    is_top_inning = play_info['isTopInning']
                    is_hit = play_type == 'atBat' and play_event_type in ['single', 'double', 'triple', 'home_run']
                    is_downgrade_play = False
                    play_runners = play_details['runners']

                    for runner in play_runners:
                        runner_start_base = runner['movement']['start']
                        runner_end_base = runner['movement']['end']
                        if runner_start_base is None and runner_end_base is not None:
                            is_downgrade_play = True
                            break

                    if is_top_inning:
                        if self.home_pitcher_broken_play is None and is_hit:
                            self.home_pitcher_broken_play = PlayDetails(play_details, self.home_team_boxscore['pitchers'][0])
                        if self.home_pitcher_downgrade_play is None and is_downgrade_play:
                            self.home_pitcher_downgrade_play = PlayDetails(play_details, self.home_team_boxscore['pitchers'][0])
                    else:
                        if self.away_pitcher_broken_play is None and is_hit:
                            self.away_pitcher_broken_play = PlayDetails(play_details, self.away_team_boxscore['pitchers'][0])
                        if self.away_pitcher_downgrade_play is None and is_downgrade_play:
                            self.away_pitcher_downgrade_play = PlayDetails(play_details, self.away_team_boxscore['pitchers'][0])

                    if self.home_pitcher_broken_play is not None and self.home_pitcher_downgrade_play is not None and self.away_pitcher_broken_play is not None and self.away_pitcher_downgrade_play is not None:
                        break

    def get_team_boxscore(self, team_id):
        return self.home_team_boxscore if team_id == self.home_team_id else self.away_team_boxscore

    def get_starting_pitcher_details(self, team_id):
        team_boxscore = self.get_team_boxscore(team_id)
        starting_pitcher_id = team_boxscore['pitchers'][0] if len(team_boxscore['pitchers']) > 0 else 0
        return team_boxscore['players']['ID{pitcher_id}'.format(pitcher_id=starting_pitcher_id)]['stats']['pitching']

    def get_starting_pitcher_stats_at_threshold(self, team_id: int, alert_threshold: float) -> dict | None:
        """Compute the starting pitcher's stats at exactly alert_threshold innings using play-by-play data.

        This avoids the mismatch where the bot polls slightly past the threshold and the boxscore
        stats reflect more innings than the pinned alert_threshold innings in the message text.

        Returns a dict with keys matching the boxscore pitching stats format:
            strikeOuts, baseOnBalls, intentionalWalks, hitByPitch, runs, pitchesThrown
        Returns None if the starting pitcher info is unavailable.
        """
        team_boxscore = self.get_team_boxscore(team_id)
        if not team_boxscore.get('pitchers'):
            return None

        starting_pitcher_id = team_boxscore['pitchers'][0]

        # Home team pitches in top half-innings (isTopInning=True); away team in bottom (False).
        is_pitching_top = team_id == self.home_team_id

        # Convert threshold to total outs already recorded at that point.
        # 6.0 innings = 18 outs, 6.1 = 19 outs, 6.2 = 20 outs.
        threshold_complete = int(alert_threshold)
        threshold_extra_outs = round((alert_threshold - threshold_complete) * 3)
        threshold_total_outs = threshold_complete * 3 + threshold_extra_outs

        strikeouts = 0
        walks = 0
        intentional_walks = 0
        hit_by_pitch = 0
        runs = 0
        pitches = 0

        for play in self.all_plays:
            about = play.get('about', {})
            if not about.get('isComplete', False):
                continue
            if about.get('isTopInning', False) != is_pitching_top:
                continue  # Wrong half-inning for this pitching team

            # count.outs = outs already recorded at the START of this at-bat (0, 1, or 2).
            # Outs reset per half-inning, so total outs = (inning - 1) * 3 + count.outs.
            inning = about.get('inning', 0)
            outs_before = play.get('count', {}).get('outs', 0)
            total_outs_before = (inning - 1) * 3 + outs_before

            if total_outs_before >= threshold_total_outs:
                break  # All further plays are at or past the threshold

            if play.get('matchup', {}).get('pitcher', {}).get('id') != starting_pitcher_id:
                continue  # Not the starting pitcher

            event_type = play.get('result', {}).get('eventType', '')
            if event_type == 'strikeout':
                strikeouts += 1
            elif event_type == 'intent_walk':
                intentional_walks += 1
            elif event_type == 'walk':
                walks += 1
            elif event_type == 'hit_by_pitch':
                hit_by_pitch += 1

            pitches += len(play.get('pitchIndex', []))

            for runner in play.get('runners', []):
                movement = runner.get('movement', {})
                details = runner.get('details', {})
                # A runner scores when start is a base and end is null (scored) or 'score'.
                # Exclude plays where the runner was put out on the bases.
                if (movement.get('start') is not None
                        and (movement.get('end') is None or movement.get('end') == 'score')
                        and not details.get('isOut', False)):
                    runs += 1

        return {
            'strikeOuts': strikeouts,
            'baseOnBalls': walks,
            'intentionalWalks': intentional_walks,
            'hitByPitch': hit_by_pitch,
            'runs': runs,
            'pitchesThrown': pitches,
        }

    def get_team_pitching_stats(self, team_id):
        team_boxscore = self.get_team_boxscore(team_id)
        return team_boxscore['teamStats']['pitching']

    def get_player_info(self, player_id):
        return self.player_info['ID{player_id}'.format(player_id=player_id)]

    def get_team_pitcher_details(self, team_id):
        team_boxscore = self.get_team_boxscore(team_id)
        team_pitcher_details = []

        for pitcher_id in team_boxscore['pitchers']:
            pitcher_details = team_boxscore['players']['ID{pitcher_id}'.format(pitcher_id=pitcher_id)]
            team_pitcher_details.append(pitcher_details)

        return team_pitcher_details

    def is_combined(self, team_id):
        team_boxscore = self.get_team_boxscore(team_id)
        num_pitchers = len(team_boxscore['pitchers'])
        return num_pitchers > 1

    def get_team_name(self, team_id):
        return self.home_team_name if team_id == self.home_team_id else self.away_team_name

    def get_team_abbrv(self, team_id):
        return self.home_team_abbrv if team_id == self.home_team_id else self.away_team_abbrv

    def get_opposing_team(self, team_id):
        return self.away_team_name if team_id == self.home_team_id else self.home_team_name

    def get_starting_pitcher_name(self, team_id):
        team_boxscore = self.get_team_boxscore(team_id)
        starting_pitcher_id = team_boxscore['pitchers'][0] if len(team_boxscore['pitchers']) > 0 else 0
        return team_boxscore['players']['ID{pitcher_id}'.format(pitcher_id=starting_pitcher_id)]['person']['fullName']

    def get_replacing_pitcher_name(self, team_id):
        team_boxscore = self.get_team_boxscore(team_id)
        replacing_pitcher_id = team_boxscore['pitchers'][1] if len(team_boxscore['pitchers']) > 1 else 0
        return team_boxscore['players']['ID{pitcher_id}'.format(pitcher_id=replacing_pitcher_id)]['person']['fullName']

    def get_broken_play_details(self, team_id):
        return self.home_pitcher_broken_play if team_id == self.home_team_id else self.away_pitcher_broken_play

    def get_downgrade_play_details(self, team_id):
        return self.home_pitcher_downgrade_play if team_id == self.home_team_id else self.away_pitcher_downgrade_play

    def get_innings_pitched(self, team_id):
        pitching_details = self.get_team_pitching_stats(team_id)
        return float(pitching_details['inningsPitched'])

    def is_no_hitter(self, team_id):
        pitching_details = self.get_team_pitching_stats(team_id)
        return pitching_details['hits'] == 0

    def is_perfect_game(self, team_id):
        pitching_details = self.get_team_pitching_stats(team_id)
        minimum_batters_faced = pitching_details['battersFaced'] == pitching_details['outs']
        num_walks = pitching_details['baseOnBalls'] + pitching_details['intentionalWalks']
        num_hit_by_pitch = pitching_details['hitByPitch']
        downgrade_play = self.get_downgrade_play_details(team_id)
        return self.is_no_hitter(team_id) and minimum_batters_faced and num_walks + num_hit_by_pitch == 0 and downgrade_play is None

    def is_final(self):
        return self.game_status == 'F'
