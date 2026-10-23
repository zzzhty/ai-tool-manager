// TEST_ONLY mock IPC; no real harness directories or oh-my-harness are touched.
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { DesktopApp } from '../src/app';
import type { DesktopApi, SkillsInventoryView, SnapshotView } from '../src/types';
const data = (): SnapshotView => ({ keys: [], targets: [], templates: [], storageKind: 'linux_secret_service' });
const entry = (name: string, kind: SkillsInventoryView['roots'][number]['entries'][number]['kind'], extra: Partial<{ displayName: string; description: string; linkTarget: string }> = {}) =>
  ({ name, kind, displayName: extra.displayName ?? null, description: extra.description ?? null, linkTarget: extra.linkTarget ?? null });
const inventory = (): SkillsInventoryView => ({
  roots: [
    { id: 'claude-code', label: 'Claude Code', path: '/TEST_ONLY/home/.claude/skills', exists: true, entries: [
      entry('managed-skill', 'omh_managed', { linkTarget: '/TEST_ONLY/home/.oh-my-harness/repo/plugins/x' }),
      entry('local-skill', 'directory', { displayName: 'Local Skill', description: 'A TEST_ONLY local skill.' }),
      entry('projected-skill', 'lkm_projected', { linkTarget: '/TEST_ONLY/data/skills-sources/sources/projected-skill' }),
    ] },
    { id: 'zcode', label: 'Z Code', path: '/TEST_ONLY/home/.zcode/skills', exists: false, entries: [] },
  ],
  trash: [{ id: 'zcode/old-skill', rootId: 'zcode', name: 'old-skill', originPath: '/TEST_ONLY/home/.zcode/skills/old-skill' }],
  managerHome: '/TEST_ONLY/home/.oh-my-harness',
});
let root: HTMLElement, app: DesktopApp, api: DesktopApi;
const get = <T extends HTMLElement = HTMLElement>(id: string) => root.querySelector<T>('#' + id)!;
const click = (id: string) => get<HTMLButtonElement>(id).click();
const ready = () => vi.waitFor(() => expect(root.getAttribute('aria-busy')).toBe('false'));
const open = () => root.querySelector<HTMLButtonElement>('[data-panel="skills"]')!.click();
beforeEach(async () => {
  if (!HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function mockShowModal(this: HTMLDialogElement) { this.setAttribute('open', ''); };
  }
  if (!HTMLDialogElement.prototype.close) {
    HTMLDialogElement.prototype.close = function mockClose(this: HTMLDialogElement) { this.removeAttribute('open'); };
  }
  api = {
    snapshot: vi.fn().mockResolvedValue(data()), cancelPreview: vi.fn(), saveKey: vi.fn(), deleteKey: vi.fn(), saveTarget: vi.fn(), deleteTarget: vi.fn(),
    preview: vi.fn(), applyPreview: vi.fn(), listBackups: vi.fn(), previewRollback: vi.fn(), inferTemplate: vi.fn(), saveTemplate: vi.fn(), deleteTemplate: vi.fn(), pickFile: vi.fn(),
    initializeStorage: vi.fn(), configureCodexCli: vi.fn(), disconnectCodexCli: vi.fn(), queryCodexUsage: vi.fn(), queryGlmUsage: vi.fn(), omhDiagnose: vi.fn(), omhCapabilities: vi.fn(), omhExecute: vi.fn(), omhStatus: vi.fn(),
    skillsInventory: vi.fn().mockResolvedValue(inventory()), skillsInstall: vi.fn().mockResolvedValue('claude-code/new-skill'),
    skillsUninstall: vi.fn().mockResolvedValue('claude-code/local-skill'), skillsRestore: vi.fn().mockResolvedValue('zcode/old-skill'),
    skillsPurge: vi.fn().mockResolvedValue(undefined), skillsCopy: vi.fn().mockResolvedValue('copilot/local-skill'), pickDirectory: vi.fn().mockResolvedValue('/TEST_ONLY/sources/new-skill'),
  };
  root = document.createElement('div'); document.body.append(root); app = new DesktopApp(root, api); await app.start();
  open();
});
afterEach(() => { app.dispose(); root.remove(); vi.restoreAllMocks(); });

