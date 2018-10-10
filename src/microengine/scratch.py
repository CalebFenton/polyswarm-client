import logging
from polyswarmclient.microengine import Microengine

logger = logging.getLogger(__name__)  # Initialize logger


class ScratchMicroengine(Microengine):
    """Scratch microengine is the same as the default behavior."""
    pass
