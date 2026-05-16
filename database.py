import json
import os
from pathlib import Path


class Database:
    """Simple JSON-based subscriber storage."""

    def __init__(self, path: str):
        self.path = Path(path)
        self._data: dict = {"subscribers": []}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {"subscribers": []}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def is_subscribed(self, chat_id: int) -> bool:
        return chat_id in self._data.get("subscribers", [])

    def add_subscriber(self, chat_id: int):
        if chat_id not in self._data["subscribers"]:
            self._data["subscribers"].append(chat_id)
            self._save()

    def remove_subscriber(self, chat_id: int):
        if chat_id in self._data["subscribers"]:
            self._data["subscribers"].remove(chat_id)
            self._save()

    def get_all_subscribers(self) -> list[int]:
        return list(self._data.get("subscribers", []))
