import discord
from discord.ext import commands, tasks
from discord.mentions import AllowedMentions
from discord_slash import cog_ext, SlashContext, ComponentContext
from discord_slash.utils.manage_commands import create_option, SlashCommandOptionType
from discord_slash.utils.manage_components import ButtonStyle, create_actionrow, create_button, wait_for_component

from datetime import datetime
import json, logging, asyncio

with open("bot.json", "r") as f:
    bot_data = json.load(f)


class Modes(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.update_modes.start()

    def cog_unload(self):
        self.update_modes.cancel()

    @tasks.loop(seconds=30.0)
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
                embed.add_field(
                    name="Searching",
                    value="`0` 🔎"
                )

                embed.add_field(
                    name="In-game",
                    value="`0` 🆚"
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
        embed.set_thumbnail(url="https://i.imgur.com/YmTNuR5.png")

        components = [
            create_actionrow(
                create_button(
                    style=ButtonStyle.blue,
                    label="View joined queues",
                    custom_id="list_joined_modes"
                ),
                create_button(
                    style=ButtonStyle.red,
                    label="Leave all queues",
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
            internal_name = ctx.custom_id[10:]
            mode = await self.bot.pg_con.fetchrow("SELECT name, status FROM modes WHERE internal_name = $1", internal_name)
            if not mode:
                logging.error(f"Mode {internal_name} not found! Button {ctx.custom_id} was clicked.")
                await ctx.send("Mode not found!", hidden=True) 
                return
            
            if mode['status'] == 1:
                await ctx.send(f"Joined queue for **{mode['name']}**.", hidden=True)
            elif mode['status'] == 0:
                await ctx.send(f"**{mode['name']}** is currently unavailable.", hidden=True)
            else:
                await ctx.send(f"**{mode['name']}** is temporarily unavailable.", hidden=True)

        elif ctx.custom_id[:10] == "mode_leave":
            internal_name = ctx.custom_id[11:]
            mode = await self.bot.pg_con.fetchrow("SELECT name, status FROM modes WHERE internal_name = $1", internal_name)
            if not mode:
                logging.error(f"Mode {internal_name} not found! Button {ctx.custom_id} was clicked.")
                await ctx.send("Mode not found!", hidden=True) 
                return
            await ctx.send(f"Left the queue for **{mode['name']}**.", hidden=True)
        
        # TODO: add joining and leaving queue functionality

    @cog_ext.cog_component()
    async def list_joined_modes(self, ctx: ComponentContext):
        await ctx.send(f"You are not in any queues!", hidden=True, allowed_mentions=AllowedMentions.all())
    
    @cog_ext.cog_component()
    async def leave_all_modes(self, ctx: ComponentContext):
        await ctx.send(f"Left all queues.", hidden=True)

def setup(bot):
    bot.add_cog(Modes(bot))