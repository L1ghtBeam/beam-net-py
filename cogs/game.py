import discord
from discord.ext import commands, tasks
from discord_slash import cog_ext, SlashContext, ComponentContext
from discord_slash.utils.manage_commands import create_option, SlashCommandOptionType, create_permission
from discord_slash.utils.manage_components import create_select, create_select_option, spread_to_rows, create_button, wait_for_component
from discord_slash.model import SlashCommandPermissionType, ButtonStyle, ComponentType
from rating_utils import create_player
from glicko2 import Player

from datetime import datetime
from dateutil.relativedelta import relativedelta
import json, logging, asyncio, pytz, random, os

from typing import Union

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


    async def send_match_result(self, player_id, old_rating, won, game, mode, match_draw, is_bravo):
        guild = discord.utils.get(self.bot.guilds, id=bot_data['guild_id'])
        member = discord.utils.get(guild.members, id=player_id)
        if not member:
            return
        
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

        embed = discord.Embed(
            colour=discord.Color.blue(),
            description=f"Match #{game['id']}",
            timestamp=datetime.utcnow()
        )

        if not match_draw:
            outcome = "won" if won else "lost"
            embed.title=f"You {outcome} your match!"
        else:
            embed.title="The match was a draw."

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
            mode = await self.bot.pg_con.fetchrow("SELECT * FROM modes WHERE internal_name = $1", game['mode'])
    
            # calculate score
            alpha = 0
            bravo = 0
            for score in game['score']:
                if score == 1:
                    alpha += 1
                elif score == 2:
                    bravo += 1
            
            if not mode['play_all_games']:
                points_to_win = mode['games'] // 2 + 1
                match_draw = alpha < points_to_win and bravo < points_to_win
            else:
                match_draw = alpha + bravo < mode['games']

            if alpha > bravo:
                alpha_won = True
            elif bravo > alpha:
                alpha_won = False
            else:
                alpha_won = True # this will do nothing if match_draw is true, but we still need to define it
                match_draw = True

            # calculate ratings
            if alpha + bravo != 0: # if no games were played, don't change any ratings
                alpha_ratings = 0
                for rating in game['alpha_ratings']:
                    alpha_ratings += rating

                bravo_ratings = 0
                for rating in game['bravo_ratings']:
                    bravo_ratings += rating

                def get_rd_list(player_rd):
                    game_rd_list = []
                    for rd in game['alpha_deviations']:
                        game_rd_list.append(rd)
                    for rd in game['bravo_deviations']:
                        game_rd_list.append(rd)

                    game_rd_list.remove(player_rd)
                    return game_rd_list

                for player_id in game['alpha_players']:
                    rating = await self.bot.pg_con.fetchrow("SELECT * FROM ratings WHERE user_id = $1 AND mode = $2", player_id, game['mode'])
                    game_rd_list = get_rd_list(rating['deviation'])
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
                    game_rd_list = get_rd_list(rating['deviation'])
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
                asyncio.create_task(self.send_match_result(player_id, game['alpha_ratings'][i], alpha_won, game, mode, match_draw, False))
                i += 1
            
            i = 0
            for player_id in game['bravo_players']:
                asyncio.create_task(self.send_match_result(player_id, game['bravo_ratings'][i], not alpha_won, game, mode, match_draw, True))
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


    async def can_change_score(self, ctx: ComponentContext, game):
        if not game['admin_locked']:
            if ctx.author_id != game['host']:
                await ctx.send("Only the host can do this action!", hidden=True)
                return False
        else:
            role = discord.utils.get(ctx.guild.roles, id=bot_data['admin_id'])
            if not role in ctx.author.roles:
                await ctx.send("The match is currently locked. Only an admin can do this action!", hidden=True)
                return False
        
        if game['submit_time']:
                await ctx.send("The score has already been submitted. If this is a problem, please report a match issue.", hidden=True)
                return False
        return True


    async def submit_score(self, ctx: Union[SlashContext, ComponentContext], id: int):
        game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)
        if not await self.can_change_score(ctx, game):
                return
            
        submit_time = pytz.utc.localize(datetime.utcnow())+relativedelta(seconds=+30)
        await self.bot.pg_con.execute(
            "UPDATE games SET submit_time = $2 WHERE id = $1",
            game['id'], submit_time
        )

        alpha = 0
        bravo = 0
        for score in game['score']:
            if score == 1:
                alpha += 1
            elif score == 2:
                bravo += 1

        if game['admin_locked']:
            extra_info=""
            title = "(admin)"
            cancel_submit = create_button(
                ButtonStyle.red,
                label="Cancel",
                custom_id=f"cancel_submit_{game['id']}"
            )
            components = spread_to_rows(cancel_submit)
        else:
            extra_info = " unless a match issue is reported"
            title = "(host)"
            match_issue = create_button(
                ButtonStyle.red,
                label="Report Match Issue",
                custom_id=f"match_issue_{game['id']}"
            )
            components = spread_to_rows(match_issue)

        embed = discord.Embed(
            colour = discord.Colour.blue(),
            timestamp=datetime.utcnow(),
            title=f"The score has been submitted as Alpha {alpha} - {bravo} Bravo",
            description=f"The match will be automatically closed in 30 seconds{extra_info}."
        )
        embed.set_author(
            name=f"{ctx.author} {title}",
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

        asyncio.create_task(ctx.send("You submitted the score.", hidden=True))
        await ctx.channel.send(content=content[:-1], embed=embed, components=components)


    @cog_ext.cog_subcommand(
        base="match",
        name="resolve",
        description="Unlock a match once a match issue has been resolved.",
        guild_ids=[bot_data['guild_id']]
    )
    async def resolve(self, ctx: SlashContext):
        category = ctx.channel.category
        if category.name[:7] != "match #":
            await ctx.send("Can't use this command here!", hidden=True)
            return

        match_chat = category.text_channels[0]
        if ctx.channel != match_chat:
            await ctx.send(f"Please use this command in {match_chat.mention}.", hidden=True)
            return

        id = int(category.name[7:])
        game = await self.bot.pg_con.fetchrow("SELECT id, admin_locked FROM games WHERE id = $1", id)
        if not game['admin_locked']:
            await ctx.send("This match is not locked.", hidden=True)
            return

        embed = discord.Embed(
            color=discord.Color.red(),
            timestamp=datetime.utcnow(),
            title="The match issue has been resolved.",
            description="The game may now resume."
        )

        asyncio.create_task(ctx.send(embed=embed))
        await self.bot.pg_con.execute("UPDATE games SET admin_locked = false WHERE id = $1", id)

        for channel in category.channels:
            await channel.set_permissions(ctx.author, overwrite=None)


    @cog_ext.cog_subcommand(
        base="match",
        name="submit",
        description="Submit the score for the current match. Useful for submitting the match as a draw.",
        guild_ids=[bot_data['guild_id']]
    )
    async def submit(self, ctx: SlashContext):
        category = ctx.channel.category
        if category.name[:7] != "match #":
            await ctx.send("Can't use this command here!", hidden=True)
            return
        
        match_chat = category.text_channels[0]
        if ctx.channel != match_chat:
            await ctx.send(f"Please use this command in {match_chat.mention}.", hidden=True)
            return

        id = int(category.name[7:])
        await self.submit_score(ctx, id)


    @cog_ext.cog_subcommand(
        base="match",
        name="delete",
        description="Deletes a game and its discord channels. DO NOT USE THIS unless you have a good reason to do so.",
        options=[
            create_option(
                name="match_id",
                description="ID number of the match.",
                option_type=SlashCommandOptionType.INTEGER,
                required=True
            )
        ],
        base_default_permission=False, # changes permissions for base command match
        base_permissions={
            bot_data['guild_id']: [
                create_permission(bot_data['admin_id'], SlashCommandPermissionType.ROLE, True)
            ]
        },
        guild_ids=[bot_data['guild_id']]
    )
    async def delete(self, ctx: SlashContext, match_id: int):
        category = discord.utils.get(ctx.guild.channels, name=f'match #{match_id}')
        reason = f"{ctx.author} used /match delete for match #{match_id}"
        logging.info(reason)

        asyncio.create_task(self.bot.pg_con.execute("DELETE FROM games WHERE id = $1", match_id))

        if category:
            coroutines = []
            for channel in category.channels:
                coroutines.append(
                    channel.delete(reason=reason)
                )
            await asyncio.gather(*coroutines)
            await category.delete(reason=reason)

        await ctx.send("Delete successful!")


    @commands.Cog.listener()
    async def on_component(self, ctx: ComponentContext):
        if ctx.custom_id[:14] == "generate_maps_":
            id = int(ctx.custom_id[14:])
            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)

            if not await self.can_change_score(ctx, game):
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

            if not await self.can_change_score(ctx, game):
                return
            
            await self.update_game_score(game, 1)
            await self.show_maps(ctx, id)
        
        elif ctx.custom_id[:10] == "win_bravo_":
            id = int(ctx.custom_id[10:])
            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)

            if not await self.can_change_score(ctx, game):
                return
            
            await self.update_game_score(game, 2)
            await self.show_maps(ctx, id)

        elif ctx.custom_id[:9] == "undo_map_":
            id = int(ctx.custom_id[9:])
            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)

            if not await self.can_change_score(ctx, game):
                return        

            await self.update_game_score(game, 0)
            await self.show_maps(ctx, id)
        
        elif ctx.custom_id[:13] == "submit_score_":
            id = int(ctx.custom_id[13:])
            await self.submit_score(ctx, id)
        
        elif ctx.custom_id[:12] == "match_issue_":
            id = int(ctx.custom_id[12:])
            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)
            if game['admin_locked'] is True:
                await ctx.send("A match issue has already been reported!", hidden=True)
                return
            
            now = pytz.utc.localize(datetime.utcnow())
            if game['submit_time']:
                if game['submit_time'] <= now:
                    await ctx.send("The match has already been submitted!", hidden=True)
                    return

            embed = discord.Embed(
                color = discord.Color.red(),
                timestamp=datetime.utcnow(),
                title="A match issue has been reported!",
                description="An admin will be here shortly to resolve the issue."
            )
            asyncio.create_task(ctx.send(embed=embed))
            await self.bot.pg_con.execute("UPDATE games SET admin_locked = true, submit_time = null WHERE id = $1", id)

            channel = discord.utils.get(ctx.guild.channels, name="match-issues")
            if not channel:
                logging.warning("A channel named \"#match-issues\" could not be found so a match issue message cannot be sent!")
            else:
                embed.title=f"A match issue has been reported in match #{id}."
                embed.description="Any available admin please press the button below."
                embed.set_author(name=f"{ctx.author} (issue reporter)", icon_url=ctx.author.avatar_url)

                assign_admin = create_button(
                    ButtonStyle.green,
                    label="Assign To Match",
                    custom_id=f"admin_assign_{id}"
                )
                components = spread_to_rows(assign_admin)

                role = discord.utils.get(ctx.guild.roles, id=bot_data['admin_id'])
                content = role.mention if role else "Admin role not found!"

                await channel.send(content=content, embed=embed, components=components)

        elif ctx.custom_id[:13] == "admin_assign_":
            id = int(ctx.custom_id[13:])

            assign_admin = create_button(
                    ButtonStyle.green,
                    label="Assign To Match",
                    disabled=True
                )
            components = spread_to_rows(assign_admin)
            asyncio.create_task(ctx.origin_message.edit(components=components))

            game = await self.bot.pg_con.fetchrow("SELECT id, game_active FROM games WHERE id = $1", id)
            if not game['game_active']:
                await ctx.send("This match has already ended.", hidden=True)
                return

            embed = discord.Embed(
                color = discord.Color.red(),
                timestamp=datetime.utcnow(),
                title=f"{ctx.author.name} has been assigned to this match.",
            )
            embed.set_author(name=f"{ctx.author} (admin)", icon_url=ctx.author.avatar_url)
            asyncio.create_task(ctx.send(embed=embed))

            category = discord.utils.get(ctx.guild.categories, name=f"match #{id}")
            for channel in category.text_channels:
                await channel.set_permissions(ctx.author, view_channel=True)
            for channel in category.voice_channels:
                await channel.set_permissions(ctx.author, view_channel=True, connect=True)
            
            await category.text_channels[0].send(content=ctx.author.mention, embed=embed)
    
        elif ctx.custom_id[:14] == "cancel_submit_":
            id = int(ctx.custom_id[14:])

            role = discord.utils.get(ctx.guild.roles, id=bot_data['admin_id'])
            if not role in ctx.author.roles:
                await ctx.send("Only an admin can do this action!", hidden=True)
                return False
            
            # disable button
            cancel_submit = create_button(
                ButtonStyle.red,
                label="Cancel",
                disabled=True
            )
            components = spread_to_rows(cancel_submit)
            asyncio.create_task(ctx.origin_message.edit(components=components))

            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)
            if not game['submit_time']:
                asyncio.create_task(ctx.send("The score is not submitted.", hidden=True))
                return

            now = pytz.utc.localize(datetime.utcnow())
            if game['submit_time'] <= now:
                await ctx.send("The match has already been submitted!", hidden=True)
                return
            
            await self.bot.pg_con.execute("UPDATE games SET submit_time = null WHERE id = $1", id)

            embed = discord.Embed(
                colour = discord.Colour.red(),
                timestamp=datetime.utcnow(),
                title="Score submission has been cancelled.",
            )
            embed.set_author(
                name=f"{ctx.author} (admin)",
                icon_url=ctx.author.avatar_url
            )
            await ctx.send(embed=embed)
            
            
            
def setup(bot):
    bot.add_cog(Game(bot))