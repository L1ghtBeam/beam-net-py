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


class Matchmaker(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def send_ready_message(self, player: discord.User, mode):
        channel = player.dm_channel
        if not channel:
            channel = await player.create_dm()
        
        def generate_components(disabled, style):
            return spread_to_rows(
                create_button(
                    style=style,
                    label="Accept",
                    disabled=disabled
                )
            )

        embed = discord.Embed(
            colour = discord.Colour.blue(),
            title="Your match is ready!",
            description=f"Mode: __{mode['name']}__",
            timestamp=datetime.utcnow(),
        )
        if mode['thumbnail']:
            embed.set_thumbnail(url=mode['thumbnail'])
        
        embed.add_field(name="You have **20 seconds** to accept the match.", value="Do not accept the match if you cannot play for up to 45 minutes.")

        msg = await channel.send(embed=embed, components=generate_components(False, ButtonStyle.green))

        try:
            comp_ctx = await wait_for_component(self.bot, msg, timeout=20.0)
        except asyncio.TimeoutError:
            await msg.edit(embed=embed, components=generate_components(True, ButtonStyle.red))
            return False
        else:
            await comp_ctx.edit_origin(embed=embed, components=generate_components(True, ButtonStyle.green))
            return True

    async def send_info_message(self, player: discord.User, content):
        channel = player.dm_channel
        if not channel:
            channel = await player.create_dm()

        await channel.send(content=content)

    # Alpha are the first 4 players, Bravo are the last 4
    # can include only 2 players for testing
    async def create_match(self, players: list[discord.User], mode: str, host: discord.User):
        try:
            two_players = True if len(players) == 2 else False

            # get name and thumbnail of the mode to send to players
            mode_data = await self.bot.pg_con.fetchrow(
                "SELECT name, internal_name, thumbnail FROM modes WHERE internal_name = $1",
                mode
            )

            coroutines = []
            ready_coroutines = []
            for player in players:
                coroutines.append(
                    self.bot.pg_con.execute(
                        "UPDATE users SET queue_disable_time = $2 WHERE user_id = $1",
                        player.id, pytz.utc.localize(datetime.utcnow())+relativedelta(seconds=+25)
                    )
                )
                coroutines.append(
                    self.bot.pg_con.execute(
                        "UPDATE queue SET available = false WHERE $1 = ANY (player_ids::bigint[]) AND available = true",
                        player.id
                    )
                )
                ready_coroutines.append(
                    self.send_ready_message(player, mode_data)
                )

            await asyncio.gather(*coroutines) # mark players as not available in queue and prevent them from re-queueing
            players_ready = await asyncio.gather(*ready_coroutines) # send ready message to all players and wait for all responces

            def grab_player(user_id):
                for player in players:
                    if player.id == user_id:
                        return player

            if False in players_ready:
                logging.info("Not all players hit ready!")
                # notify players in group of player who didn't ready
                # also remove them from queue
                for i in range(len(players_ready)): # TODO: UNFINISHED CODE THAT I WILL REWORK
                    if not players_ready[i]: # if the player didn't ready
                        group_players = await self.bot.pg_con.fetchrow( # get all players in their group
                            "SELECT player_ids, mode FROM queue WHERE $1 = ANY (player_ids::bigint[]) AND mode = $2",
                            players[i].id, mode
                        )
                        if len(group_players) == 1:
                            member = players[i]
                            self.send_info_message(member, f"You did not accept the match and have been removed from queue!")
                        else:
                            for player in group_players: # for all the players their group
                                if player == players[i].id:
                                    member = players[i]
                                    asyncio.create_task(
                                        self.send_info_message(member, f"You did not accept the match and your group has been removed from queue!")
                                    )
                                else:
                                    member = grab_player(player)
                                    asyncio.create_task(
                                        self.send_info_message(member, f"{member} did not accept the match and your group has been removed from queue!")
                                    )
                        await self.bot.pg_con.execute(
                            "DELETE FROM queue WHERE $1 = ANY (player_ids::bigint[])",
                            players[i].id
                        )

                return False
            else:
                logging.info("Create a game here!")
                return True

        except Exception as error:
            logging.exception("Create match error!", exc_info=error)
            return

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
                asyncio.create_task(
                    component_ctx.send("You cannot interact with this message!", hidden=True)
                )
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
                    await self.create_match(players, mode, member)
                    break


def setup(bot):
    bot.add_cog(Matchmaker(bot))