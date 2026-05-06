import json
import os
from pathlib import Path

import pytest

from notebook_intelligence.claude_sessions import (
    ClaudeSessionInfo,
    encode_cwd,
    get_sessions_dir,
    list_sessions,
    list_all_sessions,
)


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for obj in lines:
            fh.write(json.dumps(obj) + "\n")


def _user_line(session_id: str, text: str) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": text},
        "sessionId": session_id,
    }


def _sidechain_line(session_id: str, content: str = "Warmup") -> dict:
    return {
        "type": "user",
        "isSidechain": True,
        "message": {"role": "user", "content": content},
        "sessionId": session_id,
    }


def _preamble_line(session_id: str, content) -> dict:
    """User-message envelope for synthetic preambles (NBI / Claude Code)."""
    return {
        "type": "user",
        "message": {"role": "user", "content": content},
        "sessionId": session_id,
    }


def _assistant_line(session_id: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": "ok"},
        "sessionId": session_id,
    }


@pytest.fixture
def fake_claude_home(tmp_path):
    """Create an empty ~/.claude stand-in under a tmp_path."""
    home = tmp_path / "claude_home"
    home.mkdir()
    return home


@pytest.fixture
def project_cwd(tmp_path):
    """Create an arbitrary project directory to act as the Jupyter cwd."""
    cwd = tmp_path / "projects" / "my-notebook"
    cwd.mkdir(parents=True)
    return str(cwd)


@pytest.fixture
def sessions_dir(fake_claude_home, project_cwd):
    return get_sessions_dir(project_cwd, claude_home=str(fake_claude_home))


class TestEncodeCwd:
    def test_replaces_path_separators_with_dashes(self):
        assert encode_cwd("/Users/me/proj") == "-Users-me-proj"

    def test_normalizes_trailing_slash(self):
        assert encode_cwd("/Users/me/proj/") == "-Users-me-proj"

    def test_normalizes_parent_segments(self):
        assert encode_cwd("/Users/me/proj/../proj") == "-Users-me-proj"

    def test_resolves_symlinks(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)

        assert encode_cwd(str(link)) == encode_cwd(str(real))


class TestGetSessionsDir:
    def test_composes_claude_projects_path(self, fake_claude_home, project_cwd):
        result = get_sessions_dir(project_cwd, claude_home=str(fake_claude_home))
        assert result == fake_claude_home / "projects" / encode_cwd(project_cwd)


