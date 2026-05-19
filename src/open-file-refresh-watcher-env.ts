// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

// Live binding for the open-file refresh watcher. Lives in its own
// file so unit tests can exercise the pure logic in
// `open-file-refresh-watcher.ts` without transitively importing
// `@jupyterlab/docregistry`, which ships ESM that ts-jest's default
// transform can't parse.

import { JupyterFrontEnd } from '@jupyterlab/application';
import { DocumentWidget } from '@jupyterlab/docregistry';
import { Contents } from '@jupyterlab/services';

import { IRefreshWatcherEnv } from './open-file-refresh-watcher';

// JL4 added the 'down' split area; a notebook the user dragged below
// the main editor lives there, not in 'main'. Walk both so the watcher
// covers split-down editors. Sidebars ('left'/'right') intentionally
// excluded — almost nothing editable lives there, and including them
// would polling-stat sidebar widgets we'd never revert.
const WATCHED_SHELL_AREAS = ['main', 'down'] as const;

export function buildRefreshWatcherEnv(
  app: JupyterFrontEnd,
  contents: Contents.IManager
): IRefreshWatcherEnv {
  return {
    iterDocumentWidgets: function* () {
      for (const area of WATCHED_SHELL_AREAS) {
        for (const widget of app.shell.widgets(area)) {
          if (widget instanceof DocumentWidget) {
            yield widget;
          }
        }
      }
    },
    fetchDiskModel: path => contents.get(path, { content: false }),
    setInterval: (handler, ms) => window.setInterval(handler, ms),
    clearInterval: handle => window.clearInterval(handle as number)
  };
}
