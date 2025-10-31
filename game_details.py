import requests
import util
from play_details import PlayDetails


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

    def __init__(self, game_pk):
        self.game_id = game_pk
        self.set_live_game_details()

    @classmethod
    def get_game_status(cls, status_obj):
        game_code_live = status_obj['abstractGameCode'] == 'L'
        if game_code_live and status_obj['codedGameState'] == 'I':
            return 'I'
        elif game_code_live and status_obj['codedGameState'] == 'P':
            return 'P'
        return status_obj['abstractGameCode']

    def set_live_game_details(self):
        request_endpoint = 'https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live'.format(game_id=str(self.game_id))

        try:
            response = util.make_request(request_endpoint)

            if response.status_code == 200:
                response = response.json()

                game_data = response['gameData']
                status = game_data['status']
                home_team_details = game_data['teams']['home']
                away_team_details = game_data['teams']['away']

                live_data = response['liveData']
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
        except (ConnectionError, requests.exceptions.RequestException) as e:
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
