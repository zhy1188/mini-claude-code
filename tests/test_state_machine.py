"""Tests for the agent state machine."""

import pytest

from nexusagent.agent.state_machine import StateMachine, InvalidStateTransition


def test_initial_state_idle():
    sm = StateMachine()
    assert sm.current == "idle"


def test_valid_transition_idle_to_gathering():
    sm = StateMachine()
    sm.transition("gathering")
    assert sm.current == "gathering"


def test_full_lifecycle():
    sm = StateMachine()
    sm.transition("gathering")
    sm.transition("thinking")
    sm.transition("acting")
    sm.transition("gathering")
    sm.transition("thinking")
    sm.transition("verifying")
    sm.transition("done")
    sm.transition("idle")
    assert sm.current == "idle"


def test_invalid_transition_idle_to_done():
    sm = StateMachine()
    with pytest.raises(InvalidStateTransition):
        sm.transition("done")


def test_invalid_transition_thinking_to_idle():
    sm = StateMachine()
    sm.transition("gathering")
    sm.transition("thinking")
    with pytest.raises(InvalidStateTransition):
        sm.transition("idle")


def test_can_transition():
    sm = StateMachine()
    assert sm.can_transition("gathering") is True
    assert sm.can_transition("done") is False
    assert sm.can_transition("acting") is False


def test_can_transition_thinking():
    sm = StateMachine()
    sm.transition("gathering")
    sm.transition("thinking")
    assert sm.can_transition("acting") is True
    assert sm.can_transition("verifying") is True
    assert sm.can_transition("done") is True
    assert sm.can_transition("error") is True
    assert sm.can_transition("idle") is False


def test_force_transition():
    sm = StateMachine()
    sm.force("done")
    assert sm.current == "done"


def test_on_transition_callback():
    sm = StateMachine()
    calls = []
    sm.on_transition("gathering", lambda old, new: calls.append((old, new)))
    sm.transition("gathering")
    assert calls == [("idle", "gathering")]


def test_on_transition_callback_not_called_for_other_states():
    sm = StateMachine()
    calls = []
    sm.on_transition("thinking", lambda old, new: calls.append((old, new)))
    sm.transition("gathering")
    assert calls == []
    sm.transition("thinking")
    assert calls == [("gathering", "thinking")]


def test_reset():
    sm = StateMachine()
    sm.transition("gathering")
    sm.transition("thinking")
    sm.reset()
    assert sm.current == "idle"


def test_error_recovery():
    sm = StateMachine()
    sm.transition("gathering")
    sm.transition("thinking")
    sm.transition("error")
    assert sm.current == "error"
    sm.transition("idle")
    assert sm.current == "idle"


def test_done_to_idle():
    sm = StateMachine()
    sm.transition("gathering")
    sm.transition("thinking")
    sm.transition("verifying")
    sm.transition("done")
    sm.transition("idle")
    assert sm.current == "idle"


def test_gathering_to_compact():
    sm = StateMachine()
    sm.transition("gathering")
    sm.transition("compact")
    assert sm.current == "compact"


def test_compact_to_thinking():
    sm = StateMachine()
    sm.transition("gathering")
    sm.transition("compact")
    sm.transition("thinking")
    assert sm.current == "thinking"


def test_repr():
    sm = StateMachine()
    assert "idle" in repr(sm)


def test_invalid_state_transition_exception_attributes():
    sm = StateMachine()
    try:
        sm.transition("done")
    except InvalidStateTransition as e:
        assert e.current == "idle"
        assert e.target == "done"
