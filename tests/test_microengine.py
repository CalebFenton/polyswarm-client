import pytest

from polyswarmclient import BidStrategyBase
from polyswarmclient.abstractmicroengine import AbstractMicroengine
from microengine.bidstrategy.conservative import BidStrategy as ConservativeStrategy
from microengine.bidstrategy.default import BidStrategy as DefaultStrategy
from microengine.bidstrategy.aggressive import BidStrategy as AggressiveStrategy


class Microengine(AbstractMicroengine):
    def __init__(self, client, testing=0, scanner=None, chains=None, artifact_types=None, **kwargs):
        super().__init__(client, testing, scanner, chains, artifact_types, **kwargs)


class BidStrategy(BidStrategyBase):
    async def bid(self, guid, mask, verdicts, confidences, metadatas, min_allowed_bid, chain):
        return 11


@pytest.mark.asyncio
async def test_aggressive_bid_strategy_directly():
    # arrange
    bid_strategy = AggressiveStrategy()
    # act
    bid = await bid_strategy.bid('test', [True], [True], [1.0], [''], .0625 * 10 ** 18, 'side')
    # assert
    assert bid == 2 * 10 ** 18


@pytest.mark.asyncio
async def test_single_file_bid_aggressive(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=AggressiveStrategy())
    # act
    bid = await engine.bid('test', [True], [True], [1.0], [''], 'side')
    # assert
    assert bid == 2 * 10 ** 18


@pytest.mark.asyncio
async def test_single_file_bid_50_aggressive(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=AggressiveStrategy())
    # act
    bid = await engine.bid('test', [True], [True], [.5], [''], 'side')
    # assert
    assert bid == 1.25 * 10 ** 18


@pytest.mark.asyncio
async def test_test_file_bid_mast_false_aggressive(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=AggressiveStrategy())
    # act
    bid = await engine.bid('test', [False], [True], [1.0], [''], 'side')
    # assert
    assert bid == .5 * 10 ** 18


@pytest.mark.asyncio
async def test_single_bid_0_aggressive(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=AggressiveStrategy())
    # act
    bid = await engine.bid('test', [True], [True], [0], [''], 'side')
    # assert
    assert bid == .5 * 10 ** 18


@pytest.mark.asyncio
async def test_default_bid_strategy_directly():
    # arrange
    bid_strategy = DefaultStrategy()
    # act
    bid = await bid_strategy.bid('test', [True], [True], [1.0], [''], .0625 * 10 ** 18, 'side')
    # assert
    assert bid == .5 * 10 ** 18


@pytest.mark.asyncio
async def test_single_file_bid_default(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=DefaultStrategy())
    # act
    bid = await engine.bid('test', [True], [True], [1.0], [''], 'side')
    # assert
    assert bid == .5 * 10 ** 18


@pytest.mark.asyncio
async def test_single_file_bid_50_default(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=DefaultStrategy())
    # act
    bid = await engine.bid('test', [True], [True], [.5], [''], 'side')
    # assert
    assert bid == .28125 * 10 ** 18


@pytest.mark.asyncio
async def test_test_file_bid_mast_false_default(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=DefaultStrategy())
    # act
    bid = await engine.bid('test', [False], [True], [1.0], [''], 'side')
    # assert
    assert bid == .0625 * 10 ** 18


@pytest.mark.asyncio
async def test_single_bid_0_default(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=DefaultStrategy())
    # act
    bid = await engine.bid('test', [True], [True], [0], [''], 'side')
    # assert
    assert bid == .0625 * 10 ** 18


@pytest.mark.asyncio
async def test_conservative_bid_strategy_directly():
    # arrange
    bid_strategy = ConservativeStrategy()
    # act
    bid = await bid_strategy.bid('test', [True], [True], [1.0], [''], .0625 * 10 ** 18, 'side')
    # assert
    assert bid == .0625 * 10 ** 18


@pytest.mark.asyncio
async def test_single_file_bid_conservative(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=ConservativeStrategy())
    # act
    bid = await engine.bid('test', [True], [True], [1.0], [''], 'side')
    # assert
    assert bid == .0625 * 10 ** 18


@pytest.mark.asyncio
async def test_single_file_bid_50_conservative(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=ConservativeStrategy())
    # act
    bid = await engine.bid('test', [True], [True], [.5], [''], 'side')
    # assert
    assert bid == .0625 * 10 ** 18


@pytest.mark.asyncio
async def test_test_file_bid_mast_false_conservative(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=ConservativeStrategy())
    # act
    bid = await engine.bid('test', [False], [True], [1.0], [''], 'side')
    # assert
    assert bid == .0625 * 10 ** 18


@pytest.mark.asyncio
async def test_single_bid_0_conservative(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=ConservativeStrategy())
    # actpolyswarmd_addr
    bid = await engine.bid('test', [True], [True], [0], [''], 'side')
    # assert
    assert bid == .0625 * 10 ** 18


@pytest.mark.asyncio
async def test_two_files_100_confidence(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=DefaultStrategy())
    # act
    bid = await engine.bid('test', [True, True], [True, True], [1.0, 1.0], ['', ''], 'side')
    # assert
    assert bid == .5 * 10 ** 18


@pytest.mark.asyncio
async def test_two_files_50_confidence(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=DefaultStrategy())
    # act
    bid = await engine.bid('test', [True, True], [True, True], [.5, .5], ['', ''], 'side')
    # assert
    assert bid == .28125 * 10 ** 18


@pytest.mark.asyncio
async def test_two_files_0_confidence(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=DefaultStrategy())
    # act
    bid = await engine.bid('test', [True, True], [True, True], [0, 0], ['', ''], 'side')
    # assert
    assert bid == .0625 * 10 ** 18


@pytest.mark.asyncio
async def test_two_files_one_mask_75_confidence(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=DefaultStrategy())
    # act
    bid = await engine.bid('test', [True, False], [True, True], [.75, .2], ['', ''], 'side')
    # assert
    assert bid == .390625 * 10 ** 18


@pytest.mark.asyncio
async def test_two_files_mixed_50_confidence(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=DefaultStrategy())
    # act
    bid = await engine.bid('test', [True, True], [True, True], [.75, .25], ['', ''], 'side')
    # assert
    assert bid == .28125 * 10 ** 18


@pytest.mark.asyncio
async def test_256_files_mixed_75_confidence(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=DefaultStrategy())
    confidences = ([1.0] * 128)
    confidences.extend([.5] * 128)
    # act
    bid = await engine.bid('test', [True] * 256, [True] * 256, confidences, [''] * 256, 'side')
    # assert
    assert bid == .390625 * 10 ** 18


@pytest.mark.asyncio
async def test_no_bid_strategy(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=None)
    # assert
    with pytest.raises(NotImplementedError):
        await engine.bid('test', [True], [True], [1.0], [''], 'side')


@pytest.mark.asyncio
async def test_custom_bid_strategy(mock_client):
    # arrange
    engine = Microengine(mock_client, bid_strategy=BidStrategy())
    # act
    bid = await engine.bid('test', [True], [True], [1.0], [''], 'side')
    # assert
    assert bid == .0625 * 10 ** 18


@pytest.mark.asyncio
async def test_custom_bid_strategy_directly():
    # arrange
    bid_strategy = BidStrategy()
    # act
    bid = await bid_strategy.bid('test', [True], [True], [1.0], [''], .0625 * 10 ** 18, 'side')
    # assert
    assert bid == 11
