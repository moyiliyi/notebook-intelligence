// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import { NBIConfig } from '../../src/api';

describe('NBIConfig.additionalSkippedWorkspaceDirectories', () => {
  it('defaults to [] when capabilities are absent', () => {
    const config = new NBIConfig();
    expect(config.additionalSkippedWorkspaceDirectories).toEqual([]);
  });

  it('returns the capability array verbatim', () => {
    const config = new NBIConfig();
    config.capabilities = {
      additional_skipped_workspace_directories: ['build', 'dist']
    };
    expect(config.additionalSkippedWorkspaceDirectories).toEqual([
      'build',
      'dist'
    ]);
  });

  it('falls back to [] when the capability is not an array', () => {
    // Defensive: a malformed backend payload (string, null, number) must
    // not crash the @-mention picker — the spread into the Set in
    // chat-sidebar.tsx assumes an iterable array.
    for (const value of ['build,dist', null, 42, {}]) {
      const config = new NBIConfig();
      config.capabilities = {
        additional_skipped_workspace_directories: value
      };
      expect(config.additionalSkippedWorkspaceDirectories).toEqual([]);
    }
  });
});
