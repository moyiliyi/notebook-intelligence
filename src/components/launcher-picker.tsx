// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React, {
  ChangeEvent,
  KeyboardEvent,
  useEffect,
  useRef,
  useState
} from 'react';
import { IClaudeSessionInfo, NBIAPI } from '../api';

export interface ILauncherPickerProps {
  onSessionSelected: (session: IClaudeSessionInfo) => void;
}

export function LauncherPicker({
  onSessionSelected
}: ILauncherPickerProps): JSX.Element {
  const [sessions, setSessions] = useState<IClaudeSessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('');
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    NBIAPI.listClaudeSessions('all')
      .then(result => {
        setSessions(result.sessions);
        setLoading(false);
      })
      .catch((reason: any) => {
        setError(String(reason?.message ?? reason ?? 'Unknown error'));
        setLoading(false);
      });
  }, []);

  const needle = filter.toLowerCase();
  const filtered = filter
    ? sessions.filter(
        s =>
          s.preview?.toLowerCase().includes(needle) ||
          s.cwd?.toLowerCase().includes(needle)
      )
    : sessions;

  // A held-over index against a refetched session set could silently
  // point at a different session, so reset on any sessions change —
  // not just length, which would miss equal-length-but-different sets.
  useEffect(() => {
    setHighlightedIndex(-1);
  }, [filter, sessions]);

  useEffect(() => {
    if (highlightedIndex < 0 || !listRef.current) {
      return;
    }
    const row = listRef.current.children[highlightedIndex] as
      | HTMLElement
      | undefined;
    row?.scrollIntoView({ block: 'nearest' });
  }, [highlightedIndex]);

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (filtered.length === 0) {
      return;
    }
    // From "no row highlighted" (-1), ArrowDown jumps to the first row
    // and ArrowUp jumps to the last — each direction lands at its
    // nearest end so the user always reaches a valid row in one press.
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightedIndex(i => (i < 0 || i >= filtered.length - 1 ? 0 : i + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightedIndex(i => (i <= 0 ? filtered.length - 1 : i - 1));
    } else if (e.key === 'Enter' && highlightedIndex >= 0) {
      e.preventDefault();
      onSessionSelected(filtered[highlightedIndex]);
    }
  };

  if (loading) {
    return (
      <div className="nbi-claude-code-picker-status">
        Loading sessions&#8230;
      </div>
    );
  }
  if (error) {
    return (
      <div className="nbi-claude-code-picker-status nbi-claude-code-picker-error">
        {error}
      </div>
    );
  }
  const activeRowId =
    highlightedIndex >= 0
      ? `nbi-claude-session-row-${filtered[highlightedIndex].session_id}`
      : undefined;
  return (
    <div className="nbi-claude-code-picker-body" onKeyDown={handleKeyDown}>
      <input
        className="nbi-claude-code-picker-search"
        type="text"
        placeholder="Filter sessions..."
        value={filter}
        onChange={(e: ChangeEvent<HTMLInputElement>) =>
          setFilter(e.target.value)
        }
        autoFocus
        role="combobox"
        aria-expanded={filtered.length > 0}
        aria-controls="nbi-claude-session-listbox"
        aria-activedescendant={activeRowId}
      />
      <div
        className="nbi-claude-code-picker-list"
        id="nbi-claude-session-listbox"
        role="listbox"
        ref={listRef}
      >
        {filtered.length === 0 ? (
          <div className="nbi-claude-code-picker-empty">
            {filter
              ? 'No sessions match your filter.'
              : 'No previous sessions found.'}
          </div>
        ) : (
          filtered.map((session, index) => {
            const isHighlighted = index === highlightedIndex;
            return (
              <div
                key={session.session_id}
                id={`nbi-claude-session-row-${session.session_id}`}
                role="option"
                className={
                  'nbi-claude-code-picker-session' +
                  (isHighlighted ? ' highlighted' : '')
                }
                tabIndex={0}
                aria-selected={isHighlighted}
                onClick={() => onSessionSelected(session)}
                onKeyDown={(e: KeyboardEvent) => {
                  // Activates the row when it's directly Tab-focused;
                  // arrow-key navigation handles activation through the
                  // parent handler instead.
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSessionSelected(session);
                  }
                }}
              >
                <div className="nbi-claude-code-picker-session-top">
                  <span className="nbi-claude-code-picker-session-id">
                    {session.session_id.slice(0, 8)}
                  </span>
                  <span className="nbi-claude-code-picker-time">
                    {session.cwd}
                  </span>
                </div>
                {session.preview && (
                  <div className="nbi-claude-code-picker-msg">
                    {session.preview}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
