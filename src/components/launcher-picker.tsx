// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React, { useState, useEffect, ChangeEvent, KeyboardEvent } from 'react';
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

  useEffect(() => {
    NBIAPI.listAllClaudeSessions()
      .then(result => {
        setSessions(result);
        setLoading(false);
      })
      .catch((reason: any) => {
        setError(String(reason?.message ?? reason ?? 'Unknown error'));
        setLoading(false);
      });
  }, []);

  const filtered = filter
    ? sessions.filter(
        s =>
          s.preview?.toLowerCase().includes(filter.toLowerCase()) ||
          s.cwd?.toLowerCase().includes(filter.toLowerCase())
      )
    : sessions;

  if (loading) {
    return (
      <div className="nflx-claude-code-picker-status">
        Loading sessions&#8230;
      </div>
    );
  }
  if (error) {
    return (
      <div className="nflx-claude-code-picker-status nflx-claude-code-picker-error">
        {error}
      </div>
    );
  }
  return (
    <div className="nflx-claude-code-picker-body">
      <input
        className="nflx-claude-code-picker-search"
        type="text"
        placeholder="Filter sessions..."
        value={filter}
        onChange={(e: ChangeEvent<HTMLInputElement>) =>
          setFilter(e.target.value)
        }
        autoFocus
      />
      <div className="nflx-claude-code-picker-list">
        {filtered.length === 0 ? (
          <div className="nflx-claude-code-picker-empty">
            {filter
              ? 'No sessions match your filter.'
              : 'No previous sessions found.'}
          </div>
        ) : (
          filtered.map(session => (
            <div
              key={session.session_id}
              className="nflx-claude-code-picker-session"
              tabIndex={0}
              onClick={() => onSessionSelected(session)}
              onKeyPress={(e: KeyboardEvent) => {
                if (e.key === 'Enter') {
                  onSessionSelected(session);
                }
              }}
            >
              <div className="nflx-claude-code-picker-session-top">
                <span className="nflx-claude-code-picker-session-id">
                  {session.session_id.slice(0, 8)}
                </span>
                <span className="nflx-claude-code-picker-time">
                  {session.cwd}
                </span>
              </div>
              {session.preview && (
                <div className="nflx-claude-code-picker-msg">
                  {session.preview.length > 80
                    ? session.preview.slice(0, 80) + '…'
                    : session.preview}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
