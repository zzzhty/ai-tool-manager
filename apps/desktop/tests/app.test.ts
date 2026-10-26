import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DesktopApp } from '../src/app';
import type { DesktopApi, PreviewView, SnapshotView, TemplateCandidate } from '../src/types';
import { MASK } from '../src/safety';

const keyId = '11111111-1111-4111-8111-111111111111';
const targetId = '22222222-2222-4222-8222-222222222222';
const previewId = '33333333-3333-4333-8333-333333333333';
const templateId = '44444444-4444-4444-8444-444444444444';
const fixture = (): SnapshotView => ({
  keys: [{ id: keyId, name: '合成假密钥', mask: MASK, updatedUtc: '2026-10-13T00:00:00Z' }],
  targets: [{ Id: targetId, Label: '合成目标', FilePath: 'C:\\fake\\config.jsonc', Pointer: '/apiKey', KeyId: keyId, BearerPrefix: false, ReplaceVariables: false, TemplateId: null }],
  templates: [{ id: templateId, name: '合成模板', fields: [{ pointer: '/apiKey', label: 'apiKey', kind: 'string' }] }],
});
const preview = (): PreviewView => ({ id: previewId, files: [{ path: 'C:\\fake\\config.jsonc', fields: [{ label: '合成目标', pointer: '/apiKey', before: 'FAKE_UNEXPECTED_BACKEND_PLAINTEXT', after: 'Bearer FAKE_UNEXPECTED_BACKEND_PLAINTEXT', status: 'FAKE_UNEXPECTED_BACKEND_PLAINTEXT' }], encoding: 'UTF-8', changed: true, error: null }] });
const candidate = (): TemplateCandidate => ({ id: templateId, name: '合成候选模板', fields: [{ pointer: '/apiKey', label: 'apiKey', kind: 'string' }], schema: { type: 'object', properties: { apiKey: { type: 'string' } } } });
const deferred = <T>() => { let resolve!: (value: T) => void; let reject!: (reason: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
let root: HTMLElement;
let app: DesktopApp;
let api: DesktopApi;
const get = <T extends HTMLElement = HTMLElement>(id: string) => root.querySelector<T>(`#${id}`)!;
const input = (id: string) => get<HTMLInputElement>(id);
const click = (id: string) => get<HTMLButtonElement>(id).click();
const submit = (id: string) => get(id).dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
const change = (id: string) => get(id).dispatchEvent(new Event('change', { bubbles: true }));
const ready = async () => vi.waitFor(() => expect(root.getAttribute('aria-busy')).toBe('false'));
const selectTarget = async () => {
  const check = root.querySelector<HTMLInputElement>('#targets-list input')!; check.checked = true; check.dispatchEvent(new Event('change')); await ready();
};
const makePreview = async () => { await selectTarget(); click('preview-selected'); await ready(); };

beforeEach(async () => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  api = {
    initializeStorage: vi.fn().mockResolvedValue(undefined), configureCodexCli: vi.fn().mockResolvedValue(undefined), disconnectCodexCli: vi.fn().mockResolvedValue(undefined), queryCodexUsage: vi.fn(), queryGlmUsage: vi.fn(), harnessDiagnose: vi.fn(), harnessCapabilities: vi.fn(), harnessExecute: vi.fn(), harnessStatus: vi.fn(), skillsInventory: vi.fn(), skillsInstall: vi.fn(), skillsUninstall: vi.fn(), skillsRestore: vi.fn(), skillsPurge: vi.fn(), skillsCopy: vi.fn(), pickDirectory: vi.fn(),
    snapshot: vi.fn().mockResolvedValue(fixture()), saveKey: vi.fn().mockResolvedValue(keyId), deleteKey: vi.fn().mockResolvedValue(undefined),
    saveTarget: vi.fn().mockResolvedValue(targetId), deleteTarget: vi.fn().mockResolvedValue(undefined),
    preview: vi.fn().mockImplementation(async () => preview()), applyPreview: vi.fn().mockResolvedValue([{ path: 'C:\\fake\\config.jsonc', outcome: 'applied', message: 'FAKE_RAW_MESSAGE', code: null, backupPath: 'C:\\fake\\backups\\fake.atmbackup', temporaryPath: null }]),
    cancelPreview: vi.fn().mockResolvedValue(undefined), listBackups: vi.fn().mockResolvedValue([{ backupPath: 'C:\\fake\\backups\\fake.atmbackup', filePath: 'C:\\fake\\config.jsonc', createdUtc: '2026-10-13T00:00:00Z', error: null }]),
    previewRollback: vi.fn().mockResolvedValue(preview()), inferTemplate: vi.fn().mockResolvedValue(candidate()),
    saveTemplate: vi.fn().mockResolvedValue(templateId), deleteTemplate: vi.fn().mockResolvedValue(undefined), pickFile: vi.fn().mockResolvedValue('C:\\fake\\config.jsonc'),
  };
  root = document.createElement('div'); document.body.append(root); app = new DesktopApp(root, api); await app.start();
});
afterEach(() => { app.dispose(); root.remove(); vi.restoreAllMocks(); });

describe('vault safety and lifecycle', () => {
  it('invalidates stale plans on startup and only renders fixed masks', () => {
    expect(api.cancelPreview).toHaveBeenCalledTimes(1); expect(root.textContent).toContain(MASK);
    expect(input('key-secret').type).toBe('password'); expect(input('key-secret').autocomplete).toBe('new-password');
    expect(input('key-secret').value).toBe('');
  });
  it('does not refill saved secrets when editing and permits name-only updates', async () => {
    root.querySelector<HTMLButtonElement>('#keys-list button')!.click();
    expect(input('key-name').value).toBe('合成假密钥'); expect(input('key-secret').value).toBe(''); expect(input('key-secret').required).toBe(false);
    input('key-name').value = '改名后的假密钥'; submit('key-form'); await ready();
    expect(api.saveKey).toHaveBeenCalledWith(keyId, '改名后的假密钥', ''); expect(input('key-name').value).toBe('');
  });
  it('clears typed secrets before IPC and never reflects unknown exceptions', async () => {
    vi.mocked(api.saveKey).mockRejectedValue(new Error('FAKE_TYPED_SECRET'));
    input('key-name').value = '新假密钥'; input('key-secret').value = 'FAKE_TYPED_SECRET'; submit('key-form');
    expect(input('key-secret').value).toBe(''); await ready();
    expect(api.saveKey).toHaveBeenCalledWith(null, '新假密钥', 'FAKE_TYPED_SECRET'); expect(root.textContent).not.toContain('FAKE_TYPED_SECRET'); expect(get('notice').textContent).toContain('不会自动重试');
  });
  it('does not queue repeated secret saves while an operation is pending', async () => {
    const pending = deferred<string>(); vi.mocked(api.saveKey).mockReturnValue(pending.promise);
    input('key-name').value = '重复测试'; input('key-secret').value = 'FAKE_REPEATED'; submit('key-form'); submit('key-form');
    await vi.waitFor(() => expect(api.saveKey).toHaveBeenCalledTimes(1)); expect(get<HTMLButtonElement>('save-key').disabled).toBe(true);
    pending.resolve(keyId); await ready(); expect(api.saveKey).toHaveBeenCalledTimes(1);
  });
  it('clears secret input on cancel, blur and navigation', () => {
    input('key-secret').value = 'FAKE_CANCEL'; click('reset-key'); expect(input('key-secret').value).toBe('');
    input('key-secret').value = 'FAKE_BLUR'; window.dispatchEvent(new Event('blur')); expect(input('key-secret').value).toBe('');
    input('key-secret').value = 'FAKE_NAV'; root.querySelector<HTMLButtonElement>('[data-panel="targets"]')!.click(); expect(input('key-secret').value).toBe('');
  });
  it('requires a separate deletion confirmation and supports cancel', async () => {
    root.querySelectorAll<HTMLButtonElement>('#keys-list button')[1]!.click(); expect(api.deleteKey).not.toHaveBeenCalled();
    click('dialog-cancel'); expect(api.deleteKey).not.toHaveBeenCalled();
    root.querySelectorAll<HTMLButtonElement>('#keys-list button')[1]!.click(); click('dialog-confirm'); await ready(); expect(api.deleteKey).toHaveBeenCalledOnce();
  });
  it('renders labels as text, without injecting HTML', async () => {
    const data = fixture(); data.keys[0]!.name = '<img src=x onerror=alert(1)>'; vi.mocked(api.snapshot).mockResolvedValue(data);
    click('refresh'); await ready(); expect(root.querySelector('#keys-list img')).toBeNull(); expect(get('keys-list').textContent).toContain('<img src=x onerror=alert(1)>');
  });
});

describe('target mapping', () => {
  it('saves the PascalCase contract with variable protection and optional Bearer', async () => {
    input('target-label').value = '新合成目标'; click('pick-target'); await ready(); input('target-pointer').value = '/headers/Authorization';
    get<HTMLSelectElement>('target-key').value = keyId; input('target-bearer').checked = true; submit('target-form'); await ready();
    expect(api.saveTarget).toHaveBeenCalledWith(expect.objectContaining({ Id: '00000000-0000-0000-0000-000000000000', Pointer: '/headers/Authorization', KeyId: keyId, BearerPrefix: true, ReplaceVariables: false, TemplateId: null }));
  });
  it('preserves the current path on cancelled file picker', async () => {
    input('target-path').value = 'C:\\fake\\existing.json'; vi.mocked(api.pickFile).mockResolvedValue(null); click('pick-target'); await ready(); expect(input('target-path').value).toBe('C:\\fake\\existing.json');
  });
  it('uses only saved template fields when a template is assigned', async () => {
    input('target-label').value = '模板目标'; input('target-path').value = 'C:\\fake\\config.jsonc'; get<HTMLSelectElement>('target-key').value = keyId;
    get<HTMLSelectElement>('target-template').value = templateId; change('target-template'); input('protect-variables').checked = false;
    expect(input('target-pointer').hidden).toBe(true); expect(input('target-pointer').required).toBe(false);
    expect(get<HTMLSelectElement>('template-pointer').value).toBe('/apiKey');
    submit('target-form'); await ready(); expect(api.saveTarget).toHaveBeenCalledWith(expect.objectContaining({ Pointer: '/apiKey', TemplateId: templateId, ReplaceVariables: true }));
  });
  it('blocks malformed JSON Pointer before sending', async () => {
    input('target-label').value = '坏字段'; input('target-path').value = 'C:\\fake\\config.jsonc'; get<HTMLSelectElement>('target-key').value = keyId; input('target-pointer').value = '/bad~2escape';
    submit('target-form'); await ready(); expect(api.saveTarget).not.toHaveBeenCalled(); expect(get('notice').textContent).toContain('JSON Pointer');
  });
});

describe('preview, confirmation and interruptions', () => {
  it('previews only selected targets and masks even unexpected backend values', async () => {
    expect(get<HTMLButtonElement>('preview-selected').disabled).toBe(true); await makePreview();
    expect(api.preview).toHaveBeenCalledWith([targetId]); expect(root.textContent).not.toContain('FAKE_UNEXPECTED_BACKEND_PLAINTEXT');
    expect(get('preview-files').textContent).toContain(`Bearer ${MASK}`); expect(get<HTMLButtonElement>('apply-preview').disabled).toBe(true);
  });
  it('requires confirmation and consumes a preview once', async () => {
    await makePreview(); click('apply-preview'); expect(api.applyPreview).not.toHaveBeenCalled();
    input('confirm-preview').checked = true; change('confirm-preview'); click('apply-preview'); click('apply-preview'); await ready();
    expect(api.applyPreview).toHaveBeenCalledExactlyOnceWith(previewId, true); expect(get('preview-section').hidden).toBe(true); expect(get('results-section').hidden).toBe(false); expect(root.textContent).not.toContain('FAKE_RAW_MESSAGE');
  });
  it('cancels preview without writing', async () => {
    await makePreview(); input('confirm-preview').checked = true; change('confirm-preview'); click('cancel-preview'); await ready();
    expect(get('preview-section').hidden).toBe(true); expect(input('confirm-preview').checked).toBe(false); expect(api.applyPreview).not.toHaveBeenCalled();
  });
  it('invalidates a prior preview when selection changes', async () => {
    await makePreview(); input('confirm-preview').checked = true; change('confirm-preview'); click('select-all'); await ready();
    expect(get('preview-section').hidden).toBe(true); expect(input('confirm-preview').checked).toBe(false);
  });
  it('discards a delayed preview after the application is hidden', async () => {
    const pending = deferred<PreviewView>(); vi.mocked(api.preview).mockReturnValue(pending.promise);
    await selectTarget(); click('preview-selected'); await vi.waitFor(() => expect(api.preview).toHaveBeenCalledOnce());
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }); document.dispatchEvent(new Event('visibilitychange'));
    pending.resolve(preview()); await ready(); expect(get('preview-section').hidden).toBe(true); expect(api.applyPreview).not.toHaveBeenCalled();
  });
  it('requires a fresh checkbox after navigating between workspaces', async () => {
    await makePreview(); input('confirm-preview').checked = true; change('confirm-preview'); root.querySelector<HTMLButtonElement>('[data-panel="templates"]')!.click();
    expect(input('confirm-preview').checked).toBe(false); expect(get<HTMLButtonElement>('apply-preview').disabled).toBe(true);
  });
  it('does not offer apply when every file is unchanged or blocked', async () => {
    const view = preview(); view.files[0]!.changed = false; vi.mocked(api.preview).mockResolvedValue(view); await makePreview(); input('confirm-preview').checked = true; change('confirm-preview'); expect(get<HTMLButtonElement>('apply-preview').disabled).toBe(true);
  });
  it('shows uncertain outcomes and plaintext temporary paths without automatic retry', async () => {
    vi.mocked(api.applyPreview).mockResolvedValue([{ path: 'C:\\fake\\config.jsonc', outcome: 'outcomeUnknown', message: 'FAKE_RAW_EXCEPTION', code: null, backupPath: 'C:\\fake\\backup.atmbackup', temporaryPath: 'C:\\fake\\.atm-staging.tmp' }]);
    await makePreview(); input('confirm-preview').checked = true; change('confirm-preview'); click('apply-preview'); await ready();
    expect(get('results-list').textContent).toContain('结果未确认'); expect(get('results-list').textContent).toContain('明文暂存文件未能清理'); expect(root.textContent).not.toContain('FAKE_RAW_EXCEPTION'); expect(api.applyPreview).toHaveBeenCalledOnce();
  });
  it('clears the local plan on apply failure and never replays a write', async () => {
    vi.mocked(api.applyPreview).mockRejectedValue({ code: 'FILE_CHANGED', message: 'FAKE_RAW_EXCEPTION' });
    await makePreview(); input('confirm-preview').checked = true; change('confirm-preview'); click('apply-preview'); await ready(); click('apply-preview');
    expect(get('preview-section').hidden).toBe(true); expect(api.applyPreview).toHaveBeenCalledOnce(); expect(root.textContent).not.toContain('FAKE_RAW_EXCEPTION');
  });
});

