"""Dojo-Liste: manuell geordnete Challenge-Liste pro Server.

Platz 1 = schwerste Challenge. Gespeichert in dojolist.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import discord

FILE = Path(__file__).parent / "dojolist.json"

# Startliste, schwerste zuerst
SEED = [
    "Unbekannt",
    "Nuts",
    "Warmup 4",
    "Challenge",
    "Warmup 1",
    "KFC",
    "Torith Challenge",
]


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


def get_list(guild_id: int) -> list[str]:
    data = _load()
    key = str(guild_id)
    if key not in data:
        data[key] = list(SEED)
        _save(data)
    return data[key]


def add(guild_id: int, name: str, spot: int) -> tuple[list[str], bool]:
    """Challenge an Platz `spot` (1 = schwerste) einfügen.

    Existiert der Name schon (fuzzy), wird die Challenge dorthin verschoben.
    Gibt (Liste, verschoben?) zurück.
    """
    entries = get_list(guild_id)
    name = name.strip()

    # nur exakte Namensgleichheit gilt als Verschieben — "Warmup 5" darf
    # nicht als "Warmup 4" durchgehen
    moved = False
    lowered = [e.lower() for e in entries]
    if name.lower() in lowered:
        name = entries.pop(lowered.index(name.lower()))
        moved = True

    spot = max(1, min(spot, len(entries) + 1))
    entries.insert(spot - 1, name)

    data = _load()
    data[str(guild_id)] = entries
    _save(data)
    return entries, moved


def build_embed(guild_id: int) -> discord.Embed:
    entries = get_list(guild_id)
    # ### macht die Einträge im Embed deutlich größer
    lines = [f"### `{i:02d}` — {name}" for i, name in enumerate(entries, 1)]
    return discord.Embed(
        title="DOJO LISTE",
        color=discord.Color.dark_red(),
        description="\n".join(lines) if lines else "Noch keine Challenges.",
    )
