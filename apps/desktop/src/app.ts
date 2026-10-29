import { layout } from './layout';
import { UsagePanel } from './usage';
import { HarnessPanel } from './harness';
import { SkillsPanel } from './skills';
import { MASK, NIL_UUID, displayDate, outcomeLabels, pointerIsValid, safeError, schemaText } from './safety';
import type { BackupView, DesktopApi, FileResult, PreviewView, SnapshotView, TargetMapping, TemplateCandidate } from './types';

type Panel = 'keys' | 'targets' | 'templates' | 'backups' | 'usage' | 'harness' | 'skills';
const emptySnapshot = (): SnapshotView => ({ keys: [], targets: [], templates: [] });
const element = <K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, className?: string): HTMLElementTagNameMap[K] => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};

const option = (text: string, value: string): HTMLOptionElement => {
  const node = element('option', text); node.value = value; return node;
};

export class DesktopApp {
  private readonly usage: UsagePanel;
  private readonly harness: HarnessPanel;
  private readonly skills: SkillsPanel;
  private data: SnapshotView = emptySnapshot();
  private selected = new Set<string>();
  private currentPreview: PreviewView | null = null;
  private previewKind: 'update' | 'rollback' = 'update';
  private candidate: TemplateCandidate | null = null;
  private keyId: string | null = null;
  private targetId: string | null = null;
  private busy = false;
  private applying = false;
  private loaded = false;
  private revision = 0;
  private pendingDelete: (() => Promise<void>) | null = null;
  private disposed = false;
  private readonly listeners: Array<() => void> = [];

  constructor(private readonly root: HTMLElement, private readonly api: DesktopApi) {
    root.innerHTML = layout;
    this.usage = new UsagePanel(root, api, (message, action) => this.run(message, action), message => this.notice(message));
    this.harness = new HarnessPanel(root, api, (message, action) => this.run(message, action), message => this.notice(message),
      (description, action) => this.askDelete(description, action));
    this.skills = new SkillsPanel(root, api, (message, action) => this.run(message, action), message => this.notice(message),
      (description, action) => this.askDelete(description, action));
    this.bind();
    this.renderData();
    this.refreshControls();
  }

  private get<T extends HTMLElement = HTMLElement>(id: string): T {
    const node = this.root.querySelector<T>(`#${id}`);
    if (!node) throw new Error('Missing static application element');
    return node;
  }
  private input(id: string): HTMLInputElement { return this.get<HTMLInputElement>(id); }
  private select(id: string): HTMLSelectElement { return this.get<HTMLSelectElement>(id); }
  private listen(target: EventTarget, name: string, handler: EventListener): void {
    target.addEventListener(name, handler);
    this.listeners.push(() => target.removeEventListener(name, handler));
  }
  private on(id: string, event: string, handler: () => void): void { this.listen(this.get(id), event, handler); }
  private notice(text: string, tone: 'info' | 'success' | 'error' = 'info'): void {
    const node = this.get('notice'); node.textContent = text; node.className = `notice ${tone}`;
    node.setAttribute('role', tone === 'error' ? 'alert' : 'status');
  }

  /** One gate for every IPC operation; repeated clicks never queue writes. */
  private async run(message: string, action: () => Promise<void>, applying = false): Promise<void> {
    if (this.busy || this.disposed) return;
    this.busy = true; this.applying = applying; this.notice(message); this.refreshControls();
    try { await action(); }
    catch (error: unknown) { if (!this.disposed) this.notice(safeError(error), 'error'); }
    finally { this.busy = false; this.applying = false; if (!this.disposed) this.refreshControls(); }
  }

  async start(): Promise<void> {
    await this.run('正在连接本地密钥库…', async () => {
      // A restarted webview cannot reuse an earlier confirmation or plan.
      await this.api.cancelPreview(); await this.loadSnapshot();
      this.notice('已连接本地密钥库。选择一个工作区开始。', 'success');
    });
  }
  dispose(): void {
    this.disposed = true; this.usage.dispose(); this.harness.dispose(); this.skills.dispose(); this.clearSecret(); this.revision++;
    for (const remove of this.listeners) remove();
    this.listeners.length = 0;
  }

