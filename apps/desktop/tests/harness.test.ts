// TEST_ONLY mock IPC; no real atm-harness installation or process is touched.
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { DesktopApp } from '../src/app';
import type { DesktopApi, HarnessStatusView, SnapshotView } from '../src/types';
const data = (): SnapshotView => ({ keys: [], targets: [], templates: [], storageKind: 'linux_secret_service' });
const status = (): HarnessStatusView => ({
  source: 'recorded', managerHome: '/TEST_ONLY/home/.atm', installed: true,
  managerStatus: 'ready', channel: 'main', releaseVersion: '1.0.0', revision: '8b7b1e050f5f0701a557d28b099345d3e79f2a21',
  repository: 'git@github.com:zzzhty/atm-harness.git', harnesses: [
    { name: 'codex', status: 'ready', root: '/TEST_ONLY/home/.codex', releaseVersion: '1.0.0', updatedAt: '2026-10-14T16:10:44.095373Z' },
    { name: 'pi-agent', status: null, root: null, releaseVersion: null, updatedAt: null },
  ], operationKind: null, worktreeClean: null,
});
let root: HTMLElement, app: DesktopApp, api: DesktopApi;
const get = <T extends HTMLElement = HTMLElement>(id: string) => root.querySelector<T>('#' + id)!;
const click = (id: string) => get<HTMLButtonElement>(id).click();
const ready = () => vi.waitFor(() => expect(root.getAttribute('aria-busy')).toBe('false'));
const open = () => root.querySelector<HTMLButtonElement>('[data-panel="harness"]')!.click();
const query = async () => { open(); click('query-harness'); await ready(); };
beforeEach(async () => {
  api = {
    snapshot: vi.fn().mockResolvedValue(data()), cancelPreview: vi.fn(), saveKey: vi.fn(), deleteKey: vi.fn(), saveTarget: vi.fn(), deleteTarget: vi.fn(),
    preview: vi.fn(), applyPreview: vi.fn(), listBackups: vi.fn(), previewRollback: vi.fn(), inferTemplate: vi.fn(), saveTemplate: vi.fn(), deleteTemplate: vi.fn(), pickFile: vi.fn(),
    initializeStorage: vi.fn(), configureCodexCli: vi.fn(), disconnectCodexCli: vi.fn(), queryCodexUsage: vi.fn(), queryGlmUsage: vi.fn(),
    harnessDiagnose: vi.fn(), harnessCapabilities: vi.fn(), harnessExecute: vi.fn(), harnessStatus: vi.fn().mockResolvedValue(status()),
    skillsInventory: vi.fn(), skillsInstall: vi.fn(), skillsUninstall: vi.fn(), skillsRestore: vi.fn(), skillsPurge: vi.fn(), skillsCopy: vi.fn(), pickDirectory: vi.fn(),
  };
  root = document.createElement('div'); document.body.append(root); app = new DesktopApp(root, api); await app.start();
});
afterEach(() => { app.dispose(); root.remove(); vi.restoreAllMocks(); });

it('startup and navigation never query the harness manager; the read-only button needs no consent', () => {
  expect(api.harnessStatus).not.toHaveBeenCalled();
  expect(get<HTMLButtonElement>('query-harness').disabled).toBe(false);
  open();
  expect(get('harness-status-result').textContent).toContain('尚未查询');
  expect(api.harnessStatus).not.toHaveBeenCalled();
});

it('renders the recorded snapshot with unknown values preserved and revision shortened', async () => {
  await query();
  expect(api.harnessStatus).toHaveBeenCalledExactlyOnceWith();
  const output = get('harness-status-result');
  expect(output.textContent).toContain('记录态快照 · 非实时');
  expect(output.textContent).toContain('记录就绪');
  expect(output.textContent).not.toContain('正常');
  expect(output.textContent).toContain('通道：main');
  expect(output.textContent).toContain('8b7b1e0');
  expect(output.textContent).not.toContain('8b7b1e050f5f0701a557d28b099345d3e79f2a21');
  expect(output.textContent).toContain('codex');
  expect(output.textContent).toContain('/TEST_ONLY/home/.codex');
  // A desired harness without receipts stays listed but explicitly unknown.
  expect(output.textContent).toContain('pi-agent');
  expect(output.textContent).toContain('未知');
  expect(output.textContent).toContain('未检查');
});

it('a missing installation renders an explicit not-installed state instead of an error', async () => {
  vi.mocked(api.harnessStatus).mockRejectedValue({ code: 'HARNESS_NOT_INSTALLED' });
  await query();
  expect(get('harness-status-result').textContent).toContain('未检测到 harness 引擎安装');
  expect(get('harness-status-result').textContent).toContain('atm harness bootstrap');
  expect(root.textContent).not.toContain('/TEST_ONLY');
});

it('protocol failures surface through the safe error vocabulary only', async () => {
  vi.mocked(api.harnessStatus).mockRejectedValue({ code: 'HARNESS_PROTOCOL' });
  await query();
  expect(get('harness-status-result').textContent).toContain('尚未查询');
  expect(root.textContent).toContain('状态输出无法安全识别');
});

