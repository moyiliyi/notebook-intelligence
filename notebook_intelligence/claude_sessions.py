# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Discovery of Claude Code session transcripts.

Claude Code persists each conversation as a line-delimited JSON file at::

    ~/.claude/projects/<cwd-encoded>/<session-id>.jsonl

where ``<cwd-encoded>`` is the session cwd with path separators replaced by
dashes (e.g. ``/Users/me/proj`` -> ``-Users-me-proj``).

This module reads those files for the current Jupyter working directory and
returns lightweight metadata (id, timestamps, first user message preview) so
the UI can offer a "resume previous session" picker.

Each line in a transcript is a JSON object. User messages look like::

    {"type": "user", "message": {"role": "user", "content": "..."}, ...}

``content`` can be a string (the common case) or a list of content blocks in
the Anthropic format. Other line types (assistant replies, tool events,
snapshots) are ignored for preview purposes.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_PREVIEW_MAX_CHARS = 160

# Hard cap on lines scanned per file while looking for the first user
# message. Transcripts can grow very large, and in practice the first user
# prompt is on the first few lines.
_MAX_LINES_SCANNED = 200

# Skip filter shared by the chat-sidebar picker and the launcher tile so
# they can't disagree on what to show for the same session id.
NBI_CONTEXT_PREFIX = "Additional context: Current directory open in Jupyter is:"
# A user prompt that genuinely starts with one of these prefixes (e.g.
# "what does <command-name> do?") would be skipped in favor of the next
# message — acceptable trade-off.
_SKIPPABLE_PREFIXES = (
    NBI_CONTEXT_PREFIX,
    "<local-command-",
    "<command-",
    "[Request interrupted by user",
    "Unknown slash command:",
    "Unknown skill:",
)
# Control-only slash commands the user typed to manage the session itself
# rather than ask Claude something. A regex like ^/[A-Za-z]+$ would also
# match "/tmp" or "/etc" — common file paths someone might paste — so we
# enumerate the known set instead.
_CONTROL_SLASH_COMMANDS = frozenset({
    "/clear",
    "/compact",
    "/cost",
    "/exit",
    "/help",
    "/init",
    "/login",
    "/logout",
    "/quit",
    "/release-notes",
    "/reset",
    "/status",
})


@dataclass
class ClaudeSessionInfo:
    """Lightweight metadata for a Claude Code session transcript."""

    session_id: str
    path: str
    modified_at: float
    created_at: float
    preview: str
    cwd: str = ""


def encode_cwd(cwd: str) -> str:
    """Encode a filesystem path the way Claude Code names its project dirs.

    Claude Code replaces every path separator with a dash, so
    ``/Users/me/proj`` becomes ``-Users-me-proj``. We resolve symlinks
    first to match Claude Code's own behavior — without this, macOS's
    ``/tmp`` (a symlink to ``/private/tmp``) would map to ``-tmp`` here
    while Claude Code stores transcripts under ``-private-tmp``, so the
    picker would silently find no sessions.
    """
    normalized = os.path.realpath(cwd)
    return normalized.replace(os.sep, "-")


def get_sessions_dir(cwd: str, claude_home: Optional[str] = None) -> Path:
    """Return the directory containing session transcripts for ``cwd``.

    ``claude_home`` defaults to ``~/.claude`` but can be overridden (useful
    for tests and for the ``CLAUDE_CONFIG_DIR`` convention).
    """
    home = Path(claude_home) if claude_home else Path.home() / ".claude"
    return home / "projects" / encode_cwd(cwd)


def _list_sessions_in_dir(
    cwd: str,
    claude_home: Optional[str] = None,
) -> list[ClaudeSessionInfo]:
    """List Claude sessions for ``cwd``, newest first.

    Returns an empty list if the project directory doesn't exist or contains
    no transcripts. Corrupt or unreadable files are skipped with a log
    warning rather than raising.
    """
    sessions_dir = get_sessions_dir(cwd, claude_home=claude_home)
    if not sessions_dir.is_dir():
        return []

    sessions: list[ClaudeSessionInfo] = []
    for entry in sessions_dir.iterdir():
        # Only consider top-level .jsonl files; skip nested subagent dirs.
        if not entry.is_file() or entry.suffix != ".jsonl":
            continue
        info = _read_session_info(entry)
        if info is not None:
            sessions.append(info)

    sessions.sort(key=lambda s: s.modified_at, reverse=True)
    return sessions


def _read_session_info(path: Path) -> Optional[ClaudeSessionInfo]:
    """Read metadata from a single transcript file.

    Returns a ``ClaudeSessionInfo`` whenever the file contains at least
    one user message, even if every message is skippable — in that case
    ``preview`` is empty and the picker UI relies on the session id +
    timestamp meta row instead of rendering a literal "/exit"-style line
    (issue #187).

    Returns ``None`` for transcripts that aren't useful to resume: the
    file is unreadable, starts with a sidechain record (subagent probe),
    or contains no user messages at all (snapshot-only).
    """
    try:
        stat = path.stat()
    except OSError as exc:
        log.warning("Could not stat Claude session file %s: %s", path, exc)
        return None

    preview = ""
    saw_user_message = False
    first_parsed_obj = True

    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in itertools.islice(fh, _MAX_LINES_SCANNED):
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    # Tolerate the occasional partial write at the tail
                    # of an in-progress session.
                    continue
                # Sidechain transcripts (subagent probes) aren't resumable
                # via `claude --resume`; skip files whose first record is a
                # sidechain.
                if first_parsed_obj:
                    first_parsed_obj = False
                    if obj.get("isSidechain") is True:
                        return None
                if not _is_user_message(obj):
                    continue
                saw_user_message = True
                if _is_skippable_user_message(obj):
                    continue
                preview = _extract_preview(obj)
                break
    except OSError as exc:
        log.warning("Could not read Claude session file %s: %s", path, exc)
        return None

    if not saw_user_message:
        # Pure snapshot / non-conversation file — drop, nothing to resume.
        return None

    return ClaudeSessionInfo(
        session_id=path.stem,
        path=str(path),
        modified_at=stat.st_mtime,
        created_at=stat.st_ctime,
        preview=preview,
    )


