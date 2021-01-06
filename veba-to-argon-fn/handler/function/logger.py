import json
import logging.config
import logging
import requests


logger = logging.getLogger(__name__)


def init_logger():
    """Initialize and configure a logger for the application.
    """
    # create logger
    with open("./function/logging.json", "r", encoding="utf-8") as fd:
        logging.config.dictConfig(json.load(fd))
    # reduce log level for modules
    logging.captureWarnings(True)
    requests.packages.urllib3.disable_warnings()