describe('template confirmation and rollback', () => {
  const infer = async () => { click('pick-template'); await ready(); click('infer-template'); await ready(); };
  it('requires explicit field selection and confirmation before saving a candidate', async () => {
    await infer(); expect(api.inferTemplate).toHaveBeenCalledWith('C:\\fake\\config.jsonc'); expect(get<HTMLButtonElement>('save-template').disabled).toBe(true);
    const check = root.querySelector<HTMLInputElement>('#candidate-fields input')!; expect(check.checked).toBe(false); check.checked = true; check.dispatchEvent(new Event('change'));
    input('confirm-template').checked = true; change('confirm-template'); submit('template-form'); await ready();
    expect(api.saveTemplate).toHaveBeenCalledWith(templateId, '合成候选模板', ['/apiKey'], expect.any(String)); expect(get('template-form').hidden).toBe(true);
  });
  it('resets confirmation when schema or field selections change', async () => {
    await infer(); input('confirm-template').checked = true; get('template-schema').dispatchEvent(new Event('input')); expect(input('confirm-template').checked).toBe(false);
    input('confirm-template').checked = true; root.querySelector<HTMLInputElement>('#candidate-fields input')!.dispatchEvent(new Event('change')); expect(input('confirm-template').checked).toBe(false);
  });
  it('rejects invalid custom schema without saving', async () => {
    await infer(); const check = root.querySelector<HTMLInputElement>('#candidate-fields input')!; check.checked = true; check.dispatchEvent(new Event('change'));
    get<HTMLTextAreaElement>('template-schema').value = 'not JSON'; input('confirm-template').checked = true; submit('template-form'); await ready();
    expect(api.saveTemplate).not.toHaveBeenCalled(); expect(get('notice').textContent).toContain('有效的 JSON');
  });
  it('discards a candidate on cancel without saving', async () => { await infer(); click('cancel-template'); expect(get('template-form').hidden).toBe(true); expect(get<HTMLTextAreaElement>('template-schema').value).toBe(''); expect(api.saveTemplate).not.toHaveBeenCalled(); });
  it('requires a rollback preview and a separate whole-file confirmation', async () => {
    root.querySelector<HTMLButtonElement>('[data-panel="backups"]')!.click(); await ready(); root.querySelector<HTMLButtonElement>('#backups-list button')!.click(); await ready();
    expect(api.previewRollback).toHaveBeenCalledWith('C:\\fake\\backups\\fake.atmbackup'); expect(get('confirm-preview-label').textContent).toContain('整个文件'); expect(api.applyPreview).not.toHaveBeenCalled();
    input('confirm-preview').checked = true; change('confirm-preview'); click('apply-preview'); await ready(); expect(api.applyPreview).toHaveBeenCalledWith(previewId, true);
  });
});



