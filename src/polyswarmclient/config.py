import logging

from polyswarmclient.log_formatter import JSONFormatter
from pythonjsonlogger import jsonlogger


def init_logging(log_format, loglevel=logging.INFO):
    """
    Logic to support JSON logging.
    """
    logger = logging.getLogger()  # Root logger
    if log_format and log_format in ['json', 'datadog']:
        logHandler = logging.StreamHandler()
        formatter = jsonlogger.JsonFormatter()
        formatter = JSONFormatter('(level) (name) (timestamp) (message)')
        logHandler.setFormatter(formatter)
        logger.addHandler(logHandler)
        logger.setLevel(loglevel)
        logger.info("Logging in JSON format.")
    else:
        logging.basicConfig(level=loglevel, format='%(levelname)s:%(name)s:%(asctime)s %(message)s')
        logger.info("Logging in text format.")
