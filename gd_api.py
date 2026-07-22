"""Level-Lookup und Level-Vorschläge — komplett über kostenlose Online-APIs.

1. GDBrowser (https://gdbrowser.com/api)
   - findet fast jedes Level und liefert die offizielle Demon-Schwierigkeit
   - liefert die Vorschlags-Pools für Easy- bis Insane-Demons
     (beliebteste Demons je Schwierigkeit)
2. AREDL (https://api.aredl.net — All Rated Extreme Demons List)
   - rankt alle ~1500 Extreme Demons; die Platzierung bestimmt das Tier
   - liefert die Vorschlags-Pools für Extreme Demons inkl. Tags
     (Ship/Wave/Timings/...), die gegen Skills & Game Modes gematcht werden

Beide APIs brauchen keinen Key. (Pointercrate selbst blockt Bot-Anfragen
per Cloudflare, deshalb AREDL.)

Tier-Skala:
  1  Easy Demon          5  Easy Extreme (AREDL >150 / Legacy)
  2  Medium Demon        6  Extreme (AREDL 76-150)
  3  Hard Demon          7  Extreme (AREDL 61-75)
  4  Insane Demon        8  Extreme (AREDL 31-60)
                         9  Extreme (AREDL 11-30)
                        10  Extreme (AREDL 4-10)
                        11  Extreme (AREDL 2-3)
                        12  Extreme (AREDL Top 1)
"""

from __future__ import annotations

import asyncio
import difflib
import math
import random
from dataclasses import dataclass, field
from urllib.parse import quote

import aiohttp

MAX_TIER = 12

# Big Skill Jumps schlagen nie etwas über dieser Platzierung vor (Top 20 tabu)
TOP_FLOOR = 21

TIER_NAMES = {
    1: "Easy Demon", 2: "Medium Demon", 3: "Hard Demon", 4: "Insane Demon",
    5: "Easy Extreme Demon", 6: "Extreme Demon (Extended List)",
    7: "Extreme Demon (untere Main List)", 8: "Extreme Demon (mittlere Main List)",
    9: "Extreme Demon (Top 30)", 10: "Extreme Demon (Top 10)",
    11: "Extreme Demon (Top 3)", 12: "Extreme Demon (Top 1)",
}

# GDBrowser-Schwierigkeit -> Tier (Extreme wird per AREDL verfeinert)
DIFFICULTY_TIERS = {
    "Easy Demon": 1,
    "Medium Demon": 2,
    "Hard Demon": 3,
    "Insane Demon": 4,
    "Extreme Demon": 5,
}

# Tier -> AREDL-Platzierungsbereich
TIER_BANDS = {
    12: (1, 1), 11: (2, 3), 10: (4, 10), 9: (11, 30),
    8: (31, 60), 7: (61, 75), 6: (76, 150), 5: (151, 10**9),
}

# GDBrowser demonFilter-Werte für die Suche
DEMON_FILTERS = {1: 1, 2: 2, 3: 3, 4: 4}

# Stichwörter (deutsch + englisch) -> normalisierte Keywords
MODE_KEYWORDS = {
    "cube": "cube", "würfel": "cube", "wurfel": "cube",
    "ship": "ship", "schiff": "ship",
    "wave": "wave", "welle": "wave",
    "ball": "ball",
    "ufo": "ufo",
    "robot": "robot", "roboter": "robot",
    "spider": "spider", "spinne": "spider",
    "swing": "swing", "swingcopter": "swing",
    "dual": "duals", "duals": "duals",
}

SKILL_KEYWORDS = {
    "timing": "timing", "timings": "timing",
    "memory": "memory", "auswendig": "memory",
    "flow": "flow",
    "spam": "spam", "click spam": "spam", "klicken": "spam",
    "straight fly": "straight-fly", "straightfly": "straight-fly",
    "straight": "straight-fly", "fliegen": "straight-fly",
    "fast": "fast", "schnell": "fast", "speed": "fast",
    "wave control": "wave-control", "wellenkontrolle": "wave-control",
    "nerven": "nerve-control", "nerve": "nerve-control",
    "konsistenz": "nerve-control", "consistency": "nerve-control",
    "learny": "learny", "lernen": "learny", "practice": "learny",
}

