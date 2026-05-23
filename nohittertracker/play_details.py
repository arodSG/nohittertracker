class PlayDetails:
    pitcher_name = ''

    def __init__(self, play_details, starting_pitcher_id):
        self.batter_name = play_details['matchup']['batter']['fullName']
        self.starting_pitcher_id = starting_pitcher_id
        self.pitcher_id = play_details['matchup']['pitcher']['id']
        self.pitcher_name = play_details['matchup']['pitcher']['fullName']
        self.completed_innings = play_details['about']['inning'] - 1  # Subtract 1 for completed innings; 2 outs in the 7th is 6.2 innings pitched
        self.completed_outs = play_details['count']['outs']
        self.play_event = play_details['result']['event'].lower()

    def is_combined(self):
        return self.starting_pitcher_id != self.pitcher_id
