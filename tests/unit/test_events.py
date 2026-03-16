"""Tests for the event-sourced persistence layer (Task 2.1)."""
from __future__ import annotations

from datetime import datetime

import pytest

from orchestra.storage.events import (
    AnyEvent,
    CheckpointCreated,
    EdgeTraversed,
    ErrorOccurred,
    EventType,
    ExecutionCompleted,
    ExecutionStarted,
    HandoffCompleted,
    HandoffInitiated,
    InterruptRequested,
    InterruptResumed,
    LLMCalled,
    NodeCompleted,
    NodeStarted,
    OutputRejected,
    ParallelCompleted,
    ParallelStarted,
    StateUpdated,
    ToolCalled,
    WorkflowEvent,
    create_event,
)
from orchestra.storage.store import EventBus, InMemoryEventStore, RunSummary, project_state
from orchestra.storage.serialization import (
    dict_to_event,
    event_to_dict,
    event_to_json,
    events_to_jsonl,
    json_to_event,
    jsonl_to_events,
)
from orchestra.storage.contracts import BoundaryContract, ContractRegistry


# ---- Event Type Tests ----


class TestEventTypes:
    def test_all_event_types_instantiate(self):
        """Every event type can be created with minimal required fields."""
        events = [
            ExecutionStarted(run_id="r1", workflow_name="test"),
            ExecutionCompleted(run_id="r1", final_state={"x": 1}),
            NodeStarted(run_id="r1", node_id="n1"),
            NodeCompleted(run_id="r1", node_id="n1"),
            StateUpdated(run_id="r1", node_id="n1", resulting_state={"x": 1}),
            ErrorOccurred(run_id="r1", error_type="ValueError"),
            LLMCalled(run_id="r1", node_id="n1", model="gpt-4"),
            ToolCalled(run_id="r1", node_id="n1", tool_name="search"),
            EdgeTraversed(run_id="r1", from_node="a", to_node="b"),
            ParallelStarted(run_id="r1", source_node="a", target_nodes=("b", "c")),
            ParallelCompleted(run_id="r1", source_node="a", target_nodes=("b", "c")),
            InterruptRequested(run_id="r1", node_id="n1"),
            InterruptResumed(run_id="r1", node_id="n1"),
            CheckpointCreated(run_id="r1", state_snapshot={"x": 1}),
            OutputRejected(run_id="r1", node_id="n1", agent_name="a1"),
            HandoffInitiated(run_id="r1", from_agent="a", to_agent="b"),
            HandoffCompleted(run_id="r1", from_agent="a", to_agent="b"),
        ]
        assert len(events) == 17
        for e in events:
            assert e.run_id == "r1"
            assert e.event_id  # auto-generated
            assert isinstance(e.timestamp, datetime)

    def test_events_are_immutable(self):
        """Frozen events cannot be modified."""
        event = NodeStarted(run_id="r1", node_id="n1")
        with pytest.raises(Exception):  # ValidationError for frozen model
            event.node_id = "changed"

    def test_create_event_factory(self):
        """create_event() auto-generates id and timestamp."""
        event = create_event(NodeStarted, run_id="r1", sequence=5, node_id="n1")
        assert event.run_id == "r1"
        assert event.sequence == 5
        assert event.node_id == "n1"
        assert event.event_type == EventType.NODE_STARTED

    def test_event_type_enum_completeness(self):
        """EventType enum has an entry for every event class."""
        assert len(EventType) == 21


# ---- EventBus Tests ----


class TestEventBus:
    async def test_emit_dispatches_to_subscribers(self):
        bus = EventBus()
        received = []
        bus.subscribe(lambda e: received.append(e))
        event = NodeStarted(run_id="r1", node_id="n1")
        await bus.emit(event)
        assert len(received) == 1
        assert received[0].node_id == "n1"

    async def test_emit_filters_by_event_type(self):
        bus = EventBus()
        received = []
        bus.subscribe(lambda e: received.append(e), event_types=[EventType.NODE_STARTED])
        await bus.emit(NodeStarted(run_id="r1", node_id="n1"))
        await bus.emit(LLMCalled(run_id="r1", node_id="n1", model="gpt-4"))
        assert len(received) == 1

    async def test_wildcard_subscriber_receives_all(self):
        bus = EventBus()
        received = []
        bus.subscribe(lambda e: received.append(e))  # No filter = wildcard
        await bus.emit(NodeStarted(run_id="r1", node_id="n1"))
        await bus.emit(LLMCalled(run_id="r1", node_id="n1", model="gpt-4"))
        await bus.emit(NodeCompleted(run_id="r1", node_id="n1"))
        assert len(received) == 3

    async def test_async_subscriber(self):
        """EventBus correctly awaits async subscribers."""
        bus = EventBus()
        received = []

        async def async_handler(e: WorkflowEvent) -> None:
            received.append(e)

        bus.subscribe(async_handler)
        await bus.emit(NodeStarted(run_id="r1", node_id="n1"))
        assert len(received) == 1

    def test_sequence_numbers_monotonic(self):
        bus = EventBus()
        seqs = [bus.next_sequence("r1") for _ in range(5)]
        assert seqs == [0, 1, 2, 3, 4]

    def test_sequence_numbers_independent_per_run(self):
        bus = EventBus()
        assert bus.next_sequence("r1") == 0
        assert bus.next_sequence("r2") == 0
        assert bus.next_sequence("r1") == 1
        assert bus.next_sequence("r2") == 1


