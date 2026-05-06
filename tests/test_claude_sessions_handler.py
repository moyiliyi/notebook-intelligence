"""Wire-shape tests for ClaudeSessionsListHandler.

The handler is a thin wrapper around ``list_all_sessions``, but its
response shape (``{sessions, current_cwd, current_sessions_dir}``) is the
only Python↔TypeScript contract not pinned elsewhere. A silent rename of
any of those keys would break the chat picker's ``filterSessionsToDir``
filter without any test failing — these tests prevent that.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import notebook_intelligence.extension as ext_module
from notebook_intelligence.claude_sessions import ClaudeSessionInfo
from notebook_intelligence.extension import ClaudeSessionsListHandler


def _make_handler():
    handler = MagicMock(spec=ClaudeSessionsListHandler)
    handler.request = MagicMock()
    return handler


def _parse_response(handler) -> dict:
    return json.loads(handler.finish.call_args[0][0])


@pytest.fixture
def claude_mode_on():
    with patch.object(ext_module, "ai_service_manager") as mock_asm:
        mock_asm.is_claude_code_mode = True
        yield mock_asm


@pytest.fixture
def claude_mode_off():
    with patch.object(ext_module, "ai_service_manager") as mock_asm:
        mock_asm.is_claude_code_mode = False
        yield mock_asm


class TestClaudeSessionsListHandler:
    def test_returns_404_when_claude_code_mode_off(self, claude_mode_off):
        handler = _make_handler()
        ClaudeSessionsListHandler.get(handler)
        handler.set_status.assert_called_with(404)
        body = _parse_response(handler)
        assert "error" in body

    def test_response_shape_pins_python_typescript_contract(
        self, claude_mode_on, tmp_path
    ):
        # Empty result is enough — we're pinning keys, not values.
        with patch.object(ext_module, "list_all_claude_sessions", return_value=[]):
            with patch.object(
                ext_module, "get_jupyter_root_dir", return_value=str(tmp_path)
            ):
                handler = _make_handler()
                ClaudeSessionsListHandler.get(handler)

        body = _parse_response(handler)
        assert set(body.keys()) == {
            "sessions",
            "current_cwd",
            "current_sessions_dir",
        }

    def test_serializes_session_info_records(self, claude_mode_on, tmp_path):
        sessions = [
            ClaudeSessionInfo(
                session_id="abc12345",
                path=str(tmp_path / "abc12345.jsonl"),
                modified_at=1.0,
                created_at=0.0,
                preview="hello",
                cwd=str(tmp_path),
            )
        ]
        with patch.object(
            ext_module, "list_all_claude_sessions", return_value=sessions
        ):
            with patch.object(
                ext_module, "get_jupyter_root_dir", return_value=str(tmp_path)
            ):
                handler = _make_handler()
                ClaudeSessionsListHandler.get(handler)

        body = _parse_response(handler)
        assert len(body["sessions"]) == 1
        assert set(body["sessions"][0].keys()) == {
            "session_id",
            "path",
            "modified_at",
            "created_at",
            "preview",
            "cwd",
        }
        assert body["sessions"][0]["session_id"] == "abc12345"
        assert body["sessions"][0]["preview"] == "hello"

    def test_handles_missing_cwd_gracefully(self, claude_mode_on):
        with patch.object(ext_module, "list_all_claude_sessions", return_value=[]):
            with patch.object(ext_module, "get_jupyter_root_dir", return_value=None):
                handler = _make_handler()
                ClaudeSessionsListHandler.get(handler)

        body = _parse_response(handler)
        assert body["current_cwd"] == ""
        assert body["current_sessions_dir"] == ""
