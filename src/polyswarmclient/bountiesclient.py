import logging

from polyswarmclient import bloom


class BountiesClient(object):
    def __init__(self, client):
        self.__client = client
        self.parameters = {}

    async def get_parameters(self, chain='home'):
        """Get bounty parameters from polyswarmd

        Args:
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing bounty parameters
        """
        self.parameters[chain] = await self.__client.make_request('GET', '/bounties/parameters', chain)
        if self.parameters[chain] is None:
            raise Exception('Error retrieving bounty parameters')

    async def calculate_bloom(self, ipfs_uri):
        """Calculate bloom filter for a set of artifacts

        Args:
            ipfs_uri (str): IPFS URI for the artifact set

        Returns:
            Bloom filter value for the artifact set
        """
        artifacts = await self.__client.list_artifacts(ipfs_uri)
        bf = bloom.BloomFilter()
        for _, h in artifacts:
            bf.add(h.encode('utf-8'))

        return int(bf)

    async def get_bounty(self, guid, chain='home'):
        """Get a bounty from polyswarmd

        Args:
            guid (str): GUID of the bounty to retrieve
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing bounty details
        """
        path = '/bounties/{0}'.format(guid)
        return await self.__client.make_request('GET', path, chain)

    async def post_bounty(self, amount, artifact_uri, duration, chain='home'):
        """Post a bounty to polyswarmd

        Args:
            amount (int): The amount to put up as a bounty
            artifact_uri (str): URI of artifacts
            duration (int): Number of blocks to accept new assertions
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing emitted events
        """
        bounty = {
            'amount': str(amount),
            'uri': artifact_uri,
            'duration': duration,
        }
        results = await self.__client.make_request('POST', '/bounties', chain, json=bounty, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, chain)
        if 'bounties' not in results:
            logging.error('Expected bounty, received: %s', results)
        return results.get('bounties', [])

    async def get_assertion(self, bounty_guid, index, chain='home'):
        """Get an assertion from polyswarmd

        Args:
            bounty_guid (str): GUID of the bounty to retrieve the assertion from
            index (int): Index of the assertion
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing assertion details
        """
        path = '/bounties/{0}/assertions/{1}'.format(bounty_guid, index)
        return await self.__client.make_request('GET', path, chain)

    async def post_assertion(self, bounty_guid, bid, mask, verdicts, chain='home'):
        """Post an assertion to polyswarmd

        Args:
            bounty_guid (str): The bounty to assert on
            bid (int): The amount to bid
            mask (List[bool]): Which artifacts in the bounty to assert on
            verdicts (List[bool]): Verdict (malicious/benign) for each of the artifacts in the bounty
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing emitted events
        """
        path = '/bounties/{0}/assertions'.format(bounty_guid)
        assertion = {
            'bid': str(bid),
            'mask': mask,
            'verdicts': verdicts,
        }
        results = await self.__client.make_request('POST', path, chain, json=assertion, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        nonce = results.get('nonce', -1)
        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, chain)
        if 'assertions' not in results:
            logging.error('Expected assertion, received: %s', results)
        return nonce, results.get('assertions', [])

    async def post_reveal(self, bounty_guid, index, nonce, verdicts, metadata, chain='home'):
        """Post an assertion reveal to polyswarmd

        Args:
            bounty_guid (str): The bounty which we have asserted on
            index (int): The index of the assertion to reveal
            nonce (str): Secret nonce used to reveal assertion
            verdicts (List[bool]): Verdict (malicious/benign) for each of the artifacts in the bounty
            metadata (str): Optional metadata
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing emitted events
        """
        path = '/bounties/{0}/assertions/{1}/reveal'.format(bounty_guid, index)
        reveal = {
            'nonce': nonce,
            'verdicts': verdicts,
            'metadata': metadata,
        }
        results = await self.__client.make_request('POST', path, chain, json=reveal, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, chain)
        if 'reveals' not in results:
            logging.error('Expected reveal, received: %s', results)
        return results.get('reveals', [])

    async def post_vote(self, bounty_guid, verdicts, valid_bloom, chain='home'):
        """Post a bounty to polyswarmd

        Args:
            bounty_guid (str): The bounty which we are voting on
            verdicts (List[bool]): Verdict (malicious/benign) for each of the artifacts in the bounty
            valid_bloom (bool): Is the bloom filter reported by the bounty poster valid
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing emitted events
        """
        path = '/bounties/{0}/vote'.format(bounty_guid)
        vote = {
            'verdicts': verdicts,
            'valid_bloom': valid_bloom,
        }
        results = await self.__client.make_request('POST', path, chain, json=vote, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, chain)
        if 'verdicts' not in results:
            logging.error('Expected verdict, received: %s', results)
        return results.get('verdicts', [])

    async def settle_bounty(self, bounty_guid, chain='home'):
        """Settle a bounty via polyswarmd

        Args:
            bounty_guid (str): The bounty which we are settling
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing emitted events
        """
        path = '/bounties/{0}/settle'.format(bounty_guid)
        results = await self.__client.make_request('POST', path, chain, track_nonce=True)
        if not results:
            logging.error('Expected transactions, received: %s', results)
            return {}

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, chain)
        if 'transfers' not in results:
            logging.warning('No transfer event, received: %s (maybe expected)', results)
        return results.get('transfers', [])
