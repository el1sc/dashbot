"""Geometry Dash Level-Suggestion Discord Bot.

/panel postet ein Panel mit einem "Suggest Level"-Button. Der Button öffnet
ein Formular (Modal) mit drei Feldern; danach schlägt der Bot passende
Level vor — komplett über die GDBrowser- und AREDL-APIs (siehe gd_api.py).
"""

import os
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

import challenges
import dojolist
import hardest
from gd_api import build_route, lookup_level, suggest

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
# optional: Server-IDs (kommagetrennt) für sofortigen Slash-Command-Sync
TEST_GUILD_IDS = [g.strip() for g in os.getenv("TEST_GUILD_ID", "").split(",") if g.strip()]


# Auto-Rollen (IDs vom Server)
JOIN_ROLE_ID = 1510099651741614168
ROLE_HARD_DEMON = 1510099272203243680
ROLE_EXTREME_DEMON = 1510098922008350871
ROLE_BLOODBATH = 1510097746760306778
ROLE_SONIC_WAVE = 1510097367318270114
ROLE_TOP_150 = 1510096993664503999
ROLE_TOP_75 = 1510096389432938567

ROBTOP_HARD_DEMONS = {"Clubstep", "Theory of Everything 2", "Deadlocked"}


async def apply_hardest_roles(guild: discord.Guild, member: discord.Member,
                              entry: dict) -> bool:
    """Rollen anhand des Hardest-Eintrags setzen/entfernen.

    entry["sort"]: AREDL-Platzierung bei Extremes, sonst Klassen-Werte
    (Insane 2000, Hard 2500, ... — siehe hardest._resolve).
    """
    # Bloodbath-/Sonic-Wave-Platzierungen live holen (Cache in gd_api)
    bb = await lookup_level("Bloodbath")
    sw = await lookup_level("Sonic Wave")
    bb_pos = bb.position if bb and bb.position else 792
    sw_pos = sw.position if sw and sw.position else 160

    sort = float(entry.get("sort", 9000))
    robtop_hard = (entry.get("label") == "RobTop Level"
                   and entry.get("display") in ROBTOP_HARD_DEMONS)

    # höchste erfüllte Rolle gewinnt — man hat immer genau eine der 7
    ladder = [
        (ROLE_TOP_75, sort <= 75),
        (ROLE_TOP_150, sort <= 150),
        (ROLE_SONIC_WAVE, sort <= sw_pos),
        (ROLE_BLOODBATH, sort <= bb_pos),
        (ROLE_EXTREME_DEMON, sort <= 1800),
        (ROLE_HARD_DEMON, sort <= 2500 or robtop_hard),
    ]
    best_id = next((rid for rid, ok in ladder if ok), JOIN_ROLE_ID)

    all_ids = [rid for rid, _ in ladder] + [JOIN_ROLE_ID]
    to_add = [r for rid in all_ids if rid == best_id
              and (r := guild.get_role(rid)) and r not in member.roles]
    to_remove = [r for rid in all_ids if rid != best_id
                 and (r := guild.get_role(rid)) and r in member.roles]
    try:
        if to_add:
            await member.add_roles(*to_add, reason="Hardest-Update")
        if to_remove:
            await member.remove_roles(*to_remove, reason="Hardest-Update")
    except discord.Forbidden:
        return False
    return True


async def find_guild_member(guild: discord.Guild,
                            name: str) -> discord.Member | None:
    """Discord-Member zum Board-Namen suchen (Prefix-Query + Fuzzy)."""
    import difflib
    try:
        matches = await guild.query_members(query=name, limit=10)
    except discord.HTTPException:
        return None
    best, best_score = None, 0.0
    for m in matches:
        for cand in (m.display_name, m.name, m.global_name or ""):
            score = difflib.SequenceMatcher(
                None, cand.lower(), name.lower()).ratio()
            best, best_score = (m, score) if score > best_score else (best, best_score)
    return best if best_score >= 0.6 else None


def difficulty_label(difficulty: str, source: str) -> str:
    """Schwierigkeit + Demonlist-Platzierung (falls vorhanden), ohne API-Namen."""
    if source.startswith("AREDL #"):
        return f"{difficulty} ({source.removeprefix('AREDL ')})"
    return difficulty


