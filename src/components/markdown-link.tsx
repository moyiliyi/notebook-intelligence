// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React from 'react';
import { JupyterFrontEnd } from '@jupyterlab/application';
import { PathExt } from '@jupyterlab/coreutils';
import { SafeAnchor } from './safe-anchor';
import { hasDangerousTextCodepoints } from '../utils';

// Match an absolute URI by its scheme prefix so a workspace-relative path
// (`README.md`) is distinguished from a protocol-rooted URL (`http://...`).
// Mirrors the SCHEME_RE in utils.ts; kept local because this discriminant
// answers a different question (presence vs. allowlist).
const SCHEME_PREFIX_RE = /^[A-Za-z][A-Za-z0-9+.-]*:/;

/**
 * True when a freshly-joined workspace path is *not* safe to hand to
 * `docmanager:open` or expose on a rendered anchor. Rejects:
 *
 * - leading `..` segments or absolute paths: the join didn't anchor and
 *   the path escapes the Jupyter root (ContentsManager rejects too, but
 *   we want to fail closed visually as well so the status bar/title
 *   never previews a traversal target),
 * - any embedded scheme: `PathExt.join('', 'java\tscript:alert(1)')`
 *   returns the input verbatim, so a path that looks workspace-relative
 *   pre-join can unmask into a `javascript:` href when `baseDir` is
 *   empty (any active doc at server root),
 * - dangerous codepoints (bidi-override, zero-width, C0/C1/DEL, etc.):
 *   the WHATWG URL parser strips these from the scheme during
 *   recognition, and they also visually impersonate the link target on
 *   hover / in dev-tools logs.
 */
function isUnsafeWorkspacePath(path: string): boolean {
  // Empty / cwd-only paths reach here when react-markdown's built-in
  // `urlTransform` strips an unsafe scheme (`javascript:`, `data:`, ...)
  // to an empty string before our override runs: the result joins to
  // either `""` or `"."`, both of which would render as a dead
  // `<a href="#">` that 404s on click. Surface them as blocked-link
  // spans so the user sees why nothing happened.
  if (path === '' || path === '.' || path === './') {
    return true;
  }
  if (path.startsWith('/') || path === '..' || path.startsWith('../')) {
    return true;
  }
  if (SCHEME_PREFIX_RE.test(path)) {
    return true;
  }
  if (hasDangerousTextCodepoints(path)) {
    return true;
  }
  return false;
}

type MarkdownLinkProps = {
  app: JupyterFrontEnd;
  // Directory the LLM-emitted relative link should resolve against. The
  // active document's directory matches the user's mental model: a
  // workspace-relative link like `[file](README.md)` in a chat scoped to
  // `notebooks/proj/work.ipynb` lands at `notebooks/proj/README.md`, not
  // at the server-root README. Empty string is treated as "server root".
  baseDir: string;
  href: unknown;
  title?: unknown;
  children?: React.ReactNode;
};

/**
 * Render an anchor node coming out of `react-markdown` so chat-sidebar
 * links can never replace the JupyterLab shell or pivot through the
 * lab origin.
 *
 * Three branches:
 *   - Fragment-only (`#section`): inert plain text. A new-tab open would
 *     navigate to `about:blank#section`, and a same-tab open would scroll
 *     the wrong document; neither matches what the LLM meant.
 *   - Workspace-relative (no scheme, no leading `/`, no `//` prefix):
 *     resolved against the active document's directory, re-validated,
 *     and routed through JupyterLab's `docmanager:open` command so a
 *     `.ipynb` opens with the notebook factory and a `.md` opens in the
 *     editor. The anchor's `href` stays `"#"` because a populated `href`
 *     bypasses React's onClick on middle/Cmd-click, letting the browser
 *     navigate `/lab/<path>` with session cookies attached; the hover
 *     preview moves to `title` so the user still sees the intended
 *     target.
 *   - Everything else: handed to `SafeAnchor`, which enforces the
 *     `safeAnchorUri` scheme allowlist and emits a `_blank` anchor with
 *     `rel="noopener noreferrer"`.
 */
export function MarkdownLink({
  app,
  baseDir,
  href,
  title,
  children
}: MarkdownLinkProps): React.ReactElement {
  if (typeof href === 'string') {
    if (href.startsWith('#')) {
      return <span>{children}</span>;
    }
    if (
      !SCHEME_PREFIX_RE.test(href) &&
      !href.startsWith('/') &&
      !href.startsWith('//')
    ) {
      // PathExt.join: plain concatenation + normalization. Resolve()
      // would fall back to the browser process cwd when `baseDir` is
      // relative, which gives nonsense like `/Users/.../notebooks/...`.
      const resolvedPath = PathExt.join(baseDir, href);
      // Re-validate post-join. Two attack/confusion shapes the pre-check
      // alone misses: `[x](java\tscript:alert(1))` survives the scheme
      // sniff because `\t` isn't a scheme char, then unmasks once the
      // WHATWG parser sees the joined href; `[x](../../../etc/passwd)`
      // looks workspace-relative but escapes the workspace root.
      if (isUnsafeWorkspacePath(resolvedPath)) {
        return (
          <SafeAnchor href={null} title={undefined}>
            {children}
          </SafeAnchor>
        );
      }
      // href="#" rather than href={resolvedPath}: a modifier-click on a
      // populated href bypasses the React onClick, lets the browser
      // navigate the chat sidebar to /lab/<path> in a new tab, and would
      // ride along the user's Jupyter session cookies. The hover preview
      // moves to `title` so the user still sees the intended target.
      const safeTitleFromMd =
        typeof title === 'string' && !hasDangerousTextCodepoints(title)
          ? title
          : undefined;
      const hoverTitle = safeTitleFromMd ?? resolvedPath;
      const onClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
        e.preventDefault();
        // ContentsManager rejects paths outside the Jupyter root with a
        // promise rejection. Catch so the failure surfaces in logs instead
        // of an unhandled rejection, and the user can see the rendered
        // anchor was attempted even when the target doesn't exist.
        Promise.resolve(
          app.commands.execute('docmanager:open', { path: resolvedPath })
        ).catch(err => {
          console.warn(
            `NBI: failed to open workspace path "${resolvedPath}":`,
            err
          );
        });
      };
      return (
        <a href="#" title={hoverTitle} onClick={onClick}>
          {children}
        </a>
      );
    }
  }
  return (
    <SafeAnchor
      href={typeof href === 'string' ? href : null}
      title={typeof title === 'string' ? title : undefined}
    >
      {children}
    </SafeAnchor>
  );
}
