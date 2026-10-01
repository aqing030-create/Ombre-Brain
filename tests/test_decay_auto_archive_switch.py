"""decay.auto_archive 开关：关掉以后衰减只算分，不再把低分桶归档。

2026-10-01：归档的桶 update() 写不进（终态），recall-hook 的冷却时间戳落不了地，
而且沉下去的是七八月的瞬间。知间和小渡定的：不靠"忘"来图清静，自动归档关掉，
吵不吵归冷却和门槛管。默认值保持上游行为（开），用配置或环境变量关。
"""
import frontmatter as fm
import pytest


def _backdate(bucket_mgr, bucket_id: str, days_ago: int) -> None:
    from datetime import datetime, timedelta

    fpath = bucket_mgr._find_bucket_file(bucket_id)
    post = fm.load(fpath)
    old_ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    post["created"] = old_ts
    post["last_active"] = old_ts
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(fm.dumps(post))


async def _old_low_bucket(bucket_mgr) -> str:
    bid = await bucket_mgr.create(content="很久以前的一张便条", importance=1)
    _backdate(bucket_mgr, bid, days_ago=400)
    return bid


@pytest.mark.asyncio
async def test_default_still_archives_low_score_bucket(bucket_mgr, decay_eng):
    bid = await _old_low_bucket(bucket_mgr)

    stats = await decay_eng.run_decay_cycle()

    assert stats["archived"] == 1
    assert (await bucket_mgr.get(bid))["metadata"]["type"] == "archived"


@pytest.mark.asyncio
async def test_auto_archive_off_keeps_low_score_bucket_live(test_config, bucket_mgr):
    from decay_engine import DecayEngine

    test_config["decay"]["auto_archive"] = False
    eng = DecayEngine(test_config, bucket_mgr)
    bid = await _old_low_bucket(bucket_mgr)

    stats = await eng.run_decay_cycle()

    assert stats["archived"] == 0
    bucket = await bucket_mgr.get(bid)
    assert bucket["metadata"]["type"] != "archived"
    # 关的只是归档，分数照算——低分桶在 breath 里照样沉底
    assert eng.calculate_score(bucket["metadata"]) < eng.threshold


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["0", "false", "off", "no"])
async def test_env_switch_turns_auto_archive_off(test_config, bucket_mgr, monkeypatch, raw):
    from decay_engine import DecayEngine

    monkeypatch.setenv("OMBRE_AUTO_ARCHIVE", raw)
    eng = DecayEngine(test_config, bucket_mgr)
    bid = await _old_low_bucket(bucket_mgr)

    stats = await eng.run_decay_cycle()

    assert eng.auto_archive is False
    assert stats["archived"] == 0
    assert (await bucket_mgr.get(bid))["metadata"]["type"] != "archived"


def test_env_switch_overrides_config(test_config, bucket_mgr, monkeypatch):
    from decay_engine import DecayEngine

    test_config["decay"]["auto_archive"] = False
    monkeypatch.setenv("OMBRE_AUTO_ARCHIVE", "1")
    assert DecayEngine(test_config, bucket_mgr).auto_archive is True