class SuggestionModal(discord.ui.Modal, title="Level Suggestion"):
    hardest = discord.ui.TextInput(
        label="Dein Hardest Level",
        placeholder="z.B. Bloodbath",
        max_length=100,
    )
    new_hardest = discord.ui.TextInput(
        label="Soll es ein New Hardest sein? (Ja/Nein)",
        placeholder="Ja oder Nein",
        max_length=10,
    )
    modes = discord.ui.TextInput(
        label="Bevorzugte Game Modes",
        placeholder="z.B. Wave, Ship, Duals, Timing, Spam ...",
        max_length=100,
    )
    big_jump = discord.ui.TextInput(
        label="Big Skill Jump? (Ja/Nein)",
        placeholder="Nein",
        required=False,
        max_length=10,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # Online-Lookup kann ein paar Sekunden dauern -> erst deferren
        await interaction.response.defer(ephemeral=True, thinking=True)

        def is_yes(text: str) -> bool:
            return text.strip().lower() in ("ja", "j", "yes", "y", "jo", "klar")

        wants_new_hardest = is_yes(self.new_hardest.value)
        wants_big_jump = is_yes(self.big_jump.value)

        # Hardest Level online nachschlagen (GDBrowser + AREDL bei Extremes)
        api = await lookup_level(self.hardest.value)
        if api:
            user_tier = api.tier
            exclude = api.name
            hardest_info = (f"{api.name} von {api.creator} · "
                            f"{difficulty_label(api.difficulty, api.source)}")
        else:
            user_tier = 2
            exclude = None
            hardest_info = (f"„{self.hardest.value}“ – online nicht gefunden, "
                            f"ich schätze dich als Medium-Demon-Spieler ein.")

        results, target_desc = await suggest(
            user_tier, wants_new_hardest, self.modes.value,
            exclude_name=exclude,
            user_position=api.position if api else None,
            big_jump=wants_big_jump,
        )

        if not results:
            await interaction.followup.send(
                "Die Level-APIs sind gerade nicht erreichbar — probier es "
                "gleich nochmal. 😕",
                ephemeral=True,
            )
            return

        top = results[0]
        details = f"von **{top.creator}** · {difficulty_label(top.difficulty, top.source)}"
        if top.tags:
            details += f"\nTags: {', '.join(sorted(top.tags))}"
        embed = discord.Embed(
            title="Dein Level-Vorschlag",
            color=discord.Color.green(),
            description=f"## {top.name}\n{details}",
        )

        embed.add_field(name="Dein Hardest", value=hardest_info, inline=True)
        embed.add_field(
            name="New Hardest?",
            value="Ja ✅" if wants_new_hardest else "Nein ❌",
            inline=True,
        )

        if len(results) > 1:
            alts = "\n".join(
                f"• **{s.name}** von {s.creator} "
                f"({difficulty_label(s.difficulty, s.source)})"
                for s in results[1:3]
            )
            embed.add_field(name="Alternativen", value=alts, inline=False)

        embed.set_footer(text=f"Ziel: {target_desc}")
        await interaction.followup.send(embed=embed, ephemeral=True)


class PanelView(discord.ui.View):
    """Persistente View, damit der Button auch nach einem Neustart funktioniert."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Suggest Level",
        style=discord.ButtonStyle.primary,
        emoji="⭐",
        custom_id="dashbot:suggest_level",
    )
    async def suggest_level(self, interaction: discord.Interaction,
                            button: discord.ui.Button) -> None:
        await interaction.response.send_modal(SuggestionModal())


class UpdateHardestModal(discord.ui.Modal, title="Hardest updaten"):
    member = discord.ui.TextInput(
        label="Member",
        placeholder="z.B. Zevoo",
        max_length=50,
    )
    level = discord.ui.TextInput(
        label="Gebeatetes Level",
        placeholder="z.B. Bloodbath",
        max_length=100,
    )

    def __init__(self, board_message: discord.Message | None = None) -> None:
        super().__init__()
        self.board_message = board_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # Level-Einordnung braucht einen API-Call -> erst deferren
        await interaction.response.defer(ephemeral=True, thinking=True)

        member, entry, created = await hardest.set_hardest(
            interaction.guild_id, self.member.value, self.level.value
        )

        # Board-Nachricht (an der der Button hängt) aktualisieren
        target = self.board_message or interaction.message
        if target is not None:
            try:
                await target.edit(embed=hardest.build_embed(interaction.guild_id))
            except discord.HTTPException:
                pass

        note = " *(neu im Board)*" if created else ""
        if entry["label"] == "?":
            note += ("\nDas Level konnte ich nicht einordnen — es steht "
                     "vorerst ganz unten.")

        # Auto-Rollen für den betroffenen Member aktualisieren
        discord_member = await find_guild_member(interaction.guild, member)
        if discord_member is None:
            note += (f"\nRollen: keinen Discord-User namens „{member}“ "
                     f"gefunden — Rollen nicht angepasst.")
        elif await apply_hardest_roles(interaction.guild, discord_member, entry):
            note += f"\nRollen für {discord_member.mention} aktualisiert."
        else:
            note += ("\nRollen konnte ich nicht anpassen — mir fehlt "
                     "„Rollen verwalten“ oder meine Rolle steht zu niedrig.")

        await interaction.followup.send(
            f"{member}s Hardest ist jetzt **{entry['display']}** "
            f"({entry['label']}){note}",
            ephemeral=True,
        )


class HardestView(discord.ui.View):
    """Persistente View für den Update-Button unter dem Hardest-Board."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Update Hardest",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="dashbot:update_hardest",
    )
    async def update_hardest(self, interaction: discord.Interaction,
                             button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            UpdateHardestModal(interaction.message)
        )


