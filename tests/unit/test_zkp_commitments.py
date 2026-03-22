"""Tests for SHA-256 state commitments (Tier 1)."""

from __future__ import annotations

from orchestra.interop.zkp import StateCommitment


def test_state_commitment_verify():
    state = {"agent": "A", "status": "working"}
    result = StateCommitment.commit(state)

    # Correct verification
    assert StateCommitment.verify(state, result.commitment, result.nonce) is True


def test_state_commitment_tamper():
    state = {"agent": "A", "status": "working"}
    result = StateCommitment.commit(state)

    # Tampered state should fail
    tampered_state = {"agent": "A", "status": "failed"}
    assert StateCommitment.verify(tampered_state, result.commitment, result.nonce) is False


def test_state_commitment_chain():
    state0 = {"step": 0}
    res0 = StateCommitment.commit(state0)

    state1 = {"step": 1}
    res1 = StateCommitment.commit(state1, previous_commitment=res0.commitment)

    # Correct chained verification
    assert (
        StateCommitment.verify(
            state1, res1.commitment, res1.nonce, previous_commitment=res0.commitment
        )
        is True
    )

    # Wrong previous commitment should fail
    assert (
        StateCommitment.verify(state1, res1.commitment, res1.nonce, previous_commitment=b"wrong")
        is False
    )