# AREDL-Tags -> dieselben normalisierten Keywords
TAG_ALIASES = {
    "cube": "cube", "ship": "ship", "wave": "wave", "ball": "ball",
    "ufo": "ufo", "robot": "robot", "spider": "spider", "swing": "swing",
    "duals": "duals", "dual": "duals",
    "timings": "timing", "timing": "timing",
    "fast-paced": "fast", "fast paced": "fast",
    "chokepoints": "nerve-control",
    "memory": "memory", "spam": "spam", "flow": "flow",
    "learny": "learny",
    "straight fly": "straight-fly", "straightfly": "straight-fly",
    "wave control": "wave-control",
}


@dataclass
class ApiLevelInfo:
    """Ergebnis des Hardest-Level-Lookups."""
    name: str
    creator: str
    tier: int
    difficulty: str
    source: str  # z.B. "GDBrowser" oder "AREDL #42"
    position: int | None = None  # AREDL-Platzierung (nur Extreme Demons)


@dataclass
class Suggestion:
    """Ein vorgeschlagenes Level."""
    name: str
    creator: str
    tier: int
    difficulty: str
    source: str
    tags: set[str] = field(default_factory=set)


# RobTops offizielle Demons stehen nicht auf den Servern, die GDBrowser
# durchsucht — deshalb die einzige Hardcode-Ausnahme:
OFFICIAL_DEMONS = {
    "clubstep": ApiLevelInfo("Clubstep", "RobTop", 3, "Hard Demon", "Official Level"),
    "theory of everything 2":
        ApiLevelInfo("Theory of Everything 2", "RobTop", 3, "Hard Demon", "Official Level"),
    "toe2": ApiLevelInfo("Theory of Everything 2", "RobTop", 3, "Hard Demon", "Official Level"),
    "toe 2": ApiLevelInfo("Theory of Everything 2", "RobTop", 3, "Hard Demon", "Official Level"),
    "deadlocked": ApiLevelInfo("Deadlocked", "RobTop", 3, "Hard Demon", "Official Level"),
}

_lookup_cache: dict[str, ApiLevelInfo | None] = {}
_aredl_cache: list[dict] | None = None
_aredl_creator_cache: dict[str, str] = {}
_pool_cache: dict[tuple[int, int], list[Suggestion]] = {}


def parse_keywords(text: str, table: dict[str, str]) -> set[str]:
    text = text.lower()
    return {norm for key, norm in table.items() if key in text}


def normalize_tags(entry: dict) -> set[str]:
    return {TAG_ALIASES[t.lower()] for t in entry.get("tags") or []
            if isinstance(t, str) and t.lower() in TAG_ALIASES}


def position_to_tier(pos: int) -> int:
    for tier, (lo, hi) in TIER_BANDS.items():
        if lo <= pos <= hi:
            return tier
    return 5


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


async def _get_json(session: aiohttp.ClientSession, url: str):
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            # GDBrowser liefert teils text/html als Content-Type
            return await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None


def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))


# --------------------------------------------------------------- AREDL

async def _aredl_levels(session: aiohttp.ClientSession) -> list[dict]:
    """Lädt die komplette AREDL einmal und cacht sie im Speicher."""
    global _aredl_cache
    if _aredl_cache is None:
        data = await _get_json(session, "https://api.aredl.net/v2/api/aredl/levels")
        levels = [lv for lv in data if isinstance(lv, dict)] \
            if isinstance(data, list) else []
        if not levels:
            return []  # Fehler -> beim nächsten Aufruf erneut versuchen
        _aredl_cache = levels
    return _aredl_cache


