import importlib.util
import os
import sys
import json
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import logging
from pythonjsonlogger import jsonlogger

ARODSGNTFY_INSTALLED = is_module_installed('arodsgntfy')
if ARODSGNTFY_INSTALLED:
    from arodsgntfy import ntfy_send
    print('arodsgntfy module found.')

ENVIRONMENT = os.getenv('ENVIRONMENT', 'test')

logger = logging.getLogger()
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.flush = sys.stdout.flush
    log_format = "%(asctime)s %(levelname)s %(message)s"
    json_formatter = jsonlogger.JsonFormatter(log_format)
    handler.setFormatter(json_formatter)
    logger.addHandler(handler)

config = {}
session = requests.session()


def is_module_installed(module_name):
    return importlib.util.find_spec(module_name) is not None


def load_config(config_file_path):
    global logger, config
    logger.info('Loading config...')
    try:
        with open(config_file_path, 'r+') as file:
            required_keys = {'num_innings_to_alert', 'ntfy_settings', 'team_hashtags'}
            config_data = json.load(file)
            missing_keys = required_keys - config_data.keys()

            if missing_keys:
                raise KeyError(f"Missing required config keys: {', '.join(missing_keys)}")

            config = config_data
    except FileNotFoundError:
        logger.error('Config file not found.')
        return None


def create_session():
    global logger, session
    if session is not None:
        session.close()
    logger.info('Creating https session...')
    retries = Retry(total=5, backoff_factor=1)
    session.mount('https://', HTTPAdapter(max_retries=retries))


def make_request(url, params=None):
    return session.get(url, params=params)


def arodsg_ntfy(message, click_action=None):
    global config
    logger.info(message)

    if ARODSGNTFY_INSTALLED and config['ntfy_settings']['enabled']:
        ntfy_send(topic=config['ntfy_settings']['topic'], title=config['ntfy_settings']['title'], message=message, click_action=click_action, low_priority=False)