  private async loadSnapshot(): Promise<void> {
    try {
      this.data = await this.api.snapshot(); this.data.templates ??= []; this.loaded = true;
      this.get('configuration-status').hidden = true;
    } catch (error: unknown) {
      this.loaded = false; this.data = emptySnapshot(); this.selected.clear(); this.clearSecret();
      this.invalidateLocal(); this.resetCandidate();
      const status = this.get('configuration-status'); status.hidden = false;
      status.textContent = `配置服务暂不可用：${safeError(error)} 本地技能、内置技能分发及 Codex 查询仍可使用；恢复后请刷新状态。`;
      this.usage.setSnapshot(this.data); this.renderData();
      throw error;
    }
    this.selected = new Set([...this.selected].filter(id => this.data.targets.some(target => target.Id === id)));
    this.usage.setSnapshot(this.data); this.renderData();
  }
  private clearSecret(): void { this.input('key-secret').value = ''; }
  private invalidateLocal(): void {
    this.revision++; this.currentPreview = null; this.input('confirm-preview').checked = false;
    this.get('preview-section').hidden = true;
  }
  private async invalidate(): Promise<void> { this.invalidateLocal(); await this.api.cancelPreview(); }
  private interrupt(): void {
    if (this.disposed || this.applying) return;
    // A page hidden while an operation is in flight is usually the app's own
    // system dialog (for example the keyring prompt during a storage
    // connect), not the user leaving: keep the user's confirmations then.
    // Leaving while idle still invalidates every confirmation.
    if (!this.busy) { this.clearSecret(); this.usage.clearConfirmations(); this.skills.clearConfirmations(); }
    this.invalidateLocal();
    // No automatic mutation retry. A delayed preview response is also discarded.
    void this.api.cancelPreview().catch(() => undefined);
    this.refreshControls();
  }
  private switchPanel(panel: Panel): void {
    if (this.busy) return;
    this.clearSecret(); this.usage.clearConfirmations(); this.skills.clearConfirmations(); this.input('confirm-preview').checked = false; this.refreshControls();
    for (const button of this.root.querySelectorAll<HTMLButtonElement>('[data-panel]')) {
      if (button.dataset.panel === panel) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    }
    for (const name of ['keys', 'targets', 'templates', 'backups', 'usage', 'harness', 'skills']) this.get(`panel-${name}`).hidden = name !== panel;
    if (panel === 'backups' && this.loaded) void this.refreshBackups();
  }