# ---- InMemoryEventStore Tests ----


class TestInMemoryEventStore:
    async def test_append_and_get(self):
        store = InMemoryEventStore()
        e1 = NodeStarted(run_id="r1", node_id="n1", sequence=0)
        e2 = NodeCompleted(run_id="r1", node_id="n1", sequence=1)
        await store.append(e1)
        await store.append(e2)
        events = await store.get_events("r1")
        assert len(events) == 2

    async def test_filter_by_type(self):
        store = InMemoryEventStore()
        await store.append(NodeStarted(run_id="r1", node_id="n1", sequence=0))
        await store.append(LLMCalled(run_id="r1", node_id="n1", model="gpt-4", sequence=1))
        await store.append(NodeCompleted(run_id="r1", node_id="n1", sequence=2))
        events = await store.get_events("r1", event_types=[EventType.LLM_CALLED])
        assert len(events) == 1
        assert events[0].event_type == EventType.LLM_CALLED

    async def test_after_sequence_filter(self):
        # after_sequence is exclusive: returns events with sequence > after_sequence
        store = InMemoryEventStore()
        for i in range(5):
            await store.append(NodeStarted(run_id="r1", node_id=f"n{i}", sequence=i))
        events = await store.get_events("r1", after_sequence=3)
        assert len(events) == 1  # only sequence=4

    async def test_checkpoint_save_and_restore(self):
        store = InMemoryEventStore()
        cp = CheckpointCreated(run_id="r1", state_snapshot={"x": 42}, sequence=10)
        await store.save_checkpoint(cp)
        restored = await store.get_latest_checkpoint("r1")
        assert restored is not None
        assert restored.state_snapshot == {"x": 42}

    async def test_list_runs(self):
        store = InMemoryEventStore()
        await store.append(ExecutionStarted(run_id="r1", workflow_name="wf1", sequence=0))
        await store.append(ExecutionStarted(run_id="r2", workflow_name="wf2", sequence=0))
        runs = await store.list_runs()
        assert len(runs) == 2
        assert all(isinstance(r, RunSummary) for r in runs)

    async def test_protocol_conformance(self):
        """InMemoryEventStore satisfies the EventStore protocol."""
        from orchestra.storage.store import EventStore

        store = InMemoryEventStore()
        assert isinstance(store, EventStore)


# ---- Serialization Tests ----


