# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Tests for the PluginManager and the plugins management policy gate."""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from notebook_intelligence.extension import (
    PluginsBaseHandler,
    PluginsListHandler,
)
from notebook_intelligence._claude_cli import redact_argv_for_log
from notebook_intelligence.plugin_manager import (
    PluginManager,
    is_acceptable_marketplace_source,
    is_github_marketplace_source,
)


@pytest.fixture
def fake_cli(monkeypatch):
    monkeypatch.setattr(
        "notebook_intelligence._claude_cli.resolve_claude_cli_path",
        lambda: "/usr/local/bin/claude",
    )


from tests.conftest import stub_claude_subprocess as _stub_subprocess  # noqa: E402


class TestIsGithubMarketplaceSource:
    @pytest.mark.parametrize(
        "source",
        [
            "github:owner/repo",
            "https://github.com/owner/repo",
            "https://github.com/owner/repo.git",
            "http://github.com/owner/repo",
            "git@github.com:owner/repo.git",
            "owner/repo",
            "owner/repo/",  # trailing slash on shorthand
            "owner/repo.git",  # .git suffix on shorthand
            "https://github.com:443/owner/repo",  # explicit port
            "HTTPS://GitHub.com/owner/repo",  # case variation
            "https://www.github.com/owner/repo",  # www subdomain
            "git://github.com/owner/repo",  # deprecated git protocol
            "ssh://git@github.com/owner/repo",  # ssh protocol
        ],
    )
    def test_recognizes_github(self, source):
        assert is_github_marketplace_source(source) is True

    @pytest.mark.parametrize(
        "source",
        [
            "/abs/path/to/marketplace",
            "./relative/path",
            "~/home/path",
            "https://example.com/marketplace",
            "owner/repo/extra",  # too many slashes — not bare shorthand
            "https://github.org/owner/repo",  # similar but not GitHub
            "https://gitfake.com/owner/repo",
            "",
        ],
    )
    def test_rejects_non_github(self, source):
        assert is_github_marketplace_source(source) is False


class TestIsAcceptableMarketplaceSource:
    @pytest.mark.parametrize(
        "source",
        [
            "https://example.com/manifest",
            "https://github.com/owner/repo",
            "github:owner/repo",
            "ssh://git@github.com/owner/repo",
            "git://github.com/owner/repo",
            "git@github.com:owner/repo",
            "owner/repo",
            "/abs/path/to/marketplace",
            "./relative/path",
            "~/home/path",
        ],
    )
    def test_accepts(self, source):
        assert is_acceptable_marketplace_source(source) is True

    @pytest.mark.parametrize(
        "source",
        [
            "http://internal.attacker/manifest",  # plain http blocked (SSRF)
            "http://169.254.169.254/latest/",  # IMDS-style probe
            "file:///etc/passwd",
            "ftp://example.com/manifest",
            "gopher://example.com",
            "git://example.com/repo",  # non-github git://
            "ssh://git@gitlab.com/owner/repo",  # non-github ssh://
            "",
        ],
    )
    def test_rejects(self, source):
        assert is_acceptable_marketplace_source(source) is False


