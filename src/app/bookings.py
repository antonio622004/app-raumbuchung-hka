"""Räume, Zeitfenster und Buchungen. Die Buchungen liegen in SQLite unter DATA_DIR (im Container /data)."""

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from platform_sdk.common.dates import LOCAL_TIME

ROOMS = ("A101", "A102", "B201", "B202")


@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    start: time
    end: time

    @property
    def times(self) -> str:
        return f"{self.start:%H:%M} bis {self.end:%H:%M} Uhr"


SLOTS = (
    Slot("vormittag", "Vormittag", time(8, 0), time(12, 0)),
    Slot("nachmittag", "Nachmittag", time(13, 0), time(17, 0)),
)
SLOTS_BY_KEY = {s.key: s for s in SLOTS}


def now() -> datetime:
    """Aktuelle Zeit in Berlin (ohne Zeitzonendaten: UTC)."""
    return datetime.now(LOCAL_TIME) if LOCAL_TIME else datetime.now()


class AlreadyBooked(Exception):
    """Der Raum ist in diesem Zeitfenster schon gebucht."""


class BookingStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS booking (
                    day TEXT NOT NULL,
                    room TEXT NOT NULL,
                    slot TEXT NOT NULL,
                    person TEXT NOT NULL,
                    created TEXT NOT NULL,
                    PRIMARY KEY (day, room, slot)
                )"""
            )

    @classmethod
    def from_env(cls) -> "BookingStore":
        return cls(Path(os.environ.get("DATA_DIR", "build/data")) / "raumbuchung.sqlite3")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def for_day(self, day: date) -> dict[tuple[str, str], str]:
        """(Raum, Zeitfenster) → Kennung der buchenden Person."""
        with self._connect() as db:
            rows = db.execute("SELECT room, slot, person FROM booking WHERE day = ?", (day.isoformat(),))
            return {(room, slot): person for room, slot, person in rows}

    def book(self, day: date, room: str, slot: str, person: str) -> None:
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO booking (day, room, slot, person, created) VALUES (?, ?, ?, ?, ?)",
                    (day.isoformat(), room, slot, person, now().isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise AlreadyBooked from exc

    def cancel(self, day: date, room: str, slot: str, person: str) -> bool:
        """Löscht nur eine eigene Buchung. Gibt zurück, ob es eine gab."""
        with self._connect() as db:
            cur = db.execute(
                "DELETE FROM booking WHERE day = ? AND room = ? AND slot = ? AND person = ?",
                (day.isoformat(), room, slot, person),
            )
            return cur.rowcount > 0

    def clear(self) -> None:
        """Nur für Tests."""
        with self._connect() as db:
            db.execute("DELETE FROM booking")
