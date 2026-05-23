from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class GameFeedApiError:
    gamePk: int
    error: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrackerApiResponse:
    date: str
    generated_at: str
    num_games: int
    num_in_progress_no_hitters: int
    in_progress_no_hitters: list[dict[str, Any]]
    events: list[dict[str, Any]]
    games: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