class DojoAddModal(discord.ui.Modal, title="Challenge hinzufügen"):
    name = discord.ui.TextInput(
        label="Name der Challenge",
        placeholder="z.B. Warmup 5",
        max_length=100,
    )
    spot = discord.ui.TextInput(
        label="Spot (1 = schwerste)",
        placeholder="z.B. 3",
        max_length=4,
    )

    def __init__(self, board_message: discord.Message | None = None) -> None:
        super().__init__()
        self.board_message = board_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            spot = int(self.spot.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "Der Spot muss eine Zahl sein (1 = schwerste Challenge).",
                ephemeral=True,
            )
            return

        entries, moved = dojolist.add(
            interaction.guild_id, self.name.value, spot
        )
        embed = dojolist.build_embed(interaction.guild_id)

        target = self.board_message or interaction.message
        if target is not None:
            try:
                await target.edit(embed=embed)
                await interaction.response.send_message(
                    f"**{self.name.value.strip()}** ist jetzt auf "
                    f"Spot {min(max(spot, 1), len(entries))}"
                    + (" *(verschoben)*" if moved else "") + ".",
                    ephemeral=True,
                )
                return
            except discord.HTTPException:
                pass
        await interaction.response.send_message(embed=embed)


class DojoView(discord.ui.View):
    """Persistente View für den Add-Challenge-Button unter der Dojo-Liste."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Add Challenge",
        style=discord.ButtonStyle.secondary,
        emoji="➕",
        custom_id="dashbot:dojo_add",
    )
    async def add_challenge(self, interaction: discord.Interaction,
                            button: discord.ui.Button) -> None:
        await interaction.response.send_modal(DojoAddModal(interaction.message))


class RouteModal(discord.ui.Modal, title="Dream Hardest Route"):
    hardest = discord.ui.TextInput(
        label="Dein aktuelles Hardest Level",
        placeholder="z.B. Bloodbath",
        max_length=100,
    )
    dream = discord.ui.TextInput(
        label="Dein Dream Hardest",
        placeholder="z.B. LIMBO",
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # Routen-Bau macht mehrere API-Calls -> erst deferren
        await interaction.response.defer(ephemeral=True, thinking=True)

        current, dream_info, steps, error = await build_route(
            self.hardest.value, self.dream.value
        )
        if error:
            await interaction.followup.send(error, ephemeral=True)
            return

        start_text = (f"**{current.name}** "
                      f"({difficulty_label(current.difficulty, current.source)})"
                      if current else
                      f"„{self.hardest.value}“ (nicht gefunden — "
                      f"ich starte bei Medium Demon)")
        dream_text = (f"**{dream_info.name}** "
                      f"({difficulty_label(dream_info.difficulty, dream_info.source)})")

        lines = [f"Start: {start_text}", ""]
        for i, s in enumerate(steps, 1):
            line = (f"`{i}.` **{s.name}** von {s.creator} "
                    f"({difficulty_label(s.difficulty, s.source)})")
            if s.tags:
                line += f"\n{'':6}Tags: {', '.join(sorted(s.tags))}"
            lines.append(line)
        if not steps:
            lines.append("*Kein Zwischenschritt nötig — dein Dream ist in Reichweite!*")
        lines += ["", f"Ziel: {dream_text} 🏁"]

        embed = discord.Embed(
            title=f"Route zu {dream_info.name}",
            color=discord.Color.purple(),
            description="\n".join(lines),
        )
        embed.set_footer(text="Empfohlene Reihenfolge, von leicht nach schwer — "
                              "die Level passen zum Skill-Set deines Dream-Levels.")
        await interaction.followup.send(embed=embed, ephemeral=True)


class RouteView(discord.ui.View):
    """Persistente View für den Route-Button."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Route erstellen",
        style=discord.ButtonStyle.primary,
        emoji="🗺️",
        custom_id="dashbot:route",
    )
    async def create_route(self, interaction: discord.Interaction,
                           button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RouteModal())


