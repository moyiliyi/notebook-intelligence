"""Regression tests for the api.py hygiene fixes.

Pins the four behavioral contracts that the hygiene PR changes:
- Abstract methods raise ``NotImplementedError`` (not the singleton
  ``NotImplemented``, which would itself raise ``TypeError``).
- ``Toolset(tools=[...])`` doesn't share its tool list across instances.
- ``Signal.disconnect`` tolerates removing a listener that wasn't
  connected.
- ``RegistrationError`` is exported and is the documented contract for
  registrar collisions (see ``ai_service_manager.register_*``).
"""

import pytest

from notebook_intelligence.api import (
    Host,
    MCPServer,
    RegistrationError,
    Signal,
    Toolset,
)


class TestAbstractMethodsRaiseNotImplementedError:
    """Pre-fix bare ``raise NotImplemented`` would itself raise
    ``TypeError: exceptions must derive from BaseException``. Verify the
    abstract methods now raise the expected exception type.
    """

    def test_host_chat_model_raises(self):
        with pytest.raises(NotImplementedError):
            Host().chat_model

    def test_host_inline_completion_model_raises(self):
        with pytest.raises(NotImplementedError):
            Host().inline_completion_model

    def test_host_get_mcp_server_raises(self):
        # Was ``return NotImplemented``; callers' ``if mcp_server is not
        # None`` checks would silently treat the sentinel as a real
        # server object.
        with pytest.raises(NotImplementedError):
            Host().get_mcp_server("any")

    def test_mcpserver_get_tools_raises(self):
        with pytest.raises(NotImplementedError):
            MCPServer().get_tools()


class TestToolsetMutableDefault:
    def test_two_toolsets_have_independent_tool_lists(self):
        a = Toolset("a", "a", "a", provider=None)
        b = Toolset("b", "b", "b", provider=None)
        assert a.tools is not b.tools

    def test_explicit_tools_arg_is_copied_not_aliased(self):
        shared_seed = []
        a = Toolset("a", "a", "a", provider=None, tools=shared_seed)
        a.tools.append("x")
        # ``Toolset`` should defensively copy so callers' lists aren't
        # mutated and Toolsets stay independent.
        assert shared_seed == []


class TestSignalDisconnectIsTolerant:
    def test_disconnect_unknown_listener_is_noop(self):
        s = Signal()

        def listener():
            pass

        # Was ``list.remove`` raising ``ValueError`` — now silent.
        s.disconnect(listener)

    def test_double_disconnect_is_noop(self):
        s = Signal()

        def listener():
            pass

        s.connect(listener)
        s.disconnect(listener)
        s.disconnect(listener)  # second one used to crash


class TestRegistrationErrorIsExported:
    def test_registration_error_is_exception_subclass(self):
        assert issubclass(RegistrationError, Exception)
