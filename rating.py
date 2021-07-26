from glicko2 import Player

def create_player(teammates_rating, opponents_rating, RD_list, wins, losses):
    r = opponents_rating - teammates_rating
    
    rd = 0
    for deviation in RD_list:
        rd += deviation
    rd = rd / len(RD_list)

    games = wins + losses
    return [r] * games, [rd] * games, [1] * wins + [0] * losses

def worth_playing(players):
    for i in range(len(players)):
        team = i // 4
        teammates_ratings = []
        opponents_ratings = []
        RD_list = []

        for j in range(4):
            index = team * 4 + j
            if i == index:
                continue
            teammates_ratings.append(players[index].rating)
            RD_list.append(players[index].rd)
        for j in range(4):
            index = (1 - team) * 4 + j
            opponents_ratings.append(players[index].rating)
            RD_list.append(players[index].rd)
        
        ratings, rds, outcomes = create_player(teammates_ratings, opponents_ratings, RD_list, 3, 1)

        player_sim = Player()
        player_sim.rating = players[i].rating
        player_sim.rd = players[i].rd
        player_sim.vol = players[i].vol

        player_sim.update_player(ratings, rds, outcomes)
        if player_sim.rating < players[i].rating:
            print(i)
            return False
    return True