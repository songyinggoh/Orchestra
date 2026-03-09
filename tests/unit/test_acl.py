"""Tests for Tool ACL (Access Control List) security."""

from __future__ import annotations

import pytest
from orchestra.core.agent import BaseAgent
from orchestra.core.context import ExecutionContext
from orchestra.core.types import ToolResult, ToolCall
from orchestra.security.acl import ToolACL
from orchestra.storage.events import SecurityViolation


class MockTool:
    def __init__(self, name: str):
        self.name = name
        self.description = f"Test tool {name}"
        self.parameters_schema = {}

    async def execute(self, arguments: dict, context: ExecutionContext) -> ToolResult:
        return ToolResult(tool_call_id="123", name=self.name, content=f"executed {self.name}")


@pytest.mark.asyncio
async def test_tool_acl_allow_list() -> None:
    """Verify explicit allow list works."""
    t1 = MockTool("read_db")
    t2 = MockTool("write_db")
    
    # Only allow read_db
    acl = ToolACL.allow_list(["read_db"])
    agent = BaseAgent(name="secure_agent", tools=[t1, t2], acl=acl)
    
    context = ExecutionContext(run_id="test_run")
    
    # Authorized call
    res1 = await agent._execute_tool(ToolCall(id="c1", name="read_db", arguments={}), context)
    assert "executed read_db" in res1.content
    
    # Unauthorized call
    res2 = await agent._execute_tool(ToolCall(id="c2", name="write_db", arguments={}), context)
    assert "Security Policy Violation" in res2.error
    assert res2.content == ""


@pytest.mark.asyncio
async def test_tool_acl_patterns() -> None:
    """Verify pattern-based authorization."""
    t1 = MockTool("safe_tool_1")
    t2 = MockTool("safe_tool_2")
    t3 = MockTool("unsafe_tool")
    
    acl = ToolACL(allow_patterns=["safe_*"], allow_all=False)
    agent = BaseAgent(tools=[t1, t2, t3], acl=acl)
    context = ExecutionContext(run_id="test_run")
    
    assert "executed safe_tool_1" in (await agent._execute_tool(ToolCall(id="1", name="safe_tool_1", arguments={}), context)).content
    assert "executed safe_tool_2" in (await agent._execute_tool(ToolCall(id="2", name="safe_tool_2", arguments={}), context)).content
    assert "Security Policy Violation" in (await agent._execute_tool(ToolCall(id="3", name="unsafe_tool", arguments={}), context)).error


@pytest.mark.asyncio
async def test_acl_security_event_emission() -> None:
    """Verify SecurityViolation events are emitted."""
    from orchestra.storage.store import EventBus
    
    t1 = MockTool("forbidden")
    acl = ToolACL.allow_list(["allowed"])
    agent = BaseAgent(tools=[t1], acl=acl)
    
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))
    
    context = ExecutionContext(run_id="r1", node_id="n1")
    context.event_bus = bus
    
    await agent._execute_tool(ToolCall(id="c1", name="forbidden", arguments={}), context)
    
    assert len(events) == 1
    assert isinstance(events[0], SecurityViolation)
    assert events[0].agent_name == "agent"
    assert events[0].violation_type == "unauthorized_tool"
    assert events[0].details["tool_name"] == "forbidden"
