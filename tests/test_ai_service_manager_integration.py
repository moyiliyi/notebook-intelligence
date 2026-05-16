import pytest
from unittest.mock import Mock, patch
from notebook_intelligence.ai_service_manager import AIServiceManager
from notebook_intelligence.rule_manager import RuleManager


# AIServiceManager.__init__ constructs a ClaudeCodeChatParticipant whose own __init__
# reads nbi_config.claude_settings and does `ToolType in settings.get('tools', [])`.
# A bare Mock() returns another Mock from .get(), which isn't iterable — so every
# mock_config in this file sets `claude_settings = {}` to keep that check happy.
class TestAIServiceManagerIntegration:
    def test_init_with_rules_enabled(self):
        """Test AIServiceManager initialization with rules enabled."""
        with patch('notebook_intelligence.ai_service_manager.NBIConfig') as mock_config_class:
            mock_config = Mock()
            mock_config.rules_enabled = True
            mock_config.rules_directory = "/test/rules"
            mock_config.mcp = {"mcpServers": {}, "participants": {}}
            mock_config.user_skills_directory = "/test/user_skills"
            mock_config.project_skills_directory = lambda _root: "/test/project_skills"
            mock_config.claude_settings = {}
            mock_config_class.return_value = mock_config
            
            with patch('notebook_intelligence.ai_service_manager.RuleManager') as mock_rule_manager_class:
                mock_rule_manager = Mock(spec=RuleManager)
                mock_rule_manager_class.return_value = mock_rule_manager
                
                manager = AIServiceManager({"server_root_dir": "/test"})
                
                assert manager._rule_manager is mock_rule_manager
                mock_rule_manager_class.assert_called_once_with("/test/rules")
    
    def test_init_with_rules_disabled(self):
        """Test AIServiceManager initialization with rules disabled."""
        with patch('notebook_intelligence.ai_service_manager.NBIConfig') as mock_config_class:
            mock_config = Mock()
            mock_config.rules_enabled = False
            mock_config.mcp = {"mcpServers": {}, "participants": {}}
            mock_config.user_skills_directory = "/test/user_skills"
            mock_config.project_skills_directory = lambda _root: "/test/project_skills"
            mock_config.claude_settings = {}
            mock_config_class.return_value = mock_config
            
            manager = AIServiceManager({"server_root_dir": "/test"})
            
            assert manager._rule_manager is None
    
    def test_get_rule_manager_when_available(self):
        """Test getting rule manager when it's available."""
        with patch('notebook_intelligence.ai_service_manager.NBIConfig') as mock_config_class:
            mock_config = Mock()
            mock_config.rules_enabled = True
            mock_config.rules_directory = "/test/rules"
            mock_config.mcp = {"mcpServers": {}, "participants": {}}
            mock_config.user_skills_directory = "/test/user_skills"
            mock_config.project_skills_directory = lambda _root: "/test/project_skills"
            mock_config.claude_settings = {}
            mock_config_class.return_value = mock_config
            
            with patch('notebook_intelligence.ai_service_manager.RuleManager') as mock_rule_manager_class:
                mock_rule_manager = Mock(spec=RuleManager)
                mock_rule_manager_class.return_value = mock_rule_manager
                
                manager = AIServiceManager({"server_root_dir": "/test"})
                
                result = manager.get_rule_manager()
                assert result is mock_rule_manager
    
    def test_get_rule_manager_when_not_available(self):
        """Test getting rule manager when it's not available."""
        with patch('notebook_intelligence.ai_service_manager.NBIConfig') as mock_config_class:
            mock_config = Mock()
            mock_config.rules_enabled = False
            mock_config.mcp = {"mcpServers": {}, "participants": {}}
            mock_config.user_skills_directory = "/test/user_skills"
            mock_config.project_skills_directory = lambda _root: "/test/project_skills"
            mock_config.claude_settings = {}
            mock_config_class.return_value = mock_config
            
            manager = AIServiceManager({"server_root_dir": "/test"})
            
            result = manager.get_rule_manager()
            assert result is None
    
    def test_reload_rules_when_available(self):
        """Test reloading rules when rule manager is available."""
        with patch('notebook_intelligence.ai_service_manager.NBIConfig') as mock_config_class:
            mock_config = Mock()
            mock_config.rules_enabled = True
            mock_config.rules_directory = "/test/rules"
            mock_config.mcp = {"mcpServers": {}, "participants": {}}
            mock_config.user_skills_directory = "/test/user_skills"
            mock_config.project_skills_directory = lambda _root: "/test/project_skills"
            mock_config.claude_settings = {}
            mock_config_class.return_value = mock_config
            
            with patch('notebook_intelligence.ai_service_manager.RuleManager') as mock_rule_manager_class:
                mock_rule_manager = Mock(spec=RuleManager)
                mock_rule_manager_class.return_value = mock_rule_manager
                
                manager = AIServiceManager({"server_root_dir": "/test"})
                
                manager.reload_rules()
                
                mock_rule_manager.load_rules.assert_called_once_with(force_reload=True)
    
    def test_reload_rules_when_not_available(self):
        """Test reloading rules when rule manager is not available."""
        with patch('notebook_intelligence.ai_service_manager.NBIConfig') as mock_config_class:
            mock_config = Mock()
            mock_config.rules_enabled = False
            mock_config.mcp = {"mcpServers": {}, "participants": {}}
            mock_config.user_skills_directory = "/test/user_skills"
            mock_config.project_skills_directory = lambda _root: "/test/project_skills"
            mock_config.claude_settings = {}
            mock_config_class.return_value = mock_config

            manager = AIServiceManager({"server_root_dir": "/test"})

            # Should not raise an exception
            manager.reload_rules()

    def test_claude_mode_triggers_model_fetch_when_cache_empty(self):
        """When Claude mode is enabled and the model cache is empty,
        update_models_from_config should fire a background fetch so the
        capabilities response surfaces the list to the settings panel
        (issue #235: the persisted chat_model showed as Default because
        the dropdown had no options to render against).
        """
        with patch('notebook_intelligence.ai_service_manager.NBIConfig') as mock_config_class:
            mock_config = Mock()
            mock_config.rules_enabled = False
            mock_config.mcp = {"mcpServers": {}, "participants": {}}
            mock_config.user_skills_directory = "/test/user_skills"
            mock_config.project_skills_directory = lambda _root: "/test/project_skills"
            mock_config.claude_settings = {
                "enabled": True,
                "chat_model": "claude-sonnet-4-6",
                "api_key": "test-key",
            }
            mock_config.chat_model = {"provider": "none", "model": "none"}
            mock_config.inline_completion_model = {"provider": "none", "model": "none"}
            mock_config.using_github_copilot_service = False
            mock_config_class.return_value = mock_config
            with patch(
                'notebook_intelligence.ai_service_manager.fetch_claude_models'
            ) as mock_fetch, patch(
                'notebook_intelligence.ai_service_manager.get_claude_models',
                return_value=[],
            ):
                manager = AIServiceManager({"server_root_dir": "/test"})
                # __init__ already calls initialize which calls
                # update_models_from_config; the fetch should have been
                # scheduled on a background thread.
                # Poll briefly: the daemon thread starts but the call
                # itself may be deferred a tick.
                import time as _t
                for _ in range(20):
                    if mock_fetch.call_count >= 1:
                        break
                    _t.sleep(0.05)
                assert mock_fetch.call_count >= 1, (
                    "Expected fetch_claude_models to be invoked when cache "
                    "is empty and Claude mode is enabled"
                )
                call_kwargs = mock_fetch.call_args.kwargs
                assert call_kwargs.get("api_key") == "test-key"

    def test_claude_mode_skips_fetch_when_cache_already_populated(self):
        """If the Claude model cache is already populated (e.g. a prior
        startup or a manual refresh), don't re-fetch on every config
        refresh — the existing list is good enough and the round trip
        wastes a request to the Anthropic API.
        """
        with patch('notebook_intelligence.ai_service_manager.NBIConfig') as mock_config_class:
            mock_config = Mock()
            mock_config.rules_enabled = False
            mock_config.mcp = {"mcpServers": {}, "participants": {}}
            mock_config.user_skills_directory = "/test/user_skills"
            mock_config.project_skills_directory = lambda _root: "/test/project_skills"
            mock_config.claude_settings = {
                "enabled": True,
                "chat_model": "claude-sonnet-4-6",
                "api_key": "test-key",
            }
            mock_config.chat_model = {"provider": "none", "model": "none"}
            mock_config.inline_completion_model = {"provider": "none", "model": "none"}
            mock_config.using_github_copilot_service = False
            mock_config_class.return_value = mock_config
            with patch(
                'notebook_intelligence.ai_service_manager.fetch_claude_models'
            ) as mock_fetch, patch(
                'notebook_intelligence.ai_service_manager.get_claude_models',
                return_value=[{"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"}],
            ):
                AIServiceManager({"server_root_dir": "/test"})
                # Cache had entries, so no fetch should have fired.
                assert mock_fetch.call_count == 0

    def test_no_fetch_when_claude_mode_disabled(self):
        """Claude mode disabled = no fetch, regardless of cache state.
        Don't reach out to the Anthropic API for users not using Claude.
        """
        with patch('notebook_intelligence.ai_service_manager.NBIConfig') as mock_config_class:
            mock_config = Mock()
            mock_config.rules_enabled = False
            mock_config.mcp = {"mcpServers": {}, "participants": {}}
            mock_config.user_skills_directory = "/test/user_skills"
            mock_config.project_skills_directory = lambda _root: "/test/project_skills"
            mock_config.claude_settings = {"enabled": False}
            mock_config.chat_model = {"provider": "none", "model": "none"}
            mock_config.inline_completion_model = {"provider": "none", "model": "none"}
            mock_config.using_github_copilot_service = False
            mock_config_class.return_value = mock_config
            with patch(
                'notebook_intelligence.ai_service_manager.fetch_claude_models'
            ) as mock_fetch, patch(
                'notebook_intelligence.ai_service_manager.get_claude_models',
                return_value=[],
            ):
                AIServiceManager({"server_root_dir": "/test"})
                assert mock_fetch.call_count == 0
