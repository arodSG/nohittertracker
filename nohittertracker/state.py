from __future__ import annotations

import os
import pickle
from pathlib import Path

from . import constants


class TrackerStateStore:
    def __init__(self, last_game_date_path: str | None = None, team_state_path: str | None = None):
        project_root = Path(__file__).resolve().parent.parent
        fallback_data_dir = project_root / 'data'

        self.last_game_date_path = Path(
            last_game_date_path
            or os.getenv('NOHITTERTRACKER_LAST_GAME_DATE_PATH')
            or self._default_path(constants.LAST_GAME_DATE_FILE_PATH, fallback_data_dir / 'last_game_date.pkl')
        )
        self.team_state_path = Path(
            team_state_path
            or os.getenv('NOHITTERTRACKER_TEAM_STATE_PATH')
            or self._default_path(constants.TEAM_IDS_TWEETED_FILE_PATH, fallback_data_dir / 'team_ids_tweeted.pkl')
        )

    @staticmethod
    def _default_path(preferred: str, fallback: Path) -> str:
        preferred_path = Path(preferred)
        return str(preferred_path) if preferred_path.parent.exists() else str(fallback)

    def _ensure_parent(self, file_path: Path) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_pickle(self, file_path: Path, default):
        try:
            with file_path.open('rb') as file:
                return pickle.load(file)
        except (FileNotFoundError, EOFError, ValueError, pickle.PickleError):
            return default

    def _dump_pickle(self, file_path: Path, value) -> None:
        self._ensure_parent(file_path)
        with file_path.open('wb') as file:
            pickle.dump(value, file)

    def load_last_game_date(self) -> str | None:
        value = self._load_pickle(self.last_game_date_path, None)
        return value if isinstance(value, str) else None

    def save_last_game_date(self, game_date: str) -> None:
        self._dump_pickle(self.last_game_date_path, game_date)

    def load_team_state(self) -> dict[int, dict[str, bool]]:
        value = self._load_pickle(self.team_state_path, {})
        return value if isinstance(value, dict) else {}

    def save_team_state(self, state: dict[int, dict[str, bool]]) -> None:
        self._dump_pickle(self.team_state_path, state)

    def reset_team_state(self) -> dict[int, dict[str, bool]]:
        state: dict[int, dict[str, bool]] = {}
        self.save_team_state(state)
        return state

    def update_team_state(self, team_id: int, *, is_combined: bool, is_perfect_game: bool, is_finished: bool) -> None:
        state = self.load_team_state()
        state[team_id] = {
            'is_combined': is_combined,
            'is_perfect_game': is_perfect_game,
            'is_finished': is_finished,
        }
        self.save_team_state(state)

    def get_daily_state(self, game_date: str, *, persist: bool) -> dict[int, dict[str, bool]]:
        last_game_date = self.load_last_game_date()
        if last_game_date == game_date:
            return self.load_team_state()

        if persist:
            self.save_last_game_date(game_date)
            return self.reset_team_state()

        return {}
