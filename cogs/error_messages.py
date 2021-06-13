import discord
from discord.ext import commands
from discord_slash import SlashContext, error

import logging


class Error(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        # Allows us to check for original exceptions raised and sent to CommandInvokeError.
        # If nothing is found. We keep the exception passed to on_command_error.
        error = getattr(error, 'original', error)

        # checks.
        if isinstance(error, commands.errors.MissingPermissions):
            perms = ', '.join(error.missing_perms)
            s = 's' if len(error.missing_perms) > 1 else ''
            await ctx.send(f'Missing required permission{s}: {perms}.')
        # in-command errors.
        elif isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send(f'Missing required argument: {error.param}.')
        elif isinstance(error, commands.errors.ExtensionNotFound):
            await ctx.send('Extension not found.')
        elif isinstance(error, commands.errors.ExtensionAlreadyLoaded):
            await ctx.send('Extension already loaded.')
        elif isinstance(error, commands.errors.ExtensionNotLoaded):
            await ctx.send('Extension not loaded.')
        else:
            logging.exception("Command error!", exc_info=error)

    @commands.Cog.listener()
    async def on_slash_command_error(self, ctx: SlashContext, ex: Exception):
        # checks.
        if isinstance(ex, commands.errors.NotOwner):
            await ctx.send('Only the bot owner can use this command.', hidden=True)
        elif isinstance(ex, commands.errors.NoPrivateMessage):
            await ctx.send('This command cannot be used in a direct message.', hidden=True)
        elif isinstance(ex, commands.errors.MissingPermissions):
            perms = ', '.join(ex.missing_perms)
            s = 's' if len(ex.missing_perms) > 1 else ''
            await ctx.send(f'Missing required permission{s}: {perms}.', hidden=True)
        # in-command errors.
        else:
            logging.exception("Slash command error!", exc_info=ex)

def setup(bot):
    bot.add_cog(Error(bot))