class TestListSessions:
    def test_returns_empty_when_dir_missing(
        self, fake_claude_home, project_cwd
    ):
        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert result == []

    def test_returns_empty_when_dir_has_no_jsonl_files(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "notes.txt").write_text("hi")
        (sessions_dir / "subagents").mkdir()

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert result == []

    def test_lists_sessions_with_metadata(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        session_id = "abc123"
        path = sessions_dir / f"{session_id}.jsonl"
        _write_jsonl(
            path,
            [
                _user_line(session_id, "Help me fix this bug"),
                _assistant_line(session_id),
                _user_line(session_id, "Follow-up question"),
            ],
        )

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))

        assert len(result) == 1
        session = result[0]
        assert isinstance(session, ClaudeSessionInfo)
        assert session.session_id == session_id
        assert session.preview == "Help me fix this bug"
        assert session.path == str(path)

    def test_sorts_sessions_newest_first(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        older_path = sessions_dir / "older.jsonl"
        newer_path = sessions_dir / "newer.jsonl"
        _write_jsonl(older_path, [_user_line("older", "first")])
        _write_jsonl(newer_path, [_user_line("newer", "second")])

        # Force distinct mtimes regardless of filesystem resolution.
        os.utime(older_path, (1_000_000_000, 1_000_000_000))
        os.utime(newer_path, (2_000_000_000, 2_000_000_000))

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))

        assert [s.session_id for s in result] == ["newer", "older"]

    def test_skips_files_without_user_messages(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # A transcript that only contains a file-history-snapshot should be
        # filtered out so the picker doesn't show an empty row.
        snapshot_only = sessions_dir / "snapshot.jsonl"
        _write_jsonl(
            snapshot_only,
            [{"type": "file-history-snapshot", "messageId": "x", "snapshot": {}}],
        )

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert result == []

    def test_ignores_nested_subagent_files(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Subagent transcripts live under a nested subagents/ directory and
        # must not surface as top-level sessions.
        main_path = sessions_dir / "main.jsonl"
        _write_jsonl(main_path, [_user_line("main", "hello")])

        nested = sessions_dir / "main" / "subagents"
        nested.mkdir(parents=True)
        _write_jsonl(
            nested / "agent-xyz.jsonl", [_user_line("sub", "sub prompt")]
        )

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert [s.session_id for s in result] == ["main"]

    def test_skips_top_level_sidechain_files(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Some Claude Agent SDK setups land sidechain "Warmup" probes (the
        # /clear pre-roll) at the top level under short agent-* names.
        # These aren't resumable via `claude --resume`, so they must not show
        # up in the picker.
        _write_jsonl(
            sessions_dir / "real-session.jsonl",
            [_user_line("real-session", "hello")],
        )
        _write_jsonl(
            sessions_dir / "agent-a94b68b.jsonl",
            [_sidechain_line("real-session")],
        )

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert [s.session_id for s in result] == ["real-session"]

    def test_sidechain_filter_skips_corrupt_first_line(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # A malformed first line falls through to the next; if that next line
        # is a sidechain, the file is still filtered.
        sessions_dir.mkdir(parents=True)
        path = sessions_dir / "agent-corrupt.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write("{ broken\n")
            fh.write(json.dumps(_sidechain_line("real-session")) + "\n")

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert result == []

    def test_keeps_files_when_isSidechain_is_false(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Real sessions explicitly mark isSidechain:false; treat them as
        # normal even though the field is present.
        line = {
            "type": "user",
            "isSidechain": False,
            "message": {"role": "user", "content": "hello"},
            "sessionId": "real",
        }
        _write_jsonl(sessions_dir / "real.jsonl", [line])

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert [s.session_id for s in result] == ["real"]

    def test_skips_nbi_context_preamble_when_extracting_preview(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # NBI prepends an "Additional context: ..." user message before the
        # real prompt; the preview should reflect the user's intent, not the
        # boilerplate.
        preamble = _preamble_line(
            "real",
            "Additional context: Current directory open in Jupyter is: "
            "'/tmp/proj' and current file is: 'foo.ipynb'",
        )
        real_prompt = _user_line("real", "Implement fizzbuzz in a new cell")
        _write_jsonl(sessions_dir / "real.jsonl", [preamble, real_prompt])

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert result[0].preview == "Implement fizzbuzz in a new cell"

    def test_skips_preamble_in_structured_content(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Same shape, but the preamble arrives as a list of content blocks.
        preamble = _preamble_line(
            "real",
            [
                {
                    "type": "text",
                    "text": (
                        "Additional context: Current directory open in "
                        "Jupyter is: ''"
                    ),
                }
            ],
        )
        real_prompt = _user_line("real", "Hello world")
        _write_jsonl(sessions_dir / "real.jsonl", [preamble, real_prompt])

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert [s.preview for s in result] == ["Hello world"]

    def test_falls_back_to_no_preview_when_only_preamble(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Pure-preamble file (e.g. session created but no real prompt yet)
        # should be filtered out — no preview to show.
        preamble = _preamble_line(
            "real", "Additional context: Current directory open in Jupyter is: ''"
        )
        _write_jsonl(sessions_dir / "real.jsonl", [preamble])

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert result == []

    def test_skips_claude_code_command_envelopes(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Claude Code itself wraps slash-command artifacts in synthetic user
        # messages: <local-command-caveat>, <command-name>, <local-command-
        # stdout>. None of these are real user prompts.
        envelopes = [
            _preamble_line(
                "real",
                "<local-command-caveat>Caveat: The messages below were "
                "generated by the user while running local commands."
                "</local-command-caveat>",
            ),
            _preamble_line("real", "<command-name>/clear</command-name>"),
            _preamble_line(
                "real", "<local-command-stdout>Bye!</local-command-stdout>"
            ),
        ]
        real_prompt = _user_line("real", "Tell me about pandas")
        _write_jsonl(sessions_dir / "real.jsonl", envelopes + [real_prompt])

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert [s.preview for s in result] == ["Tell me about pandas"]

    def test_tolerates_partial_trailing_line(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Sessions that are still being written can have a half-flushed
        # trailing line; we should keep parsing earlier messages instead of
        # dropping the whole file.
        sessions_dir.mkdir(parents=True)
        path = sessions_dir / "partial.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(_user_line("partial", "first message")) + "\n")
            fh.write('{"type": "user", "message": {"role": "user", "content')

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert result[0].preview == "first message"

    def test_preview_is_truncated(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        long_text = "a" * 500
        _write_jsonl(
            sessions_dir / "long.jsonl",
            [_user_line("long", long_text)],
        )

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert len(result[0].preview) < len(long_text)
        assert result[0].preview.endswith("\u2026")

    def test_preview_collapses_whitespace(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        _write_jsonl(
            sessions_dir / "ws.jsonl",
            [_user_line("ws", "line one\n\n   line two\tthree")],
        )

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert result[0].preview == "line one line two three"

    def test_handles_structured_content_blocks(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        _write_jsonl(
            sessions_dir / "blocks.jsonl",
            [
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "hello"},
                            {"type": "image", "source": {}},
                            {"type": "text", "text": "world"},
                        ],
                    },
                }
            ],
        )

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert result[0].preview == "hello world"

    def test_skips_tool_result_user_envelopes(
        self, sessions_dir, fake_claude_home, project_cwd
    ):
        # Tool results are wrapped in user messages but carry no real
        # prompt text. They should not steal the preview from a real user
        # turn.
        _write_jsonl(
            sessions_dir / "tools.jsonl",
            [
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "abc",
                                "content": "done",
                            }
                        ],
                    },
                },
                _user_line("tools", "actual prompt"),
            ],
        )

        result = list_sessions(project_cwd, claude_home=str(fake_claude_home))
        assert result[0].preview == "actual prompt"


def _history_line(session_id: str, project: str, ts: int, display: str) -> dict:
    return {
        "sessionId": session_id,
        "project": project,
        "timestamp": ts,
        "display": display,
    }


class TestListAllSessions:
    def test_returns_empty_when_no_history(self, fake_claude_home):
        result = list_all_sessions(claude_home=str(fake_claude_home))
        assert result == []

    def test_returns_cwd_sessions_when_history_missing(
        self, fake_claude_home, sessions_dir, project_cwd
    ):
        _write_jsonl(
            sessions_dir / "s1.jsonl", [_user_line("s1", "nbi session")]
        )
        result = list_all_sessions(cwd=project_cwd, claude_home=str(fake_claude_home))
        assert len(result) == 1
        assert result[0].session_id == "s1"
        assert result[0].cwd == project_cwd

    def test_merges_cwd_sessions_not_in_history(
        self, fake_claude_home, sessions_dir, project_cwd
    ):
        # history.jsonl has session "hist-only"
        history_path = fake_claude_home / "history.jsonl"
        hist_jsonl = sessions_dir / "hist-only.jsonl"
        _write_jsonl(hist_jsonl, [_user_line("hist-only", "from history")])
        with history_path.open("w") as fh:
            fh.write(
                json.dumps(
                    _history_line("hist-only", project_cwd, 2_000_000_000_000, "from history")
                )
                + "\n"
            )

        # cwd dir also has "nbi-only" which is not in history.jsonl
        _write_jsonl(
            sessions_dir / "nbi-only.jsonl", [_user_line("nbi-only", "nbi session")]
        )

        result = list_all_sessions(cwd=project_cwd, claude_home=str(fake_claude_home))
        ids = [s.session_id for s in result]
        assert "hist-only" in ids
        assert "nbi-only" in ids

    def test_deduplicates_sessions_in_both_sources(
        self, fake_claude_home, sessions_dir, project_cwd
    ):
        session_id = "shared"
        jsonl_path = sessions_dir / f"{session_id}.jsonl"
        _write_jsonl(jsonl_path, [_user_line(session_id, "shared session")])

        history_path = fake_claude_home / "history.jsonl"
        with history_path.open("w") as fh:
            fh.write(
                json.dumps(
                    _history_line(session_id, project_cwd, 1_000_000_000_000, "shared session")
                )
                + "\n"
            )

        result = list_all_sessions(cwd=project_cwd, claude_home=str(fake_claude_home))
        assert len([s for s in result if s.session_id == session_id]) == 1