  private bind(): void {
    for (const button of this.root.querySelectorAll<HTMLButtonElement>('[data-panel]')) {
      this.listen(button, 'click', () => this.switchPanel(button.dataset.panel as Panel));
    }
    this.listen(document, 'visibilitychange', () => { if (document.visibilityState === 'hidden') this.interrupt(); });
    this.listen(window, 'blur', () => this.clearSecret());
    this.listen(window, 'pagehide', () => this.interrupt());
    this.listen(window, 'beforeunload', (event: Event) => {
      this.clearSecret();
      if (this.applying) { event.preventDefault(); (event as BeforeUnloadEvent).returnValue = ''; }
      else this.interrupt();
    });
    this.on('refresh', 'click', () => void this.run('正在刷新…', async () => {
      this.clearSecret(); await this.invalidate(); await this.loadSnapshot(); this.notice('状态已刷新。旧预览已取消。', 'success');
    }));
    this.listen(this.get('key-form'), 'submit', event => { event.preventDefault(); void this.saveKey(); });
    this.on('reset-key', 'click', () => { this.resetKey(); this.notice('密钥输入已清空。'); });
    this.listen(this.get('target-form'), 'submit', event => { event.preventDefault(); void this.saveTarget(); });
    this.on('reset-target', 'click', () => this.resetTarget());
    this.on('pick-target', 'click', () => void this.pickFile('target-path'));
    this.on('target-template', 'change', () => { this.renderPointerOptions(); this.refreshControls(); });
    this.on('select-all', 'click', () => void this.run('正在更新选择…', async () => {
      const all = this.data.targets.length > 0 && this.selected.size === this.data.targets.length;
      this.selected = new Set(all ? [] : this.data.targets.map(target => target.Id));
      await this.invalidate(); this.renderTargets(); this.notice(all ? '已取消全部选择。' : '已选中全部目标，请生成新的遮罩预览。');
    }));
    this.on('preview-selected', 'click', () => void this.createPreview());
    this.on('confirm-preview', 'change', () => this.refreshControls());
    this.on('apply-preview', 'click', () => void this.applyPreview());
    this.on('cancel-preview', 'click', () => void this.run('正在取消预览…', async () => {
      await this.invalidate(); this.notice('预览已取消，没有应用本次预览。');
    }));
    this.on('refresh-backups', 'click', () => void this.refreshBackups());
    this.on('pick-template', 'click', () => void this.pickFile('template-source'));
    this.on('infer-template', 'click', () => void this.inferTemplate());
    this.on('confirm-template', 'change', () => this.refreshControls());
    this.on('template-schema', 'input', () => { this.input('confirm-template').checked = false; this.refreshControls(); });
    this.on('template-name', 'input', () => { this.input('confirm-template').checked = false; this.refreshControls(); });
    this.listen(this.get('template-form'), 'submit', event => { event.preventDefault(); void this.saveTemplate(); });
    this.on('cancel-template', 'click', () => { this.resetCandidate(); this.notice('模板候选已丢弃。'); });
    this.on('dialog-cancel', 'click', () => this.closeDelete());
    this.on('dialog-confirm', 'click', () => {
      const action = this.pendingDelete; this.closeDelete();
      if (action) void this.run('正在删除…', action);
    });
    this.listen(this.get('confirm-dialog'), 'cancel', () => { this.pendingDelete = null; });
    this.listen(this.get('confirm-dialog'), 'close', () => { this.pendingDelete = null; });
  }

  private refreshControls(): void {
    this.root.setAttribute('aria-busy', String(this.busy));
    for (const control of this.root.querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLSelectElement | HTMLTextAreaElement>('input,button,select,textarea')) control.disabled = this.busy || !this.loaded;
    // These domains do not depend on the encrypted configuration service.
    for (const control of this.root.querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLSelectElement>(
      '[data-panel], #panel-skills input, #panel-skills button, #panel-skills select, #panel-harness input, #panel-harness button, #panel-harness select, #panel-usage input, #panel-usage button, #panel-usage select, #dialog-confirm, #dialog-cancel, #refresh',
    )) control.disabled = this.busy;
    const disable = (id: string, condition: boolean) => { this.get<HTMLButtonElement>(id).disabled = this.busy || !this.loaded || condition; };
    disable('preview-selected', this.selected.size === 0);
    disable('select-all', this.data.targets.length === 0);
    disable('save-target', this.data.keys.length === 0);
    disable('apply-preview', !this.currentPreview || !this.input('confirm-preview').checked || !this.currentPreview.files.some(file => file.changed && !file.error));
    disable('infer-template', !this.input('template-source').value);
    disable('save-template', !this.candidate || !this.input('confirm-template').checked || !this.selectedCandidatePointers().length);
    this.usage.refreshControls(this.busy, true);
    this.harness.refreshControls(this.busy, true);
    this.skills.refreshControls(this.busy, true);
    const selection = this.get('selection-count'); selection.textContent = `已选择 ${this.selected.size} 项`;
    this.get('select-all').textContent = this.selected.size === this.data.targets.length && this.selected.size > 0 ? '取消全选' : '全选';
  }