describe('skills confirmation interruptions', () => {
  it.each(['visibilitychange', 'pagehide'])('clears install and copy consent on %s', async event => {
    // TEST_ONLY inventory and picker fixtures; no filesystem or service access.
    vi.mocked(api.skillsInventory).mockResolvedValue({
      roots: [{ id: 'claude-code', label: 'Claude Code', path: '/TEST_ONLY/skills', exists: true,
        entries: [{ name: 'local-skill', kind: 'directory', displayName: null, description: null, linkTarget: null }] }],
      trash: [], managerHome: '/TEST_ONLY/manager',
    });
    vi.mocked(api.pickDirectory).mockResolvedValue('/TEST_ONLY/source/new-skill');
    root.querySelector<HTMLButtonElement>('[data-panel="skills"]')!.click();
    click('inventory-skills'); await ready();
    click('pick-skills-source'); await ready();
    [...get('skills-roots').querySelectorAll<HTMLButtonElement>('button')]
      .find(button => button.textContent === '复制到…')!.click();
    click('confirm-skills-install'); click('confirm-skills-copy');
    expect(get<HTMLButtonElement>('install-skill').disabled).toBe(false);
    expect(get<HTMLButtonElement>('copy-skill').disabled).toBe(false);
    if (event === 'visibilitychange') {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
      document.dispatchEvent(new Event(event));
    } else window.dispatchEvent(new Event(event));
    for (const action of ['install', 'copy']) {
      expect(input(`confirm-skills-${action}`).checked).toBe(false);
      expect(get<HTMLButtonElement>(`${action}-skill`).disabled).toBe(true);
      click(`${action}-skill`);
    }
    expect(api.skillsInstall).not.toHaveBeenCalled();
    expect(api.skillsCopy).not.toHaveBeenCalled();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
    click('confirm-skills-install'); click('confirm-skills-copy');
    expect(get<HTMLButtonElement>('install-skill').disabled).toBe(false);
    expect(get<HTMLButtonElement>('copy-skill').disabled).toBe(false);
  });
});


