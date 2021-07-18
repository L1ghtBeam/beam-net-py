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

        # content and components
        def generate_components(start_disabled):
            start_button = create_button(
                style=ButtonStyle.green,
                label="Create Match",
                disabled=start_disabled,
                custom_id="start_game"
            )

            return spread_to_rows(mode_select, host_select, start_button)
        
        def generate_content(ctx, mode, host):
            content = "Please choose a mode and a host for the match."
            if mode:
                content += f"\nMode: `{mode}`"
            else:
                content += "\nMode: `none`"

            if host:
                member = discord.utils.get(ctx.guild.members, id=host)
                content += f"\nHost: `{member}`"
            else:
                content += "\nHost: `none`"
            return content

        mode = None
        host = None

        msg = await ctx.send(content=generate_content(ctx, mode, host), components=generate_components(True))
        
        while True:
            try:
                component_ctx = await wait_for_component(self.bot, messages=msg, timeout=60.0)
            except asyncio.TimeoutError:
                await msg.edit(content="Took too long! Please try again.", components=None)
                return
            
            if component_ctx.custom_id == "set_mode":
                mode = component_ctx.selected_options[0]

            elif component_ctx.custom_id == "set_host":
                host = int(component_ctx.selected_options[0])
                
            elif component_ctx.custom_id == "start_game":
                await msg.edit(content="Starting the match!", components=None)
                logging.info("Starting a match!") # TODO: start match here
                break

            ready = mode is None or host is None
            await component_ctx.edit_origin(content=generate_content(ctx, mode, host), components=generate_components(False))


def setup(bot):
    bot.add_cog(Matchmaker(bot))