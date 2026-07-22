# DashBot – Geometry Dash Discord Bot

A Discord bot for Geometry Dash: level suggestions, a hardest-level board
with auto-roles, self-made challenges, and a dojo list. All level data
comes live from the GDBrowser and AREDL APIs — there's no local level
database (see [gd_api.py](gd_api.py)).

## Features

- **`/panel`** — panel with a "Suggest Level" button. The modal asks for
  hardest level, new hardest (Yes/No), game modes, and an optional big
  skill jump, then suggests a matching level.
- **`/route`** — panel with a "Route erstellen" button. Builds a level
  staircase between your current hardest and dream hardest, weighted by
  the skill set (AREDL tags) of the dream level.
- **`/hardest`** — board of every member's hardest level, automatically
  sorted by difficulty. "Update Hardest" button to log a new level;
  automatically assigns roles (see below).
- **`/challenge`** — post a self-made challenge with screenshot, level ID,
  and skill tags. "Gebeated" button with a beat counter and name list.
- **`/dojolist`** — manually ordered challenge list (hardest first). "Add
  Challenge" button to insert/move entries by spot number.

## Setup

### 1. Create the bot in the Discord Developer Portal

1. https://discord.com/developers/applications → **New Application**
2. Go to **Bot** → **Reset Token** → copy the token
3. Under **Bot**, enable the **Server Members Intent** privileged intent
   (needed for auto-roles and member lookup in `/hardest`)
4. Go to **OAuth2** → URL Generator: scopes `bot` + `applications.commands`,
   permissions **Send Messages**, **Manage Roles** → invite the bot with
   the generated URL

### 2. Set the token

Create a `.env` file in the project root:

```
DISCORD_TOKEN=your-bot-token

# optional, comma-separated, for instant slash-command sync while testing
TEST_GUILD_ID=123456789012345678,987654321098765432
```

### 3. Install dependencies & run

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip
.venv/bin/python bot.py                     # Windows: .venv\Scripts\python
```

### 4. Set up roles for `/hardest`

[bot.py](bot.py) defines the role IDs as constants (`ROLE_HARD_DEMON`,
`ROLE_EXTREME_DEMON`, `ROLE_BLOODBATH`, `ROLE_SONIC_WAVE`, `ROLE_TOP_150`,
`ROLE_TOP_75`, `JOIN_ROLE_ID`) — adjust them to your server's roles. The
bot's role needs **Manage Roles** and must sit above these roles in the
role list.

## Persistent data

`hardest.json`, `dojolist.json`, `challenges.json`, and
`challenge_images/` are created automatically at runtime and excluded via
`.gitignore` — on a fresh checkout, boards start from the seed data in
[hardest.py](hardest.py) and [dojolist.py](dojolist.py).
