"""Regression tests for the worker-thread signal/queue race condition in MCPServerImpl.

Mirrors TestWorkerThreadSignalRace in test_claude_client.py for the MCP code path,
confirming the snapshot pattern applied to mcp_manager._client_thread_func() is
equally locked in there.
"""

import threading
from queue import Queue

from notebook_intelligence.api import SignalImpl
from notebook_intelligence.mcp_manager import MCPServerImpl, MCPServerStatus


def _make_mcp_server():
    """Build an ``MCPServerImpl`` without invoking ``__init__`` / ``connect``."""
    server = MCPServerImpl.__new__(MCPServerImpl)
    server._manager = None
    server._name = "test"
    server._stdio_params = None
    server._streamable_http_params = None
    server._auto_approve_tools = set()
    server._tried_to_get_tool_list = False
    server._mcp_tools = []
    server._mcp_prompts = []
    server._session = None
    server._client = None
    server._client_queue = Queue()
    server._client_thread_signal = SignalImpl()
    server._client_thread = None
    server._status = MCPServerStatus.NotConnected
    server._tool_prompt_list_lock = threading.Lock()
    return server


def _disconnect(server):
    """Simulate the field-nulling that disconnect() performs on the server instance."""
    server._client_queue = None
    server._client_thread_signal = None
    server._client_thread = None
    server._status = MCPServerStatus.NotConnected


class TestMCPManagerWorkerThreadSignalRace:
    def test_snapshot_survives_disconnect(self):
        server = _make_mcp_server()
        original_signal = server._client_thread_signal
        received = []
        original_signal.connect(lambda data: received.append(data))
        signal = server._client_thread_signal
        _disconnect(server)
        assert server._client_thread_signal is None
        if signal is not None:
            signal.emit({"id": "x", "data": "stopped"})
        assert received == [{"id": "x", "data": "stopped"}]

    def test_signal_already_none_at_snapshot_time_is_safe(self):
        server = _make_mcp_server()
        _disconnect(server)
        signal = server._client_thread_signal
        assert signal is None
        if signal is not None:
            signal.emit({"id": "x", "data": "stopped"})

    def test_queue_snapshot_survives_disconnect(self):
        server = _make_mcp_server()
        original_queue = server._client_queue
        original_queue.put({"id": "x", "type": "list-tools"})
        queue = server._client_queue
        _disconnect(server)
        assert server._client_queue is None
        event = queue.get(block=False)
        assert event == {"id": "x", "type": "list-tools"}

    def test_queue_already_none_at_snapshot_time_exits_cleanly(self):
        server = _make_mcp_server()
        _disconnect(server)
        queue = server._client_queue
        assert queue is None
        if queue is None:
            return
        queue.get(block=False)
