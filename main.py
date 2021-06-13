import discord
from discord.ext import commands
from discord_slash import SlashCommand

import logging, os, asyncpg, json


DB_PORT = '5432'

# get bot data from bot.json file
with open("bot.json", "r") as f:
    bot_data = json.load(f)


# logging to discord.log
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(handler)


intents = discord.Intents.all()
intents.presences = False

help_command = commands.DefaultHelpCommand(
    no_category = 'Utility'
)

bot = commands.Bot(
    activity = discord.Activity(type=discord.ActivityType.listening, name='slash commands'),
    command_prefix = commands.when_mentioned_or('.'),
    help_command = help_command,
    intents=intents,
)
slash = SlashCommand(bot, sync_commands=False, sync_on_cog_reload=False)

bot.GUILD_IDS = bot_data['guild_ids']

async def create_db_pool():
    bot.pg_con = await asyncpg.create_pool(host=bot_data['address'], port=DB_PORT, database=bot_data['name'], user='postgres', password=bot_data['pass'])

@bot.event
async def on_ready():
    logging.info(f"We have logged in as {bot.user}")
    print(f"We have logged in as {bot.user}") # don't include if logging in console

# cogs
@bot.command(
    name="cogs",
    aliases=["cog"]
)
@commands.has_permissions(administrator=True)
async def cogs(ctx: commands.Context):
    # loaded cogs
    content = "Loaded cogs: "
    for e in bot.extensions.keys():
        content += str(e)[5:] + ", "
    content = content[:-2] + "."

    # all cogs
    content += "\nAll cogs: "
    for f in os.listdir("./cogs"):
        if f == "__pycache__":
            continue
        content += f[:-3] + ", "
    content = content[:-2] + "."

    await ctx.send(content=content)

@bot.command(
    name = "load",
)
@commands.has_permissions(administrator=True)
async def load(ctx: commands.Context, cog):
    bot.load_extension(f"cogs.{cog}")
    await ctx.send(f"Successfully loaded {cog}. Make sure to use the `sync` command!")

@bot.command(
    name = "unload",
)
@commands.has_permissions(administrator=True)
async def load(ctx: commands.Context, cog):
    bot.unload_extension(f"cogs.{cog}")
    await ctx.send(f"Successfully unloaded {cog}. Make sure to use the `sync` command!")

@bot.command(
    name = "reload",
)
@commands.has_permissions(administrator=True)
async def load(ctx: commands.Context, cog):
    bot.reload_extension(f"cogs.{cog}")
    await ctx.send(f"Successfully reloaded {cog}. If any commands have been updated, make sure to use the `sync` command!")

@bot.command(
    name="sync"
)
@commands.is_owner()
async def sync(ctx: commands.Context):
    await ctx.send("Syncing commands...")
    await slash.sync_all_commands()
    await ctx.send("Completed syncing all commands!")

# load cogs
for file in os.listdir('./cogs'):
    if file.endswith('.py') and not file.startswith('_'):
        bot.load_extension(f'cogs.{file[:-3]}')

bot.loop.run_until_complete(create_db_pool())
bot.run(bot_data['token'])
