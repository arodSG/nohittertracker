import json
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
# from arodsgntfy import ntfy_send

config = {}
session = requests.session()


def load_config(config_file_path):
    global config
    print('Loading config...')
    try:
        with open(config_file_path, 'r+') as file:
            required_keys = {'num_innings_to_alert', 'debug_mode', 'ntfy_settings', 'last_game_date', 'team_hashtags'}
            config_data = json.load(file)
            missing_keys = required_keys - config_data.keys()

            if missing_keys:
                raise KeyError(f"Missing required config keys: {', '.join(missing_keys)}")

            config = config_data
            print('Config loaded.')
    except FileNotFoundError:
        print('Error loading config.')
        return None


def create_session():
    global session
    retries = Retry(total=5, backoff_factor=1)
    session.mount('https://', HTTPAdapter(max_retries=retries))


def make_request(url, params=None):
    return session.get(url, params=params)


def arodsg_ntfy(message, click_action=None):
    global config
    # if config['ntfy_settings']['enabled']:
    #     ntfy_send(topic=config['ntfy_settings']['topic'], title=config['ntfy_settings']['title'], message=message, click_action=click_action, low_priority=False)
    # else:
    #     print(message)
