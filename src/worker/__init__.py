import asyncio
import json
import logging
import sys
import time

import aiohttp
import aioredis

from polyswarmclient.utils import asyncio_join, asyncio_stop, exit, MAX_WAIT

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 5.0


class Worker():
    def __init__(self, redis_addr, queue, polyswarmd_addr, api_key=None, testing=0, insecure_transport=False,
                 scanner=None):
        self.redis_uri = 'redis://' + redis_addr

        protocol = 'http://' if insecure_transport else 'https://'
        self.polyswarmd_uri = protocol + polyswarmd_addr

        self.queue = queue
        self.polyswarmd_addr = polyswarmd_addr
        self.api_key = api_key
        self.testing = testing
        self.insecure_transport = insecure_transport
        self.scanner = scanner

        self.tries = 0

    def run(self):
        while True:
            loop = asyncio.SelectorEventLoop()

            # Default event loop does not support pipes on Windows
            if sys.platform == 'win32':
                loop = asyncio.ProactorEventLoop()

            asyncio.set_event_loop(loop)

            try:
                asyncio.get_event_loop().run_until_complete(self.run_task())
            except asyncio.CancelledError:
                logger.info('Clean exit requested, exiting')

                asyncio_join()
                exit(0)
            except Exception:
                logger.exception('Unhandled exception at top level')
                asyncio_stop()
                asyncio_join()

                self.tries += 1
                wait = min(MAX_WAIT, self.tries * self.tries)

                logger.critical('Detected unhandled exception, sleeping for %s seconds then resetting task', wait)
                time.sleep(wait)
                continue

    async def run_task(self):
        if self.api_key and not self.polyswarmd_uri.startswith('https://'):
            raise Exception('Refusing to send API key over insecure transport')

        conn = aiohttp.TCPConnector(limit=0, limit_per_host=0)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout) as session:
            redis = await aioredis.create_redis(self.redis_uri)
            while True:
                try:
                    _, job = await redis.blpop(self.queue)
                    job = json.loads(job.decode('utf-8'))
                    logger.info('Got job: %s', job)

                    guid = job['guid']
                    uri = job['uri']
                    index = job['index']
                    chain = job['chain']
                except (AttributeError, TypeError, ValueError):
                    logger.exception('Invalid job received, ignoring')
                    continue

                headers = {'Authorization': self.api_key} if self.api_key is not None else None
                uri = '{}/artifacts/{}/{}'.format(self.polyswarmd_uri, uri, index)

                try:
                    response = await session.get(uri, headers=headers)
                    response.raise_for_status()

                    content = await response.read()
                except aiohttp.ClientResponseError:
                    logger.exception('Error fetching artifact %s', uri)
                    continue
                except asyncio.TimeoutError:
                    logger.exception('Timeout fetching artifact %s', uri)
                    continue

                result = await self.scanner.scan(guid, content, chain)

                j = json.dumps({
                    'index': index,
                    'bit': result.bit,
                    'verdict': result.verdict,
                    'confidence': result.confidence,
                    'metadata': result.metadata,
                })

                logger.info('Scan results: %s', j)

                key = '{}_{}_{}_results'.format(self.queue, guid, chain)
                await redis.rpush(key, j)
