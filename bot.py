"""Stage Role Play | 01 - Discord -> SA-MP admin bridge (RCON).

Slash commands: /srv <command>, /online, /say <text>.
Security: only Discord IDs listed in ADMIN_DISCORD_IDS may use the bot, the ID is sent to the
game server which checks it again (scriptfiles/stage_discord.cfg), dangerous characters are rejected.
"""
import logging
import os
import re
import sys

import discord
discord.VoiceClient.warn_nacl = False  # voice is not used
from discord import app_commands
from dotenv import load_dotenv

from rcon import rcon

load_dotenv()
log = logging.getLogger("stage-bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def fatal(msg: str):
    log.error("[config] %s", msg)
    sys.exit(1)


TOKEN = os.getenv("DISCORD_TOKEN", "")
RCON_PASSWORD = os.getenv("SAMP_RCON_PASSWORD", "")
HOST = os.getenv("SAMP_HOST", "127.0.0.1")
PORT = int(os.getenv("SAMP_PORT", "7777"))
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "").strip()
ADMINS = {x.strip() for x in os.getenv("ADMIN_DISCORD_IDS", "").split(",") if x.strip()}

if not TOKEN or TOKEN.startswith("put_"):
    fatal("DISCORD_TOKEN is not set")
if not RCON_PASSWORD:
    fatal("SAMP_RCON_PASSWORD is not set")
if len(RCON_PASSWORD) < 12 or RCON_PASSWORD.lower() in {"5656", "changeme", "1234", "123456"} or "CHANGE_ME" in RCON_PASSWORD:
    fatal("SAMP_RCON_PASSWORD is weak: use at least 12 random characters (the same value as in server.cfg)")
if not ADMINS:
    fatal("ADMIN_DISCORD_IDS is empty")
for _id in ADMINS:
    if not re.fullmatch(r"\d{17,20}", _id):
        fatal(f"Invalid Discord ID in ADMIN_DISCORD_IDS: {_id}")

FORBIDDEN = re.compile(r"['\"`\\%;{}\r\n\x00]")  # same rule as the Pawn side
MAX_LEN = 200


async def send_to_server(discord_id: int, text: str) -> str:
    # the Discord ID is sent too: the game server verifies it against stage_discord.cfg
    lines = await rcon(HOST, PORT, RCON_PASSWORD, f"dc {discord_id} {text}")
    return "\n".join(lines) if lines else '(no reply - is the server online and is "query 1" enabled?)'


intents = discord.Intents.none()
intents.guilds = True


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        log.info("logged in as %s, %d authorised admin(s)", self.user, len(ADMINS))


bot = Bot()


async def run(inter: discord.Interaction, text: str):
    if str(inter.user.id) not in ADMINS:
        log.warning("[deny] %s (%s) tried /%s", inter.user, inter.user.id, inter.command.name if inter.command else "?")
        return await inter.response.send_message("Нет доступа.", ephemeral=True)
    text = text.strip()
    if not text or len(text) > MAX_LEN or FORBIDDEN.search(text):
        return await inter.response.send_message("Недопустимые символы или слишком длинная команда.", ephemeral=True)
    await inter.response.defer(ephemeral=True)
    try:
        out = await send_to_server(inter.user.id, text)
        log.info("[exec] %s (%s): %s", inter.user, inter.user.id, text)
        await inter.followup.send(f"```\n{out[:1800]}\n```", ephemeral=True)
    except Exception as e:  # network/DNS errors
        log.error("[rcon] %s", e)
        await inter.followup.send(f"Ошибка связи с сервером: {e}", ephemeral=True)


@bot.tree.command(name="srv", description="Команда администратора на игровой сервер (напр. ban 5 3 причина; help - список)")
@app_commands.describe(command="команда и аргументы")
@app_commands.guild_only()
async def srv(inter: discord.Interaction, command: str):
    await run(inter, command)


@bot.tree.command(name="online", description="Игроки онлайн")
@app_commands.guild_only()
async def online(inter: discord.Interaction):
    await run(inter, "online")


@bot.tree.command(name="say", description="Сообщение всем игрокам от имени Discord")
@app_commands.describe(text="текст")
@app_commands.guild_only()
async def say(inter: discord.Interaction, text: str):
    await run(inter, "say " + text)


if __name__ == "__main__":
    bot.run(TOKEN, log_handler=None)