it('startup and navigation never inventory; results start unknown', () => {
  expect(api.skillsInventory).not.toHaveBeenCalled();
  expect(get('skills-roots').textContent).toContain('尚未盘点');
});

it('inventory renders roots, source badges, omh lock and descriptions', async () => {
  click('inventory-skills'); await ready();
  expect(api.skillsInventory).toHaveBeenCalledExactlyOnceWith();
  const output = get('skills-roots');
  expect(output.textContent).toContain('Claude Code · claude-code');
  expect(output.textContent).toContain('/TEST_ONLY/home/.claude/skills');
  expect(output.textContent).toContain('由 OMH 管理');
  expect(output.textContent).toContain('ATM 投影');
  expect(output.textContent).toContain('由 ATM 投影管理');
  expect(output.textContent).toContain('A TEST_ONLY local skill.');
  expect(output.textContent).toContain('Local Skill');
  expect(output.textContent).toContain('根不存在');
  // The managed link's target is shown on its own entry line only.
  expect(output.textContent).toContain('链接目标：/TEST_ONLY/home/.oh-my-harness/repo/plugins/x');
  // Trash section renders alongside.
  expect(get('skills-trash').textContent).toContain('old-skill');
});

it('install flows pick directory, default the name and pass confirmed=true once', async () => {
  click('inventory-skills'); await ready();
  expect(get<HTMLButtonElement>('install-skill').disabled).toBe(true);
  click('pick-skills-source'); await ready();
  expect(get<HTMLInputElement>('skills-source').value).toBe('/TEST_ONLY/sources/new-skill');
  expect(get<HTMLInputElement>('skills-name').value).toBe('new-skill');
  expect(get<HTMLButtonElement>('install-skill').disabled).toBe(true);
  get<HTMLInputElement>('confirm-skills-install').checked = true;
  get<HTMLInputElement>('confirm-skills-install').dispatchEvent(new Event('change'));
  click('install-skill'); await ready();
  expect(api.skillsInstall).toHaveBeenCalledExactlyOnceWith('/TEST_ONLY/sources/new-skill', 'claude-code', 'new-skill', true);
  expect(api.skillsInventory).toHaveBeenCalledTimes(2);
  expect(root.textContent).toContain('技能已安装到 claude-code');
});

it('uninstall asks, uninstalls once and never touches managed entries', async () => {
  click('inventory-skills'); await ready();
  const buttons = [...get('skills-roots').querySelectorAll<HTMLButtonElement>('button')];
  const managedUninstall = buttons.find(button => button.textContent === '卸载' && button.disabled);
  expect(managedUninstall).toBeUndefined(); // managed entries render no uninstall button at all
  const uninstallButton = buttons.find(button => button.textContent === '卸载' && !button.disabled)!;
  uninstallButton.click();
  const dialog = get<HTMLDialogElement>('confirm-dialog');
  expect(dialog.textContent).toContain('移动到保管区');
  get('dialog-confirm').click(); await ready();
  expect(api.skillsUninstall).toHaveBeenCalledExactlyOnceWith('claude-code', 'local-skill', true);
  expect(api.skillsInventory).toHaveBeenCalledTimes(2);
});