  private renderData(): void {
    this.get('key-count').textContent = String(this.data.keys.length);
    this.get('target-count').textContent = String(this.data.targets.length);
    this.get('template-count').textContent = String(this.data.templates.length);
    this.renderKeys(); this.renderTargets(); this.renderTemplates(); this.renderSelects(); this.refreshControls();
  }
  private empty(container: HTMLElement, text: string): void { container.replaceChildren(element('p', text, 'empty-state')); }
  private button(text: string, action: () => void, className = 'text-button'): HTMLButtonElement {
    const button = element('button', text, className); button.type = 'button'; button.disabled = this.busy;
    button.addEventListener('click', action); return button;
  }
  private actionRow(...buttons: HTMLButtonElement[]): HTMLElement { const row = element('div', undefined, 'item-actions'); row.append(...buttons); return row; }
  private detail(label: string, value: string): HTMLElement {
    const row = element('p', undefined, 'detail'); row.append(element('span', label, 'detail-label'), element('span', value, 'breakable')); return row;
  }

  private renderKeys(): void {
    const list = this.get('keys-list'); list.replaceChildren();
    if (!this.data.keys.length) return this.empty(list, '还没有密钥。添加一个命名密钥，再把它绑定到配置字段。');
    for (const key of this.data.keys) {
      const item = element('article', undefined, 'item');
      item.append(element('h4', key.name), element('p', MASK, 'secret-mask'), element('p', `更新于 ${displayDate(key.updatedUtc)}`, 'help'));
      item.append(this.actionRow(this.button('编辑', () => {
        this.keyId = key.id; this.clearSecret(); this.input('key-name').value = key.name;
        this.get('key-form-heading').textContent = '编辑密钥'; this.get('key-secret-optional').textContent = '（留空保留原值）';
        this.input('key-secret').required = false; this.input('key-name').focus();
      }), this.button('删除', () => this.askDelete(`删除密钥“${key.name}”？若仍有目标引用它，删除会被阻止。已写入的配置不会随之删除。`, async () => {
        await this.invalidate(); await this.api.deleteKey(key.id); if (this.keyId === key.id) this.resetKey(); await this.loadSnapshot(); this.notice('密钥已删除。', 'success');
      }), 'text-button danger-text')));
      list.append(item);
    }
  }
  private resetKey(): void {
    this.keyId = null; this.get<HTMLFormElement>('key-form').reset(); this.clearSecret();
    this.get('key-form-heading').textContent = '添加密钥'; this.get('key-secret-optional').textContent = ''; this.input('key-secret').required = true;
  }
  private async saveKey(): Promise<void> {
    if (this.busy || !this.get<HTMLFormElement>('key-form').reportValidity()) return;
    const id = this.keyId; const name = this.input('key-name').value;
    // Intentionally not trimmed: silently changing a secret would be dangerous.
    let secret = this.input('key-secret').value; this.clearSecret();
    await this.run('正在保存密钥…', async () => {
      await this.invalidate();
      try { await this.api.saveKey(id, name, secret); } finally { secret = ''; }
      this.resetKey(); await this.loadSnapshot(); this.notice('密钥已保存，输入已清空。', 'success');
    });
    secret = '';
  }

