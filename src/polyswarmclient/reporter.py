import asyncio
import base64
import logging
import os
import random
import sys

from polyswarmclient import Client
from polyswarmclient.events import SettleBounty

logger = logging.getLogger(__name__)
EICAR = base64.b64decode(b'WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo=')

# TODO: Do we want all 'drivers' in this library?
POLYSWARMD_HOST = os.environ.get('POLYSWARMD_HOST', 'gamma-polyswarmd.prod.polyswarm.network')
KEYFILE = os.environ.get('KEYFILE', '')


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
        """
        Check a bounty's progress on a particular block.

        Args:
            number (int): Block number
            chain (str): Chain to operate on
        """
        if self.failed_already:
            return

        if self.stage == 'posted' and number > self.expiration:
            logger.error('Failed to get at least 1 assertion on bounty %s before expiration of %s (block %s) check micro engines',
                         self.guid, self.expiration, number)
            self.failed_already = True

    def mark_stage_complete(self, s):
        """
        Pass in the stage you want to mark as complete, it gets verified
        as a valid state transition and stored in the class.

        Args:
            s (str): State to mark complete
        """
        expected_current_stage = self.valid_transitions.get(s)
        if expected_current_stage == self.stage:
            self.stage = s
            return
        raise Exception('Invalid state transition {0} -> {1}'.format(self.stage, s))

    def all_complete(self):
        """
        Return true if all stages have been completed.

        Returns:
            bool: Whether or not all stages have been completed (based on self.stage)
        """
        # TODO advance
        return self.stage == 'asserted'


class Reporter(object):
    def __init__(self, polyswarmd_uri, keyfile, password, api_key=None, testing=0, insecure_transport=False, chains={'home'}):
    """Instantiate a Reporter and connect to `Client`.

    Args:
        polyswarmd_uri (str): URI of polyswarmd you are referring to.
        keyfile (str): Keyfile filename.
        password (str): Password associated with Keyfile.
        api_key (str): Your PolySwarm API key.
        testing (int): Number of testing bounties to use.
        insecure_transport (bool): Allow insecure transport such as HTTP?
        chains (set(str)):  Set of chains you are acting on.
    """
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
        """
        Run the `Client` on the Reporter's chains.
        """
        self.client.run(self.chains)

    def handle_run(self, chain):
        """
        Function to handle Reporter run logic.

        Args:
            chain (str): Chain to operate on.
        """
        asyncio.get_event_loop().create_task(self.run_task(0, chain))

    async def run_task(self, number, chain):
        """
        Function logic for how to run a task. If the bounty hasn't been submitted
        yet then post the artifact to ipfs and post the bounty to the specified chain.

        Args:
            number (int): Block number
            chain (str): Chain to operate on
        """
        if not self.submitted:
            bounty_amount_minimum = self.client.bounties.parameters[chain]['bounty_amount_minimum']
            assertion_reveal_window = self.client.bounties.parameters[chain]['assertion_reveal_window']
            arbiter_vote_window = self.client.bounties.parameters[chain]['arbiter_vote_window']

            ipfs_uri = await self.client.post_artifacts([('eicar.com.txt', EICAR)])
            if not ipfs_uri:
                logger.error('Error posting artifact')
                return

            # TODO track that they make it through stages of bounty hell: vote, arbitration, close
            logger.info('Posting bounty')
            bounties = await self.client.bounties.post_bounty(bounty_amount_minimum + random.randint(0, 600000), ipfs_uri, 20, chain)
            logger.info('Bounty posted')

            for bounty in bounties:
                expiration = int(bounty['expiration'])
                guid = bounty['guid']
                logger.warning('Posted bounty %s ipfs %s', guid, ipfs_uri)

                self.bounties['guid'] = BountyProgress(guid, expiration, assertion_reveal_window, arbiter_vote_window)

                sb = SettleBounty(guid)
                self.client.schedule(expiration + assertion_reveal_window + arbiter_vote_window, sb, chain)

            if self.bounties:
                self.submitted = True

    async def block_checker(self, number, chain):
        """
        Check the status of all of our bounties on a particular block and chain
        to see if they're all complete.

        Args:
            number (int): Block number
            chain (str): Chain to operate on
        """
        # TODO check that we're moving things through pipeline.
        # TODO report status per block
        for b in self.bounties.values():
            b.check_block(number, chain)

        completions = [b.all_complete() for b in self.bounties.values()]
        if completions:
            if functools.reduce(lambda x, y: x and y, completions):
                self.stop_event.set()

    async def handle_assertion(self, bounty_guid, author, index, bid, mask, commitment, chain=None):
        """
        Logic on how to handle a bounty assertion. If we have a record of the bounty
        then mark it as asserted.

        Args:
            bounty_guid (str): GUID of the bounty being asserted.
        """
        b = self.bounties.get(bounty_guid)
        if b:
            # TODO check assertion came before our deadline?
            b.mark_stage_complete('asserted')

    async def handle_settle_bounty(self, bounty_guid, chain):
        """
        Logic on how to handle a bounty settlement.

        Args:
            bounty_guid (str): The bounty which we are settling
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing emitted events
        """
        return await self.client.bounties.settle_bounty(bounty_guid, chain)


def main():
    n = Reporter(POLYSWARMD_HOST, KEYFILE, 'password', insecure_transport=True)
    n.run()


if __name__ == '__main__':
    main()
