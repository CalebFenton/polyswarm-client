import click
import importlib.util
import logging
import sys

from polyswarmclient.config import init_logging, LoggerConfig

logger = logging.getLogger(__name__)


def choose_backend(backend, logger_config):
    """Resolves amabassador name string to implementation

    Args:
        backend (str): Name of the backend to load, either one of the predefined
            implementations or the name of a module to load
            (module:ClassName syntax or default of module:Ambassador)
    Returns:
        (Class): Ambassador class of the selected implementation
    Raises:
        (Exception): If backend is not found
    """
    backend_list = backend.split(":")
    module_name_string = backend_list[0]

    # determine if this string is a module that can be imported as-is or as sub-module of the ambassador package
    mod_spec = importlib.util.find_spec(module_name_string) or importlib.util.find_spec(
        "ambassador.{0}".format(module_name_string))
    if mod_spec is None:
        raise Exception("Ambassador backend `{0}` cannot be imported as a python module.".format(backend))

    # have valid module that can be imported, so import it.
    ambassador_module = importlib.import_module(mod_spec.name)
    logger_config.configure(ambassador_module.__name__)

    # find Ambassador class in this module
    if hasattr(ambassador_module, "Ambassador"):
        ambassador_class = ambassador_module.Ambassador
    elif len(backend_list) == 2 and hasattr(ambassador_module, backend_list[1]):
        ambassador_class = getattr(ambassador_module, backend_list[1])
    else:
        raise Exception("No ambassador backend found {0}".format(backend))

    return ambassador_class


@click.command()
@click.option('--log', default='WARNING',
              help='Logging level')
@click.option('--polyswarmd-addr', envvar='POLYSWARMD_ADDR', default='localhost:31337',
              help='Address (host:port) of polyswarmd instance')
@click.option('--keyfile', envvar='KEYFILE', type=click.Path(exists=True), default='keyfile',
              help='Keystore file containing the private key to use with this ambassador')
@click.option('--password', envvar='PASSWORD', prompt=True, hide_input=True,
              help='Password to decrypt the keyfile with')
@click.option('--api-key', envvar='API_KEY', default='',
              help='API key to use with polyswarmd')
@click.option('--backend', envvar='BACKEND', required=True,
              help='Backend to use')
@click.option('--testing', default=0,
              help='Activate testing mode for integration testing, respond to N bounties and N offers then exit')
@click.option('--insecure-transport', is_flag=True,
              help='Connect to polyswarmd via http:// and ws://, mutually exclusive with --api-key')
@click.option('--chains', multiple=True, default=['side'],
              help='Chain(s) to operate on')
@click.option('--watchdog', default=0,
              help='Number of blocks to check if bounties are being processed')
@click.option('--log-format', default='text',
              help='Log format. Can be `json` or `text` (default)')
@click.option('--submission-rate', default=0, type=click.FLOAT,
              help='How often to submit a new sample in seconds. Default: No delay between submissions.')
# @click.option('--offers', envvar='OFFERS', default=False, is_flag=True,
#               help='Should the abassador send offers')
def main(log, polyswarmd_addr, keyfile, password, api_key, backend, testing, insecure_transport, chains, watchdog,
         log_format, submission_rate):
    """Entrypoint for the ambassador driver

    Args:
        log (str): Logging level
        polyswarmd_addr(str): Address of polyswarmd
        keyfile (str): Path to private key file to use to sign transactions
        password (str): Password to decrypt the encrypted private key
        backend (str): Backend implementation to use
        api_key(str): API key to use with polyswarmd
        testing (int): Mode to process N bounties then exit (optional)
        insecure_transport (bool): Connect to polyswarmd without TLS
        chains (List[str]): Chain(s) to operate on
        watchdog (int): Number of blocks to look back and see if bounties are being submitted
        log_format (str): Format to output logs in. `text` or `json`
    """
    loglevel = getattr(logging, log.upper(), None)
    if not isinstance(loglevel, int):
        logging.error('invalid log level')
        sys.exit(-1)
    # setup polyswarm-client logs
    init_logging(log_format, loglevel)
    # setup microengine logs
    config = LoggerConfig(log_format, loglevel)
    config.configure('ambassador')

    ambassador_class = choose_backend(backend, config)
    ambassador_class.connect(polyswarmd_addr, keyfile, password,
                             api_key=api_key, testing=testing,
                             insecure_transport=insecure_transport,
                             chains=set(chains), watchdog=watchdog,
                             submission_rate=submission_rate).run()


if __name__ == '__main__':
    # pylint: disable=no-value-for-parameter
    main()
