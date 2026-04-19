"""Tests for permission system."""

import pytest

from nexusagent.permission.policy import TrustPolicy
from nexusagent.permission.gate import PermissionGate
from nexusagent.models import ToolCall, PermissionDecision


def test_trust_policy_defaults():
    policy = TrustPolicy()
    assert policy.get_level("Read") == "approve"
    assert policy.get_level("Write") == "ask"
    assert policy.get_level("Bash") == "ask"


def test_trust_policy_custom():
    policy = TrustPolicy(tool_permissions={"Read": "deny"})
    assert policy.get_level("Read") == "deny"
    assert policy.get_level("Write") == "ask"  # default


def test_trust_policy_unknown_tool():
    policy = TrustPolicy()
    assert policy.get_level("UnknownTool") == "ask"  # fallback


@pytest.mark.asyncio
async def test_permission_gate_auto_approve():
    policy = TrustPolicy(tool_permissions={"Read": "approve"})
    gate = PermissionGate(policy)

    tc = ToolCall(id="1", name="Read", input={"file_path": "test.txt"})
    decision = await gate.check(tc)
    assert decision == PermissionDecision.APPROVE


@pytest.mark.asyncio
async def test_permission_gate_deny():
    policy = TrustPolicy(tool_permissions={"Bash": "deny"})
    gate = PermissionGate(policy)

    tc = ToolCall(id="1", name="Bash", input={"command": "rm -rf /"})
    decision = await gate.check(tc)
    assert decision == PermissionDecision.DENY
