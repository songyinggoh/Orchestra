import pytest
from orchestra.identity.agent_identity import AgentIdentity, AgentCard
from orchestra.identity.discovery import SignedDiscoveryProvider
from orchestra.core.errors import InvalidSignatureError
from orchestra.security.secrets import InMemorySecretProvider

def test_register_signed_card():
    identity = AgentIdentity.create()
    card = identity.create_card("agent-1", "worker", ["web_search"])
    
    discovery = SignedDiscoveryProvider()
    assert discovery.register(card) is True
    assert discovery.registered_count == 1
    
    retrieved = discovery.lookup(identity.did)
    assert retrieved.name == "agent-1"

def test_reject_unsigned_card():
    identity = AgentIdentity.create()
    card = AgentCard(did=identity.did, name="unsigned", agent_type="worker")
    
    discovery = SignedDiscoveryProvider()
    assert discovery.register(card) is False

def test_reject_tampered_card():
    identity = AgentIdentity.create()
    card = identity.create_card("agent-1", "worker", ["web_search"])
    
    # Tamper
    card.name = "evil"
    
    discovery = SignedDiscoveryProvider()
    assert discovery.register(card) is False

def test_max_cards_per_did():
    identity = AgentIdentity.create()
    discovery = SignedDiscoveryProvider(max_cards_per_did=2)
    
    c1 = identity.create_card("a1", "w", [], ttl=100)
    c1.version = 1
    c1.sign_jws(identity._make_okp_key())
    
    c2 = identity.create_card("a1", "w", [], ttl=100)
    c2.version = 2
    c2.sign_jws(identity._make_okp_key())
    
    c3 = identity.create_card("a1", "w", [], ttl=100)
    c3.version = 3
    c3.sign_jws(identity._make_okp_key())
    
    discovery.register(c1)
    discovery.register(c2)
    discovery.register(c3)
    
    # Only c3 and c2 should remain
    assert len(discovery._cards[identity.did]) == 2
    assert discovery.lookup(identity.did).version == 3

def test_lookup_by_type():
    discovery = SignedDiscoveryProvider()
    
    i1 = AgentIdentity.create()
    c1 = i1.create_card("w1", "worker", [])
    discovery.register(c1)
    
    i2 = AgentIdentity.create()
    c2 = i2.create_card("s1", "supervisor", [])
    discovery.register(c2)
    
    workers = discovery.lookup_by_type("worker")
    assert len(workers) == 1
    assert workers[0].name == "w1"

def test_expired_card_rejected():
    identity = AgentIdentity.create()
    card = identity.create_card("expired", "worker", [], ttl=-10)
    
    discovery = SignedDiscoveryProvider()
    assert discovery.register(card) is False

@pytest.mark.asyncio
async def test_in_memory_secret_provider():
    provider = InMemorySecretProvider()
    await provider.put_secret("path/to/key", b"secret-bytes")
    
    val = await provider.get_secret("path/to/key")
    assert val == b"secret-bytes"
    
    await provider.delete_secret("path/to/key")
    with pytest.raises(KeyError):
        await provider.get_secret("path/to/key")

def test_reject_wrong_key_card():
    i1 = AgentIdentity.create()
    i2 = AgentIdentity.create()
    
    # Sign i1's card with i2's key
    card = AgentCard(did=i1.did, name="fake", agent_type="worker")
    card.sign_jws(i2._make_okp_key())
    
    discovery = SignedDiscoveryProvider()
    assert discovery.register(card) is False

def test_version_ordering():
    identity = AgentIdentity.create()
    discovery = SignedDiscoveryProvider()
    
    c1 = identity.create_card("v1", "w", [], ttl=100)
    c1.version = 1
    c1.sign_jws(identity._make_okp_key())
    
    c2 = identity.create_card("v2", "w", [], ttl=100)
    c2.version = 2
    c2.sign_jws(identity._make_okp_key())
    
    # Register v2 first
    discovery.register(c2)
    
    # Try to register v1 (lower version) -> should be rejected or ignored
    assert discovery.register(c1) is False
    assert discovery.lookup(identity.did).version == 2
