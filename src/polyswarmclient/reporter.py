import asyncio
import base64
import logging
import os
import random
import sys

from polyswarmclient import Client
from polyswarmclient.events import SettleBounty

EICAR = base64.b64decode(b'WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo=')

# TODO: Do we want all 'drivers' in this library?
POLYSWARMD_HOST = os.environ.get('POLYSWARMD_HOST', 'gamma-polyswarmd.prod.polyswarm.network')
KEYFILE = os.environ.get('KEYFILE', '')

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
    datefmt='%H:%M:%S.',
    stream=sys.stdout)


class BountyProgress(object):
    def __init__(self, guid, expiration, assertion_reveal_window, arbiter_vote_window):
        self.expiration = expiration
        self.assertion_reveal_window = assertion_reveal_window
        self.arbiter_vote_window = arbiter_vote_window
        self.guid = guid
        self.marked_voted = False

        self.next_stages = {
            'posted': 'asserted',
            'asserted': 'revealed'
        }

        self.valid_transitions = {v: k for k, v in self.next_stages.items()}
        self.stage = 'posted'
        self.failed_already = False

    def check_block(self, number, chain):
        if self.failed_already:
            return

        if self.stage == 'posted' and number > self.expiration:
            logging.error('Failed to get at least 1 assertion on bounty %s before expiration of %s (block %s) check micro engines',
                          self.guid, self.expiration, number)
            self.failed_already = True

    def mark_stage_complete(self, s):
        expected_current_stage = self.valid_transitions.get(s)
        if expected_current_stage == self.stage:
            self.stage = s
            return
        raise Exception('Invalid state transition {0} -> {1}'.format(self.stage, s))

    def all_complete(self):
        # TODO advance
        return self.stage == 'asserted'


class Reporter(object):
    def __init__(self, polyswarmd_uri, keyfile, password, api_key=None, testing=0, insecure_transport=False, chains={'home'}):
        self.chains = chains
        self.testing = testing
        self.client = Client(polyswarmd_uri, keyfile, password, api_key, testing > 0, insecure_transport)
        self.client.on_new_block.register(self.run_task)
        self.client.on_new_block.register(self.block_checker)
        self.client.on_settle_bounty_due.register(self.handle_settle_bounty)
        # self.client.on_new_verdict.register(self.handle_verdict)
        self.client.on_new_assertion.register(self.handle_assertion)

        self.bounties = {}
        self.submitted = False

    def run(self):
        self.client.run(self.chains)

    def handle_run(self, chain):
        asyncio.get_event_loop().create_task(self.run_task(0, chain))

    async def run_task(self, number, chain):
        if not self.submitted:
            bounty_amount_minimum = self.client.bounties.parameters[chain]['bounty_amount_minimum']
            assertion_reveal_window = self.client.bounties.parameters[chain]['assertion_reveal_window']
            arbiter_vote_window = self.client.bounties.parameters[chain]['arbiter_vote_window']

            ipfs_uri = await self.client.post_artifacts([('eicar.com.txt', EICAR)])
            if not ipfs_uri:
                logging.error('Error posting artifact')
                return

            # TODO track that they make it through stages of bounty hell: vote, arbitration, close
            logging.info('Posting bounty')
            bounties = await self.client.bounties.post_bounty(bounty_amount_minimum + random.randint(0, 600000), ipfs_uri, 20, chain)
            logging.info('Bounty posted')

            for bounty in bounties:
                expiration = int(bounty['expiration'])
                guid = bounty['guid']
                logging.warning('Posted bounty %s ipfs %s', guid, ipfs_uri)

                self.bounties['guid'] = BountyProgress(guid, expiration, assertion_reveal_window, arbiter_vote_window)

                sb = SettleBounty(guid)
                self.client.schedule(expiration + assertion_reveal_window + arbiter_vote_window, sb, chain)

            if self.bounties:
                self.submitted = True

    async def block_checker(self, number, chain):
        # TODO check that we're moving things through pipeline.
        # TODO report status per block
        for b in self.bounties.values():
            b.check_block(number, chain)

        completions = [b.all_complete() for b in self.bounties.values()]
        if completions:
            if functools.reduce(lambda x, y: x and y, completions):
                self.stop_event.set()

    async def handle_assertion(self, bounty_guid, author, index, bid, mask, commitment, chain=None):
        b = self.bounties.get(bounty_guid)
        if b:
            # TODO check assertion came before our deadline?
            b.mark_stage_complete('asserted')

    async def handle_settle_bounty(self, bounty_guid, chain):
        return await self.client.bounties.settle_bounty(bounty_guid, chain)


def main():
    n = Reporter(POLYSWARMD_HOST, KEYFILE, 'password', insecure_transport=True)
    n.run()


if __name__ == '__main__':
    main()
