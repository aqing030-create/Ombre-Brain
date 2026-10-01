"""recall-hook：冷却掉的名额空着，不让后面的顶上。

原先是"先滤冷却、再取满 3 张"：最像的三张递过一次以后，名额就由第 4–9 名顶上，
聊得越久递来的越不沾边（一句"好诶好诶"能递来三张不相干的）。
知间 2026-10-01 定的："没合适的空着，这个也要"——宁可不递，也不乱递。

三个通道一个规矩：语义层只看前 N 名，情绪共鸣只看最近的一张，feel 只看最像的一条；
它们在冷却，就空着。
"""
from datetime import datetime, timezone

import pytest

from web import _shared as sh
from web import hooks


class _RankedEmbedding:
    enabled = True

    def __init__(self):
        self.ranked: list[tuple[str, float]] = []

    async def generate_and_store(self, bucket_id: str, content: str) -> bool:
        return True

    def delete_embedding(self, bucket_id: str) -> None:
        return None

    async def get_embedding(self, bucket_id: str):
        return [0.1, 0.2, 0.3]

    async def search_similar(self, query: str, top_k: int = 10):
        return list(self.ranked[:top_k])


@pytest.fixture
def recall_env(test_config, monkeypatch):
    from bucket_manager import BucketManager

    engine = _RankedEmbedding()
    mgr = BucketManager(test_config, embedding_engine=engine)
    monkeypatch.setattr(sh, "bucket_mgr", mgr)
    monkeypatch.setattr(sh, "embedding_engine", engine)
    volatile = getattr(hooks, "_volatile_surfaced", None)
    if volatile is not None:
        volatile.clear()
    return mgr, engine


async def _cool(mgr, bucket_id: str) -> None:
    assert await mgr.update(
        bucket_id, last_surfaced=datetime.now(timezone.utc).isoformat()
    )


@pytest.mark.asyncio
async def test_cooled_top_ranks_are_not_backfilled_by_lower_ranks(recall_env):
    mgr, engine = recall_env
    ids = [
        await mgr.create(content=f"第 {i + 1} 名的记忆", importance=6)
        for i in range(5)
    ]
    engine.ranked = [(bid, 0.9 - i * 0.01) for i, bid in enumerate(ids)]

    first = await hooks._recall_three_layers("今天怎么样")
    second = await hooks._recall_three_layers("今天怎么样")

    assert all(bid in first for bid in ids[:3])
    assert ids[3] not in first and ids[4] not in first
    assert second == "", "前三名都在冷却：空着，不该让第四、第五名顶上"


@pytest.mark.asyncio
async def test_only_uncooled_members_of_top_ranks_surface(recall_env):
    mgr, engine = recall_env
    ids = [
        await mgr.create(content=f"第 {i + 1} 名的记忆", importance=6)
        for i in range(4)
    ]
    await _cool(mgr, ids[0])
    engine.ranked = [(bid, 0.9 - i * 0.01) for i, bid in enumerate(ids)]

    out = await hooks._recall_three_layers("今天怎么样")

    assert ids[0] not in out
    assert ids[1] in out and ids[2] in out
    assert ids[3] not in out, "第一名冷却空出来的位置，不给第四名"


@pytest.mark.asyncio
async def test_cooled_best_feel_is_not_replaced_by_next_feel(recall_env):
    mgr, engine = recall_env
    live = await mgr.create(content="今天的日记", importance=6)
    best_feel = await mgr.create(content="不确定有了位置放", bucket_type="feel")
    next_feel = await mgr.create(content="你在", bucket_type="feel")
    await _cool(mgr, best_feel)
    engine.ranked = [(live, 0.9), (best_feel, 0.8), (next_feel, 0.7)]

    out = await hooks._recall_three_layers("有点拿不准")

    assert live in out
    assert best_feel not in out
    assert next_feel not in out, "最像的那条 feel 在冷却：空着，不拿次像的顶"


@pytest.mark.asyncio
async def test_cooled_nearest_emotion_is_not_replaced_by_next_nearest(recall_env):
    mgr, engine = recall_env
    live = await mgr.create(content="今天的日记", importance=6)
    # "开心" → (valence 0.8, arousal 0.6)
    nearest = await mgr.create(content="月光花开了", importance=6, valence=0.8, arousal=0.6)
    runner_up = await mgr.create(content="图鉴满了", importance=6, valence=0.75, arousal=0.6)
    await _cool(mgr, nearest)
    engine.ranked = [(live, 0.9)]

    out = await hooks._recall_three_layers("今天好开心")

    assert live in out
    assert nearest not in out
    assert runner_up not in out, "情绪最近的那张在冷却：空着，不拿次近的顶"


@pytest.mark.asyncio
async def test_uncooled_feel_and_emotion_still_surface(recall_env):
    """对照：没冷却的时候，feel 和情绪共鸣照常来——没把通道改哑。"""
    mgr, engine = recall_env
    live = await mgr.create(content="今天的日记", importance=6)
    feel = await mgr.create(content="不确定有了位置放", bucket_type="feel")
    emo = await mgr.create(content="月光花开了", importance=6, valence=0.8, arousal=0.6)
    engine.ranked = [(live, 0.9), (feel, 0.8)]

    out = await hooks._recall_three_layers("今天好开心")

    assert live in out and feel in out and emo in out