async def _aredl_creator(session: aiohttp.ClientSession, aredl_id: str) -> str:
    """Holt den Creator-Namen aus dem AREDL-Detail-Endpoint (gecacht)."""
    if aredl_id in _aredl_creator_cache:
        return _aredl_creator_cache[aredl_id]
    data = await _get_json(
        session, f"https://api.aredl.net/v2/api/aredl/levels/{aredl_id}"
    )
    name = "unbekannt"
    if isinstance(data, dict):
        pub = data.get("publisher") or {}
        for cand in (pub.get("global_name"), pub.get("username")):
            if cand and cand.strip() and cand.strip() != "-":
                name = cand.strip()
                break
    _aredl_creator_cache[aredl_id] = name
    return name


async def _demonlist_position(session: aiohttp.ClientSession, name: str,
                              level_id: int | None = None) -> int | None:
    levels = await _aredl_levels(session)
    if not levels:
        return None

    # Exakter Treffer über die Level-ID (kommt aus der GDBrowser-Suche)
    if level_id is not None:
        for lv in levels:
            if lv.get("level_id") == level_id:
                pos = lv.get("position")
                return pos if isinstance(pos, int) and pos > 0 else None

    best = max(levels, key=lambda d: _similarity(str(d.get("name", "")), name))
    if _similarity(str(best.get("name", "")), name) < 0.75:
        return None
    pos = best.get("position")
    return pos if isinstance(pos, int) and pos > 0 else None


# ------------------------------------------------- Hardest-Level-Lookup

async def lookup_level(query: str) -> ApiLevelInfo | None:
    """Sucht ein Demon-Level online. Gibt None zurück, wenn nichts passt."""
    key = query.strip().lower()
    if not key:
        return None
    official = difflib.get_close_matches(key, OFFICIAL_DEMONS.keys(), n=1, cutoff=0.8)
    if official:
        return OFFICIAL_DEMONS[official[0]]
    if key in _lookup_cache:
        return _lookup_cache[key]

    result: ApiLevelInfo | None = None
    async with _session() as session:
        data = await _get_json(
            session, f"https://gdbrowser.com/api/search/{quote(key)}?count=10"
        )
        demons = [
            lv for lv in (data if isinstance(data, list) else [])
            if isinstance(lv, dict) and "Demon" in str(lv.get("difficulty", ""))
        ]
        if demons:
            best = max(demons, key=lambda lv: _similarity(str(lv.get("name", "")), key))
            if _similarity(str(best.get("name", "")), key) >= 0.6:
                difficulty = str(best.get("difficulty"))
                tier = DIFFICULTY_TIERS.get(difficulty, 3)
                source = "GDBrowser"
                position = None
                if difficulty == "Extreme Demon":
                    try:
                        level_id = int(best.get("id", 0)) or None
                    except (TypeError, ValueError):
                        level_id = None
                    pos = await _demonlist_position(
                        session, str(best.get("name")), level_id
                    )
                    if pos is not None:
                        tier = position_to_tier(pos)
                        source = f"AREDL #{pos}"
                        position = pos
                result = ApiLevelInfo(
                    name=str(best.get("name")),
                    creator=str(best.get("author", "unbekannt")),
                    tier=tier,
                    difficulty=difficulty,
                    source=source,
                    position=position,
                )

    _lookup_cache[key] = result
    return result


# ------------------------------------------------------- Vorschläge

def _pos(lv: dict) -> int | None:
    pos = lv.get("position")
    return pos if isinstance(pos, int) and pos > 0 else None


