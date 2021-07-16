import discord
from discord.ext import commands
from discord_slash import cog_ext, SlashContext, ComponentContext
from discord_slash.utils.manage_commands import create_option, SlashCommandOptionType, create_permission
from discord_slash.utils.manage_components import ButtonStyle, create_actionrow, create_button, wait_for_component
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
                create_permission(800274945682309120, SlashCommandPermissionType.ROLE, False) # TODO: use a variable for the registered role
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
            title="Have you read and agreed to the rules and understand how Beam Net works?",
            description="More information in `#info` of the Beam Net server."
        )

        embed.set_author(
            name=f"Registration - {ctx.author}",
            icon_url=ctx.author.avatar_url
        )
        embed.set_footer(text="Page (1/3)")

        embed.add_field(name="Yes", value="I agree with all the rules and understand how Beam Net works.")
        embed.add_field(name="No", value="I disagree with any of the above mentioned.")

        components = [create_actionrow(
            create_button(ButtonStyle.success, label="Yes", custom_id="yes"),
            create_button(ButtonStyle.danger, label="No", custom_id="no"),
        )]
        
        msg = await channel.send(embed=embed, components=components)
        
        try:
            button_ctx = await wait_for_component(self.bot, message=msg, timeout=90)
        except:
            await timeout()
            return

        if button_ctx.custom_id == "no":
            await msg.edit(content="Please read `#info` and try again.", embed=None, components=None)
            return
        
        # Registration 2/3
        embed = discord.Embed(
            colour = discord.Colour.blue(),
            timestamp=datetime.utcnow(),
            title="Do you understand how the online lounge works and have a device with both the Nintendo Switch Online app and Discord installed?",
            description="More information in `#online-lounge` of the Beam Net server."
        )

        embed.set_author(
            name=f"Registration - {ctx.author}",
            icon_url=ctx.author.avatar_url
        )
        embed.set_footer(text="Page (2/3)")

        embed.add_field(name="Yes", value="I have a device with both apps installed and I understand how to use the online lounge.")
        embed.add_field(name="No", value="I disagree with any of the above mentioned.")

        await button_ctx.edit_origin(embed=embed, components=components)

        try:
            button_ctx = await wait_for_component(self.bot, message=msg, timeout=90)
        except:
            await timeout()
            return
        
        if button_ctx.custom_id == "no":
            await msg.edit(content="Please read `#online-lounge` and try again.", embed=None, components=None)
            return
        
        # Registration 3/3
        embed = discord.Embed(
            colour = discord.Colour.blue(),
            timestamp=datetime.utcnow(),
            title="Please rate your ability to host matches."
        )

        embed.set_author(
            name=f"Registration - {ctx.author}",
            icon_url=ctx.author.avatar_url
        )
        embed.set_footer(text="Page (3/3)")

        embed.add_field(name="1", value="My internet connection is good and I would like to host whenever possible.")
        embed.add_field(name="2", value="My internet connection is decent to good, but I would rather not host unless I have to.")
        embed.add_field(name="3", value="My internet connection is poor and I should never host.")

        components = [create_actionrow(
            create_button(ButtonStyle.secondary, label="1", custom_id="1"),
            create_button(ButtonStyle.secondary, label="2", custom_id="2"),
            create_button(ButtonStyle.secondary, label="3", custom_id="3"),
        )]

        await button_ctx.edit_origin(embed=embed, components=components)

        try:
            button_ctx = await wait_for_component(self.bot, message=msg, timeout=90)
        except:
            await timeout()
            return

        host_pref = 3 - int(button_ctx.custom_id)

        try:
            await db.execute(
                "INSERT INTO users (user_id, host_pref, register_date) VALUES ($1, $2, $3)",
                user_id, host_pref, pytz.utc.localize(datetime.utcnow())
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