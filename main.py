#!/usr/bin/python3
# No-Hitter Tracker

import os
from dotenv import load_dotenv
import constants
from datetime import datetime, timedelta
from game_details import GameDetails
import requests
import json
import tweepy
import pickle
from tweepy import TweepyException
import util

load_dotenv()

team_ids_tweeted = {}  # {team_id: {is_combined: False, is_perfect_game: False, is_finished: False}}


def get_game_info_by_date(date):  # Returns a map of { game_id: { game_status, home_team_id, away_team_id } for all games on the specified date
    games = {}
    params = {'sportId': 1, 'date': date}
    request_endpoint = 'https://statsapi.mlb.com/api/v1/schedule/games/'

    try:
        response = util.make_request(request_endpoint, params)
        if response.status_code == 200:
            if response.json()['dates']:
                games_json = response.json()['dates'][0]['games']
                for game_json in games_json:
                    game_pk = game_json['gamePk']
                    games[game_pk] = {}
                    games[game_pk]['status'] = GameDetails.get_game_status(game_json['status'])
                    games[game_pk]['home_team_id'] = game_json['teams']['home']['team']['id']
                    games[game_pk]['away_team_id'] = game_json['teams']['away']['team']['id']
    except (ConnectionError, requests.exceptions.RequestException) as e:
        util.arodsg_ntfy(str(e))

    return games


def check_no_hitter(game_details, team_id):
    is_final = game_details.is_final()
    innings_pitched = game_details.get_innings_pitched(team_id)
    is_no_hitter = game_details.is_no_hitter(team_id)

    if innings_pitched >= util.config['num_innings_to_alert']:
        team_id_tweeted = team_id in team_ids_tweeted
        tweeted_not_finished = team_id_tweeted and not team_ids_tweeted[team_id]['is_finished']

        if is_no_hitter:
            try:
                game_details.set_broken_details()
                is_combined = game_details.is_combined(team_id)
                is_perfect_game = game_details.is_perfect_game(team_id)
                is_downgrade = team_id_tweeted and team_ids_tweeted[team_id]['is_perfect_game'] and not is_perfect_game
                is_pitching_change = team_id_tweeted and not team_ids_tweeted[team_id]['is_combined'] and is_combined

                if not team_id_tweeted or (is_final and tweeted_not_finished):
                    send_no_hitter_tweet(game_details, team_id, is_perfect_game, innings_pitched)
                elif is_downgrade:
                    send_downgrade_tweet(game_details, team_id, innings_pitched)
                elif is_pitching_change:
                    send_pitching_change_tweet(game_details, team_id, is_perfect_game, innings_pitched)
            except KeyError as e:
                print(game_details.game_id)
                pass
        elif tweeted_not_finished:
            try:
                game_details.set_broken_details()
                send_broken_tweet(game_details, team_id)
            except KeyError:
                pass


def update_team_ids_tweeted(team_id, is_combined, is_perfect_game, is_finished):
    team_ids_tweeted[team_id] = {'is_combined': is_combined, 'is_perfect_game': is_perfect_game, 'is_finished': is_finished}
    with open(constants.TEAM_IDS_TWEETED_FILE_PATH, 'wb') as team_ids_tweeted_file:
        pickle.dump(team_ids_tweeted, team_ids_tweeted_file)


def reset_team_ids_tweeted():
    with open(constants.TEAM_IDS_TWEETED_FILE_PATH, 'wb') as file:
        pickle.dump({}, file)


