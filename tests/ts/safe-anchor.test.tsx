// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import React from 'react';
import { render, screen } from '@testing-library/react';

import { SafeAnchor } from '../../src/components/safe-anchor';

describe('SafeAnchor', () => {
  it('renders an anchor with target=_blank and rel=noopener noreferrer for https hrefs', () => {
    render(<SafeAnchor href="https://example.com/page">click</SafeAnchor>);
    const anchor = screen.getByRole('link', { name: /click/ });
    expect(anchor).toHaveAttribute('href', 'https://example.com/page');
    expect(anchor).toHaveAttribute('target', '_blank');
    expect(anchor).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('appends an "opens in new tab" SR-only suffix so SR users are warned', () => {
    render(<SafeAnchor href="https://example.com">docs</SafeAnchor>);
    expect(screen.getByText(/opens in new tab/)).toHaveClass('nbi-sr-only');
  });

  it.each([
    ['javascript', 'javascript:alert(1)'],
    ['data', 'data:text/html,<script>x</script>'],
    ['vbscript', 'vbscript:msgbox(1)'],
    ['blob', 'blob:https://example.com/abc'],
    ['file', 'file:///etc/passwd'],
    ['scheme with C0 unmask', 'java\tscript:alert(1)']
  ])('blocks %s schemes by falling back to a non-anchor span', (_, href) => {
    render(<SafeAnchor href={href}>click</SafeAnchor>);
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText(/link blocked/)).toHaveClass('nbi-sr-only');
  });

  it.each([
    ['empty', ''],
    ['whitespace-only', '   '],
    ['null', null],
    ['undefined', undefined],
    ['no scheme', 'just/some/path'],
    ['scheme-relative', '//example.com/path']
  ])('blocks %s hrefs', (_, href) => {
    render(<SafeAnchor href={href as any}>click</SafeAnchor>);
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('renders children verbatim on both success and block branches', () => {
    const { rerender } = render(
      <SafeAnchor href="https://example.com">
        <strong>Important</strong>
      </SafeAnchor>
    );
    expect(screen.getByText('Important').tagName).toBe('STRONG');
    rerender(
      <SafeAnchor href="javascript:alert(1)">
        <strong>Important</strong>
      </SafeAnchor>
    );
    expect(screen.getByText('Important').tagName).toBe('STRONG');
  });

  it('forwards a clean title attribute', () => {
    render(
      <SafeAnchor href="https://example.com" title="hover text">
        click
      </SafeAnchor>
    );
    expect(screen.getByRole('link')).toHaveAttribute('title', 'hover text');
  });

  it('drops a title containing bidi-override codepoints', () => {
    // U+202E RIGHT-TO-LEFT OVERRIDE can visually impersonate the link.
    render(
      <SafeAnchor href="https://example.com" title={'docs\u202E.gpj'}>
        click
      </SafeAnchor>
    );
    expect(screen.getByRole('link')).not.toHaveAttribute('title');
  });

  it('accepts mailto: as a safe scheme', () => {
    render(<SafeAnchor href="mailto:foo@example.com">email</SafeAnchor>);
    expect(screen.getByRole('link')).toHaveAttribute(
      'href',
      'mailto:foo@example.com'
    );
  });

  it('trims surrounding whitespace from an accepted href', () => {
    render(<SafeAnchor href="  https://example.com  ">click</SafeAnchor>);
    expect(screen.getByRole('link')).toHaveAttribute(
      'href',
      'https://example.com'
    );
  });
});
