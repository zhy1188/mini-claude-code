"""Tests for SessionManager."""

import json
import tempfile
import time
from pathlib import Path

from nexusagent.memory.session import SessionManager


def make_mgr():
    d = Path(tempfile.mkdtemp())
    return SessionManager(d)


def test_create_session_id():
    mgr = make_mgr()
    sid = mgr.create_session_id()
    assert isinstance(sid, str)
    assert len(sid) > 0


def test_create_unique_ids():
    mgr = make_mgr()
    id1 = mgr.create_session_id()
    time.sleep(1.1)  # Ensure different second (ID is strftime at second precision)
    id2 = mgr.create_session_id()
    assert id1 != id2


def test_save_session():
    mgr = make_mgr()
    sid = mgr.create_session_id()
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    path = mgr.save(sid, messages)
    assert path.exists()


def test_load_session():
    mgr = make_mgr()
    sid = mgr.create_session_id()
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    mgr.save(sid, messages)

    loaded = mgr.load(sid)
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded[0]["role"] == "user"


def test_load_nonexistent_session():
    mgr = make_mgr()
    loaded = mgr.load("nonexistent_session_id")
    assert loaded is None


def test_list_sessions():
    mgr = make_mgr()
    for i in range(3):
        sid = mgr.create_session_id()
        mgr.save(sid, [{"role": "user", "content": f"test {i}"}])
        time.sleep(1.1)

    sessions = mgr.list_sessions()
    assert len(sessions) == 3


def test_session_file_is_valid_json():
    mgr = make_mgr()
    sid = mgr.create_session_id()
    messages = [
        {"role": "user", "content": "test"},
        {"role": "assistant", "content": "response", "tool_calls": []},
    ]
    path = mgr.save(sid, messages)

    data = json.loads(path.read_text())
    assert "messages" in data
    assert len(data["messages"]) == 2
