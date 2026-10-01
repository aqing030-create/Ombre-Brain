"""recall-hook：归档桶不该被动浮现，冷却写不进去时也不能无限重复。

2026-10-01 查到的线上毛病（一个月的 jsonl 数出来的）：
337 个被浮现过的桶里，331 个 10 小时冷却内重复 0 次；重复的 3 个全是归档桶，
其中一张（已解决、重要度 4）一个月里被递了 249 回。

根因是两处叠在一起：
1. 归档不删向量，层 1（语义）和 feel 通道走 search_similar + get(bid)，照样搜得到归档桶
   （只有层 3 情绪共鸣用 list_all(include_archive=False) 排除了它们）；
2. 冷却靠 update(bid, last_surfaced=...) 写进桶的 frontmatter，而 update() 对
   type == "archived" 的桶直接 return False（归档是终态）——时间戳永远写不上去。

修复：被动浮现跳过归档桶；_mark_surfaced 在写不进去时用进程内存兜底。
"""
import pytest

from web import _shared as sh
from web import hooks


class _RankedEmbedding:
    """按给定顺序返回 (bucket_id, score) 的 embedding 替身。"""

    enabled = True

    def __init__(self):
        self.ranked: list[tuple[str, float]] = []
        self._store: dict[str, list[float]] = {}

    async def generate_and_store(self, bucket_id: str, content: str) -> bool:
        self._store[bucket_id] = [0.1, 0.2, 0.3]
        return True

    def delete_embedding(self, bucket_id: str) -> None:
        self._store.pop(bucket_id, None)

    async def get_embedding(self, bucket_id: str):
        return self._store.get(bucket_id)

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


@pytest.mark.asyncio
async def test_live_bucket_surfaces_once_then_cools(recall_env):
    mgr, engine = recall_env
    bid = await mgr.create(content="她说家的地址叫 xiaodu", importance=6)
    engine.ranked = [(bid, 0.9)]

    first = await hooks._recall_three_layers("家的地址是什么")
    second = await hooks._recall_three_layers("家的地址是什么")

    assert bid in first
    assert second == "", "活桶递过一次，冷却内不该再递"
    assert (await mgr.get(bid))["metadata"].get("last_surfaced")


@pytest.mark.asyncio
async def test_archived_bucket_is_not_passively_surfaced(recall_env):
    mgr, engine = recall_env
    live = await mgr.create(content="今天的日记：水声", importance=6)
    gone = await mgr.create(content="一天被夹好几次头的原因找到了", importance=4)
    assert await mgr.archive(gone)
    engine.ranked = [(gone, 0.95), (live, 0.9)]

    first = await hooks._recall_three_layers("好诶好诶 今天怎么样")

    assert gone not in first, "归档的桶不该被动浮现"
    assert live in first

    # 归档桶排在最前面也一样：一轮一轮问，它都不该出来
    engine.ranked = [(gone, 0.95)]
    for _ in range(3):
        assert gone not in await hooks._recall_three_layers("好诶好诶 今天怎么样")


@pytest.mark.asyncio
async def test_mark_surfaced_falls_back_when_metadata_write_is_rejected(recall_env):
    """冷却时间戳写不进桶（update 返回 False）时，同一进程里仍然算冷却中。"""
    mgr, _engine = recall_env
    bid = await mgr.create(content="写不进时间戳的桶", importance=6)
    assert await mgr.archive(bid)
    bucket = await mgr.get(bid)
    assert bucket is not None and not hooks._is_bucket_cooled(bucket)

    await hooks._mark_surfaced([bid])

    assert hooks._is_bucket_cooled(await mgr.get(bid)), (
        "update() 拒绝了归档桶，冷却必须有兜底，否则这张会每轮都来"
    )
