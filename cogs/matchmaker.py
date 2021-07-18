import discord
from discord.ext import commands
from discord_slash import cog_ext, SlashContext, ComponentContext
from discord_slash.utils.manage_commands import create_option, SlashCommandOptionType, create_permission
from discord_slash.utils.manage_components import create_select, create_select_option, spread_to_rows, create_button, wait_for_component
from discord_slash.model import SlashCommandPermissionType, ButtonStyle, ComponentType

from datetime import datetime
import json, logging, asyncio, pytz

with open("bot.json", "r") as f:
    bot_data = json.load(f)


class Matchmaker(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @cog_ext.cog_subcommand(
        base="match",
        name="create",
        description="Create a new 4v4 match on any mode.",
        options=[
            create_option(
                name="player1",
                description="The first player of team Alpha.",
                option_type=SlashCommandOptionType.USER,
                required=True
            ),
            create_option(
                name="player2",
                description="The second player of team Alpha.",
                option_type=SlashCommandOptionType.USER,
                required=True
            ),
            create_option(
                name="player3",
                description="The third player of team Alpha.",
                option_type=SlashCommandOptionType.USER,
                required=True
            ),
            create_option(
                name="player4",
                description="The fourth player of team Alpha.",
                option_type=SlashCommandOptionType.USER,
                required=True
            ),
            create_option(
                name="player5",
                description="The first player of team Bravo.",
                option_type=SlashCommandOptionType.USER,
                required=True
            ),
            create_option(
                name="player6",
                description="The second player of team Bravo.",
                option_type=SlashCommandOptionType.USER,
                required=True
            ),
            create_option(
                name="player7",
                description="The third player of team Bravo.",
                option_type=SlashCommandOptionType.USER,
                required=True
            ),
            create_option(
                name="player8",
                description="The fourth player of team Bravo.",
                option_type=SlashCommandOptionType.USER,
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
    async def create(self, ctx: SlashContext, player1, player2, player3, player4, player5, player6, player7, player8):
        pass # TODO: update this with create_test

    @cog_ext.cog_subcommand(
        base="match",
        name="create-test",
        description="Use this command to test match creation without requiring 8 players.",
        options=[
            create_option(
                name="player1",
                description="The first player of team Alpha.",
                option_type=SlashCommandOptionType.USER,
                required=True
            ),
            create_option(
                name="player2",
                description="The first player of team Bravo.",
                option_type=SlashCommandOptionType.USER,
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
    async def create_test(self, ctx: SlashContext, player1, player2):
        players = []
        players.extend([player1, player2])

        for i in range(len(players)):
            for j in range(len(players) - (i+1)):
                if players[i] == players[j + i + 1]:
                    await ctx.send("Do not use duplicate players!", hidden=True) 
                    return
        
        # mode select
        modes = await self.bot.pg_con.fetch("SELECT name, internal_name FROM modes ORDER BY sort_order ASC")

        options = []
        for mode in modes:
            options.append(create_select_option(label=mode['name'], value=mode['internal_name']))
        
        mode_select = create_select(
            options=options,
            placeholder="Choose a mode.",
            min_values=1,
            max_values=1,
            custom_id="set_mode"
        )
 
        # player host select
        coroutines = []
        for player in players:
            coroutines.append(self.bot.pg_con.fetchrow("SELECT host_pref FROM users WHERE user_id = $1", player.id))

        host_prefs = await asyncio.gather(*coroutines)
        if [] in host_prefs:
            index = host_prefs.index([])
            await ctx.send(f"{players[index]} is not registered!", hidden=True)
            return

        options = []
        for i in range(len(players)):
            emoji = ["🔴", "🟡", "🟢"][host_prefs[i]['host_pref']]
            options.append(create_select_option(label=str(players[i]), value=str(players[i].id), emoji=emoji))

        host_select = create_select(
            options=options,
            placeholder="Choose a host. 🟢 Good, 🟡 okay, 🔴 bad.",
            min_values=1,
            max_values=1,
            custom_id="set_host"
        )

        # regular start button
        start_button = create_button(
            style=ButtonStyle.green,
            label="Create Match",
            custom_id="start_game"
        )
        
        content = "Please choose a mode and a host for the match."
        mode = None
        host = None

        msg = await ctx.send(content=content, components=spread_to_rows(mode_select, host_select, start_button))
        
        while True:
            try:
                component_ctx = await wait_for_component(self.bot, messages=msg, timeout=60.0)
            except asyncio.TimeoutError:
                await msg.edit(content="Took too long! Please try again.", components=None)
                return
            
            if not ctx.author_id == component_ctx.author_id:
                await component_ctx.send("You cannot interact with this message!", hidden=True)
                continue

            elif component_ctx.custom_id == "set_mode":
                mode = component_ctx.selected_options[0]
                await component_ctx.send(f"Mode set to `{mode}`.", hidden=True)

            elif component_ctx.custom_id == "set_host":
                host = int(component_ctx.selected_options[0])
                member = discord.utils.get(ctx.guild.members, id=host)
                await component_ctx.send(f"Host set to `{member}`.", hidden=True)

            elif component_ctx.custom_id == "start_game":
                ready = not (mode is None or host is None)
                if not ready:
                    await component_ctx.send("Please select a mode and a host!", hidden=True)
                else:
                    member = discord.utils.get(ctx.guild.members, id=host)
                    await msg.edit(content=f"Starting the match!\nMode: `{mode}`\nHost: `{member}`", components=None)
                    logging.info("Starting a match!") # TODO: start match here
                    break


def setup(bot):
    bot.add_cog(Matchmaker(bot))