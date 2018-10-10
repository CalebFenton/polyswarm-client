import logging

logger = logging.getLogger(__name__)


class StakingClient(object):
    def __init__(self, client):
        self.__client = client
        self.parameters = {}

    async def get_parameters(self, chain='home'):
        """Get staking parameters from polyswarmd

        Args:
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing staking parameters
        """
        self.parameters[chain] = await self.__client.make_request('GET', '/staking/parameters', chain)
        if self.parameters[chain] is None:
            raise Exception('Error retrieving bounty parameters')

    async def get_total_balance(self, chain='home'):
        """Get total staking balance from polyswarmd

        Args:
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing staking balance
        """
        path = '/balances/{0}/staking/total'.format(self.__client.account)
        return int(await self.__client.make_request('GET', path, chain))

    async def get_withdrawable_balance(self, chain='home'):
        """Get withdrawable staking balance from polyswarmd

        Args:
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing staking balance
        """
        path = '/balances/{0}/staking/withdrawable'.format(self.__client.account)
        return int(await self.__client.make_request('GET', path, chain))

    async def post_deposit(self, amount, chain='home'):
        """Post a deposit to the staking contract

        Args:
            amount (int): The amount to stake
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing emitted events
        """
        deposit = {
            'amount': str(amount),
        }
        results = await self.__client.make_request('POST', '/staking/deposit', chain, json=deposit, track_nonce=True)
        if not results:
            logger.error('Expected transactions, received: %s', results)
            return []

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, chain)
        if 'deposits' not in results:
            logger.error('Expected deposit, received: %s', results)
        return results.get('deposits', [])

    async def post_withdraw(self, amount, chain='home'):
        """Post a withdrawal to the staking contract

        Args:
            amount (int): The amount to withdraw
            chain (str): Which chain to operate on

        Returns:
            Response JSON parsed from polyswarmd containing emitted events
        """
        withdrawal = {
            'amount': str(amount),
        }
        results = await self.__client.make_request('POST', '/staking/withdraw', chain, json=withdrawal, track_nonce=True)
        if not results:
            logger.error('Expected transactions, received: %s', results)
            return []

        transactions = results.get('transactions', [])
        results = await self.__client.post_transactions(transactions, chain)
        if 'withdrawals' not in results:
            logger.error('Expected withdrawal, received: %s', results)
        return results.get('withdrawals', [])