it('an in-flight operation is reported as a record, never as a failure', async () => {
  const active = status(); active.operationKind = 'update'; active.managerStatus = 'degraded';
  vi.mocked(api.harnessStatus).mockResolvedValue(active);
  await query();
  expect(get('harness-status-result').textContent).toContain('update');
  expect(get('harness-status-result').textContent).toContain('记录降级');
  expect(get('harness-status-result').textContent).not.toContain('失败');
});

it('demo snapshots are labelled as TEST_ONLY data', async () => {
  const demo = status(); demo.source = 'synthetic_demo';
  vi.mocked(api.harnessStatus).mockResolvedValue(demo);
  await query();
  expect(get('harness-status-result').textContent).toContain('TEST_ONLY 演示数据');
});

it('at most 64 harness rows are rendered from one snapshot', async () => {
  const many = status();
  many.harnesses = Array.from({ length: 80 }, (_, index) => ({ name: `h${index}`, status: 'ready', root: null, releaseVersion: '1.0.0', updatedAt: null }));
  vi.mocked(api.harnessStatus).mockResolvedValue(many);
  await query();
  const rows = get('harness-status-result').querySelectorAll('article').length;
  expect(rows).toBe(65); // 1 head + 64 harnesses
});

const capabilities = () => ({ harnesses: ['codex', 'claude-code'], operations: {
  install: { supported: true, requiresConfirmation: true, explicitHarnesses: true },
  refresh: { supported: true, requiresConfirmation: true, explicitHarnesses: true },
  remove: { supported: true, requiresConfirmation: true, explicitHarnesses: true },
  update: { supported: false, requiresConfirmation: true, explicitHarnesses: true },
} });
it('old CLI keeps mutation disabled while preserving recorded status', async () => {
  vi.mocked(api.harnessCapabilities).mockRejectedValue({ code: 'HARNESS_PROTOCOL' });
  await query();
  expect(get<HTMLButtonElement>('harness-preview').disabled).toBe(true);
  expect(get('harness-capability-note').textContent).toContain('已禁用');
  expect(get('harness-status-result').textContent).toContain('记录态快照');
  expect(api.harnessExecute).not.toHaveBeenCalled();
});
it('requires exact target selection and cancel never executes', async () => {
  vi.mocked(api.harnessCapabilities).mockResolvedValue(capabilities());
  await query();
  expect(get<HTMLButtonElement>('harness-preview').disabled).toBe(true);
  const target = root.querySelector<HTMLInputElement>('#harness-targets input')!;
  target.click(); click('harness-preview');
  expect(get('confirm-dialog').textContent).toContain('codex');
  expect(api.harnessExecute).not.toHaveBeenCalled();
  click('dialog-cancel');
  expect(api.harnessExecute).not.toHaveBeenCalled();
});
it('confirmed lifecycle operation refreshes snapshot and clears target consent', async () => {
  vi.mocked(api.harnessCapabilities).mockResolvedValue(capabilities());
  vi.mocked(api.harnessExecute).mockResolvedValue();
  await query();
  root.querySelector<HTMLInputElement>('#harness-targets input')!.click();
  click('harness-preview'); click('dialog-confirm'); await ready();
  expect(api.harnessExecute).toHaveBeenCalledExactlyOnceWith('install', ['codex'], true);
  expect(api.harnessStatus).toHaveBeenCalledTimes(2);
  expect(get<HTMLButtonElement>('harness-preview').disabled).toBe(true);
});
it('busy and confirmation-required errors refresh partial-state record without retry', async () => {
  vi.mocked(api.harnessCapabilities).mockResolvedValue(capabilities());
  vi.mocked(api.harnessExecute).mockRejectedValue({ code: 'HARNESS_CONFIRMATION_REQUIRED' });
  await query(); root.querySelector<HTMLInputElement>('#harness-targets input')!.click();
  click('harness-preview'); click('dialog-confirm'); await ready();
  expect(api.harnessExecute).toHaveBeenCalledTimes(1);
  expect(api.harnessStatus).toHaveBeenCalledTimes(2);
  expect(root.textContent).toContain('额外确认');
});
it('diagnostics are capability gated and report current observations separately from records', async () => {
  const caps = capabilities();
  vi.mocked(api.harnessCapabilities).mockResolvedValue({ ...caps, operations: { ...caps.operations, check: { supported: true, requiresConfirmation: false, explicitHarnesses: false } } });
  vi.mocked(api.harnessDiagnose).mockResolvedValue({ operation: 'check', passed: false, exitCode: 1 });
  await query(); expect(get<HTMLButtonElement>('harness-doctor').disabled).toBe(true);
  click('harness-check'); await ready();
  expect(api.harnessDiagnose).toHaveBeenCalledExactlyOnceWith('check');
  expect(get('harness-diagnostic-result').textContent).toContain('发现问题');
  expect(get('harness-status-result').textContent).toContain('记录态快照');
  expect(api.harnessExecute).not.toHaveBeenCalled();
});