describe('configuration failure isolation', () => {
  it('keeps independent panels usable, clears stale state, and recovers on explicit refresh', async () => {
    vi.mocked(api.snapshot).mockRejectedValueOnce({ code: 'STORAGE_UNAVAILABLE', message: 'FAKE_PRIVATE_ERROR' });
    click('refresh'); await ready();
    expect(get('configuration-status').hidden).toBe(false);
    expect(root.textContent).not.toContain('FAKE_PRIVATE_ERROR');
    expect(get<HTMLButtonElement>('save-key').disabled).toBe(true);
    expect(get<HTMLButtonElement>('save-target').disabled).toBe(true);
    expect(get('keys-list').textContent).not.toContain('合成假密钥');
    for (const panel of ['harness', 'skills', 'usage']) {
      const nav = root.querySelector<HTMLButtonElement>(`[data-panel="${panel}"]`)!;
      expect(nav.disabled).toBe(false); nav.click();
      expect(get(`panel-${panel}`).hidden).toBe(false);
    }
    input('codex-cli').value = '/fake/codex'; input('codex-profile').value = '/fake/profile';
    input('codex-cli').dispatchEvent(new Event('input')); input('codex-profile').dispatchEvent(new Event('input'));
    click('connect-codex'); await ready();
    expect(api.configureCodexCli).toHaveBeenCalledOnce();
    vi.mocked(api.snapshot).mockResolvedValue(fixture());
    click('refresh'); await ready();
    expect(get('configuration-status').hidden).toBe(true);
    expect(get<HTMLButtonElement>('save-key').disabled).toBe(false);
  });
});