  private renderSelects(): void {
    const keys = this.select('target-key'); const keyValue = keys.value;
    keys.replaceChildren(option('请选择密钥', '')); for (const key of this.data.keys) keys.add(option(key.name, key.id)); keys.value = keyValue;
    const templates = this.select('target-template'); const templateValue = templates.value;
    templates.replaceChildren(option('手动填写精确字段', '')); for (const template of this.data.templates) templates.add(option(template.name, template.id)); templates.value = templateValue;
    this.renderPointerOptions();
  }
  private renderPointerOptions(pointer?: string): void {
    const template = this.data.templates.find(item => item.id === this.select('target-template').value);
    const select = this.select('template-pointer'); const old = pointer ?? select.value;
    this.input('target-pointer').hidden = !!template; this.input('target-pointer').required = !template; select.hidden = !template;
    select.replaceChildren();
    if (template) {
      for (const field of template.fields) select.add(option(`${field.pointer || '（根字符串）'}${field.label ? ` · ${field.label}` : ''}`, field.pointer));
      // Do not depend on a webview's implicit first-option selection.
      select.value = template.fields.some(field => field.pointer === old) ? old : template.fields[0]?.pointer ?? '';
    }
  }
  private renderTargets(): void {
    const list = this.get('targets-list'); list.replaceChildren();
    if (!this.data.targets.length) return this.empty(list, '还没有目标。手动选择一个已知配置文件，注册精确字段。');
    for (const target of this.data.targets) {
      const item = element('article', undefined, 'item'); const label = element('label', undefined, 'check-line item-title');
      const check = element('input'); check.type = 'checkbox'; check.checked = this.selected.has(target.Id); check.setAttribute('aria-label', `选择目标 ${target.Label}`);
      check.addEventListener('change', () => void this.run('正在更新选择…', async () => {
        if (check.checked) this.selected.add(target.Id); else this.selected.delete(target.Id);
        await this.invalidate(); this.notice('选择已更新，请重新生成预览。');
      }));
      label.append(check, element('strong', target.Label)); item.append(label);
      item.append(this.detail('文件', target.FilePath), this.detail('字段', target.Pointer || '（根字符串）'), this.detail('密钥', this.data.keys.find(key => key.id === target.KeyId)?.name ?? '（密钥不存在）'));
      const badges = element('div', undefined, 'badges');
      badges.append(element('span', target.ReplaceVariables ? '允许替换变量' : '保护变量', target.ReplaceVariables ? 'pill caution' : 'pill'));
      if (target.BearerPrefix) badges.append(element('span', 'Bearer', 'pill'));
      if (target.TemplateId) badges.append(element('span', this.data.templates.find(template => template.id === target.TemplateId)?.name ?? '模板不可用', 'pill'));
      item.append(badges, this.actionRow(this.button('编辑', () => this.editTarget(target)), this.button('删除', () => this.askDelete(`删除目标“${target.Label}”的映射？配置文件及其中现有值不会因此删除。`, async () => {
        await this.invalidate(); await this.api.deleteTarget(target.Id); this.selected.delete(target.Id); if (this.targetId === target.Id) this.resetTarget(); await this.loadSnapshot(); this.notice('目标映射已删除。', 'success');
      }), 'text-button danger-text')));
      list.append(item);
    }
  }
  private editTarget(target: TargetMapping): void {
    this.targetId = target.Id; this.input('target-label').value = target.Label; this.input('target-path').value = target.FilePath;
    this.input('target-pointer').value = target.Pointer; this.select('target-key').value = target.KeyId;
    this.select('target-template').value = target.TemplateId ?? ''; this.renderPointerOptions(target.Pointer);
    this.input('target-bearer').checked = target.BearerPrefix; this.input('protect-variables').checked = !target.ReplaceVariables;
    this.get('target-form-heading').textContent = '编辑目标映射'; this.input('target-label').focus();
  }
  private resetTarget(): void {
    this.targetId = null; this.get<HTMLFormElement>('target-form').reset(); this.select('target-template').value = '';
    this.input('protect-variables').checked = true; this.renderPointerOptions(); this.get('target-form-heading').textContent = '添加目标映射';
  }
  private async pickFile(destination: 'target-path' | 'template-source'): Promise<void> {
    await this.run('等待选择本机配置文件…', async () => {
      this.clearSecret(); const path = await this.api.pickFile();
      if (path === null) { this.notice('已取消文件选择。'); return; }
      this.input(destination).value = path;
      if (destination === 'template-source') this.resetCandidate();
      this.notice('已选择文件。尚未修改配置。');
    });
  }
  private async saveTarget(): Promise<void> {
    if (this.busy || !this.get<HTMLFormElement>('target-form').reportValidity()) return;
    const templateId = this.select('target-template').value;
    const pointer = templateId ? this.select('template-pointer').value : this.input('target-pointer').value;
    if (!pointerIsValid(pointer)) { this.notice('JSON Pointer 格式无效；/ 写成 ~1，~ 写成 ~0。', 'error'); return; }
    if (templateId && !this.data.templates.find(template => template.id === templateId)?.fields.some(field => field.pointer === pointer)) {
      this.notice('请选择模板允许绑定的字段。', 'error'); return;
    }
    const target: TargetMapping = {
      Id: this.targetId ?? NIL_UUID, Label: this.input('target-label').value, FilePath: this.input('target-path').value,
      Pointer: pointer, KeyId: this.select('target-key').value, BearerPrefix: this.input('target-bearer').checked,
      ReplaceVariables: !this.input('protect-variables').checked, TemplateId: templateId || null,
    };
    await this.run('正在保存目标映射…', async () => {
      await this.invalidate(); await this.api.saveTarget(target); this.resetTarget(); await this.loadSnapshot(); this.notice('映射已保存。勾选目标后生成遮罩预览。', 'success');
    });
  }