class TestPluginManagerReads:
    def test_list_plugins_parses_json_array(self, fake_cli, monkeypatch):
        captured: dict = {}
        _stub_subprocess(
            monkeypatch,
            captured=captured,
            stdout=b'[{"name":"a","scope":"user","enabled":true}]',
        )
        manager = PluginManager()
        result = asyncio.run(manager.list_plugins())
        assert result == [{"name": "a", "scope": "user", "enabled": True}]
        assert captured["argv"][1:] == ["plugin", "list", "--json"]

    def test_list_marketplaces_parses_json_array(self, fake_cli, monkeypatch):
        captured: dict = {}
        _stub_subprocess(
            monkeypatch,
            captured=captured,
            stdout=b'[{"name":"acme","source":"github:acme/marketplace"}]',
        )
        manager = PluginManager()
        result = asyncio.run(manager.list_marketplaces())
        assert result == [{"name": "acme", "source": "github:acme/marketplace"}]

    def test_list_marketplaces_enriches_with_manifest_details(
        self, fake_cli, tmp_path, monkeypatch
    ):
        # Pin the enrichment path: when a cached marketplace.json sits
        # alongside the marketplace entry, the response carries
        # description, version, plugin_count, and plugin_names so the
        # frontend can render a rich row without a second HTTP round
        # trip per marketplace.
        plugins_root = tmp_path / "plugins"
        manifest = (
            plugins_root
            / "marketplaces"
            / "acme"
            / ".claude-plugin"
            / "marketplace.json"
        )
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "name": "acme",
                    "description": "Acme team plugins",
                    "version": "1.2.3",
                    "plugins": [
                        {"name": "alpha", "source": "./a"},
                        {"name": "beta", "source": "./b"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(plugins_root))
        _stub_subprocess(
            monkeypatch,
            captured={},
            stdout=b'[{"name":"acme","source":"github:acme/marketplace"}]',
        )

        result = asyncio.run(PluginManager().list_marketplaces())

        assert result == [
            {
                "name": "acme",
                "source": "github:acme/marketplace",
                "description": "Acme team plugins",
                "version": "1.2.3",
                "plugin_count": 2,
                "plugin_names": ["alpha", "beta"],
            }
        ]

    def test_list_marketplaces_reads_metadata_block_as_fallback(
        self, fake_cli, tmp_path, monkeypatch
    ):
        # Claude marketplaces predating the top-level fields keep
        # description/version under "metadata". Honoring both keeps the
        # row rich for older marketplaces the user already installed.
        plugins_root = tmp_path / "plugins"
        manifest = (
            plugins_root
            / "marketplaces"
            / "old"
            / ".claude-plugin"
            / "marketplace.json"
        )
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "name": "old",
                    "metadata": {"description": "Old style", "version": "0.9"},
                    "plugins": [{"name": "only", "source": "./only"}],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(plugins_root))
        _stub_subprocess(
            monkeypatch,
            captured={},
            stdout=b'[{"name":"old","source":"./old"}]',
        )

        result = asyncio.run(PluginManager().list_marketplaces())
        assert result[0]["description"] == "Old style"
        assert result[0]["version"] == "0.9"
        assert result[0]["plugin_count"] == 1
        assert result[0]["plugin_names"] == ["only"]

    def test_list_marketplaces_skips_missing_manifest(
        self, fake_cli, tmp_path, monkeypatch
    ):
        # A marketplace just added but not yet cached, or one whose
        # manifest disappeared, must not break the entire list. The
        # entry comes back without the enrichment fields.
        monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(tmp_path / "noexist"))
        _stub_subprocess(
            monkeypatch,
            captured={},
            stdout=b'[{"name":"acme","source":"./acme"}]',
        )
        result = asyncio.run(PluginManager().list_marketplaces())
        assert result == [{"name": "acme", "source": "./acme"}]

    @pytest.mark.parametrize(
        "cli_field,cli_value,manifest_field,manifest_value",
        [
            ("description", "from cli", "description", "from manifest"),
            ("version", "9.9.9", "version", "1.0.0"),
            ("plugin_count", 42, "plugin_count", 2),
            (
                "plugin_names",
                ["a", "b"],
                "plugin_names",
                ["c", "d", "e"],
            ),
        ],
    )
    def test_list_marketplaces_does_not_override_cli_supplied_fields(
        self,
        fake_cli,
        tmp_path,
        monkeypatch,
        cli_field,
        cli_value,
        manifest_field,
        manifest_value,
    ):
        # If a future Claude release surfaces any of the enrichment
        # fields on the list itself, defer to the CLI value instead of
        # overwriting from the cached manifest. Parametrized across
        # description/version/plugin_count/plugin_names so a regression
        # in any single field's override branch is caught.
        plugins_root = tmp_path / "plugins"
        manifest = (
            plugins_root
            / "marketplaces"
            / "acme"
            / ".claude-plugin"
            / "marketplace.json"
        )
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "description": "from manifest",
                    "version": "1.0.0",
                    "plugins": [
                        {"name": "c", "source": "./c"},
                        {"name": "d", "source": "./d"},
                        {"name": "e", "source": "./e"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(plugins_root))
        cli_entry = {"name": "acme", "source": "./acme", cli_field: cli_value}
        _stub_subprocess(
            monkeypatch,
            captured={},
            stdout=json.dumps([cli_entry]).encode(),
        )
        result = asyncio.run(PluginManager().list_marketplaces())
        assert result[0][cli_field] == cli_value

    def test_list_marketplaces_overrides_empty_cli_string_with_manifest_value(
        self, fake_cli, tmp_path, monkeypatch
    ):
        # An empty-string CLI value must not shadow a useful manifest
        # value. The overlay rule is "prefer CLI when truthy", so
        # description: "" from the CLI falls through to the manifest's
        # description.
        plugins_root = tmp_path / "plugins"
        manifest = (
            plugins_root
            / "marketplaces"
            / "acme"
            / ".claude-plugin"
            / "marketplace.json"
        )
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"description": "from manifest", "plugins": []}),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(plugins_root))
        _stub_subprocess(
            monkeypatch,
            captured={},
            stdout=b'[{"name":"acme","source":"./acme","description":""}]',
        )
        result = asyncio.run(PluginManager().list_marketplaces())
        assert result[0]["description"] == "from manifest"

    def test_list_marketplaces_rejects_oversize_manifest(
        self, fake_cli, tmp_path, monkeypatch
    ):
        # A marketplace.json that exceeds the size cap is treated as
        # missing for enrichment purposes; the entry comes back from
        # the CLI unenriched. Test would otherwise OOM the server on a
        # large or hostile manifest.
        plugins_root = tmp_path / "plugins"
        manifest = (
            plugins_root
            / "marketplaces"
            / "huge"
            / ".claude-plugin"
            / "marketplace.json"
        )
        manifest.parent.mkdir(parents=True)
        # Write 2 MiB of valid-looking JSON so the size check fires
        # rather than the JSON parser.
        manifest.write_text(
            "{" + '"x":"' + "z" * (2 * 1024 * 1024) + '"}',
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(plugins_root))
        _stub_subprocess(
            monkeypatch,
            captured={},
            stdout=b'[{"name":"huge","source":"./huge"}]',
        )
        result = asyncio.run(PluginManager().list_marketplaces())
        assert result == [{"name": "huge", "source": "./huge"}]

    def test_list_marketplaces_skips_unreadable_manifest_dir(
        self, fake_cli, tmp_path, monkeypatch
    ):
        # PermissionError from a stat on the manifest dir must not abort
        # the list endpoint. The entry comes back from the CLI without
        # enrichment fields, mirroring the missing-manifest behavior.
        plugins_root = tmp_path / "plugins"

        from pathlib import Path

        original_stat = Path.stat

        def stat_with_permission_error(self, *args, **kwargs):
            if "huge" in str(self):
                raise PermissionError("simulated")
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", stat_with_permission_error)
        monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(plugins_root))
        _stub_subprocess(
            monkeypatch,
            captured={},
            stdout=b'[{"name":"huge","source":"./huge"}]',
        )
        result = asyncio.run(PluginManager().list_marketplaces())
        assert result == [{"name": "huge", "source": "./huge"}]

    def test_list_marketplace_plugins_reads_cached_manifest(
        self, tmp_path, monkeypatch
    ):
        plugins_root = tmp_path / "plugins"
        manifest = (
            plugins_root
            / "marketplaces"
            / "acme"
            / ".claude-plugin"
            / "marketplace.json"
        )
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "plugins": [
                        {
                            "name": "alpha",
                            "description": "Alpha plugin",
                            "source": "./plugins/alpha",
                        },
                        {"name": "beta", "source": "./plugins/beta"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(plugins_root))

        manager = PluginManager()

        assert asyncio.run(manager.list_marketplace_plugins("acme")) == [
            {
                "name": "alpha",
                "description": "Alpha plugin",
                "source": "./plugins/alpha",
            },
            {"name": "beta", "source": "./plugins/beta"},
        ]

    def test_list_marketplace_plugins_rejects_path_traversal(self):
        manager = PluginManager()

        with pytest.raises(ValueError, match="Invalid marketplace name"):
            asyncio.run(manager.list_marketplace_plugins("..\\evil"))

    def test_list_plugins_handles_installed_object_shape(self, fake_cli, monkeypatch):
        # `claude plugin list --available --json` returns an object — the
        # bare `--json` form returns an array, but tolerate both.
        _stub_subprocess(
            monkeypatch,
            captured={},
            stdout=json.dumps(
                {"installed": [{"name": "a"}], "available": [{"name": "b"}]}
            ).encode(),
        )
        manager = PluginManager()
        result = asyncio.run(manager.list_plugins())
        assert result == [{"name": "a"}]

    def test_list_plugins_empty_output(self, fake_cli, monkeypatch):
        _stub_subprocess(monkeypatch, captured={}, stdout=b"")
        manager = PluginManager()
        assert asyncio.run(manager.list_plugins()) == []

    def test_list_plugins_invalid_json_raises(self, fake_cli, monkeypatch):
        _stub_subprocess(monkeypatch, captured={}, stdout=b"not json")
        manager = PluginManager()
        with pytest.raises(ValueError, match="Could not parse"):
            asyncio.run(manager.list_plugins())

    @pytest.mark.parametrize(
        "wrapper",
        [
            b'{"installed":[{"name":"a"}]}',
            b'{"plugins":[{"name":"a"}]}',
            b'{"items":[{"name":"a"}]}',
        ],
    )
    def test_list_plugins_handles_wrapper_shapes(
        self, fake_cli, monkeypatch, wrapper
    ):
        _stub_subprocess(monkeypatch, captured={}, stdout=wrapper)
        manager = PluginManager()
        assert asyncio.run(manager.list_plugins()) == [{"name": "a"}]

    def test_list_plugins_rejects_generic_data_wrapper(
        self, fake_cli, monkeypatch
    ):
        # `data` is generic enough to mean a metadata envelope rather than
        # a plugin list, so the parser does not walk into it.
        _stub_subprocess(
            monkeypatch, captured={}, stdout=b'{"data":[{"name":"a"}]}'
        )
        manager = PluginManager()
        with pytest.raises(ValueError, match="Unrecognized JSON shape"):
            asyncio.run(manager.list_plugins())

    def test_list_plugins_unknown_shape_raises(self, fake_cli, monkeypatch):
        # Surface CLI version skew explicitly rather than masquerading as
        # "no plugins installed".
        _stub_subprocess(
            monkeypatch, captured={}, stdout=b'{"unknownKey":[{"name":"a"}]}'
        )
        manager = PluginManager()
        with pytest.raises(ValueError, match="Unrecognized JSON shape"):
            asyncio.run(manager.list_plugins())


class TestPluginManagerWrites:
    def test_install_invokes_cli_with_scope(self, fake_cli, monkeypatch):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        manager = PluginManager()
        asyncio.run(manager.install_plugin(plugin="my-plugin", scope="project"))
        assert captured["argv"][1:] == [
            "plugin",
            "install",
            "--scope",
            "project",
            "my-plugin",
        ]

    def test_uninstall_passes_yes_flag_for_non_tty(self, fake_cli, monkeypatch):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        manager = PluginManager()
        asyncio.run(manager.uninstall_plugin(plugin="my-plugin", scope="user"))
        assert captured["argv"][1:] == [
            "plugin",
            "uninstall",
            "--scope",
            "user",
            "-y",
            "my-plugin",
        ]

    @pytest.mark.parametrize("enabled,verb", [(True, "enable"), (False, "disable")])
    def test_set_plugin_enabled_invokes_correct_verb(
        self, fake_cli, monkeypatch, enabled, verb
    ):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        manager = PluginManager()
        asyncio.run(
            manager.set_plugin_enabled(plugin="p", enabled=enabled, scope="user")
        )
        assert captured["argv"][1:] == ["plugin", verb, "--scope", "user", "p"]

    def test_set_plugin_enabled_omits_scope_when_none(
        self, fake_cli, monkeypatch
    ):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        manager = PluginManager()
        asyncio.run(manager.set_plugin_enabled(plugin="p", enabled=True))
        assert captured["argv"][1:] == ["plugin", "enable", "p"]

    def test_add_marketplace_passes_source(self, fake_cli, monkeypatch):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        manager = PluginManager()
        asyncio.run(manager.add_marketplace(source="acme/repo", scope="user"))
        assert captured["argv"][1:] == [
            "plugin",
            "marketplace",
            "add",
            "--scope",
            "user",
            "acme/repo",
        ]

    def test_add_marketplace_blocks_github_when_disabled(
        self, fake_cli, monkeypatch
    ):
        _stub_subprocess(monkeypatch, captured={})
        manager = PluginManager()
        with pytest.raises(PermissionError, match="GitHub"):
            asyncio.run(
                manager.add_marketplace(
                    source="acme/repo", scope="user", allow_github=False
                )
            )

    def test_add_marketplace_injects_github_token_for_github_source(
        self, fake_cli, monkeypatch
    ):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        # Force the token resolver to return a known value (skip env / gh).
        monkeypatch.setattr(
            "notebook_intelligence.plugin_manager.resolve_github_token",
            lambda: "ghp_testtoken",
        )
        manager = PluginManager()
        asyncio.run(
            manager.add_marketplace(source="acme/repo", scope="user")
        )
        # Token flows through env, not argv — kept out of DEBUG logs.
        env = captured["kwargs"]["env"]
        assert env["GITHUB_TOKEN"] == "ghp_testtoken"
        assert env["GH_TOKEN"] == "ghp_testtoken"
        assert "ghp_testtoken" not in " ".join(captured["argv"])

    def test_add_marketplace_skips_token_injection_for_local_source(
        self, fake_cli, monkeypatch
    ):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        monkeypatch.setattr(
            "notebook_intelligence.plugin_manager.resolve_github_token",
            lambda: "ghp_testtoken",
        )
        manager = PluginManager()
        asyncio.run(
            manager.add_marketplace(
                source="/abs/path/marketplace", scope="user"
            )
        )
        # Local path → no env-overrides → subprocess inherits parent env
        # unchanged (None signals "don't override"). The token shouldn't
        # leak into requests for non-GitHub sources.
        assert captured["kwargs"]["env"] is None

    def test_add_marketplace_skips_token_injection_when_unavailable(
        self, fake_cli, monkeypatch
    ):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        monkeypatch.setattr(
            "notebook_intelligence.plugin_manager.resolve_github_token",
            lambda: None,
        )
        # Belt-and-suspenders: scrub real GitHub envs so a stale or
        # accidentally-broken patch can't leak the developer's token into
        # the test process.
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        manager = PluginManager()
        asyncio.run(
            manager.add_marketplace(source="acme/repo", scope="user")
        )
        assert captured["kwargs"]["env"] is None

    def test_add_marketplace_skips_token_for_non_github_https(
        self, fake_cli, monkeypatch
    ):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        monkeypatch.setattr(
            "notebook_intelligence.plugin_manager.resolve_github_token",
            lambda: "ghp_should_not_be_used",
        )
        manager = PluginManager()
        asyncio.run(
            manager.add_marketplace(
                source="https://example.com/manifest", scope="user"
            )
        )
        # Non-GitHub HTTPS source must not receive a github.com PAT.
        assert captured["kwargs"]["env"] is None

    def test_add_marketplace_env_overrides_win_over_inherited(
        self, fake_cli, monkeypatch
    ):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        monkeypatch.setenv("GITHUB_TOKEN", "stale_from_parent_env")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        monkeypatch.setattr(
            "notebook_intelligence.plugin_manager.resolve_github_token",
            lambda: "fresh_resolved",
        )
        manager = PluginManager()
        asyncio.run(
            manager.add_marketplace(source="acme/repo", scope="user")
        )
        env = captured["kwargs"]["env"]
        # Override wins on collision.
        assert env["GITHUB_TOKEN"] == "fresh_resolved"
        # Inherited keys survive the merge.
        assert env["PATH"] == "/usr/bin:/bin"

    def test_add_marketplace_remediation_hint_on_auth_failure(
        self, fake_cli, monkeypatch
    ):
        # CLI fails with a typical git-auth-missing message; we should
        # wrap the error with an actionable hint when the source is
        # GitHub and we had no token to inject.
        async def fake_subprocess(*argv, **kwargs):
            proc = MagicMock()

            async def communicate():
                return (b"", b"fatal: could not read Username for 'https://github.com'")

            proc.communicate = communicate
            proc.returncode = 1
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
        monkeypatch.setattr(
            "notebook_intelligence.plugin_manager.resolve_github_token",
            lambda: None,
        )
        manager = PluginManager()
        with pytest.raises(ValueError, match="GITHUB_TOKEN"):
            asyncio.run(
                manager.add_marketplace(source="acme/repo", scope="user")
            )

    def test_github_gate_independent_of_policy_gate(
        self, fake_cli, monkeypatch
    ):
        """The two gates compose: ``allow_github=False`` rejects a GitHub
        source with ``PermissionError`` regardless of policy state, and a
        non-GitHub source with ``allow_github=False`` still proceeds. The
        policy gate (force-off → 403 in the handler's ``prepare()``)
        sits *above* the manager and is independent — exercised by
        ``test_policy_gate.py``. This test pins the manager-layer
        contract: ``allow_github`` is the only thing that affects the
        manager's permission decision."""
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        manager = PluginManager()

        # GitHub source + allow_github=False → PermissionError, no CLI call.
        captured.clear()
        with pytest.raises(PermissionError):
            asyncio.run(
                manager.add_marketplace(
                    source="acme/repo", scope="user", allow_github=False
                )
            )
        assert captured.get("argv") is None

        # Non-GitHub source + allow_github=False → CLI call proceeds.
        asyncio.run(
            manager.add_marketplace(
                source="https://example.com/manifest",
                scope="user",
                allow_github=False,
            )
        )
        assert captured["argv"][1:5] == [
            "plugin",
            "marketplace",
            "add",
            "--scope",
        ]

    def test_add_marketplace_allows_non_github_when_disabled(
        self, fake_cli, monkeypatch
    ):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        manager = PluginManager()
        asyncio.run(
            manager.add_marketplace(
                source="https://example.com/marketplace",
                scope="user",
                allow_github=False,
            )
        )
        assert "marketplace" in captured["argv"]

    def test_remove_marketplace_invokes_cli(self, fake_cli, monkeypatch):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        manager = PluginManager()
        asyncio.run(manager.remove_marketplace(name="acme"))
        assert captured["argv"][1:] == [
            "plugin",
            "marketplace",
            "remove",
            "acme",
        ]

    def test_update_marketplace_invokes_cli(self, fake_cli, monkeypatch):
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        # No GitHub token available so the env-overrides branch is
        # skipped; argv carries only the literal command.
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setattr(
            "notebook_intelligence.plugin_manager.resolve_github_token",
            lambda: None,
        )
        manager = PluginManager()
        asyncio.run(manager.update_marketplace(name="acme"))
        assert captured["argv"][1:] == [
            "plugin",
            "marketplace",
            "update",
            "acme",
        ]
        # Without a token, run_claude_cli passes env=None so the
        # subprocess inherits the parent environment unchanged.
        assert captured["kwargs"]["env"] is None

    def test_update_marketplace_injects_github_token_when_available(
        self, fake_cli, monkeypatch
    ):
        # If the user has GITHUB_TOKEN set, the update flow injects it
        # the same way add_marketplace does, so refreshing a private GHE
        # marketplace works without process-level env. Token flows via
        # env (not argv) so it doesn't appear in the redacted DEBUG log.
        captured: dict = {}
        _stub_subprocess(monkeypatch, captured=captured)
        monkeypatch.setattr(
            "notebook_intelligence.plugin_manager.resolve_github_token",
            lambda: "ghu_test_token",
        )
        manager = PluginManager()
        asyncio.run(manager.update_marketplace(name="acme"))
        env = captured["kwargs"]["env"]
        assert env is not None
        assert env["GITHUB_TOKEN"] == "ghu_test_token"
        assert env["GH_TOKEN"] == "ghu_test_token"

    def test_update_marketplace_rejects_path_traversal_name(self):
        manager = PluginManager()
        with pytest.raises(ValueError, match="Invalid marketplace name"):
            asyncio.run(manager.update_marketplace(name="..\\evil"))

    def test_cli_failure_raises_with_stderr(self, fake_cli, monkeypatch):
        async def fake_subprocess(*argv, **kwargs):
            proc = MagicMock()

            async def communicate():
                return (b"", b"plugin not found")

            proc.communicate = communicate
            proc.returncode = 1
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
        manager = PluginManager()
        with pytest.raises(ValueError, match="plugin not found"):
            asyncio.run(manager.uninstall_plugin(plugin="x", scope="user"))

    def test_cli_failure_scrubs_injected_token_from_stderr(
        self, fake_cli, monkeypatch
    ):
        # If a downstream tool (git, curl in verbose mode, a misconfigured
        # credential helper) echoes the injected token into stderr, the
        # ValueError surfaced to the browser via `_error()` would otherwise
        # leak the secret. `_claude_cli` must scrub `env_overrides` values
        # before raising.
        secret = "ghp_supersecrettoken1234567890"

        async def fake_subprocess(*argv, **kwargs):
            proc = MagicMock()

            async def communicate():
                return (
                    b"",
                    f"auth failed: tried {secret} but expired".encode(),
                )

            proc.communicate = communicate
            proc.returncode = 1
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
        monkeypatch.setenv("GITHUB_TOKEN", secret)
        manager = PluginManager()
        try:
            asyncio.run(
                manager.add_marketplace(
                    source="https://github.com/owner/repo",
                    scope="user",
                    allow_github=True,
                )
            )
        except ValueError as exc:
            assert secret not in str(exc), "Token leaked in error message"
            assert "<redacted>" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_passes_cwd_to_cli(self, fake_cli, monkeypatch):
        # Project-scope writes must resolve against the user's working
        # directory, not the Jupyter server's cwd. A missing cwd means
        # `--scope project` lands the manifest in the wrong tree.
        captured: dict = {}

        async def fake_subprocess(*argv, **kwargs):
            captured["cwd"] = kwargs.get("cwd")
            proc = MagicMock()

            async def communicate():
                return (b"[]", b"")

            proc.communicate = communicate
            proc.returncode = 0
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
        manager = PluginManager(working_dir="/home/user/work")
        asyncio.run(manager.list_plugins())
        assert captured["cwd"] == "/home/user/work"

    def test_missing_cli_raises_filenotfound(self, monkeypatch):
        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: None,
        )
        manager = PluginManager()
        with pytest.raises(FileNotFoundError):
            asyncio.run(manager.list_plugins())

    @pytest.mark.parametrize(
        "field,value",
        [
            ("plugin", "--evil"),
            ("source", "-x"),
            ("name", "--remove-everything"),
        ],
    )
    def test_leading_dash_rejected(self, fake_cli, monkeypatch, field, value):
        _stub_subprocess(monkeypatch, captured={})
        manager = PluginManager()
        with pytest.raises(ValueError, match="leading '-'"):
            if field == "plugin":
                asyncio.run(manager.install_plugin(plugin=value, scope="user"))
            elif field == "source":
                asyncio.run(manager.add_marketplace(source=value, scope="user"))
            else:
                asyncio.run(manager.remove_marketplace(name=value))