it('copy requires choosing a source, target and confirmation', async () => {
  click('inventory-skills'); await ready();
  expect(get<HTMLButtonElement>('copy-skill').disabled).toBe(true);
  const copyButtons = [...get('skills-roots').querySelectorAll<HTMLButtonElement>('button')].filter(button => button.textContent === '复制到…');
  expect(copyButtons.length).toBe(3);
  copyButtons[1]!.click(); // the local directory entry, not the managed link or projection
  expect(get('copy-source-label').textContent).toContain('claude-code / local-skill');
  expect(get<HTMLButtonElement>('copy-skill').disabled).toBe(true);
  const targetSelect = get<HTMLSelectElement>('copy-target-root');
  targetSelect.value = 'zcode'; targetSelect.dispatchEvent(new Event('change'));
  get<HTMLInputElement>('confirm-skills-copy').checked = true;
  get<HTMLInputElement>('confirm-skills-copy').dispatchEvent(new Event('change'));
  click('copy-skill'); await ready();
  expect(api.skillsCopy).toHaveBeenCalledExactlyOnceWith('claude-code', 'local-skill', 'zcode', true);
});

it('trash restore and purge both pass through explicit confirmation', async () => {
  click('inventory-skills'); await ready();
  const restoreButton = [...get('skills-trash').querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '恢复到原根')!;
  restoreButton.click();
  get('dialog-confirm').click(); await ready();
  expect(api.skillsRestore).toHaveBeenCalledExactlyOnceWith('zcode/old-skill', true);
  const purgeButton = [...get('skills-trash').querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '彻底删除')!;
  purgeButton.click();
  expect(get('confirm-dialog').textContent).toContain('不可恢复');
  get('dialog-confirm').click(); await ready();
  expect(api.skillsPurge).toHaveBeenCalledExactlyOnceWith('zcode/old-skill', true);
});

it('demo refusals surface the safe vocabulary without paths', async () => {
  click('inventory-skills'); await ready();
  vi.mocked(api.skillsInstall).mockRejectedValue({ code: 'DEMO_READONLY' });
  click('pick-skills-source'); await ready();
  get<HTMLInputElement>('confirm-skills-install').checked = true;
  get<HTMLInputElement>('confirm-skills-install').dispatchEvent(new Event('change'));
  click('install-skill'); await ready();
  expect(root.textContent).toContain('演示模式不修改任何本机目录');
});

const confirm = (id: string) => get<HTMLInputElement>(id).click();
const change = (id: string, value: string, event: string | null = 'change') => {
  get<HTMLInputElement | HTMLSelectElement>(id).value = value;
  if (event) get(id).dispatchEvent(new Event(event));
};
const chooseCopy = (index: number) => [...get('skills-roots').querySelectorAll<HTMLButtonElement>('button')]
  .filter(button => button.textContent === '复制到…')[index]!.click();

it.each([
  ['skills-name', 'renamed-skill', 'input'],
  ['skills-name', 'renamed-skill', 'change'],
  ['skills-source', '/TEST_ONLY/sources/another-skill', 'input'],
  ['skills-target-root', 'zcode', 'change'],
  // Submission must reject stale consent even when a value setter emits no event.
  ['skills-name', 'renamed-skill', null],
  ['skills-source', '/TEST_ONLY/sources/another-skill', null],
  ['skills-target-root', 'zcode', null],
])('install requires fresh confirmation after %s changes (%s, %s)', async (id, value, event) => {
  click('inventory-skills'); await ready();
  click('pick-skills-source'); await ready();
  confirm('confirm-skills-install');
  expect(get<HTMLButtonElement>('install-skill').disabled).toBe(false);
  change(id!, value!, event);
  click('install-skill'); await ready();
  expect(api.skillsInstall).not.toHaveBeenCalled();
  expect(get<HTMLInputElement>('confirm-skills-install').checked).toBe(false);
  expect(get<HTMLButtonElement>('install-skill').disabled).toBe(true);
  confirm('confirm-skills-install');
  const source = get<HTMLInputElement>('skills-source').value;
  const name = get<HTMLInputElement>('skills-name').value;
  const target = get<HTMLSelectElement>('skills-target-root').value;
  click('install-skill'); await ready();
  expect(api.skillsInstall).toHaveBeenCalledExactlyOnceWith(source, target, name, true);
});

