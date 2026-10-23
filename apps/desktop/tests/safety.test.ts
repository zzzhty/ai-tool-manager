import { describe, expect, it } from 'vitest';
import { displayDate, pointerIsValid, safeError, schemaText } from '../src/safety';
import { readFileSync } from 'node:fs';
// Read the actual source: Vitest intentionally stubs CSS modules, including ?raw.
const stylesheetPath = '../src/styles.css';
const styles = readFileSync(new URL(stylesheetPath, import.meta.url), 'utf8');
import layout from '../src/layout.ts?raw';

describe('bounded safe presentation', () => {
  it('accepts exact JSON Pointers and rejects invalid escapes, dot paths, and empty root', () => {
    for (const pointer of ['/key', '/a~1b/~0key', '/servers/0/key', '/']) expect(pointerIsValid(pointer)).toBe(true);
    for (const pointer of ['', 'servers.apiKey', '/bad~', '/bad~2']) expect(pointerIsValid(pointer)).toBe(false);
  });
  it('never reflects arbitrary error content or unknown error codes', () => {
    for (const error of ['FAKE_SECRET', new Error('FAKE_SECRET'), { code: 'FAKE_SECRET', message: 'FAKE_SECRET' }, null]) expect(safeError(error)).not.toContain('FAKE_SECRET');
    expect(safeError({ code: 'KEY_IN_USE', message: 'FAKE_SECRET' })).toContain('引用');
  });
  it('renders invalid dates safely and schema objects readably', () => {
    expect(displayDate('invalid')).toBe('时间不可用'); expect(displayDate(null)).toBe('时间不可用'); expect(schemaText({ type: 'object' })).toContain('"type": "object"'); expect(schemaText('{}')).toBe('{}');
  });
  it('allows small-window document scrolling and accessible reduced-motion focus styles', () => {
    expect(styles).toContain('@media (max-width: 660px)'); expect(styles).toContain('@media (max-width: 900px)'); expect(styles).toContain(':focus-visible'); expect(styles).toContain('prefers-reduced-motion'); expect(styles).not.toMatch(/body\s*\{[^}]*overflow:\s*hidden/);
    expect(layout).toContain('aria-live="polite"'); expect(layout).toContain('autocomplete="new-password"');
  });
});