class TestSerialization:
    def test_json_roundtrip(self):
        event = LLMCalled(
            run_id="r1",
            node_id="n1",
            sequence=3,
            agent_name="researcher",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.003,
        )
        json_str = event_to_json(event)
        restored = json_to_event(json_str)
        assert isinstance(restored, LLMCalled)
        assert restored.agent_name == "researcher"
        assert restored.cost_usd == 0.003

    def test_dict_roundtrip(self):
        event = StateUpdated(
            run_id="r1",
            node_id="n1",
            sequence=2,
            field_updates={"count": 5},
            resulting_state={"count": 5, "name": "test"},
        )
        d = event_to_dict(event)
        restored = dict_to_event(d)
        assert isinstance(restored, StateUpdated)
        assert restored.resulting_state == {"count": 5, "name": "test"}

    def test_jsonl_roundtrip(self):
        events = [
            NodeStarted(run_id="r1", node_id="n1", sequence=0),
            NodeCompleted(run_id="r1", node_id="n1", sequence=1),
        ]
        jsonl = events_to_jsonl(events)
        restored = jsonl_to_events(jsonl)
        assert len(restored) == 2
        assert isinstance(restored[0], NodeStarted)
        assert isinstance(restored[1], NodeCompleted)

    def test_all_types_json_roundtrip(self):
        """Every event type survives JSON serialization."""
        events = [
            ExecutionStarted(run_id="r1", workflow_name="test"),
            ExecutionCompleted(run_id="r1"),
            NodeStarted(run_id="r1", node_id="n1"),
            NodeCompleted(run_id="r1", node_id="n1"),
            StateUpdated(run_id="r1", node_id="n1", resulting_state={}),
            ErrorOccurred(run_id="r1"),
            LLMCalled(run_id="r1", node_id="n1"),
            ToolCalled(run_id="r1", node_id="n1"),
            EdgeTraversed(run_id="r1", from_node="a", to_node="b"),
            ParallelStarted(run_id="r1", source_node="a"),
            ParallelCompleted(run_id="r1", source_node="a"),
            InterruptRequested(run_id="r1", node_id="n1"),
            InterruptResumed(run_id="r1", node_id="n1"),
            CheckpointCreated(run_id="r1"),
            OutputRejected(run_id="r1", node_id="n1"),
            HandoffInitiated(run_id="r1", from_agent="a", to_agent="b"),
            HandoffCompleted(run_id="r1", from_agent="a", to_agent="b"),
        ]
        for event in events:
            json_str = event_to_json(event)
            restored = json_to_event(json_str)
            assert type(restored) is type(event), f"Type mismatch for {type(event).__name__}"


# ---- Projection Tests ----


class TestProjection:
    def test_project_from_state_updated(self):
        events = [
            ExecutionStarted(run_id="r1", initial_state={"x": 0, "y": 0}, sequence=0),
            StateUpdated(
                run_id="r1", node_id="n1", resulting_state={"x": 1, "y": 0}, sequence=1
            ),
            StateUpdated(
                run_id="r1", node_id="n2", resulting_state={"x": 1, "y": 2}, sequence=2
            ),
        ]
        state = project_state(events)
        assert state == {"x": 1, "y": 2}

    def test_project_with_checkpoint(self):
        events = [
            ExecutionStarted(run_id="r1", initial_state={"x": 0}, sequence=0),
            StateUpdated(run_id="r1", node_id="n1", resulting_state={"x": 5}, sequence=1),
            CheckpointCreated(run_id="r1", state_snapshot={"x": 5}, sequence=2),
            StateUpdated(run_id="r1", node_id="n2", resulting_state={"x": 10}, sequence=3),
        ]
        state = project_state(events)
        assert state == {"x": 10}

    def test_project_with_explicit_initial_state(self):
        events = [
            StateUpdated(run_id="r1", node_id="n1", resulting_state={"x": 42}, sequence=0),
        ]
        state = project_state(events, initial_state={"x": 0, "y": 0})
        assert state == {"x": 42}

    def test_project_empty_events(self):
        state = project_state([], initial_state={"x": 0})
        assert state == {"x": 0}


# ---- Contract Tests ----


class TestContracts:
    def test_contract_from_pydantic(self):
        from pydantic import BaseModel

        class Output(BaseModel):
            answer: str
            confidence: float

        contract = BoundaryContract.from_pydantic(Output)
        assert contract.name == "Output"
        assert "properties" in contract.schema

    def test_registry_validates_registered(self):
        from pydantic import BaseModel

        class Output(BaseModel):
            answer: str

        registry = ContractRegistry()
        registry.register("agent1", BoundaryContract.from_pydantic(Output))
        errors = registry.validate("agent1", {"answer": "hello"})
        assert errors == []

    def test_registry_skips_unregistered(self):
        registry = ContractRegistry()
        errors = registry.validate("unknown_agent", {"anything": "goes"})
        assert errors == []


# ---- Persistence Error Tests ----


class TestPersistenceErrors:
    def test_error_hierarchy(self):
        from orchestra.core.errors import (
            CheckpointError,
            ContractValidationError,
            EventStoreError,
            OrchestraError,
            PersistenceError,
        )

        assert issubclass(PersistenceError, OrchestraError)
        assert issubclass(EventStoreError, PersistenceError)
        assert issubclass(CheckpointError, PersistenceError)
        assert issubclass(ContractValidationError, PersistenceError)


# ---- Context Integration Test ----


class TestContextIntegration:
    def test_event_bus_field_exists(self):
        from orchestra.core.context import ExecutionContext

        ctx = ExecutionContext()
        assert ctx.event_bus is None

    def test_event_bus_field_accepts_bus(self):
        from orchestra.core.context import ExecutionContext

        bus = EventBus()
        ctx = ExecutionContext(event_bus=bus)
        assert ctx.event_bus is bus
