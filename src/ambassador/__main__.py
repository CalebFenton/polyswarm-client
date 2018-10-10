import click
import importlib
import logging
import sys

from ambassador.eicar import EicarAmbassador
from ambassador.filesystem import FilesystemAmbassador
from polyswarmclient.config import init_logging

logger = logging.getLogger(__name__)  # Initialize logger


def choose_backend(backend):
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
    ambassador_class = None
    if backend == 'eicar':
        ambassador_class = EicarAmbassador
    elif backend == 'filesystem':
        ambassador_class = FilesystemAmbassador
    else:
        import_l = backend.split(":")
        ambassador_module_s = import_l[0]

        ambassador_module = importlib.import_module(ambassador_module_s)
        ambassador_class = ambassador_module.Ambassador if ":" not in backend else getattr(ambassador_module, import_l[1])

    if ambassador_class is None:
        raise Exception("No ambassador backend found {0}".format(backend))

    return ambassador_class


@click.command()
@click.option('--log', default='INFO',
              help='Logging level')
@click.option('--polyswarmd-addr', envvar='POLYSWARMD_ADDR', default='localhost:31337',
              help='Address (host:port) of polyswarmd instance')
@click.option('--keyfile', envvar='KEYFILE', type=click.Path(exists=True), default='keyfile',
              help='Keystore file containing the private key to use with this ambassador')
@click.option('--password', envvar='PASSWORD', prompt=True, hide_input=True,
              help='Password to decrypt the keyfile with')
@click.option('--api-key', envvar='API_KEY', default='',
              help='API key to use with polyswarmd')
@click.option('--backend', envvar='BACKEND', default='scratch',
              help='Backend to use')
@click.option('--testing', default=0,
              help='Activate testing mode for integration testing, respond to N bounties and N offers then exit')
@click.option('--insecure-transport', is_flag=True,
              help='Connect to polyswarmd via http:// and ws://, mutially exclusive with --api-key')
@click.option('--chains', multiple=True, default=['home'],
              help='Chain(s) to operate on')
@click.option('--watchdog', default=0,
              help='Number of blocks to check if bounties are being processed')
@click.option('--log_format', default='text',
              help='Log format. Can be `json` or `text` (default)')
# @click.option('--offers', envvar='OFFERS', default=False, is_flag=True,
#               help='Should the abassador send offers')
def main(log, polyswarmd_addr, keyfile, password, api_key, backend, testing, insecure_transport, chains, watchdog, log_format):
    """Entrypoint for the ambassador driver

    Args:
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
    init_logging(log_format, loglevel)

    ambassador_class = choose_backend(backend)
    ambassador_class.connect(polyswarmd_addr, keyfile, password,
                             api_key=api_key, testing=testing,
                             insecure_transport=insecure_transport,
                             chains=set(chains), watchdog=watchdog).run()


if __name__ == '__main__':
    main()
