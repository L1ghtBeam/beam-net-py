import discord
from discord.ext import commands, tasks
from discord.mentions import AllowedMentions
from discord_slash import cog_ext, SlashContext, ComponentContext
from discord_slash.utils.manage_commands import create_option, SlashCommandOptionType
from discord_slash.utils.manage_components import ButtonStyle, create_actionrow, create_button, wait_for_component

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

    async def join_queue(self, ctx: ComponentContext, internal_name):
        try:
            mode = await self.bot.pg_con.fetchrow("SELECT name, status FROM modes WHERE internal_name = $1", internal_name)
            if not mode:
                logging.error(f"Mode {internal_name} not found! Button {ctx.custom_id} was clicked.")
                await ctx.send("Mode not found!", hidden=True) 
                return
            
            if mode['status'] == 0:
                await ctx.send(f"**{mode['name']}** is currently unavailable.", hidden=True)
                return
            elif mode['status'] == 2:
                await ctx.send(f"**{mode['name']}** is temporarily unavailable.", hidden=True)
                return

            # TODO: Check if player is in party. If they are, prevent the player from joining if they are not the party leader.
            # If they are the leader, add their entire team to the queue and do the checks below for all of them

            # prevent players from joining if they are already in a game
            games = await self.bot.pg_con.fetch(
                "SELECT game_active, alpha_players, bravo_players FROM games WHERE game_active = true AND ($1 = ANY (alpha_players::bigint[]) OR $1 = ANY (bravo_players::bigint[]))",
                ctx.author_id
            )
            if games:
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
                "SELECT * FROM queue WHERE $1 = ANY (player_ids::bigint[]) AND mode = $2",
                ctx.author_id, internal_name
            )
            if queue:
                await ctx.send(f"You are already in queue for **{mode['name']}**.", hidden=True)
                return
            
            ratings = await self.bot.pg_con.fetchrow(
                "SELECT * FROM ratings WHERE user_id = $1 AND mode = $2",
                ctx.author_id, internal_name
            )
            if not ratings:
                ratings = await self.bot.pg_con.fetchrow(
                    "INSERT INTO ratings (user_id, mode, rating, deviation, volatility) VALUES ($1, $2, $3, $4, $5) RETURNING rating, deviation, volatility",
                    ctx.author_id, internal_name, 1500.0, 350.0, 0.06
                )

            await self.bot.pg_con.execute(
                "INSERT INTO queue (mode, player_count, player_ids, ratings, deviations, volatilities, join_date) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                internal_name, 1, [ctx.author_id], [ratings['rating']], [ratings['deviation']], [ratings['volatility']], pytz.utc.localize(datetime.utcnow())
            )

        except Exception as error:
            logging.exception("Join queue error!", exc_info=error)
            await ctx.send(f"There was an error joining **{mode['name']}**.", hidden=True)
        else:
            await ctx.send(f"Joined the queue for **{mode['name']}**.", hidden=True)

    async def leave_queue(self, ctx: ComponentContext, internal_name):
        mode = await self.bot.pg_con.fetchrow("SELECT name, status FROM modes WHERE internal_name = $1", internal_name)
        if not mode:
            logging.error(f"Mode {internal_name} not found! Button {ctx.custom_id} was clicked.")
            await ctx.send("Mode not found!", hidden=True) 
            return

        result = await self.bot.pg_con.execute(
            "DELETE FROM queue WHERE $1 = ANY (player_ids::bigint[]) AND mode = $2",
            ctx.author_id, internal_name
        )
        if result == "DELETE 1":
            await ctx.send(f"Left the queue for **{mode['name']}**.", hidden=True)
        elif result == "DELETE 0":
            await ctx.send(f"You were not in queue for **{mode['name']}**.", hidden=True)
        else:
            logging.error(f"Result \"{result}\" received when leaving {mode['internal_name']}!")
            await ctx.send(f"Left the queue for **{mode['name']}**.", hidden=True)

    @tasks.loop(seconds=15.0)
    async def update_modes(self):
        channel = discord.utils.get(self.bot.get_all_channels(), guild__id=bot_data['guild_id'], name='modes')

        gather = await asyncio.gather(
            channel.history(limit=100).flatten(),
            self.bot.pg_con.fetch("SELECT * FROM modes ORDER BY sort_order ASC")
        )
        messages = gather[0]
        modes = gather[1]
        change = len(modes) - len(messages) + 1

        # create or delete messages
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
        
        i = 0
        for mode in modes:
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
                disabled = True
                label = "Currently Unavailable"
                style = ButtonStyle.red
            elif mode['status'] == 1:
                disabled = False
                label = "Join Queue"
                style = ButtonStyle.green
            else:
                disabled = True
                label = "Temporarily Unavailable"
                style = ButtonStyle.green

            if mode['status'] in (1, 2):
                queue = await self.bot.pg_con.fetch(
                    "SELECT * FROM queue WHERE mode = $1",
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

            b1 = create_button(style=style, label=label, custom_id=f"mode_join_{mode['internal_name']}", disabled=disabled)
            b2 = create_button(style=ButtonStyle.red, label="Leave Queue", custom_id=f"mode_leave_{mode['internal_name']}", disabled=False)

            if style == ButtonStyle.green:
                components = [create_actionrow(b1, b2)]
            else:
                components = [create_actionrow(b1)]

            asyncio.create_task(
                messages[i].edit(content=None, embed=embed, components=components)
            )
            i += 1
        
        embed = discord.Embed(
            colour = discord.Colour.blue(),
            title="Info",
            description="Modes are listed below. Multiple modes can be queued for at the same time. If you are on mobile, please scroll down after clicking any button."
        )
        embed.set_thumbnail(url=ICON_URL)

        components = [
            create_actionrow(
                create_button(
                    style=ButtonStyle.blue,
                    label="View Joined Queues",
                    custom_id="list_joined_modes"
                ),
                create_button(
                    style=ButtonStyle.red,
                    label="Leave All Queues",
                    custom_id="leave_all_modes"
                )
            )
        ]

        asyncio.create_task(
            messages[i].edit(content=None, embed=embed, components=components)
        )

    @update_modes.before_loop
    async def before_update_modes(self):
        await self.bot.wait_until_ready()
        logging.info("Starting mode updater.")
    
    @update_modes.error
    async def error_update_modes(self, error):
        logging.exception("Mode Updater error!", exc_info=error)

    @commands.Cog.listener()
    async def on_component(self, ctx: ComponentContext):
        if ctx.custom_id[:9] == "mode_join":
            await self.join_queue(ctx, ctx.custom_id[10:])

        elif ctx.custom_id[:10] == "mode_leave":
            await self.leave_queue(ctx, ctx.custom_id[11:])

    @cog_ext.cog_component()
    async def list_joined_modes(self, ctx: ComponentContext):
        queue = await self.bot.pg_con.fetch(
            "SELECT mode, player_ids FROM queue WHERE $1 = ANY (player_ids::bigint[])",
            ctx.author_id
        )
        if not queue:
            await ctx.send(f"You are not in any queues!", hidden=True)
        else:
            modes = await self.bot.pg_con.fetch(
                "SELECT internal_name, name FROM modes",
            )   
            content = "You are currently in queue for:"
            for queue_mode in queue:
                for mode in modes:
                    if mode['internal_name'] == queue_mode['mode']:
                        content += f"\n**{mode['name']}**"
                        break
            await ctx.send(content=content, hidden=True)
    
    @cog_ext.cog_component()
    async def leave_all_modes(self, ctx: ComponentContext):
        result = await self.bot.pg_con.execute(
            "DELETE FROM queue WHERE $1 = ANY (player_ids::bigint[])",
            ctx.author_id
        )
        num = result[7:]
        if num == "0":
            await ctx.send("You are not in a queue!", hidden=True)
        elif num == "1":
            await ctx.send(f"Left `{num}` queue.", hidden=True)
        else:
            await ctx.send(f"Left `{num}` queues.", hidden=True)

def setup(bot):
    bot.add_cog(Modes(bot))