it('directory picker invalidates install consent before its new source can be installed', async () => {
  click('inventory-skills'); await ready();
  click('pick-skills-source'); await ready();
  confirm('confirm-skills-install');
  vi.mocked(api.pickDirectory).mockResolvedValue('/TEST_ONLY/sources/changed-source');
  click('pick-skills-source'); await ready();
  expect(get<HTMLInputElement>('confirm-skills-install').checked).toBe(false);
  expect(get<HTMLButtonElement>('install-skill').disabled).toBe(true);
  click('install-skill'); await ready();
  expect(api.skillsInstall).not.toHaveBeenCalled();
  confirm('confirm-skills-install');
  click('install-skill'); await ready();
  expect(api.skillsInstall).toHaveBeenCalledExactlyOnceWith('/TEST_ONLY/sources/changed-source', 'claude-code', 'new-skill', true);
});

it.each(['change', null])('copy destination changes require fresh confirmation (%s)', async event => {
  click('inventory-skills'); await ready();
  chooseCopy(1);
  confirm('confirm-skills-copy');
  expect(get<HTMLButtonElement>('copy-skill').disabled).toBe(false);
  change('copy-target-root', 'zcode', event);
  click('copy-skill'); await ready();
  expect(api.skillsCopy).not.toHaveBeenCalled();
  expect(get<HTMLInputElement>('confirm-skills-copy').checked).toBe(false);
  expect(get<HTMLButtonElement>('copy-skill').disabled).toBe(true);
  confirm('confirm-skills-copy');
  click('copy-skill'); await ready();
  expect(api.skillsCopy).toHaveBeenCalledExactlyOnceWith('claude-code', 'local-skill', 'zcode', true);
});

it.each(['name', 'root'])('copy source %s changes require fresh confirmation', async field => {
  const view = inventory();
  view.roots[1]!.exists = true;
  view.roots[1]!.entries = [entry('local-skill', 'directory')];
  vi.mocked(api.skillsInventory).mockResolvedValue(view);
  click('inventory-skills'); await ready();
  chooseCopy(1);
  confirm('confirm-skills-copy');
  chooseCopy(field === 'name' ? 2 : 3);
  expect(get<HTMLInputElement>('confirm-skills-copy').checked).toBe(false);
  expect(get<HTMLButtonElement>('copy-skill').disabled).toBe(true);
  click('copy-skill'); await ready();
  expect(api.skillsCopy).not.toHaveBeenCalled();
  confirm('confirm-skills-copy');
  click('copy-skill'); await ready();
  expect(api.skillsCopy).toHaveBeenCalledExactlyOnceWith(field === 'name' ? 'claude-code' : 'zcode',
    field === 'name' ? 'projected-skill' : 'local-skill', 'claude-code', true);
});

it('inventory refresh clears both confirmations even if root IDs are unchanged', async () => {
  click('inventory-skills'); await ready();
  click('pick-skills-source'); await ready();
  chooseCopy(1);
  confirm('confirm-skills-install'); confirm('confirm-skills-copy');
  const changed = inventory();
  changed.roots[0]!.path = '/TEST_ONLY/another-home/skills';
  vi.mocked(api.skillsInventory).mockResolvedValue(changed);
  click('inventory-skills'); await ready();
  for (const action of ['install', 'copy']) {
    expect(get<HTMLInputElement>(`confirm-skills-${action}`).checked).toBe(false);
    expect(get<HTMLButtonElement>(`${action}-skill`).disabled).toBe(true);
    click(`${action}-skill`);
  }
  expect(api.skillsInstall).not.toHaveBeenCalled(); expect(api.skillsCopy).not.toHaveBeenCalled();
});

it('destructive dialog stays bound to its original target when copy inputs change', async () => {
  click('inventory-skills'); await ready();
  [...get('skills-roots').querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '卸载')!.click();
  chooseCopy(2);
  change('copy-target-root', 'zcode');
  get('dialog-confirm').click(); await ready();
  expect(api.skillsUninstall).toHaveBeenCalledExactlyOnceWith('claude-code', 'local-skill', true);
  expect(api.skillsCopy).not.toHaveBeenCalled();
});