def _is_user_message(obj: dict) -> bool:
    if obj.get("type") != "user":
        return False
    message = obj.get("message")
    if not isinstance(message, dict):
        return False
    # Guard against tool-result "user" envelopes; we only want real prompts.
    content = message.get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(
            isinstance(block, dict) and block.get("type") == "text"
            for block in content
        )
    return False


def _is_skippable_user_message(obj: dict) -> bool:
    content = obj.get("message", {}).get("content")
    if isinstance(content, str):
        return _is_skippable_text(content)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                return isinstance(text, str) and _is_skippable_text(text)
    return False


def _is_skippable_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith(_SKIPPABLE_PREFIXES):
        return True
    return stripped in _CONTROL_SLASH_COMMANDS


def _extract_preview(obj: dict) -> str:
    """Extract a short preview string from a user message line."""
    content = obj.get("message", {}).get("content")
    text = ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        text = "\n".join(parts)

    # Collapse whitespace so multi-line prompts render as a single row.
    text = " ".join(text.split())
    return _truncate_preview(text)


def _truncate_preview(text: str) -> str:
    if len(text) > _PREVIEW_MAX_CHARS:
        return text[: _PREVIEW_MAX_CHARS - 1].rstrip() + "\u2026"
    return text


def list_all_sessions(
    cwd: Optional[str] = None,
    claude_home: Optional[str] = None,
) -> list[ClaudeSessionInfo]:
    """List all resumable Claude sessions across all projects, newest first.

    Reads ``~/.claude/history.jsonl`` \u2014 Claude Code writes one entry per
    prompt, so every session that appears there can actually be resumed.
    Each session is enriched with its ``cwd`` (project path) so callers
    can run ``claude --resume <id>`` from the correct directory.

    If ``cwd`` is provided, sessions from that project directory are also
    included (e.g. NBI Claude Mode sessions that may not appear in
    ``history.jsonl``). Results are de-duplicated by session ID.

    Sessions are de-duplicated by session ID and sorted by most recent
    activity. Only sessions whose ``.jsonl`` transcript file still exists
    in ``~/.claude/projects/`` are returned.
    """
    home = Path(claude_home) if claude_home else Path.home() / ".claude"
    history_path = home / "history.jsonl"

    if not history_path.exists():
        if cwd:
            sessions = _list_sessions_in_dir(cwd, claude_home=claude_home)
            for s in sessions:
                s.cwd = cwd
            return sessions
        return []

    # Build index: session_id -> .jsonl path for existence check.
    projects_dir = home / "projects"
    session_to_jsonl: dict[str, Path] = {}
    if projects_dir.is_dir():
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                session_to_jsonl[jsonl_file.stem] = jsonl_file

    # Read history.jsonl: group entries by session_id, track first/last timestamps.
    # Structure: {session_id: {"project": str, "first_ts": int, "last_ts": int, "preview": str}}
    seen: dict[str, dict] = {}
    try:
        with history_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = obj.get("sessionId")
                if not session_id:
                    continue
                project = obj.get("project", "")
                ts = int(obj.get("timestamp", 0))
                display = obj.get("display", "")
                if session_id not in seen:
                    seen[session_id] = {
                        "project": project,
                        "first_ts": ts,
                        "last_ts": ts,
                        "preview": display,
                    }
                else:
                    if ts < seen[session_id]["first_ts"]:
                        seen[session_id]["first_ts"] = ts
                        seen[session_id]["preview"] = display
                    if ts > seen[session_id]["last_ts"]:
                        seen[session_id]["last_ts"] = ts
    except OSError as exc:
        log.warning("Could not read Claude history file %s: %s", history_path, exc)
        if cwd:
            sessions = _list_sessions_in_dir(cwd, claude_home=claude_home)
            for s in sessions:
                s.cwd = cwd
            return sessions
        return []

    sessions: list[ClaudeSessionInfo] = []
    for session_id, data in seen.items():
        # Only include sessions whose transcript file still exists.
        if session_id not in session_to_jsonl:
            continue
        jsonl_path = session_to_jsonl[session_id]
        try:
            stat = jsonl_path.stat()
        except OSError:
            continue
        preview = data["preview"]
        # When display is skippable, prefer a transcript-derived preview;
        # if neither yields anything meaningful, leave preview empty so
        # the picker UI can show only the session id + timestamp instead
        # of a literal "/exit"-style row (issues #181, #187).
        if _is_skippable_text(preview):
            transcript_info = _read_session_info(jsonl_path)
            preview = transcript_info.preview if transcript_info else ""
        preview = _truncate_preview(preview)
        sessions.append(ClaudeSessionInfo(
            session_id=session_id,
            path=str(jsonl_path),
            modified_at=data["last_ts"] / 1000.0,
            created_at=stat.st_ctime,
            preview=preview,
            cwd=data["project"],
        ))

    # Merge in cwd-scoped sessions (e.g. NBI Claude Mode sessions that may
    # not appear in history.jsonl), deduplicating by session_id.
    if cwd:
        existing_ids = {s.session_id for s in sessions}
        for s in _list_sessions_in_dir(cwd, claude_home=claude_home):
            if s.session_id not in existing_ids:
                s.cwd = cwd
                sessions.append(s)
                existing_ids.add(s.session_id)

    sessions.sort(key=lambda s: s.modified_at, reverse=True)
    return sessions