  private async createPreview(): Promise<void> {
    if (!this.selected.size) return;
    await this.run('正在检查所选文件并生成遮罩预览…', async () => {
      await this.invalidate(); const revision = this.revision;
      const view = await this.api.preview([...this.selected]);
      if (this.disposed || revision !== this.revision) { await this.api.cancelPreview(); this.notice('预览因中断已丢弃，请重新生成。'); return; }
      this.previewKind = 'update'; this.showPreview(view);
      this.notice('遮罩预览已生成。请逐文件检查，再明确确认。', 'success');
    });
  }
  private showPreview(view: PreviewView): void {
    this.currentPreview = view; this.input('confirm-preview').checked = false;
    this.get('results-section').hidden = true;
    const rollback = this.previewKind === 'rollback';
    this.get('preview-heading').textContent = rollback ? '整文件回滚预览' : '遮罩预览';
    this.get('confirm-preview-label').textContent = rollback ? '我已检查文件与备份，确认恢复整个文件的原始字节。' : '我已检查本次文件和字段，确认将密钥写入所选配置。';
    this.get('apply-preview').textContent = rollback ? '确认并回滚整个文件' : '应用本次预览';
    const list = this.get('preview-files'); list.replaceChildren();
    if (!view.files.length) this.empty(list, '没有可预览的文件。');
    for (const file of view.files) {
      const item = element('article', undefined, 'item preview-file');
      item.append(element('h3', file.path, 'breakable'));
      if (file.error) item.append(element('p', safeError(file.error), 'error-text'));
      else {
        item.append(element('p', `${file.encoding} · ${file.changed ? '将写入（需确认）' : '无需写入'}`, 'help'));
        for (const field of file.fields) {
          const row = element('div', undefined, 'field-preview');
          row.append(element('strong', field.label), element('p', field.pointer || '（根字符串）', 'monospace breakable'));
          // Only a finite safe vocabulary is allowed for value displays.
          const before = field.before === '（空值）' ? '（空值）' : field.before === '变量引用（已遮罩）' ? '变量引用（已遮罩）' : MASK;
          const after = field.after === '保留原引用' ? '保留原引用' : field.after.startsWith('Bearer ') ? `Bearer ${MASK}` : MASK;
          row.append(element('p', `${before} → ${after}`, 'masked-change'));
          const allowedStatuses = ['已保留变量', '保留变量引用', '变量已保留', '替换变量引用', '将替换', '值相同', '无需修改', '将明确替换变量', '准备写入', '内容匹配，可回滚', '已是原文，无需回滚'];
          row.append(element('p', allowedStatuses.includes(field.status) ? field.status : '字段已检查，内容已遮罩', 'help'));
          item.append(row);
        }
      }
      list.append(item);
    }
    const section = this.get('preview-section'); section.hidden = false; section.focus();
  }
  private async applyPreview(): Promise<void> {
    const preview = this.currentPreview;
    if (!preview || !this.input('confirm-preview').checked || !preview.files.some(file => file.changed && !file.error)) return;
    const rollback = this.previewKind === 'rollback';
    await this.run(rollback ? '正在回滚。请勿关闭窗口；开始后不能取消。' : '正在应用。请勿关闭窗口；开始后不能取消。', async () => {
      this.clearSecret(); this.invalidateLocal();
      const results = await this.api.applyPreview(preview.id, true);
      this.renderResults(results);
      const attention = results.some(result => !['applied', 'skipped'].includes(result.outcome) || !!result.temporaryPath);
      this.notice(attention ? '操作已结束，部分文件需要核查。请查看逐文件结果；不会自动重试或撤销。' : '操作已结束，请查看逐文件结果。', attention ? 'error' : 'success');
    }, true);
  }
  private renderResults(results: FileResult[]): void {
    const list = this.get('results-list'); list.replaceChildren();
    if (!results.length) this.empty(list, '没有返回文件结果。请检查状态后再决定下一步。');
    for (const result of results) {
      const item = element('article', undefined, 'item');
      item.append(element('h3', result.path, 'breakable'), element('strong', outcomeLabels[result.outcome] ?? '结果未确认，需核查', ['applied', 'skipped'].includes(result.outcome) ? 'success-text' : 'error-text'));
      const explanations: Record<string, string> = {
        applied: '文件已原子替换并验证。加密备份已保存。', skipped: '值相同或已保留变量，无需写入。',
        conflict: '文件自预览后变化，已拒绝写入。重新检查后生成新预览。',
        failed: result.code ? safeError({ code: result.code }) : '本文件操作未完成，请检查状态后再决定下一步。',
        appliedUnverified: '写入已发生，但最终验证未完成或内容随后变化。请检查目标文件；备份已保留。',
        outcomeUnknown: '无法确认最终文件状态。不会自动覆盖或回滚，请先检查目标文件。',
      };
      item.append(element('p', explanations[result.outcome] ?? '无法确认结果，请先检查文件。', 'help'));
      if (result.backupPath) item.append(this.detail('加密备份', result.backupPath));
      if (result.temporaryPath) {
        item.append(element('p', '明文暂存文件未能清理。关闭文件占用后，检查并妥善处理以下路径。', 'error-text'), this.detail('暂存文件', result.temporaryPath));
      }
      list.append(item);
    }
    const section = this.get('results-section'); section.hidden = false; section.focus();
  }

