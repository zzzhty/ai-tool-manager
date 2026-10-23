// TEST_ONLY mock IPC; no network, native CLI or system keyring actions.
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { DesktopApp } from '../src/app';
import type { DesktopApi, SnapshotView, UsageSnapshot } from '../src/types';
const keyA = '11111111-1111-4111-8111-111111111111';
const keyB = '22222222-2222-4222-8222-222222222222';
const data = (): SnapshotView => ({ keys: [{ id: keyA, name: 'TEST_ONLY_A', mask: '••••••••', updatedUtc: '2026-10-13T00:00:00Z' }, { id: keyB, name: 'TEST_ONLY_B', mask: '••••••••', updatedUtc: '2026-10-13T00:00:00Z' }], targets: [], templates: [], storageKind: 'linux_secret_service' });
const usage = (provider: 'codex' | 'glm' = 'glm'): UsageSnapshot => ({
  provider, region: provider === 'glm' ? 'china' : 'global', authKind: provider === 'glm' ? 'coding_plan_key' : 'chatgpt_oauth', source: provider === 'glm' ? 'official_plugin_compat' : 'official_app_server',
  observedAt: '2026-10-13T00:00:00Z', checkedAt: '2026-10-13T00:00:00Z', status: 'ok', planName: 'pro', credits: null, warnings: [],
  windows: [{ id: 'TEST_ONLY', label: 'TEST_ONLY_SECRET_ECHO', kind: 'subscription_quota', usedPercent: 25, remainingPercent: 75, windowDurationMins: 300, resetsAt: null, status: 'ok' }],
});
let root: HTMLElement, app: DesktopApp, api: DesktopApi;
const get = <T extends HTMLElement = HTMLElement>(id: string) => root.querySelector<T>('#' + id)!;
const input = (id: string) => get<HTMLInputElement>(id);
const select = (id: string) => get<HTMLSelectElement>(id);
const click = (id: string) => get<HTMLButtonElement>(id).click();
const change = (id: string) => get(id).dispatchEvent(new Event('change'));
const ready = () => vi.waitFor(() => expect(root.getAttribute('aria-busy')).toBe('false'));
const glm = async () => { select('glm-key').value = keyA; change('glm-key'); input('confirm-glm-query').checked = true; change('confirm-glm-query'); click('query-glm'); await ready(); };
beforeEach(async () => {
  api = {
    snapshot: vi.fn().mockResolvedValue(data()), cancelPreview: vi.fn(), saveKey: vi.fn(), deleteKey: vi.fn(), saveTarget: vi.fn(), deleteTarget: vi.fn(),
    preview: vi.fn(), applyPreview: vi.fn(), listBackups: vi.fn(), previewRollback: vi.fn(), inferTemplate: vi.fn(), saveTemplate: vi.fn(), deleteTemplate: vi.fn(), pickFile: vi.fn(),
    initializeStorage: vi.fn(), configureCodexCli: vi.fn(), disconnectCodexCli: vi.fn(),
    queryCodexUsage: vi.fn().mockResolvedValue(usage('codex')), queryGlmUsage: vi.fn().mockResolvedValue(usage()), omhDiagnose: vi.fn(), omhCapabilities: vi.fn(), omhExecute: vi.fn(), omhStatus: vi.fn(), skillsInventory: vi.fn(), skillsInstall: vi.fn(), skillsUninstall: vi.fn(), skillsRestore: vi.fn(), skillsPurge: vi.fn(), skillsCopy: vi.fn(), pickDirectory: vi.fn(),
  };
  root = document.createElement('div'); document.body.append(root); app = new DesktopApp(root, api); await app.start();
  root.querySelector<HTMLButtonElement>('[data-panel="usage"]')!.click();
});
afterEach(() => { app.dispose(); root.remove(); vi.restoreAllMocks(); });
it('startup and navigation perform no query, keyring probe or auto polling', async () => {
  expect(api.queryCodexUsage).not.toHaveBeenCalled(); expect(api.queryGlmUsage).not.toHaveBeenCalled(); expect(api.initializeStorage).not.toHaveBeenCalled();
  expect(get<HTMLButtonElement>('query-codex').disabled).toBe(true); expect(get<HTMLButtonElement>('query-glm').disabled).toBe(true);
  expect(get('glm-usage-result').textContent).toContain('未知'); expect(get('glm-usage-result').textContent).not.toContain('0.0%');
});
it('macOS Keychain initialization requires explicit consent and stays disabled in demo', async () => {
  const mac = data(); mac.storageKind = 'macos_keychain';
  vi.mocked(api.snapshot).mockResolvedValue(mac);
  click('refresh'); await ready();
  expect(get('storage-label').textContent).toContain('Keychain · AES-GCM');
  expect(get('storage-connect').hidden).toBe(false);
  expect(get('storage-connect').textContent).toContain('macOS Keychain');
  expect(api.initializeStorage).not.toHaveBeenCalled();
  expect(get<HTMLButtonElement>('connect-storage').disabled).toBe(true);
  input('confirm-storage').checked = true; change('confirm-storage');
  click('connect-storage'); click('connect-storage'); await ready();
  expect(api.initializeStorage).toHaveBeenCalledExactlyOnceWith(true);
  expect(input('confirm-storage').checked).toBe(false);
  mac.demo = true;
  click('refresh'); await ready();
  expect(get('storage-connect').hidden).toBe(true);
  expect(get('storage-label').textContent).toContain('演示模式');
});
it('CLI consent is consumed per query and space-containing paths stay separate IPC arguments', async () => {
  input('codex-cli').value = 'C:/TEST_ONLY space/codex.exe'; input('codex-cli').dispatchEvent(new Event('input'));
  input('codex-profile').value = 'C:/TEST_ONLY account'; input('codex-profile').dispatchEvent(new Event('input'));
  click('connect-codex'); await ready();
  expect(api.configureCodexCli).toHaveBeenCalledWith('C:/TEST_ONLY space/codex.exe', 'C:/TEST_ONLY account', true);
  expect(api.queryCodexUsage).not.toHaveBeenCalled();
  input('confirm-codex-query').checked = true; change('confirm-codex-query'); click('query-codex'); click('query-codex'); await ready();
  expect(api.queryCodexUsage).toHaveBeenCalledExactlyOnceWith(true); expect(input('confirm-codex-query').checked).toBe(false);
  expect(get('codex-usage-result').textContent).toContain('75.0%'); expect(get('codex-usage-result').textContent).toContain('官方 app-server');
  expect(root.textContent).not.toContain('TEST_ONLY_SECRET_ECHO');
});
// Known PlanType additions from openai/codex b043762f9e3eb65dd5164ff5880f139bc6d084c7.
it.each(['prolite', 'promax', 'self_serve_business_prolite', 'self_serve_business_usage_based', 'ent26', 'enterprise_cbp_automation', 'enterprise_cbp_usage_based', 'edu_plus', 'edu_pro'])('renders the known Codex %s plan after a confirmed mock query', async (planName) => {
  const result = usage('codex'); result.planName = planName;
  vi.mocked(api.queryCodexUsage).mockResolvedValue(result);
  input('codex-cli').value = '/TEST_ONLY/codex'; input('codex-cli').dispatchEvent(new Event('input'));
  input('codex-profile').value = '/TEST_ONLY/account'; input('codex-profile').dispatchEvent(new Event('input'));
  click('connect-codex'); await ready();
  input('confirm-codex-query').checked = true; change('confirm-codex-query'); click('query-codex'); await ready();
  expect(api.queryCodexUsage).toHaveBeenCalledExactlyOnceWith(true);
  expect(get('codex-usage-result').textContent).toContain('套餐：' + planName);
  expect(get('codex-usage-result').textContent).not.toContain('套餐：未知');
});
it.each([
  ['ordinary_usage_not_allowed', 'Codex 后端未允许普通用量，额度窗口已隐藏。'],
  ['ordinary_usage_permission_unknown', 'Codex 普通用量许可未知，额度窗口已隐藏。'],
] as const)('removes prior Codex windows and displays %s after a confirmed mock query', async (warning, message) => {
  input('codex-cli').value = '/TEST_ONLY/codex'; input('codex-cli').dispatchEvent(new Event('input'));
  input('codex-profile').value = '/TEST_ONLY/account'; input('codex-profile').dispatchEvent(new Event('input'));
  click('connect-codex'); await ready();
  input('confirm-codex-query').checked = true; change('confirm-codex-query'); click('query-codex'); await ready();
  expect(get('codex-usage-result').textContent).toContain('75.0%');
  const result = usage('codex'); result.status = 'unknown'; result.windows = []; result.warnings = [warning];
  vi.mocked(api.queryCodexUsage).mockResolvedValue(result);
  input('confirm-codex-query').checked = true; change('confirm-codex-query'); click('query-codex'); await ready();
  expect(api.queryCodexUsage).toHaveBeenCalledTimes(2);
  expect(get('codex-usage-result').textContent).toContain(message);
  expect(get('codex-usage-result').textContent).not.toContain('75.0%');
});
it('GLM passes only region, purpose and key reference; nulls remain unknown', async () => {
  const result = usage(); result.windows[0]!.remainingPercent = null; result.windows[0]!.usedPercent = null; result.windows[0]!.windowDurationMins = null; result.status = 'unknown';
  vi.mocked(api.queryGlmUsage).mockResolvedValue(result);
  select('glm-region').value = 'international'; change('glm-region'); await glm();
  expect(api.queryGlmUsage).toHaveBeenCalledExactlyOnceWith('international', 'personal', keyA, true);
  expect(get('glm-usage-result').textContent).toContain('剩余：未知'); expect(get('glm-usage-result').textContent).not.toContain('0.0%');
  expect(get('glm-usage-result').textContent).toContain('观测时间'); expect(input('confirm-glm-query').checked).toBe(false);
});
it('changing region, key, kind or credential revision removes old snapshots and consent', async () => {
  await glm(); expect(get('glm-usage-result').textContent).toContain('75.0%');
  select('glm-region').value = 'international'; change('glm-region'); expect(get('glm-usage-result').textContent).not.toContain('75.0%');
  await glm(); select('glm-key').value = keyB; change('glm-key'); expect(get('glm-usage-result').textContent).not.toContain('75.0%');
  await glm(); select('glm-plan-kind').value = 'api_balance'; change('glm-plan-kind'); expect(get('glm-usage-result').textContent).not.toContain('75.0%');
  select('glm-plan-kind').value = 'personal'; change('glm-plan-kind'); await glm();
  const rotated = data(); rotated.keys[0]!.updatedUtc = '2026-10-13T01:00:00Z'; vi.mocked(api.snapshot).mockResolvedValue(rotated);
  click('refresh'); await ready(); expect(get('glm-usage-result').textContent).not.toContain('75.0%');
});
it('authentication failures hide even erroneous backend old windows and arbitrary fields', async () => {
  await glm(); const failed = usage(); failed.status = 'authentication_failed'; failed.planName = 'TEST_ONLY_SECRET_ECHO'; failed.source = 'TEST_ONLY_SECRET_ECHO'; failed.warnings = ['TEST_ONLY_SECRET_ECHO'];
  vi.mocked(api.queryGlmUsage).mockResolvedValue(failed); await glm();
  expect(get('glm-usage-result').textContent).toContain('认证失败'); expect(get('glm-usage-result').textContent).not.toContain('75.0%');
  expect(root.textContent).not.toContain('TEST_ONLY_SECRET_ECHO');
});
it('stale windows are explicitly marked as old and unknown plan stays unknown', async () => {
  const old = usage(); old.status = 'stale'; old.planName = null; old.warnings = ['cached_snapshot_not_live'];
  vi.mocked(api.queryGlmUsage).mockResolvedValue(old); await glm();
  expect(get('glm-usage-result').textContent).toContain('过期快照'); expect(get('glm-usage-result').textContent).toContain('套餐：未知');
});
it('team and API purposes omit key and never pretend subscription is API balance', async () => {
  select('glm-plan-kind').value = 'api_balance'; change('glm-plan-kind');
  input('confirm-glm-query').checked = true; change('confirm-glm-query'); click('query-glm'); await ready();
  expect(api.queryGlmUsage).toHaveBeenCalledExactlyOnceWith('china', 'api_balance', null, true);
});
it('Linux storage initialization requires its own consumed explicit confirmation', async () => {
  expect(get('storage-connect').hidden).toBe(false); click('connect-storage'); expect(api.initializeStorage).not.toHaveBeenCalled();
  input('confirm-storage').checked = true; change('confirm-storage'); click('connect-storage'); await ready();
  expect(api.initializeStorage).toHaveBeenCalledExactlyOnceWith(true); expect(input('confirm-storage').checked).toBe(false);
});
it('a delayed quota result is discarded after context changes while controls remain blocked', async () => {
  let resolve!: (s: UsageSnapshot) => void;
  vi.mocked(api.queryGlmUsage).mockImplementation(() => new Promise<UsageSnapshot>(r => { resolve = r; }));
  select('glm-key').value = keyA; change('glm-key'); input('confirm-glm-query').checked = true; change('confirm-glm-query'); click('query-glm');
  select('glm-region').value = 'international'; change('glm-region'); expect(get<HTMLButtonElement>('query-glm').disabled).toBe(true);
  resolve(usage()); await ready(); expect(get('glm-usage-result').textContent).not.toContain('75.0%');
});

