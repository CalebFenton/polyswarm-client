import asyncio
import functools
import sys
import logging

from polyswarmclient import Client

logger = logging.getLogger(__name__)  # Initialize logger


# Extra blocks for the relay to process. Includes multiple relay transactions.
# 3 is minimum. 5 Gives a little extra room for slow transactions
RELAY_LEEWAY = 5

class BalanceManager():
    """
    Balance manager is used for single transfer events in either direction.
    Create a client, choose a chain and amount then run it.
    """
    def __init__(self, client, amount, testing=0, chains={'home', 'side'}):
        self.client = client
        self.chains = chains
        self.amount = amount
        self.testing = testing
        self.client.on_run.register(self.handle_run)
        self.exit_code = 0

    def run(self):
        """
        Starts the client on whichever chain this uses.
        """
        self.client.run(self.chains)

    async def handle_run(self, chain):
        """
        Just starts the transfer up async.
        """
        if self.testing > 0:
            for i in range(0, self.testing):
                logger.info('Transferred %d times of %s', i, self.testing)
                await self.handle_transfer(chain)
        else:
            await self.handle_transfer(chain)
        self.client.stop()

    async def handle_transfer(self, chain):
        """
        On client start, this tries to deposit or withdraw nectar from the sidechain.
        The direction, depends on the chain the client is running on.
        If it is on homechain, it deposits. Otherwise, withdraws.

        It also checks the balances to make sure the source chain wallet can cover the transfer.
        """
        balance = await self.client.balances.get_nct_balance(chain=chain)
        amount_wei = self.client.toWei(self.amount)
        if balance >= amount_wei:
            if chain == 'home':
                # deposit
                logger.info('Depositing: %s', self.amount)
                await self.client.relay.post_deposit(amount_wei)
            elif chain == 'side':
                # withdraw
                logger.info('Withdrawing: %s', self.amount)
                await self.client.relay.post_withdraw(amount_wei)
        else:
            if chain == 'home':
                # Converting from amount_wei because it gives a better string output than self.amount
                logger.info('Insufficient funds for deposit. Have %s, need %s', self.client.fromWei(balance), self.client.fromWei(amount_wei))
            elif chain == 'side':
                logger.info('Insufficient funds for withdrawal. Have %s, need %s', self.client.fromWei(balance), self.client.fromWei(amount_wei))

            self.exit_code = 1
            self.client.stop()

class Deposit(BalanceManager):
    """
    Deposit only version of Balance Manager
    """
    def __init__(self, client, amount, testing=0):
        super().__init__(client, amount, testing=testing, chains={'home'})

class Withdraw(BalanceManager):
    """
    Withdraw only version of Balance Manager
    """
    def __init__(self, client, amount, testing=0):
        super().__init__(client, amount, testing=testing, chains={'side'})

class Maintainer():
    """
    This class maintains a balance on the sidechain.
    It requires a base setup of a minimum balance.
    Optionally, it can take a maximum balance, so that earnings can automatically be transferred back to the homechain.
    """
    def __init__(self, client, confirmations, minimum, refill_amount, maximum, withdraw_target, testing=0):
        self.deposit_lock = asyncio.Lock()
        self.block_lock = asyncio.Lock()
        self.client = client
        self.client.on_new_block.register(self.watch_balance)
        self.last_relay = None
        self.latest_block = 0
        self.confirmations = confirmations
        self.minimum = self.client.toWei(minimum)
        self.refill_amount = self.client.toWei(refill_amount)
        self.maximum = None if maximum < 0 else self.client.toWei(maximum)
        self.withdraw_target = None if withdraw_target < 0 else self.client.toWei(withdraw_target)
        self.testing = testing
        self.transfers = 0

    def run(self):
        """
        Starts the client.
        Have to run with both chains, or lots of nonce errors
        """
        self.client.run({'home', 'side'})

    async def try_withdrawal(self, side_balance):
        """
        Computes the amount to withdraw based on the current balance, and the target balance.
        Then, it tries to withdraw the required NCT.
        """
        withdrawal_amount = side_balance - self.withdraw_target
        if side_balance > withdrawal_amount:
            logger.info('Sidechain balance (%s NCT) exceeds maximum (%s NCT). Withdrawing %s NCT', side_balance, self.maximum, withdrawal_amount)
            await self.client.relay.post_withdraw(withdrawal_amount)
            self.transfers += 1
            logger.info('Transferred %d times of %s', self.transfers, self.testing)
            # Don't need to wait on withdrawals. The funds are instantly locked up on the sidechain
        else:
            logger.info('Insufficient funds for withdrawal. Have %s, need %s', side_balance, withdrawal_amount)

    async def try_deposit(self, side_balance):
        """
        Deposits the refill amount to the sidechain, as long as there is a sufficient balance on the homechain.
        """
        home_balance = await self.client.balances.get_nct_balance(chain='home')
        if home_balance >= self.refill_amount:
            logger.info('Sidechain balance (%s NCT) is below minimum (%s NCT). Depositing %s NCT', side_balance, self.minimum, self.refill_amount)
            # Tell it to wait for the transaction to complete
            if await self.client.relay.post_deposit(self.refill_amount):
                # Account for blocks that moved while creating the transaction, and the transactions made by the relay
                async with self.block_lock:
                    self.last_relay = self.latest_block + RELAY_LEEWAY
            self.transfers += 1
            logger.info('Transferred %d times of %s', self.transfers, self.testing)
        else:
            logger.info('Insufficient funds for deposit. Have %s, need %s', home_balance, self.refill_amount)

    async def watch_balance(self, block, chain):
        """
        Stores the latest block and then kicks off some balance checks.
        If the balance is outside the given range, it deposits, or withdraws as needed.
        """
        if chain == 'home':
            return

        # Keep block up to date, so we can use that value when figuring out what block the transaction may have gone in
        if chain == 'side':
            async with self.block_lock:
                if block > self.latest_block:
                    self.latest_block = block
                else:
                    return

        async with self.deposit_lock:
            if self.testing > 0 and self.testing <= self.transfers:
                logger.info('Finished text runs')
                self.client.stop()

            if self.last_relay is not None and (self.last_relay + self.confirmations) >= block:
                more_blocks = self.last_relay + self.confirmations - block
                logger.info('Waiting for %d more blocks', more_blocks)
                return

            self.last_relay = None
            side_balance = await self.client.balances.get_nct_balance(chain='side')
            if self.maximum is not None and self.withdraw_target is not None and side_balance > self.maximum:
                await self.try_withdrawal(side_balance)
            elif side_balance < self.minimum:
                await self.try_deposit(side_balance)