  private async refreshBackups(): Promise<void> {
    await this.run('正在读取本管理器的加密备份…', async () => {
      this.renderBackups(await this.api.listBackups()); this.notice('备份列表已刷新。检查回滚后仍需再次确认。', 'success');
    });
  }
  private renderBackups(backups: BackupView[]): void {
    const list = this.get('backups-list'); list.replaceChildren();
    if (!backups.length) return this.empty(list, '还没有加密备份。每次实际写入前会先保存完整备份。');
    for (const backup of backups) {
      const item = element('article', undefined, 'card item');
      item.append(element('h3', backup.filePath, 'breakable'), element('p', `备份时间：${displayDate(backup.createdUtc)}`, 'help'), this.detail('备份', backup.backupPath));
      if (backup.error) item.append(element('p', safeError(backup.error), 'error-text'));
      else item.append(this.button('检查回滚', () => void this.run('正在检查备份与当前文件…', async () => {
        await this.invalidate(); const revision = this.revision;
        const view = await this.api.previewRollback(backup.backupPath);
        if (this.disposed || revision !== this.revision) { await this.api.cancelPreview(); this.notice('回滚预览因中断已丢弃，请重新检查。'); return; }
        this.previewKind = 'rollback'; this.showPreview(view); this.notice('回滚预览已生成。它会恢复整个文件，请仔细确认。');
      }), 'button secondary'));
      list.append(item);
    }
  }

