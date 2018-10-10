import logging

from functools import total_ordering
from queue import PriorityQueue

logger = logging.getLogger(__name__)


class Callback(object):
    """
    Abstract callback class which is the parent to a number of child
    callback classes to be used in different scenarios.

    Note:
        Classes which extend `Callback` are expected to impliment the
        `run` method.
    """

    def __init__(self):
        self.cbs = []

    def register(self, f):
        """
        Register a function to this Callback.

        Args:
            f (function): Function to register.
        """
        self.cbs.append(f)

    def remove(self, f):
        """
        Remove a function previously assigned to this Callback.

        Args:
            f (function): Function to remove.
        """
        self.cbs.remove(f)

    async def run(self, *args, **kwargs):
        """
        Run all of the registered callback functions.

        Returns:
            results (List[any]): Results returned from the callback functions
        """
        results = []
        for cb in self.cbs:
            local_ret = await cb(*args, **kwargs)
            if local_ret is not None:
                results.append(local_ret)

        if results:
            logger.info('%s callback results: %s', type(self).__name__, results)

        return results


# Create these subclasses so we can document the parameters to each callback
class OnRunCallback(Callback):
    """Called upon entering the event loop for the first time, use for initialization"""

    async def run(self, chain):
        """Run the registered callbacks

        Args:
            chain (str): Chain event received on
        """
        return await super().run(chain)


class OnNewBlockCallback(Callback):
    """Called upon receiving a new block, scheduled events triggered separately"""

    async def run(self, number, chain):
        """Run the registered callbacks

        Args:
            number (int): Block number received
            chain (str): Chain event received on
        """
        return await super().run(number, chain)


class OnNewBountyCallback(Callback):
    """Called upon receiving a new bounty"""

    async def run(self, guid, author, amount, uri, expiration, chain):
        """Run the registered callbacks

        Args:
            guid (str): Bounty GUID
            author (str): Author of the bounty
            uri (str): URI of the artifacts in the bounty
            expiration (int): Block number the bounty expires on
            chain (str): Chain event received on
        """
        return await super().run(guid, author, amount, uri, expiration, chain)


class OnNewAssertionCallback(Callback):
    """Called upon receiving a new assertion"""

    async def run(self, bounty_guid, author, index, bid, mask, commitment, chain):
        """Run the registered callbacks

        Args:
            bounty_guid (str): Bounty GUID
            author (str): Author of the assertion
            index (int): Index of the assertion within the bounty
            mask (List[bool]): Bitmask indicating which artifacts are being asserted on
            commitment (int): Commitment hash representing the assertion's confidential verdicts
            chain (str): Chain event received on
        """
        return await super().run(bounty_guid, author, index, bid, mask, commitment, chain)


class OnRevealAssertionCallback(Callback):
    """Called upon receiving a new assertion reveal"""

    async def run(self, bounty_guid, author, index, nonce, verdicts, metadata, chain):
        """Run the registered callbacks

        Args:
            bounty_guid (str): Bounty GUID
            author (str): Author of the assertion
            index (int): Index of the assertion within the bounty
            nonce (int): Nonce used to calculate the commitment hash for this assertion
            verdicts (List[bool]): Bitmask indicating malicious or benign verdicts for each artifact
            metadata (str): Optional metadata for this assertion
            chain (str): Chain event received on
        """
        return await super().run(bounty_guid, author, index, nonce, verdicts, metadata, chain)


class OnNewVerdictCallback(Callback):
    """Called upon receiving a new arbiter vote"""

    async def run(self, bounty_guid, verdicts, voter, chain):
        """Run the registered callbacks

        Args:
            bounty_guid (str): Bounty GUID
            verdicts (List[bool]): Bitmask indicating malicious or benign verdicts for each artifact
            voter (str): Which arbiter is voting
            chain (str): Chain event received on
        """
        return await super().run(bounty_guid, verdicts, voter, chain)


class OnQuorumReachedCallback(Callback):
    """Called upon a bounty reaching quorum"""

    async def run(self, bounty_guid, quorum_block, chain):
        """Run the registered callbacks

        Args:
            bounty_guid (str): Bounty GUID
            quorum_block (int): Block the bounty reached quorum on
            chain (str): Chain event received on
        """
        return await super().run(bounty_guid, quorum_block, chain)


class OnSettledBountyCallback(Callback):
    """Called upon a bounty being settled"""

    async def run(self, settled_block, settler, chain):
        """Run the registered callbacks

        Args:
            settled_block (int): Block the bounty was settled on
            settler (str): Address settling the bounty
            chain (str): Chain event received on
        """
        return await super().run(settled_block, settler, chain)


class OnAmbassadorOpenedOfferCallback(Callback):
    """Called upon a channel being created and opened by an ambassador"""

    async def run(self, guid, ambassador, expert, multi_signature, chain):
        """Run the registered callbacks

        Args:
            guid (str): GUID of the channel
            ambassador (str): Address of the ambassador
            expert (str): Address of the expert
            multi_signature (str): Address of the multisig contract
        """
        return await super().run(guid, ambassador, expert, multi_signature)

class OnExpertJoinedOfferCallback(Callback):
     """Called upon a channel being joined by an expert"""

    async def run(self, guid):
        """Run the registered callbacks

        Args:
            guid (str): GUID of the channel
        """
        return await super().run(guid)


class OnExpertReceivedOfferCallback(Callback):
    """Called upon an offer being received"""

    async def run(self, guid, amount, ipfs_uri):
        """Run the registered callbacks

        Args:
            guid (str): GUID of the channel
            ambassador (str): Address of the ambassador
            expert (str): Address of the expert
            msig (str): Address of the multi sig contract
            chain (str): Chain event received on
        """
