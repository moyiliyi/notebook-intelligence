# Changelog

All notable changes to Notebook Intelligence are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) starting with 4.0.0.

For each release we list user-facing changes grouped as **Added**, **Changed**, **Fixed**, and **Removed**. Commits are squashed into the change that motivated them; the full git log remains the source of truth for low-level history.

<!-- <START NEW CHANGELOG ENTRY> -->

## [4.7.0] — 2026-05-07

### Added

- **Cell output actions** — right-click a cell output (or hover for the toolbar) for **Explain**, **Ask**, and **Troubleshoot** quick actions that open the chat sidebar with the output already attached as context. Outputs forward as structured MIME bundles and include images for vision-capable models, token-bounded so large outputs don't overflow the context window. Per-user toggles in `config.json` (`enable_explain_error`, `enable_output_followup`, `enable_output_toolbar`, default on); admins can lock them via `NBI_EXPLAIN_ERROR_POLICY` / `NBI_OUTPUT_FOLLOWUP_POLICY` / `NBI_OUTPUT_TOOLBAR_POLICY`.
- **Image attachments in chat** — paste or attach images alongside a prompt; the image goes to the model as input when it's vision-capable.
- **Streaming inline-chat responses** — the inline chat popover now streams tokens as they arrive instead of waiting for the full response.
- **Notebook toolbar generation button** — a sparkle icon on the active notebook's toolbar opens a popover that scopes the generation to that notebook.
- **Claude Code launcher tile** — a Claude Code tile in the JupyterLab launcher opens a session picker (resume a transcript or start a new one in the file browser's active subdirectory). Session IDs are copyable from the picker.
- **Repo-level `AGENTS.md`** — when a project root contains `AGENTS.md`, NBI appends it under the system prompt's "Additional Guidelines" alongside the existing ruleset injection.
- **Claude WebSocket heartbeat** — keeps long-running Claude agent requests alive through upstream proxy / load balancer idle timeouts (e.g. JupyterHub's nginx default of 60s) by sending a status heartbeat every 20s while a request is in flight. Fixes Bedrock-style request failures where processing exceeds the proxy idle window.
- **Extended admin policy coverage** — every Settings panel toggle is now lockable via an env var. New boolean policies: `NBI_CLAUDE_MODE_POLICY`, `NBI_CLAUDE_CONTINUE_CONVERSATION_POLICY`, `NBI_CLAUDE_CODE_TOOLS_POLICY`, `NBI_CLAUDE_JUPYTER_UI_TOOLS_POLICY`, `NBI_CLAUDE_SETTING_SOURCE_USER_POLICY`, `NBI_CLAUDE_SETTING_SOURCE_PROJECT_POLICY`, `NBI_STORE_GITHUB_ACCESS_TOKEN_POLICY`. New value-presence locks: `NBI_CHAT_MODEL_PROVIDER`, `NBI_CHAT_MODEL_ID`, `NBI_INLINE_COMPLETION_MODEL_PROVIDER`, `NBI_INLINE_COMPLETION_MODEL_ID`, `NBI_CLAUDE_CHAT_MODEL`, `NBI_CLAUDE_INLINE_COMPLETION_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`. See [README → Admin policies](README.md#admin-policies).
- `/claude-sessions` HTTP route accepts `?scope=cwd` to filter to sessions whose recorded `cwd` matches the lab's working directory.

### Changed

- Claude agent connection now happens in the background so JupyterLab finishes loading without waiting on the SDK handshake.

### Fixed

- Public-API hygiene in `notebook_intelligence.api`: `raise NotImplemented` → `raise NotImplementedError` (the former raised `TypeError` at the call site), `Toolset(tools=[])` and four other shared-default-argument cases corrected, `Signal.disconnect` tolerates double-disconnect with a debug-level log, registrar methods raise a new `RegistrationError` instead of silently logging.
- Claude headers (model + version) are now sent on inline completion calls, matching the chat path.
- OpenAI-compatible provider drops the unsupported `tool` `strict` flag when targeting vLLM (#108).
- Resolve symlinks when locating Claude session transcripts so `~/.claude/projects/` symlinked off another volume keeps working.
- Claude worker thread no longer crashes on cancellation; the chat loop recovers cleanly.
- "Generating..." row no longer reflows the chat sidebar on narrow widths.
- Skills popup in the chat sidebar dismisses on click-outside or when the input is cleared.
- Spurious "Skills reloaded" notification when launching a Claude session. The watcher now keys off a structural signature of bundle dirs + `SKILL.md` mtimes, ignoring sibling writes (`.DS_Store`, `.git/`, log/cache files) to the parent `~/.claude/skills/` directory.
- Traitlets `DeprecationWarning` ("Traits should be given as instances, not types") at startup is silenced for the `disabled_*` config.

### Internal

- CI runs `pytest tests/` and `jlpm test` on every PR. The `[test]` extra was added to `pyproject.toml`. Both build jobs declare `permissions: { contents: read }` so a compromised step can't push.

<!-- <END NEW CHANGELOG ENTRY> -->

## [4.6.0] — 2026-04-29

### Added

- **Claude Skills management panel** — Settings now exposes a **Skills** tab for managing the bundles Claude can invoke (SKILL.md frontmatter, helper files, allowed tools). Skills resolve from `~/.claude/skills/` (user) and `<project>/.claude/skills/` (project) — the same locations the Claude CLI reads. Inline editor, duplicate / rename / delete with undo, and import-from-GitHub via the public tarball API. For organization deployments, NBI can install a curated set from a YAML manifest pointed at by `NBI_SKILLS_MANIFEST` and keep them in sync; managed skills are read-only in the UI. See [`docs/skills.md`](docs/skills.md) for the full reference.
- Restructured documentation: `README.md` rewritten with a TOC and concept glossary, plus new `SECURITY.md`, `PRIVACY.md`, and operator guides under `docs/` (`admin-guide.md`, `rulesets.md`, `skills.md`, `troubleshooting.md`).

### Fixed

- **Windows Claude mode reliability** — Claude agent thread now uses the Proactor event loop on Windows, fixing subprocess spawn failures and intermittent "Claude agent not connected" races at startup. The Claude SDK retry path also reconnects when the worker thread has died instead of waiting out the full response timeout.
- Anthropic credentials are normalized (whitespace + scheme handling) before being passed to the SDK.
- Skill imports from GitHub reject tarball entries with absolute paths or `../` traversal — a malicious or buggy bundle can no longer write outside its install directory.
- `_send_claude_agent_request` guarded against the disconnect race that left chat handlers waiting on a closed queue.
- WebSocket message handlers are disconnected when the originating request finishes; previously they accumulated for the lifetime of the WebSocket.
- `configChanged` handlers are disconnected when components unmount, fixing a slow leak when the chat sidebar was opened and closed repeatedly.
- Claude session picker list scrolls correctly when the transcript count exceeds the visible area.

<!-- This entry was filled in retroactively after the 4.6.0 tag shipped. -->

## [4.5.0] — 2026-04-09

### Added

- Chat feedback mechanism for AI responses, configurable via the `enable_chat_feedback` traitlet, with a `telemetry` event hook.
- Attach files as context in chat.
- `Shift+Enter` inserts a newline in the chat input.
- Disable LLM providers via the `disabled_providers` traitlet, with optional per-pod re-enable via `NBI_ENABLED_PROVIDERS`.

### Changed

- Inline completion for the OpenAI-compatible provider now uses the Chat Completions API.

### Fixed

- OpenAI-compatible provider now correctly handles `tool` and `tool_choice` parameters.
- File-attach popover styling.
- Newlines in user input are preserved.

## [4.4.0] — 2026-03-13

### Added

- Configurable Claude Code CLI path via the `NBI_CLAUDE_CLI_PATH` environment variable.

### Changed

- Subprocess invocations no longer use `shell=True`.

## [4.3.2] — 2026-03-13

### Fixed

- Refresh-models button in Claude settings; model list pulled from the Anthropic SDK.

## [4.3.1] — 2026-01-12

### Fixed

- Inline-chat autocomplete popover position.

## [4.3.0] — 2026-01-11

### Added

- Auto-complete debounce delay configuration.
- Additional inline-completion options in Claude mode.
- Conversation continuation in Claude mode.

### Changed

- Settings dialog hides Claude-specific options when Claude mode is off.
- NBI sidebar moved to the left side of the JupyterLab UI.

### Fixed

- Auto-complete tab-state handling.

## [4.2.1] — 2026-01-06

### Changed

- Project rebrand from "JUI" to "NBI" (`@notebook-intelligence/notebook-intelligence`).

## [4.2.0] — 2026-01-06

### Changed

- Notebook tool calls (e.g., cell execution) now require explicit user approval instead of being auto-allowed.

### Fixed

- Improved error handling and message-handler disconnect.
- Claude settings font color and UI state when toggling Claude mode.

## [4.1.2] — 2026-01-05

### Fixed

- Lock-handling in long-running Claude sessions.

## [4.1.1] — 2026-01-04

### Fixed

- Claude mode reliability (multiple cleanup commits).

## [4.1.0] — 2026-01-03

### Added

- Plan mode for Claude.
- Custom message for the Bash tool.

### Changed

- Claude session timeout raised to 30 minutes.
- Improved AskUserQuestion styling.

### Fixed

- Current-directory context and chat-history handling.

## [4.0.0] — 2026-01-01

### Added

- **Claude mode** — first-class integration with [Claude Code](https://code.claude.com/), including:
  - Claude Code-backed Agent Chat UI, inline chat, and auto-complete.
  - Claude Code tools, skills, MCP servers, and custom commands available inside JupyterLab.
  - Claude session resume from `~/.claude/projects/`.
- Honor `c.ServerApp.base_url` for all extension routes.

### Changed

- Settings UI restructured around Claude vs default mode.
- WebSocket connection reliability improvements.

[unreleased]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.7.0...HEAD
[4.7.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.6.0...v4.7.0
[4.6.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.5.0...v4.6.0
[4.5.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.4.0...v4.5.0
[4.4.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.3.2...v4.4.0
[4.3.2]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.3.1...v4.3.2
[4.3.1]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.3.0...v4.3.1
[4.3.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.2.1...v4.3.0
[4.2.1]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.2.0...v4.2.1
[4.2.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.1.2...v4.2.0
[4.1.2]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.1.1...v4.1.2
[4.1.1]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.1.0...v4.1.1
[4.1.0]: https://github.com/notebook-intelligence/notebook-intelligence/compare/v4.0.0...v4.1.0
[4.0.0]: https://github.com/notebook-intelligence/notebook-intelligence/releases/tag/v4.0.0

## Versioning policy

- **Major (X.0.0)** — backward-incompatible changes to traitlets, environment variables, REST routes, or on-disk file formats. Major releases are accompanied by a migration note in this file.
- **Minor (4.Y.0)** — new features and traitlets. Existing configuration continues to work.
- **Patch (4.5.Z)** — bug fixes only.

Deprecations land in a minor release with a warning at startup, and are removed no earlier than the next major release.
