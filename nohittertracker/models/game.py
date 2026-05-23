from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Team:
    id: int | None
    name: str | None
    abbreviation: str | None


@dataclass
class GameTeams:
    home: Team
    away: Team


@dataclass
class GameStatus:
    abstractGameCode: str | None
    codedGameState: str | None
    statusCode: str | None
    detailedState: str | None


@dataclass
class GameDatetime:
    dateTime: str | None


@dataclass
class GameFlags:
    noHitter: bool
    perfectGame: bool
    homeTeamNoHitter: bool
    homeTeamPerfectGame: bool
    awayTeamNoHitter: bool
    awayTeamPerfectGame: bool
    homeTeamNoHitterStatus: str
    awayTeamNoHitterStatus: str


@dataclass
class GameData:
    status: GameStatus
    datetime: GameDatetime
    teams: GameTeams
    flags: GameFlags


@dataclass
class InningHalf:
    runs: int | None
    hits: int | None
    errors: int | None


@dataclass
class InningLine:
    num: int | None
    home: InningHalf | None
    away: InningHalf | None

    def to_dict(self) -> dict[str, Any]:
        return {
            'num': self.num,
            'home': asdict(self.home) if self.home is not None else {},
            'away': asdict(self.away) if self.away is not None else {},
        }


@dataclass
class LineScore:
    currentInning: int | None
    isTopInning: bool | None
    innings: list[InningLine]
    scheduledInnings: int | None
    balls: int | None
    strikes: int | None
    outs: int | None
    offense: dict[str, Any]
    defense: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            'currentInning': self.currentInning,
            'isTopInning': self.isTopInning,
            'innings': [inning.to_dict() for inning in self.innings],
            'scheduledInnings': self.scheduledInnings,
            'balls': self.balls,
            'strikes': self.strikes,
            'outs': self.outs,
            'offense': self.offense,
            'defense': self.defense,
        }


@dataclass
class PitchingStats:
    hits: int
    outs: int
    battersFaced: int
    baseOnBalls: int
    intentionalWalks: int
    hitByPitch: int


@dataclass
class BattingStats:
    runs: int
    hits: int
    baseOnBalls: int
    hitByPitch: int


@dataclass
class FieldingStats:
    errors: int


@dataclass
class TeamStats:
    batting: BattingStats
    fielding: FieldingStats
    pitching: PitchingStats


@dataclass
class BoxscoreTeam:
    pitchers: list[int]
    pitcherName: str
    pitcherStats: str
    pitcherLines: list[dict[str, Any]]
    teamStats: TeamStats


@dataclass
class BoxscoreTeams:
    home: BoxscoreTeam
    away: BoxscoreTeam


@dataclass
class Boxscore:
    teams: BoxscoreTeams


@dataclass
class PlayResult:
    type: str | None
    eventType: str | None
    description: str | None


@dataclass
class PlayAbout:
    isTopInning: bool | None


@dataclass
class RunnerMovement:
    start: str | None
    end: str | None


@dataclass
class Runner:
    movement: RunnerMovement


@dataclass
class Play:
    result: PlayResult
    about: PlayAbout
    runners: list[Runner]


@dataclass
class Plays:
    allPlays: list[Play]

    def to_dict(self) -> dict[str, Any]:
        return {
            'allPlays': [asdict(play) for play in self.allPlays],
        }


@dataclass
class LiveData:
    linescore: LineScore
    boxscore: Boxscore
    plays: Plays

    def to_dict(self) -> dict[str, Any]:
        return {
            'linescore': self.linescore.to_dict(),
            'boxscore': asdict(self.boxscore),
            'plays': self.plays.to_dict(),
        }


@dataclass
class GamePayload:
    gamePk: int
    gameData: GameData
    liveData: LiveData

    def to_dict(self) -> dict[str, Any]:
        return {
            'gamePk': self.gamePk,
            'gameData': asdict(self.gameData),
            'liveData': self.liveData.to_dict(),
        }
