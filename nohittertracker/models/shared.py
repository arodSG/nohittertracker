from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PitchingLine:
    player_id: int
    full_name: str
    last_name: str
    innings_pitched: str
    strikeouts: int
    walks: int
    intentional_walks: int
    hit_by_pitch: int
    runs: int
    pitches_thrown: int
    stat_line: str
    final_line: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlaySnapshot:
    batter_name: str
    pitcher_name: str
    play_event: str
    completed_innings: int
    completed_outs: int
    is_combined: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TeamSnapshot:
    game_id: int
    game_status: str
    game_status_detailed: str
    is_in_progress: bool
    is_final: bool
    is_home_team: bool
    team_id: int
    team_name: str
    team_abbrv: str
    opposing_team: str
    opposing_team_id: int
    home_team_id: int
    home_team_name: str
    home_team_abbrv: str
    away_team_id: int
    away_team_name: str
    away_team_abbrv: str
    home_team_hashtag: str
    away_team_hashtag: str
    innings_pitched: float
    alert_threshold: float
    alert_eligible: bool
    is_no_hitter: bool
    is_perfect_game: bool
    is_combined: bool
    status_label: str
    starting_pitcher_name: str | None
    replacing_pitcher_name: str | None
    starting_pitcher_line: dict[str, Any] | None
    pitching_team_totals: dict[str, Any]
    pitcher_lines: list[dict[str, Any]] = field(default_factory=list)
    downgrade_play: dict[str, Any] | None = None
    broken_play: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrackerEvent:
    event_type: str
    game_id: int
    team_id: int
    is_finished: bool
    is_combined: bool
    is_perfect_game: bool
    message: str
    tweet_text: str
    snapshot: dict[str, Any]
    innings_pitched: float | None = None
    sort_key: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