class TestLockSerialization:
    """Two concurrent writes against the (process-shared) lock must not
    interleave at the subprocess layer. Catches a regression where the
    asyncio.Lock gets demoted back to instance-level."""

    def test_concurrent_install_calls_are_serialized(self, fake_cli, monkeypatch):
        events: list[str] = []

        async def fake_subprocess(*argv, **kwargs):
            proc = MagicMock()
            tag = argv[-1]

            async def communicate():
                events.append(f"start:{tag}")
                await asyncio.sleep(0.01)
                events.append(f"end:{tag}")
                return (b"", b"")

            proc.communicate = communicate
            proc.returncode = 0
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

        async def driver():
            m1 = PluginManager()
            m2 = PluginManager()
            await asyncio.gather(
                m1.install_plugin(plugin="A", scope="user"),
                m2.install_plugin(plugin="B", scope="user"),
            )

        asyncio.run(driver())
        # No interleaving: each start is followed by its own end before the
        # next start. We don't assert which won the race, just that they
        # didn't overlap.
        assert len(events) == 4
        assert events[0].startswith("start:")
        assert events[1] == events[0].replace("start:", "end:")
        assert events[2].startswith("start:")
        assert events[3] == events[2].replace("start:", "end:")


class TestRedactArgvForLog:
    def test_redacts_env_and_header_values(self):
        argv = ["claude", "plugin", "install", "-e", "K=v", "-H", "Auth: token"]
        assert redact_argv_for_log(argv) == [
            "claude",
            "plugin",
            "install",
            "-e",
            "<redacted>",
            "-H",
            "<redacted>",
        ]

    @pytest.mark.parametrize(
        "flag",
        [
            "--client-secret",
            "--client-id",
            "--token",
            "--password",
            "--auth",
            "--bearer",
        ],
    )
    def test_redacts_forward_compat_secret_flags(self, flag):
        argv = ["claude", "plugin", "install", flag, "supersecret", "name"]
        assert redact_argv_for_log(argv) == [
            "claude",
            "plugin",
            "install",
            flag,
            "<redacted>",
            "name",
        ]

    def test_passes_through_non_secret_flags(self):
        argv = ["claude", "plugin", "install", "--scope", "user", "name"]
        assert redact_argv_for_log(argv) == argv


# Per-family policy-gate coverage lives in `tests/test_policy_gate.py`,
# parametrized across SkillsBaseHandler / ClaudeMCPBaseHandler /
# PluginsBaseHandler.
