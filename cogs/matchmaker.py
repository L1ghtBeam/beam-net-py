import discord
from discord.ext import commands
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


    async def initialize_match(self, players: list[discord.User], mode, host: discord.user):
        # split the players
        if not len(players) == 2: # TODO: Remove later once testing with two is no longer needed
            alpha = players[:4]
            bravo = players[4:]
        else:
            alpha = players[:1]
            bravo = players[1:]
        
        # put the host on alpha if they are on bravo
        if host in bravo:
            alpha, bravo = bravo, alpha
        
        # move host to start of the list
        alpha.remove(host)
        alpha.insert(0, host)

        # convert to ids
        alpha_players = []
        for player in alpha:
            alpha_players.append(player.id)

        bravo_players = []
        for player in bravo:
            bravo_players.append(player.id)
        
        host_id = host.id

        # grab rating info
        async def grab_player_data(player): # TODO: make this a util function since it's directly copied from modes.py
            ratings = await self.bot.pg_con.fetchrow(
                    "SELECT user_id, mode, rating, deviation, volatility FROM ratings WHERE user_id = $1 AND mode = $2",
                    player.id, mode['internal_name']
                )
            if not ratings:
                ratings = await self.bot.pg_con.fetchrow(
                    "INSERT INTO ratings (user_id, mode, rating, deviation, volatility) VALUES ($1, $2, $3, $4, $5) RETURNING rating, deviation, volatility",
                    player.id, mode['internal_name'], 1500.0, 350.0, 0.06
                )
            return ratings

        alpha_ratings = []
        alpha_deviations = []
        alpha_volatilities = []

        for player in alpha:
            p_data = await grab_player_data(player)
            alpha_ratings.append(p_data['rating'])
            alpha_deviations.append(p_data['deviation'])
            alpha_volatilities.append(p_data['volatility'])
        
        bravo_ratings = []
        bravo_deviations = []
        bravo_volatilities = []

        for player in bravo:
            p_data = await grab_player_data(player)
            bravo_ratings.append(p_data['rating'])
            bravo_deviations.append(p_data['deviation'])
            bravo_volatilities.append(p_data['volatility'])

        # generate score list for how many games in the mode
        score = [0] * mode['games']

        # create the database once all data is gathered
        # id, alpha_players, bravo_players, mode, host, game_maps, game_modes, admin_locked, score, alpha_ratings, alpha_deviations, alpha_volatilities, bravo_ratings, bravo_deviations, bravo_volatilities
        # TODO: add alpha and bravo group data
        game_data = await self.bot.pg_con.fetchrow(
            """INSERT INTO games (alpha_players, bravo_players, mode, host, score, start_date, alpha_ratings, alpha_deviations, alpha_volatilities, bravo_ratings, bravo_deviations, bravo_volatilities)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) RETURNING id""",
            alpha_players, bravo_players, mode['internal_name'], host_id, score, pytz.utc.localize(datetime.utcnow()), alpha_ratings, alpha_deviations, alpha_volatilities, bravo_ratings, bravo_deviations, bravo_volatilities
        )

        # build the channels
        guild = discord.utils.get(self.bot.guilds, id=bot_data['guild_id'])
        template_category = discord.utils.get(guild.categories, name="match template")

        reason = f"Creating game #{game_data['id']}."

        category = await template_category.clone(name=f"match #{game_data['id']}", reason=reason)
        coroutines = []
        for channel in template_category.channels:
            coroutines.append(
                channel.clone(reason=reason)
            )
        channels = await asyncio.gather(*coroutines)

        # move
        for channel in channels:
            await channel.move(category=category, end=True, reason=reason)
        
        # move and set permissions
        async def set_text_perms(channel, players):
            for player in players:
                await channel.set_permissions(player, view_channel=True)

        async def set_voice_perms(channel, players):
            for player in players:
                await channel.set_permissions(player, view_channel=True, connect=True)

        await asyncio.gather(
            set_text_perms(channels[0], alpha + bravo),
            set_text_perms(channels[1], alpha),
            set_text_perms(channels[2], bravo),
            set_voice_perms(channels[3], alpha),
            set_voice_perms(channels[4], bravo),
        )

        # send messages
        embed = discord.Embed(
            colour=discord.Color.blue(),
            title=f"Match #{game_data['id']} - {mode['name']}",
            description=mode['description'],
            timestamp=datetime.utcnow()
        )
        if mode['thumbnail']:
            embed.set_thumbnail(url=mode['thumbnail'])

        def gen_players(players):
            value = ""
            for player in players:
                if player.nick:
                    value += f"{player.nick} ({player})\n"
                else:
                    value += f"{player.name} (#{player.discriminator})\n"
            return value[:-1]

        embed.add_field(name="__Alpha Team:__", value=gen_players(alpha))
        embed.add_field(name="__Bravo Team:__", value=gen_players(bravo))

        host_data = await self.bot.pg_con.fetchrow("SELECT user_id, friend_code FROM users WHERE user_id = $1", host_id)
        if host_data['friend_code']:
            fc = host_data['friend_code']
            fc = f"SW-{fc[:4]}-{fc[4:8]}-{fc[8:]}" # TODO: make this a util function
        else:
            fc = "unknown fc"
        embed.add_field(name=f"The host of this match is {host.name}.", value=f"Please add `{fc}` to your friend list.", inline=False)

        content = ""
        for player in players:
            content += player.mention + " "

        msg1 = await channels[0].send(content=content[:-1], embed=embed) # TODO: send a "report match issue" button

        # send additional message for map generation
        button = create_button(
            style=ButtonStyle.green,
            label="Generate Maps",
            custom_id=f"generate_maps_{game_data['id']}",
        )
        components = spread_to_rows(button)

        embed = discord.Embed(
            colour=discord.Color.blue(),
            title=f"Maps are not generated.",
            description="Click the button below to reveal the maps.",
            timestamp=datetime.utcnow()
        )

        msg2 = await channels[0].send(embed=embed, components=components)

        # pin messages
        await asyncio.gather(
            msg2.pin(),
            msg1.pin()
        )

        # mark all players as last played on this date
        now = pytz.utc.localize(datetime.utcnow())
        for player in players:
            await self.bot.pg_con.execute("UPDATE users SET last_played = $2 WHERE user_id = $1", player.id, now)


    # Alpha are the first 4 players, Bravo are the last 4
    # can include only 2 players for testing
    async def create_match(self, players: list[discord.User], mode: str, host: discord.User):
        try:
            # get name and thumbnail of the mode to send to players
            mode_data = await self.bot.pg_con.fetchrow(
                "SELECT * FROM modes WHERE internal_name = $1",
                mode
            )
            coroutines = []
            for player in players:
                await self.bot.pg_con.execute(
                    "UPDATE users SET queue_disable_time = $2 WHERE user_id = $1",
                    player.id, pytz.utc.localize(datetime.utcnow())+relativedelta(seconds=+25)
                )
                await self.bot.pg_con.execute(
                    "UPDATE queue SET available = false WHERE $1 = ANY (player_ids::bigint[]) AND available = true",
                    player.id
                )
                coroutines.append(
                    self.send_ready_message(player, mode_data)
                )

            players_ready = await asyncio.gather(*coroutines) # send ready message to all players and wait for all responces

            coroutines = []
            if False in players_ready:
                for i in range(len(players_ready)):
                    if not players_ready[i]:
                        coroutines.append(
                            self.send_info_message(players[i], "You did not accept the match and have been removed from the queue!"), #TODO: send different messages for groups
                        )
                        await self.bot.pg_con.execute(
                                "DELETE FROM queue WHERE $1 = ANY (player_ids::bigint[])",
                                players[i].id
                            )
                    else:
                        coroutines.append(
                            self.send_info_message(players[i], "A player did not accept the match."), #TODO: send different messages for groups
                        )
                        await self.bot.pg_con.execute(
                                "UPDATE queue SET available = true WHERE $1 = ANY (player_ids::bigint[])",
                                players[i].id
                        )
                await asyncio.gather(*coroutines)
                return False
            else:
                for player in players:
                    coroutines.append(
                        self.send_info_message(player, "All players accepted. Creating the match."),
                    )
                    await self.bot.pg_con.execute(
                                "DELETE FROM queue WHERE $1 = ANY (player_ids::bigint[])",
                                player.id
                        )
                await asyncio.gather(*coroutines)

                await self.initialize_match(players, mode_data, host)
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
        players = [player1, player2, player3, player4, player5, player6, player7, player8]

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
                    result = await self.create_match(players, mode, member)
                    if result:
                        await ctx.send("Match successfully created.")
                    else:
                        await ctx.send("Some players did not hit ready!")
                    break


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
        players = [player1, player2]

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
                    result = await self.create_match(players, mode, member)
                    if result:
                        await ctx.send("Match successfully created.")
                    else:
                        await ctx.send("Some players did not hit ready!")
                    break


def setup(bot):
    bot.add_cog(Matchmaker(bot))