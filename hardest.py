"""Hardest-Level-Board pro Server: Speicherung, Sortierung, Embed.

Die Level werden über gd_api.lookup_level eingeordnet und automatisch
nach Schwierigkeit sortiert (AREDL-Platzierung bei Extremes, sonst
Demon-Schwierigkeit). Gespeichert wird in hardest.json neben dem Code.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path

import discord

from gd_api import lookup_level

FILE = Path(__file__).parent / "hardest.json"

# Start-Daten: Member -> Hardest Level
SEED = {
    "Zevoo": "Limbo",
    "Peinlicher": "Shardscapes",
    "Ian": "Bloodlust",
    "Shaarkzy": "Wasureta",
    "Vro": "Blade of Justice",
    "Flo": "Stop Breathing",
    "mkay": "Sweater Weather",
    "Wampl": "Sweater Weather",
    "Rin": "Interstellar Infant",
    "n7so": "Sakupen Egg",
    "Löön": "B",
    "Eli": "Decode",
    "Wxrld": "Deadlocked",
    "Torith": "Clubstep",
    "Smt": "Clutterfunk",
}


# Offizielle Hauptlevel (in Spielreihenfolge) — landen unter allen Demons
ROBTOP_LEVELS = [
    "Stereo Madness", "Back On Track", "Polargeist", "Dry Out",
    "Base After Base", "Cant Let Go", "Jumper", "Time Machine", "Cycles",
    "xStep", "Clutterfunk", "Theory of Everything", "Electroman Adventures",
    "Clubstep", "Electrodynamix", "Hexagon Force", "Blast Processing",
    "Theory of Everything 2", "Geometrical Dominator", "Deadlocked",
    "Fingerdash", "Dash",
]
_ROBTOP_LOWER = [lv.lower() for lv in ROBTOP_LEVELS]


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


async def _resolve(level_name: str) -> dict:
    """Level online einordnen -> Eintrag mit Anzeige-Name und Sortier-Wert.

    Sortierung (kleiner = schwerer):
      AREDL-Platzierung 1-~1500 | Extreme ohne Platzierung 1800 |
      Insane 2000 | Hard 2500 | Medium 3000 | Easy 3500 |
      RobTop-Level ~8100 (untereinander in Spielreihenfolge) | unbekannt 9000
    """
    # Offizielle RobTop-Level: eigene Kategorie ganz unten
    official = difflib.get_close_matches(
        level_name.strip().lower(), _ROBTOP_LOWER, n=1, cutoff=0.8
    )
    if official:
        idx = _ROBTOP_LOWER.index(official[0])
        return {"level": level_name, "display": ROBTOP_LEVELS[idx],
                "label": "RobTop Level", "sort": 8100.0 - idx}

    info = await lookup_level(level_name)
    if info is None:
        return {"level": level_name, "display": level_name,
                "label": "?", "sort": 9000}
    if info.position is not None:
        sort = float(info.position)
        label = f"#{info.position}"
    elif info.difficulty == "Extreme Demon":
        sort = 1800.0
        label = "Extreme Demon"
    else:
        sort = 2000.0 + (4 - info.tier) * 500
        label = info.difficulty
    return {"level": level_name, "display": info.name,
            "label": label, "sort": sort}


async def ensure_board(guild_id: int) -> dict:
    """Board des Servers laden; beim ersten Mal mit den Seed-Daten füllen."""
    data = _load()
    key = str(guild_id)
    if key not in data:
        board = {}
        for member, level in SEED.items():
            board[member] = await _resolve(level)
        data[key] = board
        _save(data)
    return data[key]


async def set_hardest(guild_id: int, member_input: str,
                      level_input: str) -> tuple[str, dict, bool]:
    """Hardest eines Members setzen. Gibt (Member, Eintrag, neu?) zurück.

    Der Member wird fuzzy gegen die vorhandenen Namen gematcht;
    ohne Treffer wird er neu angelegt.
    """
    board = await ensure_board(guild_id)
    member_input = member_input.strip()
    match = difflib.get_close_matches(
        member_input.lower(), [m.lower() for m in board], n=1, cutoff=0.75
    )
    if match:
        member = next(m for m in board if m.lower() == match[0])
        created = False
    else:
        member = member_input
        created = True

    entry = await _resolve(level_input.strip())
    data = _load()
    data[str(guild_id)][member] = entry
    _save(data)
    return member, entry, created


def build_embed(guild_id: int) -> discord.Embed:
    """Sortiertes Board als Embed (hardest zuerst)."""
    board = _load().get(str(guild_id), {})
    ranked = sorted(board.items(), key=lambda kv: (kv[1]["sort"], kv[0].lower()))
    lines = [
        f"`{i:>2}.` **{e['display']}** ({e['label']}) — {member}"
        for i, (member, e) in enumerate(ranked, 1)
    ]
    return discord.Embed(
        title="Hardest Levels",
        color=discord.Color.gold(),
        description="\n".join(lines) if lines else "Noch keine Einträge.",
    )
