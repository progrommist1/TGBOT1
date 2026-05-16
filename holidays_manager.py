import json
import csv
import re
import io
from datetime import date
from pathlib import Path


class HolidaysManager:
    """
    Manages a local database of custom holidays.
    Storage format: { "DD.MM": ["Holiday 1", "Holiday 2", ...] }
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self._data: dict[str, list[str]] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def _key(self, d: date) -> str:
        return d.strftime("%d.%m")

    def get_holidays(self, d: date) -> list[str]:
        return self._data.get(self._key(d), [])

    def add_holiday(self, date_key: str, name: str):
        """Add a single holiday. date_key format: 'DD.MM'"""
        if date_key not in self._data:
            self._data[date_key] = []
        if name not in self._data[date_key]:
            self._data[date_key].append(name)
        self._save()

    def import_from_text(self, content: str, filename: str) -> int:
        """
        Parse and import holidays from file content.
        Returns count of imported holidays.
        """
        count = 0

        if filename.endswith(".json"):
            count = self._import_json(content)
        elif filename.endswith(".csv"):
            count = self._import_csv(content)
        elif filename.endswith(".txt"):
            count = self._import_txt(content)
        else:
            raise ValueError(f"Unsupported file type: {filename}")

        self._save()
        return count

    def _normalize_date(self, raw: str) -> str:
        """Convert various date formats to DD.MM"""
        raw = raw.strip()
        # Already DD.MM or DD.MM.YYYY
        m = re.match(r"^(\d{1,2})\.(\d{1,2})(?:\.\d{4})?$", raw)
        if m:
            day, month = int(m.group(1)), int(m.group(2))
            return f"{day:02d}.{month:02d}"
        # DD/MM or DD/MM/YYYY
        m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/\d{4})?$", raw)
        if m:
            day, month = int(m.group(1)), int(m.group(2))
            return f"{day:02d}.{month:02d}"
        # DD-MM or DD-MM-YYYY
        m = re.match(r"^(\d{1,2})-(\d{1,2})(?:-\d{4})?$", raw)
        if m:
            day, month = int(m.group(1)), int(m.group(2))
            return f"{day:02d}.{month:02d}"
        raise ValueError(f"Cannot parse date: '{raw}'")

    def _import_json(self, content: str) -> int:
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("JSON must be an object { 'DD.MM': ['Holiday', ...] }")
        count = 0
        for key, value in data.items():
            normalized = self._normalize_date(key)
            holidays = [value] if isinstance(value, str) else value
            for h in holidays:
                h = str(h).strip()
                if h:
                    if normalized not in self._data:
                        self._data[normalized] = []
                    if h not in self._data[normalized]:
                        self._data[normalized].append(h)
                        count += 1
        return count

    def _import_csv(self, content: str) -> int:
        count = 0
        reader = csv.reader(io.StringIO(content))
        for row in reader:
            if not row or len(row) < 2:
                continue
            raw_date = row[0].strip()
            name = ",".join(row[1:]).strip()
            if not raw_date or not name or raw_date.lower() in ("дата", "date"):
                continue
            try:
                key = self._normalize_date(raw_date)
                if key not in self._data:
                    self._data[key] = []
                if name not in self._data[key]:
                    self._data[key].append(name)
                    count += 1
            except ValueError:
                continue
        return count

    def _import_txt(self, content: str) -> int:
        count = 0
        # Supported delimiters between date and name
        separators = [" - ", " – ", " — ", "\t", ": ", " | "]

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parsed = False
            for sep in separators:
                if sep in line:
                    parts = line.split(sep, 1)
                    raw_date = parts[0].strip()
                    name = parts[1].strip()
                    try:
                        key = self._normalize_date(raw_date)
                        if key not in self._data:
                            self._data[key] = []
                        if name not in self._data[key]:
                            self._data[key].append(name)
                            count += 1
                        parsed = True
                        break
                    except ValueError:
                        continue

        return count
