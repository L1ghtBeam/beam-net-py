import discord
from discord.ext import commands, tasks
from discord.mentions import AllowedMentions
from discord_slash import cog_ext, SlashContext, ComponentContext
from discord_slash.utils.manage_commands import create_option, SlashCommandOptionType
from discord_slash.utils.manage_components import ButtonStyle, create_button, create_select_option, spread_to_rows, create_select

from datetime import datetime
import json, logging, asyncio, pytz

ICON_URL = "https://i.imgur.com/YmTNuR5.png"
with open("bot.json", "r") as f:
    bot_data = json.load(f)


class Modes(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.update_modes.start()

    def cog_unload(self):
        self.update_modes.cancel()


    def list_modes(self, internal_names, modes):
        #modes = await self.bot.pg_con.fetch("SELECT internal_name, name FROM modes WHERE internal_name = ANY ($1::varchar[]);", internal_names)   
        content = ""
        for internal_name in internal_names:
            for mode in modes:
                if mode['internal_name'] == internal_name:
                    if mode['emoji_id']:
                        emoji = self.bot.get_emoji(mode['emoji_id'])
                        if emoji:
                            emoji = str(emoji)
                        else:
                            emoji = ""
                    else:
                        emoji = ""
                    content += f"\n{emoji} {mode['name']}"
                    break
        return content


    def elapsed_time(self, time):
        now = pytz.utc.localize(datetime.utcnow())
        time = (now - time).seconds

        minutes = str(time // 60).zfill(2)
        seconds = str(time % 60).zfill(2)
        return f"{minutes}:{seconds}"


    @tasks.loop(seconds=15.0)
    async def update_modes(self):
        channel = discord.utils.get(self.bot.get_all_channels(), guild__id=bot_data['guild_id'], name='modes')

        gather = await asyncio.gather(
            channel.history(limit=100).flatten(),
            self.bot.pg_con.fetch("SELECT * FROM modes ORDER BY sort_order ASC")
        )
        messages = gather[0]
        modes = gather[1]
        
        visible_modes = 0
        for mode in modes:
            if mode['status'] >= 0:
                visible_modes += 1

        # create or delete messages
        change = visible_modes - len(messages) + 1
        if change > 0:
            for i in range(change):
                msg = await channel.send("...")
                messages.insert(0, msg)
        elif change < 0:
            change = abs(change)
            for i in range(change):
                index = len(messages) - 1
                await messages[index].delete()
                del messages[index]

        options = []
        i = 1
        for mode in modes:
            if mode['status'] < 0:
                continue

            embed = discord.Embed(
                colour = discord.Colour.blue(),
                title=mode['name'],
                description=mode['description'],
            )
            if mode['image_url']:
                embed.set_image(url=mode['image_url'])
            if mode['thumbnail']:
                embed.set_thumbnail(url=mode['thumbnail'])

            if mode['status'] == 0:
                status = "CLOSED"
            elif mode['status'] == 1:
                status = "OPEN"
            elif mode['status'] == 2:
                status = "TEMPORARILY UNAVAILABLE",
            else:
                status = "UNKNOWN"
            embed.add_field(name="Status", value=f"`{status}`") # TODO: made this inline false when more information is given

            if mode['status'] in (1, 2):
                queue = await self.bot.pg_con.fetch(
                    "SELECT * FROM queue WHERE $1 = ANY (modes::varchar[])",
                    mode['internal_name']
                )
                search_count = len(queue)
                embed.add_field(
                    name="Searching",
                    value=f"`{search_count}` 🔎"
                )

                games = await self.bot.pg_con.fetch(
                    "SELECT * FROM games WHERE mode = $1 AND game_active = true",
                    mode['internal_name']
                )
                play_count = 0
                for game in games:
                    play_count += len(game['alpha_players'])
                    play_count += len(game['bravo_players'])
                embed.add_field(
                    name="In-game",
                    value=f"`{play_count}` 🆚"
                )

            asyncio.create_task(messages[i].edit(content=None, embed=embed, components=None))

            if mode['status'] == 1:
                emoji = self.bot.get_emoji(mode['emoji_id']) if mode['emoji_id'] else None
                options.append(create_select_option(
                    label=mode['name'],
                    value=mode['internal_name'],
                    description=mode['description_brief'],
                    emoji=emoji,
                    default=False
                ))
            i += 1

        embed = discord.Embed(
            colour = discord.Colour.blue(),
            title="Info",
            description="Modes are listed above. Use the selector below to choose which modes to queue for. Multiple modes can be queued for at the same time."
        )
        embed.set_thumbnail(url=ICON_URL)

        if options == []:
            disabled = True
            options = [create_select_option(
                label="None",
                value="null_mode"
            )]
        else:
            disabled = False

        components = spread_to_rows(
            create_select(
                options=options,
                custom_id="join_queue",
                placeholder="Select modes to join.",
                min_values=1,
                max_values=len(options),
                disabled=disabled
            ),
            create_button(
                style=ButtonStyle.blue,
                label="View Joined Modes",
                custom_id="show_queue"
            ),
            create_button(
                style=ButtonStyle.red,
                label="Leave The Queue",
                custom_id="leave_queue"
            ),
        )

        await messages[0].edit(content=None, embed=embed, components=components)


    @update_modes.before_loop
    async def before_update_modes(self):
        await self.bot.wait_until_ready()
        logging.info("Starting mode updater.")
    

    @update_modes.error
    async def error_update_modes(self, error):
        logging.exception("Mode Updater error!", exc_info=error)


    @cog_ext.cog_component()
    async def join_queue(self, ctx: ComponentContext):
        try:
            modes = await self.bot.pg_con.fetch("SELECT name, internal_name, status, emoji_id FROM modes WHERE internal_name = ANY ($1::varchar[])", ctx.selected_options)

            for mode in modes:
                if mode['status'] == 2:
                    await ctx.send(f"**{mode['name']}** is temporarily unavailable.", hidden=True)
                    return
                elif mode['status'] != 1:
                    await ctx.send(f"**{mode['name']}** is currently unavailable.", hidden=True)
                    return

            # TODO: Check if player is in party. If they are, prevent the player from joining if they are not the party leader.
            # If they are the leader, add their entire team to the queue and do the checks below for all of them

            # prevent players from joining if they are already in a game
            game = await self.bot.pg_con.fetchrow(
                "SELECT game_active, alpha_players, bravo_players FROM games WHERE game_active = true AND ($1 = ANY (alpha_players::bigint[]) OR $1 = ANY (bravo_players::bigint[]))",
                ctx.author_id
            )
            if game:
                await ctx.send("You must finish your current match before starting a new one!", hidden=True)
                return
            
            # check if queue_disable_time has passed or not
            user = await self.bot.pg_con.fetchrow(
                "SELECT user_id, queue_disable_time FROM users WHERE user_id = $1",
                ctx.author_id
            )
            if user['queue_disable_time']:
                if pytz.utc.localize(datetime.utcnow()) < user['queue_disable_time']:
                    await ctx.send("You cannot join the queue at this time!", hidden=True)
                    return
                else:
                    await self.bot.pg_con.execute(
                        "UPDATE users SET queue_disable_time = $2 WHERE user_id = $1",
                        ctx.author_id, None
                    )

            queue = await self.bot.pg_con.fetchrow(
                "SELECT * FROM queue WHERE $1 = ANY (player_ids::bigint[])",
                ctx.author_id
            )
            if queue:
                await ctx.send(f"Please leave your queue before joining a new one.", hidden=True)
                return
            
            # TODO: use this code elsewhere to generate ratings
            # ratings = await self.bot.pg_con.fetchrow( 
            #     "SELECT * FROM ratings WHERE user_id = $1 AND mode = $2",
            #     ctx.author_id, internal_name
            # )
            # if not ratings:
            #     ratings = await self.bot.pg_con.fetchrow(
            #         "INSERT INTO ratings (user_id, mode, rating, deviation, volatility) VALUES ($1, $2, $3, $4, $5) RETURNING rating, deviation, volatility",
            #         ctx.author_id, internal_name, 1500.0, 350.0, 0.06
            #     )

            await self.bot.pg_con.execute(
                "INSERT INTO queue (modes, player_count, player_ids, join_date) VALUES ($1, $2, $3, $4)",
                ctx.selected_options, 1, [ctx.author_id], pytz.utc.localize(datetime.utcnow())
            )

        except Exception as error:
            logging.exception("Join queue error!", exc_info=error)
            await ctx.send(f"There was an error joining the queue!", hidden=True)
        else:
            await ctx.send(f"Joined the queue for: **{self.list_modes(ctx.selected_options, modes)}**", hidden=True)


    @cog_ext.cog_component()
    async def show_queue(self, ctx: ComponentContext):
        queue = await self.bot.pg_con.fetchrow(
            "SELECT modes, player_ids, join_date FROM queue WHERE $1 = ANY (player_ids::bigint[])",
            ctx.author_id
        )
        if not queue:
            await ctx.send(f"You are not in the queue.", hidden=True)
        else:
            modes = await self.bot.pg_con.fetch("SELECT internal_name, name, emoji_id FROM modes WHERE internal_name = ANY ($1::varchar[]);", queue['modes'])
            content = f"You are currently in queue for: **{self.list_modes(queue['modes'], modes)}**\nElapsed time: `{self.elapsed_time(queue['join_date'])}`"
            await ctx.send(content=content, hidden=True)
    

    @cog_ext.cog_component()
    async def leave_queue(self, ctx: ComponentContext):
        result = await self.bot.pg_con.fetchrow( # TODO: only allow the party leader to leave
            "DELETE FROM queue WHERE $1 = ANY (player_ids::bigint[]) RETURNING *",
            ctx.author_id
        )
        if result:
            await ctx.send(f"You left the queue!\nElapsed time: `{self.elapsed_time(result['join_date'])}`", hidden=True)
        else:
            await ctx.send(f"You are not in the queue.", hidden=True)


def setup(bot):
    bot.add_cog(Modes(bot))