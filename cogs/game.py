import discord
from discord.ext import commands
from discord.ext.commands.core import group
from discord_slash import cog_ext, SlashContext, ComponentContext
from discord_slash.utils.manage_commands import create_option, SlashCommandOptionType, create_permission
from discord_slash.utils.manage_components import create_select, create_select_option, spread_to_rows, create_button, wait_for_component
from discord_slash.model import SlashCommandPermissionType, ButtonStyle, ComponentType

from datetime import datetime
from dateutil.relativedelta import relativedelta
import json, logging, asyncio, pytz

with open("bot.json", "r") as f:
    bot_data = json.load(f)


class Game(commands.Cog):

    def __init__(self, bot):
        self.bot = bot


    @cog_ext.cog_subcommand(
        base="match",
        name="cleanup",
        description="Cleanup the channels from a game. Does not touch the database.",
        options=[
            create_option(
                name="match",
                description="The match number.",
                option_type=SlashCommandOptionType.INTEGER,
                required=True
            ),
        ],
        base_default_permission=False,
        base_permissions={
            bot_data['guild_id']: [
                create_permission(bot_data['admin_id'], SlashCommandPermissionType.ROLE, True)
            ]
        },
        guild_ids=[bot_data['guild_id']]
    )
    async def cleanup(self, ctx: SlashContext, match: int):
        category = discord.utils.get(ctx.guild.channels, name=f'match #{match}')
        reason = f"{ctx.author} used /cleanup for match #{match}"
        logging.info(reason)

        coroutines = []
        for channel in category.channels:
            coroutines.append(
                channel.delete(reason=reason)
            )
        await asyncio.gather(*coroutines)
        await category.delete(reason=reason)
        await ctx.send("Cleanup successful!")

            
def setup(bot):
    bot.add_cog(Game(bot))