def send_no_hitter_tweet(game_details, team_id, is_perfect_game, innings_pitched):
    is_combined = game_details.is_combined(team_id)
    is_final = game_details.is_final()
    no_hitter_status = 'perfect game' if is_perfect_game else 'no-hitter'
    opposing_team = game_details.get_opposing_team(team_id)

    if is_combined:
        team_name = game_details.get_team_name(team_id)

        if is_final:
            team_pitcher_details = game_details.get_team_pitcher_details(team_id)
            pitchers_stats_messages = []

            for pitcher_details in team_pitcher_details:
                pitcher_info = game_details.get_player_info(pitcher_details['person']['id'])
                pitcher_last_name = pitcher_info['lastName']
                pitcher_stats = pitcher_details['stats']['pitching']
                num_innings = pitcher_stats['inningsPitched']
                num_strikeouts = pitcher_stats['strikeOuts']
                num_walks = pitcher_stats['baseOnBalls']
                num_hit_by_pitch = pitcher_stats['hitByPitch']
                num_runs = pitcher_stats['runs']
                num_pitches = pitcher_stats['pitchesThrown']
                pitcher_stats = (constants.PITCHER_STATS_HBP if num_hit_by_pitch > 0 else constants.PITCHER_STATS).format(num_strikeouts=num_strikeouts, num_walks=num_walks, num_hit_by_pitch=num_hit_by_pitch, num_runs=num_runs, num_pitches=num_pitches)
                pitcher_stats_innings = constants.COMBINED_FINAL_PITCHER_STATS.format(pitcher_name=pitcher_last_name, num_innings=num_innings, pitcher_stats=pitcher_stats)
                pitchers_stats_messages.append(pitcher_stats_innings)

            message = constants.COMBINED_FINAL.format(team_name=team_name, game_status=no_hitter_status, opposing_team=opposing_team, pitcher_stats_message='\n'.join(pitchers_stats_messages))
        else:
            message = constants.COMBINED_CURRENT.format(team_name=team_name, game_status=no_hitter_status, opposing_team=opposing_team, innings_pitched=innings_pitched)
    else:
        pitcher_name = game_details.get_starting_pitcher_name(team_id)
        team_abbrv = game_details.get_team_abbrv(team_id)
        pitcher_details = game_details.get_starting_pitcher_details(team_id)
        num_innings = pitcher_details['inningsPitched']
        num_strikeouts = pitcher_details['strikeOuts']
        num_walks = pitcher_details['baseOnBalls']
        num_hit_by_pitch = pitcher_details['hitByPitch']
        num_runs = pitcher_details['runs']
        num_pitches = pitcher_details['pitchesThrown']
        pitcher_stats = (constants.PITCHER_STATS_HBP if num_hit_by_pitch > 0 else constants.PITCHER_STATS).format(num_strikeouts=num_strikeouts, num_walks=num_walks, num_hit_by_pitch=num_hit_by_pitch, num_runs=num_runs, num_pitches=num_pitches)

        if is_final:
            pitcher_stats_innings = constants.PITCHER_STATS_INNINGS.format(num_innings=num_innings, pitcher_stats=pitcher_stats)
            message = constants.REG_FINAL.format(pitcher_name=pitcher_name, team_abbrv=team_abbrv, game_status=no_hitter_status, opposing_team=opposing_team, pitcher_stats_message=pitcher_stats_innings)
        else:
            message = constants.REG_CURRENT.format(pitcher_name=pitcher_name, team_abbrv=team_abbrv, game_status=no_hitter_status, opposing_team=opposing_team, innings_pitched=innings_pitched, pitcher_stats_message=pitcher_stats)

    build_and_send_tweet(message, game_details, team_id, is_finished=is_final)


def send_downgrade_tweet(game_details, team_id, innings_pitched):
    downgrade_play_details = game_details.get_downgrade_play_details(team_id)
    is_combined = downgrade_play_details.is_combined()
    opposing_team = game_details.get_opposing_team(team_id)

    if is_combined:
        team_name = game_details.get_team_name(team_id)
        message = constants.COMBINED_DOWNGRADE.format(team_name=team_name, opposing_team=opposing_team, innings_pitched=innings_pitched)
    else:
        pitcher_name = downgrade_play_details.pitcher_name
        team_abbrv = game_details.get_team_abbrv(team_id)
        message = constants.REG_DOWNGRADE.format(pitcher_name=pitcher_name, team_abbrv=team_abbrv, opposing_team=opposing_team, innings_pitched=innings_pitched)

    build_and_send_tweet(message, game_details, team_id, is_finished=False)


def send_pitching_change_tweet(game_details, team_id, is_perfect_game, innings_pitched):
    starting_pitcher_name = game_details.get_starting_pitcher_name(team_id)
    replacing_pitcher_name = game_details.get_replacing_pitcher_name(team_id)
    no_hitter_status = 'perfect game' if is_perfect_game else 'no-hitter'
    team_abbrv = game_details.get_team_abbrv(team_id)
    starting_pitcher_details = game_details.get_starting_pitcher_details(team_id)
    num_innings = starting_pitcher_details['inningsPitched']
    num_strikeouts = starting_pitcher_details['strikeOuts']
    num_walks = starting_pitcher_details['baseOnBalls']
    num_hit_by_pitch = starting_pitcher_details['hitByPitch']
    num_runs = starting_pitcher_details['runs']
    num_pitches = starting_pitcher_details['pitchesThrown']
    pitcher_stats = (constants.PITCHER_STATS_HBP if num_hit_by_pitch > 0 else constants.PITCHER_STATS).format(num_strikeouts=num_strikeouts, num_walks=num_walks, num_hit_by_pitch=num_hit_by_pitch, num_runs=num_runs, num_pitches=num_pitches)
    pitcher_stats_innings = constants.PITCHER_STATS_INNINGS.format(num_innings=num_innings, pitcher_stats=pitcher_stats)
    message = constants.REG_TO_COMBINED.format(pitcher_name=starting_pitcher_name, team_abbrv=team_abbrv, new_pitcher_name=replacing_pitcher_name, game_status=no_hitter_status, innings_pitched=innings_pitched, pitcher_stats_message=pitcher_stats_innings)

    build_and_send_tweet(message, game_details, team_id, is_finished=False)


