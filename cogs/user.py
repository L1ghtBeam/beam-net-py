import discord
from discord.ext import commands
from discord_slash import cog_ext, SlashContext, ComponentContext
from discord_slash.utils.manage_commands import create_option, SlashCommandOptionType, create_permission
from discord_slash.utils.manage_components import ButtonStyle, spread_to_rows, create_button, wait_for_component
from discord_slash.model import SlashCommandPermissionType

from datetime import datetime
import json, logging, asyncio, pytz

with open("bot.json", "r") as f:
    bot_data = json.load(f)


class User(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @cog_ext.cog_slash(
        name="register",
        description="Sign up to participate in Beam Net.",
        permissions={
            bot_data['guild_id']: [
                create_permission(bot_data['registered_id'], SlashCommandPermissionType.ROLE, False) # TODO: use a variable for the registered role
            ],
        },
        guild_ids=[bot_data['guild_id']]
    )
    async def register(self, ctx: SlashContext):
        
        db = self.bot.pg_con
        role = discord.utils.get(ctx.guild.roles, name="Registered")
        user_id = ctx.author.id

        # check database for registration
        user = await db.fetch("SELECT user_id FROM users WHERE user_id = $1", user_id)
        if user:
            if discord.utils.get(ctx.author.roles, id=role.id):
                await ctx.send("You are already registered.", hidden=True)
            else:
                await ctx.author.add_roles(role)
                await ctx.send("You have registered before so you have been automatically registered.", hidden=True)
            return

        await ctx.send("Check your DM!", hidden=True)
        channel = ctx.author.dm_channel
        if not channel:
            channel = await ctx.author.create_dm()
        
        async def timeout():
            await msg.edit(content="Form timed out. Please try again.", embed=None, components=None)

        # Registration (1/3)
        embed = discord.Embed(
            colour = discord.Colour.blue(),
            timestamp=datetime.utcnow(),
            title="Have you read the rules and understand how Beam Net works?",
            description="More information in `#info` of the Beam Net server."
        )

        embed.set_author(
            name=f"Registration - {ctx.author}",
            icon_url=ctx.author.avatar_url
        )
        embed.set_footer(text="Page (1/3)")

        embed.add_field(name="Yes", value="I have read the rules and understand how Beam Net works.")
        embed.add_field(name="No", value="I have not read the rules or information.")

        components = spread_to_rows(
            create_button(ButtonStyle.green, label="Yes", custom_id="yes"),
            create_button(ButtonStyle.red, label="No", custom_id="no"),
        )
        
        msg = await channel.send(embed=embed, components=components)
        
        try:
            button_ctx = await wait_for_component(self.bot, messages=msg, timeout=90)
        except asyncio.TimeoutError:
            await timeout()
            return

        if button_ctx.custom_id == "no":
            await msg.edit(content="Please read `#info` and try again.", embed=None, components=None)
            return

        # Registration 2/3
        embed.title="Please rate your ability to host matches."
        embed.description="Option 3 will skip page 3."
        embed.timestamp=datetime.utcnow()

        embed.set_footer(text="Page (2/3)")

        embed.clear_fields()

        embed.add_field(name="1", value="My internet connection is good and I would like to host whenever possible.")
        embed.add_field(name="2", value="My internet connection is decent to good, but I would rather not host unless I have to.")
        embed.add_field(name="3", value="My internet connection is poor and I should never host.")

        components = spread_to_rows(
            create_button(ButtonStyle.gray, label="1", custom_id="1"),
            create_button(ButtonStyle.gray, label="2", custom_id="2"),
            create_button(ButtonStyle.gray, label="3", custom_id="3"),
        )

        await button_ctx.edit_origin(embed=embed, components=components)

        try:
            button_ctx = await wait_for_component(self.bot, messages=msg, timeout=90)
        except asyncio.TimeoutError:
            await timeout()
            return

        host_pref = 3 - int(button_ctx.custom_id)

        # Registration 3/3
        if host_pref != 0:
            embed.title="Please type your friend code below."
            embed.description=None
            embed.set_footer(text="Page (3/3)")
            fc_error = False

            while True:
                embed.timestamp=datetime.utcnow()
                embed.clear_fields()
                embed.add_field(
                    name="No Friend Code",
                    value="If you do not have access to your friend code, type `skip`. Without a friend code, you will not be able to host matches.",
                    inline=False
                )
                if fc_error:
                    embed.add_field(name="Invalid friend code!", value="Please try again.")

                await msg.edit(embed=embed, components=None)

                def check(msg):
                    return msg.channel == channel

                try:
                    reply = await self.bot.wait_for('message', timeout=90, check=check)
                except asyncio.TimeoutError:
                    await timeout()
                    return
                
                fc_raw = reply.content.strip().upper()
                if fc_raw == "SKIP":
                    fc = None
                    host_pref = 0
                    break

                fc = fc_raw.replace("SW", "").replace("-","")
                try:
                    int(fc)
                except ValueError:
                    fc_error = True
                    continue
                else:
                    break
        else:
            fc = None

        try:
            await db.execute(
                "INSERT INTO users (user_id, host_pref, register_date, friend_code) VALUES ($1, $2, $3, $4)",
                user_id, host_pref, pytz.utc.localize(datetime.utcnow()), fc
            )
        except:
            await msg.edit(content="You are already registered.", embed=None, components=None)
            return

        await asyncio.gather(
            ctx.author.add_roles(role),
            msg.edit(content="You have been successfully registered. You may now use Beam Net.", embed=None, components=None)
        )


    @cog_ext.cog_slash(
        name="user",
        description="Get info about a user.",
        options=[
            create_option(
                name="user",
                description="User to get info from.",
                option_type=SlashCommandOptionType.USER,
                required=False,
            ),
            create_option(
                name="hidden",
                description="Hide the user card when viewed. Default is false.",
                option_type=SlashCommandOptionType.BOOLEAN,
                required=False
            )
        ],
        guild_ids=[bot_data['guild_id']],
    )
    async def user(self, ctx: SlashContext, user: discord.Member = None, hidden: bool = False):
        if not user:
            user = ctx.author
        
        user_data = await self.bot.pg_con.fetchrow("SELECT * FROM users WHERE user_id = $1", user.id)
        if not user_data:
            await ctx.send(f"{user} is not registered!", hidden=True)
            return

        embed = discord.Embed(
            colour = user.color,
            timestamp=datetime.utcnow(),
            title=f"{user.name}'s User Card",
        )

        embed.set_thumbnail(url=user.avatar_url)

        rating_data = await self.bot.pg_con.fetch(
            "SELECT user_id, mode, rating, deviation FROM ratings WHERE user_id = $1 ORDER BY rating DESC",
            user_data['user_id']
        )

        if not rating_data:
            value = "None"
        else:
            value = ""
            modes = await self.bot.pg_con.fetch(
                "SELECT internal_name, name FROM modes",
            )  
            for rating in rating_data:
                for mode in modes:
                    if mode['internal_name'] == rating['mode']:
                        value += f"\n{mode['name']} - `{'{:.1f}'.format(rating['rating'])}`"
                        break
        
        embed.add_field(name="Ratings", value=value, inline=False)

        def date_to_string(date: datetime):
            if date:
                return date.strftime("%x")
            else:
                return "Never"

        embed.add_field(name="Last Played", value=date_to_string(user_data['last_played']))
        embed.add_field(name="Register Date", value=date_to_string(user_data['register_date']))

        await ctx.send(embed=embed, hidden=hidden)


def setup(bot):
    bot.add_cog(User(bot))