<<<<<<< HEAD
        return await super().run(guid, ambassador, expert, multi_signature)

class OnAmbassadorReceivedOfferVerdictCallback(Callback):
     """Called upon an offer verdict being received"""

    async def run(self, guid, verdicts):
        """Run the registered callbacks

        Args:
            guid (str): GUID of the channel
            ambassador (str): Address of the ambassador
            expert (str): Address of the expert
            msig (str): Address of the multi sig contract
            chain (str): Chain event received on
        """
        return await super().run(guid, verdicts)




class OnOfferClosedAgreementCallback(Callback):
    """Called upon a channel being closed"""

    async def run(self, expert, ambassador):
        """Run the registered callbacks

        Args:
            ambassador (str): Address of the ambassador
            expert (str): Address of the expert
        """
        return await super().run(expert, ambassador)


class OnOfferSettleStartedCallback(Callback):
    """Called upon a channel dispute being initiated"""

    async def run(self, initiator, nonce, settle_period_end):
        """Run the registered callbacks

        Args:
            initiator (str): Address of the challenge initiator
            nonce (int): Sequence number of the challenge
            settle_period_end (int): Block the settlement period ends on
        """
        return await super().run(initiator, nonce, settle_period_end)


class OnOfferSettleChallengedCallback(Callback):
    """Called upon a channel dispute being initiated"""

    async def run(self, challenger, nonce, settle_period_end):
        """Run the registered callbacks

        Args:
            challenger (str): Address of the challenger
            nonce (int): Sequence number of the challenge
            settle_period_end (int): Block the settlement period ends on
        """
        return await super().run(challenger, nonce, settle_period_end)


class Schedule(object):
    """
    Generic Schedule class. Uses a PriorityQueue data structure to store Events.
    """

    def __init__(self):
        self.queue = PriorityQueue()

    def empty(self):
        """
        Return True if the queue is empty.

        Returns:
            boolean: Is the queue empty.
        """
        return self.queue.empty()

    def peek(self):
        """
        Return True if the queue is empty.

        Returns:
            (block, event): Tuple at the front of the queue if the queue is full, else `None`.
        """
        return self.queue.queue[0] if self.queue.queue else None

    def get(self):
        """
        Pop the lowest valued block in the queue.

        Returns:
            (block, event): The lowest valued block in the PriorityQueue.
        """
        return self.queue.get()

    def put(self, block, event):
        """
        Add a tuple (block, event) to the PriorityQueue. Block signifies the priority of the event.
        """
        self.queue.put((block, event))


@total_ordering
class Event(object):
    """
    Generic Event class. Stores GUID and can compare for equality and order Events.

    Args:
        guid (str): GUID of the event.
    """

    def __init__(self, guid):
        self.guid = guid

    def __eq__(self, other):
        return self.guid == other.guid

    def __lt__(self, other):
        return self.guid < other.guid


class RevealAssertion(Event):
    """An assertion scheduled to be publically revealed

    Args:
        guid (str): GUID of the bounty being asserted on
        index (int): Index of the assertion to reveal
        nonce (str): Secret nonce used to reveal assertion
        verdicts (List[bool]): List of verdicts for each artifact in the bounty
        metadata (str): Optional metadata
    """

    def __init__(self, guid, index, nonce, verdicts, metadata):
        """Initialize a reveal secret assertion event"""
        super().__init__(guid)
        self.index = index
        self.nonce = nonce
        self.verdicts = verdicts
        self.metadata = metadata


class OnRevealAssertionDueCallback(Callback):
    """Called when an assertion is needing to be revealed"""

    async def run(self, bounty_guid, index, nonce, verdicts, metadata, chain):
        """Run the registered callbacks

        Args:
            bounty_guid (str): GUID of the bounty being asserted on
            index (int): Index of the assertion to reveal
            nonce (str): Secret nonce used to reveal assertion
            verdicts (List[bool]): List of verdicts for each artifact in the bounty
            metadata (str): Optional metadata
            chain (str): Chain event received on
        """
        return await super().run(bounty_guid, index, nonce, verdicts, metadata, chain)


class VoteOnBounty(Event):
    """A scheduled vote from an arbiter
     Args:
        guid (str): GUID of the bounty being voted on
        verdicts (List[bool]): List of verdicts for each artifact in the bounty
        valid_bloom (bool): Is the bloom filter submitted with the bounty valid
    """

    def __init__(self, guid, verdicts, valid_bloom):
        """Initialize a vote on verdict event"""
        super().__init__(guid)
        self.verdicts = verdicts
        self.valid_bloom = valid_bloom


class OnVoteOnBountyDueCallback(Callback):
    """Called when a bounty is needing to be voted on"""

    async def run(self, bounty_guid, verdicts, valid_bloom, chain):
        """Run the registered callbacks

        Args:
            bounty_guid (str): GUID of the bounty being voted on
            verdicts (List[bool]): List of verdicts for each artifact in the bounty
            valid_bloom (bool): Is the bloom filter submitted with the bounty valid
            chain (str): Chain event received on
        """
        return await super().run(bounty_guid, verdicts, valid_bloom, chain)


class SettleBounty(Event):
    """A bounty scheduled to be settled
     Args:
        guid (str): GUID of the bounty being asserted on
    """

    def __init__(self, guid):
        """Initialize an settle bounty event
        """
        super().__init__(guid)


class OnSettleBountyDueCallback(Callback):
    """Called when a bounty is needing to be settled"""

    async def run(self, bounty_guid, chain):
        """Run the registered callbacks

        Args:
            bounty_guid (str): GUID of the bounty being voted on
            chain (str): Chain event received on
        """
        return await super().run(bounty_guid, chain)