class ChallengeView(discord.ui.View):
    """Persistenter "Gebeated"-Button mit Zähler unter jeder Challenge."""

    def __init__(self, count: int = 0) -> None:
        super().__init__(timeout=None)
        self.beaten.label = f"Gebeated ({count})"

    @discord.ui.button(
        label="Gebeated (0)",
        style=discord.ButtonStyle.success,
        custom_id="dashbot:challenge_beaten",
    )
    async def beaten(self, interaction: discord.Interaction,
                     button: discord.ui.Button) -> None:
        entry = challenges.toggle_beaten(
            interaction.message.id, interaction.user.id,
            interaction.user.display_name,
        )
        count = len(entry["beaters"])

        embed = interaction.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if field.name.startswith("Gebeated von"):
                embed.set_field_at(
                    i, name=f"Gebeated von ({count})",
                    value=challenges.beaters_text(entry), inline=False,
                )
                break

        # Bild frisch anhängen und im Embed referenzieren — sonst zeigt
        # Discord den Anhang nach dem Edit zusätzlich einzeln an
        kwargs = {}
        image = entry.get("image")
        image_path = challenges.IMAGES_DIR / image if image else None
        if image_path is not None and image_path.exists():
            embed.set_image(url=f"attachment://{image}")
            kwargs["attachments"] = [discord.File(image_path, filename=image)]
        elif interaction.message.attachments:
            embed.set_image(
                url=f"attachment://{interaction.message.attachments[0].filename}"
            )

        await interaction.response.edit_message(
            embed=embed, view=ChallengeView(count), **kwargs
        )


class DashBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True  # für Auto-Rolle bei Join + Member-Suche
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        self.add_view(PanelView())
        self.add_view(HardestView())
        self.add_view(ChallengeView())
        self.add_view(RouteView())
        self.add_view(DojoView())
        if TEST_GUILD_IDS:
            for guild_id in TEST_GUILD_IDS:
                guild = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=guild)
                try:
                    await self.tree.sync(guild=guild)
                    print(f"Commands gesynct auf Server {guild_id}")
                except discord.Forbidden:
                    print(f"Kein Zugriff auf Server {guild_id} — "
                          f"Bot dort erst einladen!")
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        print(f"Eingeloggt als {self.user} (ID: {self.user.id})")

    async def on_member_join(self, member: discord.Member) -> None:
        role = member.guild.get_role(JOIN_ROLE_ID)
        if role is not None:
            try:
                await member.add_roles(role, reason="Auto-Rolle bei Join")
            except discord.Forbidden:
                print(f"Keine Berechtigung für Join-Rolle auf {member.guild.name}")


