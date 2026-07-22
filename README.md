# DashBot – Geometry Dash Discord Bot

Discord-Bot rund um Geometry Dash: Level-Vorschläge, ein Hardest-Board mit
Auto-Rollen, selbstgebaute Challenges und eine Dojo-Liste. Alle
Level-Daten kommen live über die GDBrowser- und AREDL-APIs — es gibt keine
lokale Leveldatenbank (siehe [gd_api.py](gd_api.py)).

## Features

- **`/panel`** — Panel mit „Suggest Level"-Button. Modal fragt Hardest
  Level, New Hardest (Ja/Nein), Game Modes und optional Big Skill Jump ab
  und schlägt passende Level vor.
- **`/route`** — Panel mit „Route erstellen"-Button. Baut aus aktuellem
  Hardest und Dream Hardest eine Level-Treppe dazwischen, gewichtet nach
  dem Skill-Set (AREDL-Tags) des Dream-Levels.
- **`/hardest`** — Board aller Member mit ihrem Hardest Level, automatisch
  nach Schwierigkeit sortiert. „Update Hardest"-Button zum Eintragen neuer
  Level; vergibt automatisch Rollen (siehe unten).
- **`/challenge`** — postet eine selbstgebaute Challenge mit Screenshot,
  Level-ID und Skill-Tags. „Gebeated"-Button mit Zähler und Namensliste.
- **`/dojolist`** — manuell geordnete Challenge-Liste (schwerste zuerst).
  „Add Challenge"-Button zum Einfügen/Verschieben per Spot-Nummer.

## Setup

### 1. Bot im Discord Developer Portal anlegen

1. https://discord.com/developers/applications → **New Application**
2. Links auf **Bot** → **Reset Token** → Token kopieren
3. Unter **Bot** die privilegierten Intents aktivieren: **Server Members
   Intent** (für Auto-Rollen und Member-Suche bei `/hardest`)
4. Links auf **OAuth2** → URL Generator: Scopes `bot` + `applications.commands`,
   Berechtigungen **Send Messages**, **Manage Roles** → mit der generierten
   URL den Bot einladen

### 2. Token eintragen

```
cp .env.example .env
```

Dann in `.env` den Token einsetzen. Für sofortigen Slash-Command-Sync
beim Testen zusätzlich `TEST_GUILD_ID` setzen (kommagetrennt bei mehreren
Servern).

### 3. Abhängigkeiten installieren & starten

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip
.venv/bin/python bot.py                     # Windows: .venv\Scripts\python
```

### 4. Rollen für `/hardest` einrichten

In [bot.py](bot.py) stehen die Rollen-IDs als Konstanten
(`ROLE_HARD_DEMON`, `ROLE_EXTREME_DEMON`, `ROLE_BLOODBATH`,
`ROLE_SONIC_WAVE`, `ROLE_TOP_150`, `ROLE_TOP_75`, `JOIN_ROLE_ID`) — an die
eigenen Server-Rollen anpassen. Die Bot-Rolle braucht **Rollen verwalten**
und muss in der Rollenliste über diesen Rollen stehen.

## Persistente Daten

`hardest.json`, `dojolist.json`, `challenges.json` und `challenge_images/`
werden zur Laufzeit automatisch angelegt und sind in `.gitignore`
ausgeschlossen — bei einem frischen Checkout starten die Boards mit den
Seed-Daten aus [hardest.py](hardest.py) bzw. [dojolist.py](dojolist.py).