  private renderTemplates(): void {
    const list = this.get('templates-list'); list.replaceChildren();
    if (!this.data.templates.length) return this.empty(list, '还没有模板。选择一份已知配置，推导并确认结构后保存。');
    for (const template of this.data.templates) {
      const item = element('article', undefined, 'item'); item.append(element('h4', template.name));
      for (const field of template.fields) item.append(element('p', field.pointer || '（根字符串）', 'monospace breakable help'));
      item.append(this.button('删除模板', () => this.askDelete(`删除模板“${template.name}”？仍被映射引用的模板不能删除。样本配置不会改变。`, async () => {
        await this.invalidate(); await this.api.deleteTemplate(template.id); await this.loadSnapshot(); this.notice('模板已删除。', 'success');
      }), 'text-button danger-text'));
      list.append(item);
    }
  }
  private resetCandidate(): void {
    this.candidate = null; this.get<HTMLFormElement>('template-form').reset(); this.get('template-form').hidden = true;
    this.get('candidate-fields').replaceChildren(); this.get<HTMLTextAreaElement>('template-schema').value = '';
    this.input('confirm-template').checked = false; this.refreshControls();
  }
  private selectedCandidatePointers(): string[] {
    return [...this.root.querySelectorAll<HTMLInputElement>('#candidate-fields input:checked')].map(input => input.value);
  }
  private async inferTemplate(): Promise<void> {
    const path = this.input('template-source').value; if (!path) return;
    await this.run('正在从选定文件推导结构…', async () => {
      this.resetCandidate(); const revision = this.revision;
      const candidate = await this.api.inferTemplate(path);
      if (this.disposed || revision !== this.revision) { this.notice('结构推导因中断已丢弃，请重试。'); return; }
      this.candidate = candidate; this.input('template-name').value = candidate.name ?? '';
      this.get<HTMLTextAreaElement>('template-schema').value = schemaText(candidate.schema);
      const fields = this.get('candidate-fields'); fields.replaceChildren();
      for (const field of candidate.fields) {
        const label = element('label', undefined, 'check-line candidate-field'); const check = element('input');
        check.type = 'checkbox'; check.value = field.pointer; check.checked = false;
        check.addEventListener('change', () => { this.input('confirm-template').checked = false; this.refreshControls(); });
        label.append(check, element('span', field.pointer || '（根字符串）', 'monospace breakable')); fields.append(label);
      }
      if (!candidate.fields.length) this.empty(fields, '没有可绑定的字符串字段。请选择其他配置。');
      this.get('template-form').hidden = false; this.input('confirm-template').checked = false;
      this.notice('候选结构已生成。请选择允许绑定的字段，检查 Schema 后确认保存。', 'success');
    });
  }
  private async saveTemplate(): Promise<void> {
    if (this.busy || !this.candidate || !this.input('confirm-template').checked || !this.get<HTMLFormElement>('template-form').reportValidity()) return;
    const pointers = this.selectedCandidatePointers(); if (!pointers.length) return;
    const schema = this.get<HTMLTextAreaElement>('template-schema').value;
    try { const parsed: unknown = JSON.parse(schema); if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(); }
    catch { this.notice('Schema 必须是有效的 JSON 对象；候选尚未保存。', 'error'); return; }
    const id = this.candidate.id; const name = this.input('template-name').value;
    await this.run('正在确认并保存模板…', async () => {
      await this.invalidate(); await this.api.saveTemplate(id, name, pointers, schema); this.resetCandidate(); await this.loadSnapshot();
      this.notice('模板已确认保存。可在目标映射的“字段来源”中选择。', 'success');
    });
  }

  private askDelete(description: string, action: () => Promise<void>): void {
    if (this.busy) return;
    this.clearSecret(); this.pendingDelete = action; this.get('dialog-description').textContent = description;
    this.get<HTMLDialogElement>('confirm-dialog').showModal(); this.get('dialog-cancel').focus();
  }
  private closeDelete(): void {
    this.pendingDelete = null; this.get<HTMLDialogElement>('confirm-dialog').close();
  }
}

