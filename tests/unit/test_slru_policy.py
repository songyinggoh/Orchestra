from orchestra.memory.tiers import MemoryEntry, SLRUPolicy, Tier


def test_slru_insert_and_promote():
    policy = SLRUPolicy(hot_max=2, warm_max=2)

    # 1. Insert first item -> goes to WARM
    policy.insert("k1", MemoryEntry("k1", "v1"))
    assert "k1" in policy.warm_keys
    assert "k1" not in policy.hot_keys

    # 2. Access item in WARM -> promotes to HOT
    new_tier, _evictions = policy.access("k1")
    assert new_tier == Tier.HOT
    assert "k1" in policy.hot_keys
    assert "k1" not in policy.warm_keys


def test_slru_hot_demotion():
    policy = SLRUPolicy(hot_max=2, warm_max=2)

    # Fill HOT
    policy.insert("k1", MemoryEntry("k1", "v1"))
    policy.access("k1")  # promote
    policy.insert("k2", MemoryEntry("k2", "v2"))
    policy.access("k2")  # promote

    assert sorted(policy.hot_keys) == ["k1", "k2"]

    # Insert and promote k3 -> should demote k1 (LRU in HOT) to WARM
    policy.insert("k3", MemoryEntry("k3", "v3"))
    policy.access("k3")

    assert "k1" in policy.warm_keys
    assert sorted(policy.hot_keys) == ["k2", "k3"]


def test_slru_warm_eviction():
    policy = SLRUPolicy(hot_max=2, warm_max=2)

    # Fill WARM
    policy.insert("k1", MemoryEntry("k1", "v1"))
    policy.insert("k2", MemoryEntry("k2", "v2"))
    assert sorted(policy.warm_keys) == ["k1", "k2"]

    # Insert k3 -> should evict k1 (LRU in WARM) to COLD
    evicted = policy.insert("k3", MemoryEntry("k3", "v3"))
    assert evicted == [("k1", Tier.COLD)]
    assert sorted(policy.warm_keys) == ["k2", "k3"]


def test_slru_chain_reaction():
    # hot_max=1, warm_max=1
    policy = SLRUPolicy(hot_max=1, warm_max=1)

    # 1. k1 in HOT
    policy.insert("k1", MemoryEntry("k1", "v1"))
    policy.access("k1")

    # 2. k2 in WARM
    policy.insert("k2", MemoryEntry("k2", "v2"))

    # 3. k3 inserted and promoted to HOT
    # k3 -> HOT
    # k1 demoted from HOT -> WARM
    # k2 evicted from WARM -> COLD
    policy.insert("k3", MemoryEntry("k3", "v3"))
    _new_tier, _evictions = policy.access("k3")

    assert "k3" in policy.hot_keys
    assert "k1" in policy.warm_keys
    assert "k2" not in policy.hot_keys and "k2" not in policy.warm_keys
    assert policy.hot_keys == ["k3"]
    assert policy.warm_keys == ["k1"]
