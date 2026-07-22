"""Speicherung für /challenge: wer hat welche Challenge gebeatet.

Ein Eintrag pro geposteter Challenge-Nachricht (Key = Message-ID).
Gespeichert wird in challenges.json neben dem Code.
"""

from __future__ import annotations

import json
from pathlib import Path

FILE = Path(__file__).parent / "challenges.json"
IMAGES_DIR = Path(__file__).parent / "challenge_images"
IMAGES_DIR.mkdir(exist_ok=True)


def _load() -> dict:
    if FILE.exists():
        try:
            return json.loads(FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict) -> None:
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def register(message_id: int, name: str, author_id: int,
             image: str | None = None) -> None:
    """Neue Challenge-Nachricht ins Tracking aufnehmen."""
    data = _load()
    data[str(message_id)] = {"name": name, "author": author_id,
                             "image": image, "beaters": {}}
    _save(data)


def toggle_beaten(message_id: int, user_id: int, display_name: str) -> dict:
    """Beat eines Users an-/abmelden. Gibt den aktuellen Eintrag zurück."""
    data = _load()
    entry = data.setdefault(str(message_id),
                            {"name": "?", "author": 0, "beaters": {}})
    uid = str(user_id)
    if uid in entry["beaters"]:
        del entry["beaters"][uid]
    else:
        entry["beaters"][uid] = display_name
    _save(data)
    return entry


def beaters_text(entry: dict, limit: int = 15) -> str:
    """Anzeige-Text der Beater-Liste."""
    names = list(entry["beaters"].values())
    if not names:
        return "noch niemand"
    shown = names[:limit]
    text = ", ".join(shown)
    if len(names) > limit:
        text += f" und {len(names) - limit} weitere"
    return text