bot = DashBot()


@bot.tree.command(name="panel", description="Postet das Level-Suggestion-Panel.")
@app_commands.default_permissions(manage_guild=True)
async def panel(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Level Suggestion",
        color=discord.Color.blurple(),
        description=(
            "Klick unten auf **Suggest Level**,\n"
            "fülle die drei Felder aus und der Bot gibt dir ein Level!"
        ),
    )
    await interaction.response.send_message(embed=embed, view=PanelView())


@bot.tree.command(name="hardest",
                  description="Zeigt die Hardest Levels aller Member, sortiert nach Schwierigkeit.")
@app_commands.guild_only()
async def hardest_board(interaction: discord.Interaction) -> None:
    # beim ersten Aufruf werden alle Start-Level online eingeordnet -> deferren
    await interaction.response.defer()
    await hardest.ensure_board(interaction.guild_id)
    await interaction.followup.send(
        embed=hardest.build_embed(interaction.guild_id), view=HardestView()
    )


@bot.tree.command(name="challenge",
                  description="Poste deine selbstgebaute Challenge mit Screenshot.")
@app_commands.describe(
    name="Name der Challenge",
    level_id="Level-ID der Challenge",
    tags="2-3 Skill-Tags, mit Komma getrennt (z.B. Wave, Timing, Spam)",
    screenshot="Screenshot / Gameplay-Preview",
)
@app_commands.guild_only()
async def challenge(interaction: discord.Interaction, name: str, level_id: str,
                    tags: str, screenshot: discord.Attachment) -> None:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()][:3]
    if len(tag_list) < 2:
        await interaction.response.send_message(
            "Bitte gib 2-3 Skill-Tags an, mit Komma getrennt — "
            "z.B. `Wave, Timing` oder `Spam, Straight Fly, Duals`.",
            ephemeral=True,
        )
        return
    if not (screenshot.content_type or "").startswith("image/"):
        await interaction.response.send_message(
            "Der Anhang muss ein Bild sein (Screenshot/Gameplay-Preview).",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=name,
        color=discord.Color.orange(),
        description=" ".join(f"`{t}`" for t in tag_list)
                    + f"\nLevel-ID: `{level_id}`",
    )
    embed.set_author(
        name=f"Challenge von {interaction.user.display_name}",
        icon_url=interaction.user.display_avatar.url,
    )
    embed.add_field(name="Gebeated von (0)", value="noch niemand", inline=False)

    # Bild lokal sichern, damit es bei jedem Button-Edit neu angehängt
    # werden kann (verhindert doppelte Anzeige nach Edits)
    ext = Path(screenshot.filename).suffix.lower() or ".png"
    image_name = f"{interaction.id}{ext}"
    image_path = challenges.IMAGES_DIR / image_name
    await screenshot.save(image_path)

    file = discord.File(image_path, filename=image_name)
    embed.set_image(url=f"attachment://{image_name}")

    await interaction.response.send_message(
        embed=embed, file=file, view=ChallengeView()
    )
    message = await interaction.original_response()
    challenges.register(message.id, name, interaction.user.id, image=image_name)


@bot.tree.command(name="route",
                  description="Postet das Dream-Hardest-Route-Panel.")
@app_commands.default_permissions(manage_guild=True)
async def route_panel(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Dream Hardest Route",
        color=discord.Color.purple(),
        description=(
            "Klick unten auf **Route erstellen**,\n"
            "gib dein aktuelles Hardest und dein Dream Hardest ein\n"
            "und der Bot baut dir deine persönliche Level-Route!"
        ),
    )
    await interaction.response.send_message(embed=embed, view=RouteView())


@bot.tree.command(name="dojolist",
                  description="Zeigt die Dojo-Challenge-Liste (schwerste zuerst).")
@app_commands.guild_only()
async def dojo_list(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        embed=dojolist.build_embed(interaction.guild_id), view=DojoView()
    )


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "Kein Token gefunden! Lege eine .env-Datei mit DISCORD_TOKEN=... an "
            "(siehe .env.example)."
        )
    bot.run(TOKEN)