async def _suggest_extremes(session: aiohttp.ClientSession, wanted: set[str],
                            exclude: str | None, user_position: int | None,
                            new_hardest: bool, big_jump: bool = False,
                            from_tier: int = 4) -> tuple[list[Suggestion], str]:
    """Extreme-Vorschläge über ein Platzierungsfenster nahe am Hardest.

    Kleine Sprünge statt ganzer Tier-Bänder: die AREDL ist nach unten hin
    immer dichter besetzt, deshalb skaliert das Fenster mit der Platzierung.
    """
    levels = await _aredl_levels(session)
    # 2-Player-Level (Duos) komplett ausschließen
    levels = [lv for lv in levels if _pos(lv) is not None
              and not lv.get("two_player")
              and "(2p" not in str(lv.get("name", "")).lower()]
    if not levels:
        return [], ""
    max_pos = max(_pos(lv) for lv in levels)

    def window_size(p: int) -> int:
        # Sprungweite wird Richtung Top 1 exponentiell kleiner:
        # unten in der Liste ~15-20 % der Platzierung, oben nur noch 2-3 Plätze
        frac = 0.07 + 0.16 * (p / max_pos) ** 1.3
        return max(2, int(p * frac))

    user_entry = next((lv for lv in levels if _pos(lv) == user_position), None)
    g = user_entry.get("gddl_tier") if user_entry else None
    g = g if isinstance(g, (int, float)) else None

    if big_jump and user_position is not None:
        # großer Sprung: mehrere Fenster über dem Hardest, aber nie Top 20
        p = user_position
        w = window_size(p)
        lo = max(TOP_FLOOR, int(p - 4.5 * w))
        hi = min(p - 1, max(lo + 3, int(p - 2.2 * w)))
        if hi < lo:
            lo, hi = TOP_FLOOR, TOP_FLOOR + 10  # Hardest ist schon fast oben
        center = (lo + hi) // 2
        desc = "Big Skill Jump — deutlich über deinem Hardest"
    elif big_jump:
        # großer Sprung von Hard/Insane Demon mitten in die Extremes
        if from_tier >= 4:
            lo, hi = int(max_pos * 0.30), int(max_pos * 0.70)
        else:
            lo, hi = int(max_pos * 0.45), int(max_pos * 0.95)
        center = (lo + hi) // 2
        desc = "Big Skill Jump in die Extreme Demons"
    elif user_position is not None:
        p = user_position
        w = window_size(p)
        if new_hardest:
            # ein "Sprung": Fenster deutlich über dem Hardest
            # (z.B. #800 -> ca. #600-750)
            lo = max(1, int(p - 1.6 * w))
            hi = max(1, min(p - 1, int(p - 0.4 * w)))
            desc = "etwas schwerer als dein Hardest"
            # Hardest ist für seine Region überdurchschnittlich schwer
            # (GDDL-Vergleich mit den Nachbarn) -> maximal 2 Sprünge erlauben
            if g is not None:
                neighbours = [lv["gddl_tier"] for lv in levels
                              if abs(_pos(lv) - p) <= 20
                              and isinstance(lv.get("gddl_tier"), (int, float))]
                if neighbours and g > sorted(neighbours)[len(neighbours) // 2] + 0.4:
                    lo = max(1, int(p - 2.4 * w))
                    desc = "deutlich schwerer — dein Hardest ist für seine Platzierung schon hart"
            center = (lo + hi) // 2
        else:
            # rund um das Hardest
            lo = max(1, p - w // 2)
            hi = min(max_pos, p + w // 2 + 2)
            desc = "ungefähr auf dem Niveau deines Hardest"
            center = p
    else:
        # Aufstieg von Insane Demon: Einsteiger-Extremes (Ende der Liste)
        lo, hi = int(max_pos * 0.85), max_pos
        center = max_pos
        desc = "Einsteiger-Extreme-Demons"

    pool = [lv for lv in levels if lo <= _pos(lv) <= hi
            and str(lv.get("name", "")).lower() != exclude]

    # Fenster zu dünn besetzt (z.B. ganz oben in der Liste) -> vorsichtig weiten
    while len(pool) < 3 and (lo > 1 or hi < max_pos):
        lo = max(1, lo - 5)
        hi = min(max_pos, hi + 5)
        pool = [lv for lv in levels if lo <= _pos(lv) <= hi
                and str(lv.get("name", "")).lower() != exclude]

    # GDDL-Feinschliff: Ausreißer im Fenster aussortieren, falls Wertung bekannt
    # (maximal ~2 GDDL-Stufen über dem Hardest, nie deutlich darunter);
    # bei Big Jumps bewusst deaktiviert
    if g is not None and not big_jump:
        g_lo, g_hi = (g - 0.5, g + 2.0) if new_hardest else (g - 1.0, g + 1.0)
        refined = [lv for lv in pool
                   if not isinstance(lv.get("gddl_tier"), (int, float))
                   or g_lo <= lv["gddl_tier"] <= g_hi]
        if len(refined) >= 3:
            pool = refined

    span = max(hi - lo, 1)

    def score(lv: dict) -> float:
        closeness = 1.0 - abs(_pos(lv) - center) / span
        return len(normalize_tags(lv) & wanted) + 0.5 * closeness + 0.75 * random.random()

    pool.sort(key=score, reverse=True)
    picks = pool[:3]

    suggestions = []
    for lv in picks:
        creator = await _aredl_creator(session, str(lv.get("id")))
        pos = _pos(lv)
        suggestions.append(Suggestion(
            name=str(lv.get("name")),
            creator=creator,
            tier=position_to_tier(pos),
            difficulty="Extreme Demon",
            source=f"AREDL #{pos}",
            tags=normalize_tags(lv),
        ))
    return suggestions, desc


async def _classic_pool(session: aiohttp.ClientSession, demon_filter: int,
                        page: int) -> list[Suggestion]:
    """Beliebteste Demons einer Schwierigkeit aus der GDBrowser-Suche (gecacht)."""
    cache_key = (demon_filter, page)
    if cache_key in _pool_cache:
        return _pool_cache[cache_key]

    url = (f"https://gdbrowser.com/api/search/*?type=mostliked&diff=-2"
           f"&demonFilter={demon_filter}&count=10&page={page}")
    data = await _get_json(session, url)
    pool = []
    for lv in (data if isinstance(data, list) else []):
        if not isinstance(lv, dict) or lv.get("platformer") or lv.get("twoPlayer"):
            continue
        difficulty = str(lv.get("difficulty", "Demon"))
        pool.append(Suggestion(
            name=str(lv.get("name")),
            creator=str(lv.get("author", "unbekannt")),
            tier=DIFFICULTY_TIERS.get(difficulty, 3),
            difficulty=difficulty,
            source="GDBrowser",
        ))
    if pool:
        _pool_cache[cache_key] = pool
    return pool


async def _suggest_classics(session: aiohttp.ClientSession, target: int,
                            include_lower: bool, exclude: str | None) -> list[Suggestion]:
    pool: list[Suggestion] = []
    filters = [target] + ([target - 1] if include_lower and target - 1 >= 1 else [])
    for f in filters:
        # zufällige Seite für Abwechslung; Seite 0 als Fallback
        for page in {random.randint(0, 2), 0}:
            pool += await _classic_pool(session, DEMON_FILTERS[f], page)
            if pool:
                break

    seen = set()
    unique = []
    for s in pool:
        key = s.name.lower()
        if key != exclude and key not in seen:
            seen.add(key)
            unique.append(s)

    # gleiche Schwierigkeit wie das Ziel leicht bevorzugen, sonst zufällig
    unique.sort(key=lambda s: (s.tier == target) + random.random(), reverse=True)
    return unique[:3]


# Ab hier (abwärts Richtung #1) werden die Gaps pro Platz deutlich brutaler
_TOP_DENSE = 20.0


def _route_coord(p: float) -> float:
    """Platzierung -> Schwierigkeits-Koordinate (1.0 = ein Trainings-Schritt).

    Oberhalb der Top 20 gilt ein ~x1.67-Positionssprung als ein Schritt,
    innerhalb der Top 20 nur noch ~x1.3 — dort werden die Sprünge zwischen
    den Leveln immer brutaler, also treppelt die Route feiner.
    """
    if p >= _TOP_DENSE:
        return math.log(p / _TOP_DENSE) / math.log(1.667)
    return math.log(p / _TOP_DENSE) / math.log(1.3)


def _route_coord_inv(c: float) -> float:
    base = 1.667 if c >= 0 else 1.3
    return _TOP_DENSE * base ** c


def _difficulty_rank(info: ApiLevelInfo) -> float:
    """Einheitliche Skala zum Vergleichen (kleiner = schwerer)."""
    if info.position is not None:
        return float(info.position)
    if info.difficulty == "Extreme Demon":
        return 1800.0
    return 2000.0 + (4 - info.tier) * 500


def _suggestion_from_aredl(lv: dict, creator: str) -> Suggestion:
    pos = _pos(lv)
    return Suggestion(
        name=str(lv.get("name")), creator=creator,
        tier=position_to_tier(pos), difficulty="Extreme Demon",
        source=f"AREDL #{pos}", tags=normalize_tags(lv),
    )


async def build_route(current_query: str, dream_query: str
                      ) -> tuple[ApiLevelInfo | None, ApiLevelInfo | None,
                                 list[Suggestion], str | None]:
    """Level-Treppe vom aktuellen Hardest zum Dream Hardest.

    Gibt (current, dream, Zwischenschritte leicht->schwer, Fehlertext) zurück.
    Die Zwischenschritte werden nach dem Skill-Set (AREDL-Tags) des
    Dream-Levels gewichtet.
    """
    current = await lookup_level(current_query)
    dream = await lookup_level(dream_query)
    if dream is None:
        return current, None, [], (
            f"Ich konnte „{dream_query}“ nicht finden — check die Schreibweise."
        )

    cur_rank = _difficulty_rank(current) if current else 3000.0  # Medium-Annahme
    if _difficulty_rank(dream) >= cur_rank:
        return current, dream, [], (
            "Dein Dream Hardest ist nicht schwerer als dein aktuelles "
            "Hardest — da gibt es keine Route. 😄"
        )

    cur_tier = current.tier if current else 2
    used = {dream.name.lower()}
    if current:
        used.add(current.name.lower())
    steps: list[Suggestion] = []

    async with _session() as session:
        levels = await _aredl_levels(session)
        levels = [lv for lv in levels if _pos(lv) is not None
                  and not lv.get("two_player")
                  and "(2p" not in str(lv.get("name", "")).lower()]

        # Skill-Set des Dream-Levels (Tags aus der AREDL)
        dream_tags: set[str] = set()
        if dream.position is not None:
            entry = next((lv for lv in levels if _pos(lv) == dream.position), None)
            if entry:
                dream_tags = normalize_tags(entry)

        def pick_near(target: float, floor: float = 0.0) -> Suggestion | None:
            # in den Top 20 sehr enges Fenster, sonst ~18 % der Platzierung;
            # floor: nie schwerer als das Dream-Level vorschlagen
            window = max(2.5, target * 0.18)
            for w in (window, window * 2):
                pool = [lv for lv in levels
                        if abs(_pos(lv) - target) <= w
                        and _pos(lv) > floor
                        and str(lv.get("name", "")).lower() not in used]
                if pool:
                    break
            if not pool:
                return None
            pool.sort(key=lambda lv: len(normalize_tags(lv) & dream_tags)
                      + 0.6 * random.random(), reverse=True)
            best = pool[0]
            used.add(str(best.get("name", "")).lower())
            return _suggestion_from_aredl(best, "?")

        # 1. Klassischer Teil: fehlende Difficulties bis Insane bzw. Dream
        if current is None or current.position is None:
            end_tier = 4 if dream.position is not None \
                or dream.difficulty == "Extreme Demon" else dream.tier - 1
            for t in range(cur_tier + 1, min(end_tier, 4) + 1):
                pool = await _classic_pool(session, DEMON_FILTERS[t],
                                           random.randint(0, 2))
                pool = [s for s in pool if s.name.lower() not in used]
                if pool:
                    pick = random.choice(pool)
                    used.add(pick.name.lower())
                    steps.append(pick)

        # 2. Extreme-Teil: geometrische Treppe durch die AREDL
        if dream.position is not None:
            max_pos = max(_pos(lv) for lv in levels)
            if current is not None and current.position is not None:
                p_start = float(current.position)
                include_start = False
            else:
                p_start = max_pos * 0.9  # Einstieg in die Extremes
                include_start = True
            p_end = float(dream.position)

            if p_start > p_end:
                extreme_steps: list[Suggestion] = []
                if include_start:
                    pick = pick_near(p_start, floor=p_end)
                    if pick:
                        extreme_steps.append(pick)
                # Schritte über die Schwierigkeits-Koordinate verteilen:
                # in den Top 20 automatisch viel feinere Treppe, und je
                # größer die Distanz zum Dream, desto mehr Zwischenlevel
                c_start = _route_coord(p_start)
                dist = c_start - _route_coord(max(p_end, 1.0))
                n = round(dist) if dist > 0.35 else 0
                n = max(0, min(n, 15 - len(steps)))
                for i in range(1, n + 1):
                    target = _route_coord_inv(c_start - dist * i / (n + 1))
                    pick = pick_near(target, floor=p_end)
                    if pick:
                        extreme_steps.append(pick)
                # strikt von leicht nach schwer sortieren
                extreme_steps.sort(
                    key=lambda s: int(s.source.removeprefix("AREDL #")),
                    reverse=True,
                )
                steps += extreme_steps

        # Creator-Namen der AREDL-Picks nachladen
        for s in steps:
            if s.creator == "?" and s.source.startswith("AREDL #"):
                pos = int(s.source.removeprefix("AREDL #"))
                entry = next((lv for lv in levels if _pos(lv) == pos), None)
                if entry:
                    s.creator = await _aredl_creator(session, str(entry.get("id")))

    return current, dream, steps, None


async def suggest(user_tier: int, new_hardest: bool, modes_text: str,
                  exclude_name: str | None = None,
                  user_position: int | None = None,
                  big_jump: bool = False
                  ) -> tuple[list[Suggestion], str]:
    """Gibt (bis zu 3 Vorschläge, Beschreibung des Ziels) zurück.

    user_position: AREDL-Platzierung des Hardest (nur bei Extreme Demons) —
    damit bleiben die Sprünge zwischen Hardest und Vorschlag klein.
    big_jump: deutlich größere Sprünge (z.B. Hard Demon -> Extremes),
    aber nie in die Top 20 der Liste.
    """
    user_tier = max(1, min(user_tier, MAX_TIER))
    target = min(user_tier + 1, MAX_TIER) if new_hardest else user_tier
    exclude = exclude_name.lower() if exclude_name else None

    # Game Modes und Skill-Begriffe (z.B. "timing", "spam") beide erkennen
    wanted = parse_keywords(modes_text, MODE_KEYWORDS)
    wanted |= parse_keywords(modes_text, SKILL_KEYWORDS)

    async with _session() as session:
        if big_jump and (user_position is not None or user_tier >= 3):
            # Hard/Insane/Extreme -> weit in die Extremes springen
            results, target_desc = await _suggest_extremes(
                session, wanted, exclude, user_position, True,
                big_jump=True, from_tier=user_tier,
            )
        elif big_jump:
            # Easy/Medium -> zwei Difficulties nach oben
            t = min(user_tier + 2, 4)
            results = await _suggest_classics(
                session, t, include_lower=False, exclude=exclude
            )
            target_desc = f"Big Skill Jump: {TIER_NAMES[t]}"
        elif target >= 5:
            results, target_desc = await _suggest_extremes(
                session, wanted, exclude, user_position, new_hardest
            )
        else:
            results = await _suggest_classics(
                session, target, include_lower=not new_hardest, exclude=exclude
            )
            target_desc = TIER_NAMES[target]
    return results, target_desc
