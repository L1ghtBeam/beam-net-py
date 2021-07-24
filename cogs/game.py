import discord
from discord.ext import commands
from discord.ext.commands.core import group
from discord_slash import cog_ext, SlashContext, ComponentContext
from discord_slash.utils.manage_commands import create_option, SlashCommandOptionType, create_permission
from discord_slash.utils.manage_components import create_select, create_select_option, spread_to_rows, create_button, wait_for_component
from discord_slash.model import SlashCommandPermissionType, ButtonStyle, ComponentType

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
                else:
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

            await self.update_game_score(game, 0)
            await self.show_maps(ctx, id)
        
        elif ctx.custom_id[:13] == "submit_score_":
            id = int(ctx.custom_id[13:])
            game = await self.bot.pg_con.fetchrow("SELECT * FROM games WHERE id = $1", id)
            if ctx.author_id != game['host']:
                await ctx.send("Only the host can report the score!", hidden=True)
                return
            
            await ctx.send("The score would have been submitted if I coded that part yet!", hidden=True) # TODO: allow submitting the score

            
def setup(bot):
    bot.add_cog(Game(bot))