def send_broken_tweet(game_details, team_id):
    broken_play_details = game_details.get_broken_play_details(team_id)
    is_combined = broken_play_details.is_combined()
    opposing_team = game_details.get_opposing_team(team_id)
    broken_by_message = constants.BROKEN_BY.format(play_event=broken_play_details.play_event, batter_name=broken_play_details.batter_name, inning=broken_play_details.completed_innings, outs=broken_play_details.completed_outs)

    if is_combined:
        team_name = game_details.get_team_name(team_id)
        message = constants.COMBINED_BROKEN.format(team_name=team_name, opposing_team=opposing_team, broken_by_message=broken_by_message)
    else:
        team_abbrv = game_details.get_team_abbrv(team_id)
        message = constants.REG_BROKEN.format(pitcher_name=broken_play_details.pitcher_name, team_abbrv=team_abbrv, opposing_team=opposing_team, broken_by_message=broken_by_message)

    build_and_send_tweet(message, game_details, team_id, is_finished=True)


def build_and_send_tweet(message, game_details, team_id, is_finished):
    is_combined = game_details.is_combined(team_id)
    is_perfect_game = game_details.is_perfect_game(team_id)
    team_id_tweeted = team_id in team_ids_tweeted
    home_team_hashtag = get_team_hashtag(game_details.home_team_abbrv)
    away_team_hashtag = get_team_hashtag(game_details.away_team_abbrv)
    tweet_text = constants.TWEET.format(message=message, home_team_hashtag=home_team_hashtag, away_team_hashtag=away_team_hashtag)
    tweet_text_encoded = tweet_text.encode('utf-8')

    if not util.config['debug_mode']:
        try:
            twitter = tweepy.Client(consumer_key=os.getenv('TWITTER_CONSUMER_KEY'), consumer_secret=os.getenv('TWITTER_CONSUMER_SECRET'), access_token=os.getenv('TWITTER_ACCESS_TOKEN'), access_token_secret=os.getenv('TWITTER_ACCESS_TOKEN_SECRET'))
            response = twitter.create_tweet(text=tweet_text_encoded)
            update_team_ids_tweeted(team_id, is_combined=is_combined, is_perfect_game=is_perfect_game, is_finished=is_finished)
            tweet_url = 'https://twitter.com/NoHitterTracker/status/{tweet_id}'.format(tweet_id=response.data['id'])
            util.arodsg_ntfy(tweet_text_encoded, tweet_url)
        except TweepyException as e:
            util.arodsg_ntfy(str(e))
    else:
        update_team_ids_tweeted(team_id, is_combined=is_combined, is_perfect_game=is_perfect_game, is_finished=is_finished)
        util.arodsg_ntfy(tweet_text_encoded)


def get_team_hashtag(team_abbrv):
    team_hashtags = util.config['team_hashtags']
    return team_hashtags[team_abbrv] if team_abbrv in team_hashtags else team_abbrv


def load_team_ids_tweeted(file_path):
    try:
        with open(file_path, 'rb') as file:
            return pickle.load(file)
    except (FileNotFoundError, ValueError):
        return {}


def update_config_date(date):
    util.config['last_game_date'] = date
    with open(constants.CONFIG_FILE_PATH, 'w') as file:
        json.dump(util.config, file, indent=4)


def check_team(team_id, status):
    team_tweeted = team_id in team_ids_tweeted
    team_finished = team_ids_tweeted[team_id]['is_finished'] if team_tweeted else False
    return not team_finished and (status == 'I' or (status == 'F' and team_tweeted))


if __name__ == '__main__':
    util.load_config(constants.CONFIG_FILE_PATH)

    if util.config is not None:
        util.create_session()
        game_date = (datetime.now() - timedelta(hours=5)).strftime('%m/%d/%Y')
        game_info = get_game_info_by_date(game_date)

        if game_date == util.config['last_game_date']:
            team_ids_tweeted = load_team_ids_tweeted(constants.TEAM_IDS_TWEETED_FILE_PATH)
        else:
            reset_team_ids_tweeted()
            update_config_date(game_date)

        for game_id, game_info in game_info.items():
            game_status = game_info['status']
            game_home_team_id = game_info['home_team_id']
            game_away_team_id = game_info['away_team_id']
            check_home_team = check_team(game_home_team_id, game_status)
            check_away_team = check_team(game_away_team_id, game_status)

            if check_home_team or check_away_team:
                game = GameDetails(game_id)
                if check_home_team:
                    check_no_hitter(game, game_home_team_id)
                if check_away_team:
                    check_no_hitter(game, game_away_team_id)
    else:
        print('Error loading config data. Required keys: num_innings_to_alert, debug_mode, ntfy_settings, last_game_date, team_hashtags')
