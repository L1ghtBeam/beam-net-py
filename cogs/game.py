import discord
from discord.ext import commands, tasks
from discord.ext.commands.core import group
from discord_slash import cog_ext, SlashContext, ComponentContext
from discord_slash.utils.manage_commands import create_option, SlashCommandOptionType, create_permission
from discord_slash.utils.manage_components import create_select, create_select_option, spread_to_rows, create_button, wait_for_component
from discord_slash.model import SlashCommandPermissionType, ButtonStyle, ComponentType
from rating import create_player
from glicko2 import Player

from datetime import datetime
from dateutil.relativedelta import relativedelta
import json, logging, asyncio, pytz, random, os

with open("bot.json", "r") as f:
    bot_data = json.load(f)

with open("./data/maps.json", "r") as f:
    map_key = json.load(f)

with open("./data/modes.json", "r") as f:
    mode_key = json.load(f)

MAPLIST_LUCK = 3 # the higher the number, the more good maps and the less bad maps


class Game(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.close_games_loop.start()

    def cog_unload(self):
        self.close_games_loop.cancel()


    async def send_match_result(self, player_id, old_rating, won, game, is_bravo):
        guild = discord.utils.get(self.bot.guilds, id=bot_data['guild_id'])
        member = discord.utils.get(guild.members, id=player_id)
        if not member:
            return
        
        outcome = "won" if won else "lost"

        ratings = await self.bot.pg_con.fetchrow("SELECT user_id, mode, rating FROM ratings WHERE user_id = $1 AND mode = $2", player_id, game['mode'])
        change = '{:.1f}'.format(ratings['rating'] - old_rating)
        if change[0] != "-":
            change = "+" + change

        alpha = 0
        bravo = 0
        for score in game['score']:
            if score == 1:
                alpha += 1
            elif score == 2:
                bravo += 1

        if is_bravo:
            alpha, bravo = bravo, alpha

        mode = await self.bot.pg_con.fetchrow("SELECT name, internal_name, thumbnail FROM modes WHERE internal_name = $1", game['mode'])

        embed = discord.Embed(
            colour=discord.Color.blue(),
            title=f"You {outcome} your match!",
            description=f"Match #{game['id']}",
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=member, icon_url=member.avatar_url)
        if mode['thumbnail']:
            embed.set_thumbnail(url=mode['thumbnail'])

        embed.add_field(name="Result:", value=f"`{alpha}` - `{bravo}`")
        embed.add_field(name=f"{mode['name']} Rating: ", value=f"`{change}`")
        
        channel = member.dm_channel
        if not channel:
            channel = await member.create_dm()
        
        await channel.send(embed=embed)


    async def close_game(self, game):
        try:
            guild = discord.utils.get(self.bot.guilds, id=bot_data['guild_id'])

            # calculate score
            # TODO: allow game to be tied or uncompleted
            alpha = 0
            bravo = 0
            for score in game['score']:
                if score == 1:
                    alpha += 1
                elif score == 2:
                    bravo += 1
            
            if alpha > bravo:
                alpha_won = True
            elif alpha < bravo:
                alpha_won = False
            else:
                alpha_won = True # game tied but there is no code for that yet

            # calculate ratings
            alpha_ratings = 0
            for rating in game['alpha_ratings']:
                alpha_ratings += rating

            bravo_ratings = 0
            for rating in game['bravo_ratings']:
                bravo_ratings += rating

            game_rd_list = []
            for rd in game['alpha_deviations']:
                game_rd_list.append(rd)
            for rd in game['bravo_deviations']:
                game_rd_list.append(rd)

            for player_id in game['alpha_players']:
                rating = await self.bot.pg_con.fetchrow("SELECT * FROM ratings WHERE user_id = $1 AND mode = $2", player_id, game['mode'])
                if not (rating['rating_initial'] and rating['deviation_initial'] and rating['volatility_initial']):
                    rating = await self.bot.pg_con.fetchrow(
                        "UPDATE ratings SET rating_initial = rating, deviation_initial = deviation, volatility_initial = volatility WHERE user_id = $1 AND mode = $2 RETURNING *",
                        player_id, game['mode']
                    )
                
                new_ratings, new_rds, new_outcomes = create_player(alpha_ratings - rating['rating'], bravo_ratings, game_rd_list, alpha, bravo)
                rating_list = rating['rating_list'] + new_ratings
                rd_list = rating['deviation_list'] + new_rds
                outcome_list = rating['outcome_list'] + new_outcomes

                glicko_player = Player(rating=rating['rating_initial'], rd=rating['deviation_initial'], vol=rating['volatility_initial'])
                glicko_player.update_player(rating_list, rd_list, outcome_list)

                await self.bot.pg_con.execute(
                    "UPDATE ratings SET rating = $3, deviation = $4, volatility = $5, rating_list = $6, deviation_list = $7, outcome_list = $8 WHERE user_id = $1 AND mode = $2",
                    player_id, game['mode'], glicko_player.rating, glicko_player.rd, glicko_player.vol, rating_list, rd_list, outcome_list
                )

            for player_id in game['bravo_players']:
                rating = await self.bot.pg_con.fetchrow("SELECT * FROM ratings WHERE user_id = $1 AND mode = $2", player_id, game['mode'])
                if not (rating['rating_initial'] and rating['deviation_initial'] and rating['volatility_initial']):
                    rating = await self.bot.pg_con.fetchrow(
                        "UPDATE ratings SET rating_initial = rating, deviation_initial = deviation, volatility_initial = volatility WHERE user_id = $1 AND mode = $2 RETURNING *",
                        player_id, game['mode']
                    )
                
                new_ratings, new_rds, new_outcomes = create_player(bravo_ratings - rating['rating'], alpha_ratings, game_rd_list, bravo, alpha)
                rating_list = rating['rating_list'] + new_ratings
                rd_list = rating['deviation_list'] + new_rds
                outcome_list = rating['outcome_list'] + new_outcomes

                glicko_player = Player(rating=rating['rating_initial'], rd=rating['deviation_initial'], vol=rating['volatility_initial'])
                glicko_player.update_player(rating_list, rd_list, outcome_list)

                await self.bot.pg_con.execute(
                    "UPDATE ratings SET rating = $3, deviation = $4, volatility = $5, rating_list = $6, deviation_list = $7, outcome_list = $8 WHERE user_id = $1 AND mode = $2",
                    player_id, game['mode'], glicko_player.rating, glicko_player.rd, glicko_player.vol, rating_list, rd_list, outcome_list
                )

            # mark game as closed
            await self.bot.pg_con.execute(
                "UPDATE games SET game_active = false, end_date = $2 WHERE id = $1",
                game['id'], pytz.utc.localize(datetime.utcnow())
            )

            # delete channels
            category = discord.utils.get(guild.channels, name=f"match #{game['id']}")
            reason = f"Automatic cleanup for game {game['id']}."
            coroutines = []
            for channel in category.channels:
                coroutines.append(
                    channel.delete(reason=reason)
                )
            await asyncio.gather(*coroutines)
            await category.delete(reason=reason)

            # send messages
            i = 0
            for player_id in game['alpha_players']:
                asyncio.create_task(self.send_match_result(player_id, game['alpha_ratings'][i], alpha_won, game, False))
                i += 1
            
            i = 0
            for player_id in game['bravo_players']:
                asyncio.create_task(self.send_match_result(player_id, game['bravo_ratings'][i], not alpha_won, game, True))
                i += 1
        
        except Exception as error:
            logging.exception("Closing game error!", exc_info=error)


    @tasks.loop(seconds=3)
    async def close_games_loop(self):
        time = pytz.utc.localize(datetime.utcnow())
        games = await self.bot.pg_con.fetch("SELECT * FROM games WHERE submit_time <= $1 AND game_active = true", time)
        for game in games:
            asyncio.create_task(self.close_game(game))
    
    @close_games_loop.before_loop
    async def before_game_closer(self):
        await self.bot.wait_until_ready()
        logging.info("Starting game closer.")

    @close_games_loop.error
    async def error_update_all(self, error):
        logging.exception("Game closer loop error!", exc_info=error)
        logging.error("Attempting to restart game closer in 2 minutes.")
        await asyncio.sleep(120)
        self.close_games_loop.start()


    def generate_maps(self, modes, maplist):

        def remove_items(test_list, item):
            # using list comprehension to perform the task
            res = [i for i in test_list if i != item]
            return res

        with open(f"./data/maplists/{maplist}.json") as f:
            data = json.load(f)

        map_pool = {}
        generated_maps = []
        generated_modes = []
        # generate map pool
        for mode in modes:
            if mode in map_pool:
                continue

            map_pool[mode] = []
            for map in data:
                for i in range(data[map][mode] ** MAPLIST_LUCK):
                    map_pool[mode].append(map)
        
        # pick maps
        for mode in modes:
            chosen_map = random.choice(map_pool[mode])
            for key in map_pool:
                map_pool[key] = remove_items(map_pool[key], chosen_map)
            generated_maps.append(chosen_map)
            generated_modes.append(mode)
    
        return generated_maps, generated_modes


    async def update_game_score(self, game, score_id):
        index = 0
        for score in game['score']:
            if score == 0:
                break
            index += 1
        
        offset = 1 if score_id == 0 else 0 # if score_id is 0, undo the last score report

        new_score = game['score']
        new_score[index - offset] = score_id
        await self.bot.pg_con.execute(
            "UPDATE games SET score = $2 WHERE id = $1",
            game['id'], new_score
        )


    async def show_maps(self, ctx: ComponentContext, id: int):
        try:
            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)
            mode = await self.bot.pg_con.fetchrow("SELECT * FROM modes WHERE internal_name = $1", game['mode'])

            num = 0
            alpha = 0
            bravo = 0
            score_history = ""
            for score in game['score']:
                if score == 0:
                    break
                elif score == 1:
                    alpha += 1
                    score_history += f"{num + 1}. Alpha Won - "
                elif score == 2:
                    bravo += 1
                    score_history += f"{num + 1}. Bravo Won - "
                
                score_history += mode_key[game['game_modes'][num]]['emoji'] + " "
                score_history += map_key[game['game_maps'][num]]['name'] + "\n"
                
                num += 1
            
            match_complete = False
            if not mode['play_all_games']:
                points_to_win = mode['games'] // 2 + 1
                match_complete = alpha >= points_to_win or bravo >= points_to_win
            else:
                match_complete = num >= mode['games']
    
            if not match_complete:
                game_map = game['game_maps'][num]
                game_map_str = map_key[game_map]['name']

                game_mode = game['game_modes'][num]
                game_mode_str = mode_key[game_mode]['name']

                embed = discord.Embed(
                    colour=discord.Color.blue(),
                    title=f"Game {num + 1}: {game_map_str} - {game_mode_str}",
                    description="Please report the score below once the game has finished.",
                    timestamp=datetime.utcnow()
                )

                embed.set_image(url=map_key[game_map]['url'])
                embed.set_thumbnail(url=mode_key[game_mode]['url'])

                if score_history:
                    embed.add_field(name="Score:", value=score_history[:-1], inline=False)

                back = create_button(
                    style=ButtonStyle.red,
                    label="Undo",
                    custom_id=f"undo_map_{id}",
                    disabled=num==0
                )
                alpha_win = create_button(
                    style=ButtonStyle.green,
                    label="Alpha Won",
                    custom_id=f"win_alpha_{id}"
                )
                bravo_win = create_button(
                    style=ButtonStyle.blue,
                    label="Bravo Won",
                    custom_id=f"win_bravo_{id}"
                )
                components=spread_to_rows(back, alpha_win, bravo_win)
            
            else:
                embed = discord.Embed(
                    colour=discord.Color.blue(),
                    title=f"Final Score: Alpha {alpha} - {bravo} Bravo",
                    description="Please verify that the score is correct before submitting.",
                    timestamp=datetime.utcnow()
                )

                if score_history:
                    embed.add_field(name="Score:", value=score_history[:-1], inline=False)
                
                back = create_button(
                    style=ButtonStyle.red,
                    label="Undo",
                    custom_id=f"undo_map_{id}",
                    disabled=num==0
                )
                submit = create_button(
                    style=ButtonStyle.green,
                    label="Submit",
                    custom_id=f"submit_score_{id}"
                )
                components=spread_to_rows(back, submit)
            
            await ctx.edit_origin(embed=embed, components=components)

        except Exception as error:
            logging.exception("Show maps error!", exc_info=error)
            return


    @cog_ext.cog_subcommand(
        base="match",
        name="cleanup",
        description="Cleanup the channels from a game. Does not touch the database.",
        options=[
            create_option(
                name="match",
                description="The match number.",
                option_type=SlashCommandOptionType.INTEGER,
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
    async def cleanup(self, ctx: SlashContext, match: int):
        category = discord.utils.get(ctx.guild.channels, name=f'match #{match}')
        reason = f"{ctx.author} used /cleanup for match #{match}"
        logging.info(reason)

        coroutines = []
        for channel in category.channels:
            coroutines.append(
                channel.delete(reason=reason)
            )
        await asyncio.gather(*coroutines)
        await category.delete(reason=reason)
        await ctx.send("Cleanup successful!")
    

    @commands.Cog.listener()
    async def on_component(self, ctx: ComponentContext):
        if ctx.custom_id[:14] == "generate_maps_":
            # prevent anyone other than the host from generating maps
            id = int(ctx.custom_id[14:])
            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)
            if ctx.author_id != game['host']:
                await ctx.send("Only the host can generate maps!", hidden=True)
                return

            mode = await self.bot.pg_con.fetchrow("SELECT internal_name, maplist, format FROM modes WHERE internal_name = $1", game['mode'])
            if game['game_maps'] is None or game['game_modes'] is None:
                game_maps, game_modes = self.generate_maps(mode['format'], mode['maplist'])
                await self.bot.pg_con.execute(
                    "UPDATE games SET game_maps = $2, game_modes = $3 WHERE id = $1",
                    id, game_maps, game_modes
                )
            
            await self.show_maps(ctx, id)
        elif ctx.custom_id[:10] == "win_alpha_":
            id = int(ctx.custom_id[10:])
            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)
            if ctx.author_id != game['host']:
                await ctx.send("Only the host can report the score!", hidden=True)
                return
            
            await self.update_game_score(game, 1)
            await self.show_maps(ctx, id)
        
        elif ctx.custom_id[:10] == "win_bravo_":
            id = int(ctx.custom_id[10:])
            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)
            if ctx.author_id != game['host']:
                await ctx.send("Only the host can report the score!", hidden=True)
                return
            
            await self.update_game_score(game, 2)
            await self.show_maps(ctx, id)

        elif ctx.custom_id[:9] == "undo_map_":
            id = int(ctx.custom_id[9:])
            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)
            if ctx.author_id != game['host']:
                await ctx.send("Only the host can do this action!", hidden=True)
                return

            if game['submit_time']:
                await ctx.send("The score has already been submitted. If this is a problem, please report a match issue.", hidden=True)
                return

            await self.update_game_score(game, 0)
            await self.show_maps(ctx, id)
        
        elif ctx.custom_id[:13] == "submit_score_":
            id = int(ctx.custom_id[13:])
            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)
            if ctx.author_id != game['host']:
                await ctx.send("Only the host can report the score!", hidden=True)
                return
            
            if game['submit_time']:
                await ctx.send("The score has already been submitted. If this is a problem, please report a match issue.", hidden=True)
                return

            submit_time = pytz.utc.localize(datetime.utcnow())+relativedelta(seconds=+30)
            await self.bot.pg_con.execute(
                "UPDATE games SET submit_time = $2 WHERE id = $1",
                id, submit_time
            )

            alpha = 0
            bravo = 0
            for score in game['score']:
                if score == 1:
                    alpha += 1
                elif score == 2:
                    bravo += 1

            embed = discord.Embed(
                colour = discord.Colour.blue(),
                timestamp=datetime.utcnow(),
                title=f"The score has been submitted as Alpha {alpha} - {bravo} Bravo",
                description="The match will be automatically closed in 30 seconds unless a match issue is reported."
            )
            embed.set_author(
                name=f"{ctx.author} (host)",
                icon_url=ctx.author.avatar_url
            )

            content = ""
            for player_id in game['alpha_players']:
                member = discord.utils.get(ctx.guild.members, id=player_id)
                if member:
                    content += member.mention + " "
            for player_id in game['bravo_players']:
                member = discord.utils.get(ctx.guild.members, id=player_id)
                if member:
                    content += member.mention + " "

            await ctx.send("You submitted the score.", hidden=True)
            await ctx.channel.send(content=content[:-1], embed=embed) # TODO: add a component with another report match issue button
            
def setup(bot):
    bot.add_cog(Game(bot))