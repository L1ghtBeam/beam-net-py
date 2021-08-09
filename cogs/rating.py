import discord
from discord.ext import commands, tasks

from datetime import datetime
from dateutil.relativedelta import relativedelta
import json, logging, asyncio, pytz

from glicko2 import Player

with open("bot.json", "r") as f:
    bot_data = json.load(f)


class Rating(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.manage_rating_periods.start()

    def cog_unload(self):
        self.manage_rating_periods.stop()

    @tasks.loop(minutes=15)
    async def manage_rating_periods(self):
        now = pytz.utc.localize(datetime.utcnow())
        modes = await self.bot.pg_con.fetch("SELECT internal_name, last_rating_period, rating_period_hours FROM modes")
        for mode in modes:
            if not mode['last_rating_period']:
                mode_changes = await self.bot.pg_con.fetchrow(
                    "UPDATE modes SET last_rating_period = $2 WHERE internal_name = $1 RETURNING last_rating_period",
                    mode['internal_name'], now
                )
                date = mode_changes['last_rating_period'].astimezone(pytz.timezone(bot_data['timezone'])).strftime("%c %Z")
                logging.warning(f"Automatically set the last_rating_period of mode \"{mode['internal_name']}\" to \"{date}\". It is recommended to change this date so the rating period is changed on the hour or on the day.")
                continue
            
            for i in range(30): # this is a loop so missed days can be advanced quickly, limit to 30 so it doesn't infinite loop
                next_rating_period = mode['last_rating_period']+relativedelta(hours=mode['rating_period_hours'])
                if now >= next_rating_period:
                    logging.info(f"Advancing rating period for mode \"{mode['internal_name']}\".")
                    players = await self.bot.pg_con.fetch( # get all players who did not play in the period
                        "SELECT * FROM ratings WHERE mode = $1 AND (rating_list = '{}' OR deviation_list = '{}' or outcome_list = '{}')",
                        mode['internal_name']
                    )
                    for player in players:
                        glicko_player = Player(rating=player['rating'], rd=player['deviation'], vol=player['volatility'])
                        glicko_player.did_not_compete()
                        rd = min(glicko_player.rd, 350)
                        await self.bot.pg_con.execute(
                            "UPDATE ratings SET rating = $3, deviation = $4, volatility = $5 WHERE user_id = $1 AND mode = $2",
                            player['user_id'], player['mode'], glicko_player.rating, rd, glicko_player.vol
                        )
                    await self.bot.pg_con.execute(
                        "UPDATE ratings SET rating_list = '{}', deviation_list = '{}', outcome_list = '{}', rating_initial = rating, deviation_initial = deviation, volatility_initial = volatility"
                    )
                    mode = await self.bot.pg_con.fetchrow(
                        "UPDATE modes SET last_rating_period = $2 WHERE internal_name = $1 RETURNING internal_name, last_rating_period, rating_period_hours",
                        mode['internal_name'], next_rating_period
                    )
                else:
                    break


    @manage_rating_periods.before_loop
    async def before_manage_rating_periods(self):
        await self.bot.wait_until_ready()
        logging.info("Starting rating period manager.")

    @manage_rating_periods.error
    async def error_manage_rating_periods(self, error):
        logging.exception("Rating period manager error!", exc_info=error)
        logging.error("Attempting to restart the rating period manager in 5 minutes.")
        await asyncio.sleep(300)
        self.manage_rating_periods.start()
            
def setup(bot):
    bot.add_cog(Rating(bot))