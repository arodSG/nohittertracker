from __future__ import annotations

from typing import Any

from . import constants
from .play_details import PlayDetails

from .models import PitchingLine, PlaySnapshot


class TweetFormatter:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def get_team_hashtag(self, team_abbrv: str) -> str:
        team_hashtags = self.config['team_hashtags']
        return team_hashtags[team_abbrv] if team_abbrv in team_hashtags else team_abbrv

    def build_tweet(self, message: str, game_details) -> str:
        return constants.TWEET.format(
            message=message,
            home_team_hashtag=self.get_team_hashtag(game_details.home_team_abbrv),
            away_team_hashtag=self.get_team_hashtag(game_details.away_team_abbrv),
        )

    def format_pitching_stats(self, pitching_stats: dict[str, Any]) -> str:
        num_hit_by_pitch = pitching_stats.get('hitByPitch', 0)
        return (constants.PITCHER_STATS_HBP if num_hit_by_pitch > 0 else constants.PITCHER_STATS).format(
            num_strikeouts=pitching_stats.get('strikeOuts', 0),
            num_walks=pitching_stats.get('baseOnBalls', 0),
            num_hit_by_pitch=num_hit_by_pitch,
            num_runs=pitching_stats.get('runs', 0),
            num_pitches=pitching_stats.get('pitchesThrown', 0),
        )

    def build_pitching_line(self, player_id: int, player_name: str, pitching_stats: dict[str, Any]) -> PitchingLine:
        last_name = player_name.split(' ')[-1]
        stat_line = self.format_pitching_stats(pitching_stats)
        innings_pitched = pitching_stats.get('inningsPitched', '0.0')
        final_line = constants.PITCHER_STATS_INNINGS.format(
            num_innings=innings_pitched,
            pitcher_stats=stat_line,
        )
        return PitchingLine(
            player_id=player_id,
            full_name=player_name,
            last_name=last_name,
            innings_pitched=innings_pitched,
            strikeouts=pitching_stats.get('strikeOuts', 0),
            walks=pitching_stats.get('baseOnBalls', 0),
            intentional_walks=pitching_stats.get('intentionalWalks', 0),
            hit_by_pitch=pitching_stats.get('hitByPitch', 0),
            runs=pitching_stats.get('runs', 0),
            pitches_thrown=pitching_stats.get('pitchesThrown', 0),
            stat_line=stat_line,
            final_line=final_line,
        )

    def build_team_pitching_lines(self, game_details, team_id: int) -> list[PitchingLine]:
        lines: list[PitchingLine] = []
        for pitcher_details in game_details.get_team_pitcher_details(team_id):
            player_id = pitcher_details['person']['id']
            player_name = pitcher_details['person']['fullName']
            lines.append(self.build_pitching_line(player_id, player_name, pitcher_details['stats']['pitching']))
        return lines

    def build_no_hitter_message(self, game_details, team_id: int, *, is_final: bool, innings_pitched: float | None = None, is_combined: bool | None = None, is_perfect_game: bool | None = None, pitcher_stats: dict | None = None) -> str:
        innings_pitched = innings_pitched if innings_pitched is not None else game_details.get_innings_pitched(team_id)
        is_combined = is_combined if is_combined is not None else game_details.is_combined(team_id)
        is_perfect_game = is_perfect_game if is_perfect_game is not None else game_details.is_perfect_game(team_id)
        no_hitter_status = 'perfect game' if is_perfect_game else 'no-hitter'
        opposing_team = game_details.get_opposing_team(team_id)

        if is_combined:
            team_name = game_details.get_team_name(team_id)
            if is_final:
                pitcher_lines = self.build_team_pitching_lines(game_details, team_id)
                pitcher_stats_messages = [
                    constants.COMBINED_FINAL_PITCHER_STATS.format(
                        pitcher_name=pitcher_line.last_name,
                        num_innings=pitcher_line.innings_pitched,
                        pitcher_stats=pitcher_line.stat_line,
                    )
                    for pitcher_line in pitcher_lines
                ]
                return constants.COMBINED_FINAL.format(
                    team_name=team_name,
                    game_status=no_hitter_status,
                    opposing_team=opposing_team,
                    pitcher_stats_message='\n'.join(pitcher_stats_messages),
                )
            return constants.COMBINED_CURRENT.format(
                team_name=team_name,
                game_status=no_hitter_status,
                opposing_team=opposing_team,
                innings_pitched=innings_pitched,
            )

        pitcher_name = game_details.get_starting_pitcher_name(team_id)
        team_abbrv = game_details.get_team_abbrv(team_id)
        pitching_stats = pitcher_stats if pitcher_stats is not None else game_details.get_starting_pitcher_details(team_id)
        pitcher_line = self.build_pitching_line(
            game_details.get_team_boxscore(team_id)['pitchers'][0],
            pitcher_name,
            pitching_stats,
        )

        if is_final:
            return constants.REG_FINAL.format(
                pitcher_name=pitcher_name,
                team_abbrv=team_abbrv,
                game_status=no_hitter_status,
                opposing_team=opposing_team,
                pitcher_stats_message=pitcher_line.final_line,
            )

        return constants.REG_CURRENT.format(
            pitcher_name=pitcher_name,
            team_abbrv=team_abbrv,
            game_status=no_hitter_status,
            opposing_team=opposing_team,
            innings_pitched=innings_pitched,
            pitcher_stats_message=pitcher_line.stat_line,
        )

    def build_downgrade_message(self, game_details, team_id: int) -> str | None:
        downgrade_play_details = game_details.get_downgrade_play_details(team_id)
        if downgrade_play_details is None:
            return None

        innings_pitched = game_details.get_innings_pitched(team_id)
        opposing_team = game_details.get_opposing_team(team_id)

        if downgrade_play_details.is_combined():
            return constants.COMBINED_DOWNGRADE.format(
                team_name=game_details.get_team_name(team_id),
                opposing_team=opposing_team,
                innings_pitched=innings_pitched,
            )

        return constants.REG_DOWNGRADE.format(
            pitcher_name=downgrade_play_details.pitcher_name,
            team_abbrv=game_details.get_team_abbrv(team_id),
            opposing_team=opposing_team,
            innings_pitched=innings_pitched,
        )

    def build_pitching_change_message(self, game_details, team_id: int, starter_innings_pitched: float | None = None) -> str | None:
        if not game_details.is_combined(team_id):
            return None

        starting_pitcher_name = game_details.get_starting_pitcher_name(team_id)
        replacing_pitcher_name = game_details.get_replacing_pitcher_name(team_id)
        innings_pitched = starter_innings_pitched if starter_innings_pitched is not None else game_details.get_innings_pitched(team_id)
        no_hitter_status = 'perfect game' if game_details.is_perfect_game(team_id) else 'no-hitter'
        team_abbrv = game_details.get_team_abbrv(team_id)
        pitching_stats = game_details.get_starting_pitcher_details(team_id)
        pitcher_line = self.build_pitching_line(
            game_details.get_team_boxscore(team_id)['pitchers'][0],
            starting_pitcher_name,
            pitching_stats,
        )

        return constants.REG_TO_COMBINED.format(
            pitcher_name=starting_pitcher_name,
            team_abbrv=team_abbrv,
            new_pitcher_name=replacing_pitcher_name,
            game_status=no_hitter_status,
            innings_pitched=innings_pitched,
            pitcher_stats_message=pitcher_line.final_line,
        )

    def build_broken_by_message(self, play_details: PlayDetails) -> str:
        return constants.BROKEN_BY.format(
            play_event=play_details.play_event,
            batter_name=play_details.batter_name,
            inning=play_details.completed_innings,
            outs=play_details.completed_outs,
        )

    def build_broken_message(self, game_details, team_id: int) -> str | None:
        broken_play_details = game_details.get_broken_play_details(team_id)
        if broken_play_details is None:
            return None

        opposing_team = game_details.get_opposing_team(team_id)
        broken_by_message = self.build_broken_by_message(broken_play_details)
        if broken_play_details.is_combined():
            return constants.COMBINED_BROKEN.format(
                team_name=game_details.get_team_name(team_id),
                opposing_team=opposing_team,
                broken_by_message=broken_by_message,
            )

        return constants.REG_BROKEN.format(
            pitcher_name=broken_play_details.pitcher_name,
            team_abbrv=game_details.get_team_abbrv(team_id),
            opposing_team=opposing_team,
            broken_by_message=broken_by_message,
        )

    def play_snapshot(self, play_details: PlayDetails | None) -> PlaySnapshot | None:
        if play_details is None:
            return None

        return PlaySnapshot(
            batter_name=play_details.batter_name,
            pitcher_name=play_details.pitcher_name,
            play_event=play_details.play_event,
            completed_innings=play_details.completed_innings,
            completed_outs=play_details.completed_outs,
            is_combined=play_details.is_combined(),
        )


