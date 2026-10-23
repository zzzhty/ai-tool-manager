import type { DesktopApi, SkillEntryView, SkillsInventoryView } from './types';

const kindLabels: Record<string, string> = {
  omh_managed: 'OMH 管理', lkm_projected: 'ATM 投影', symlink: '链接', directory: '本地目录', other: '普通文件',
};
const canCopy = (entry: SkillEntryView): boolean =>
  entry.kind === 'directory' || (entry.kind === 'lkm_projected' && entry.linkTarget === null);
const node = (tag: string, text?: string, className?: string): HTMLElement => {
  const result = document.createElement(tag); if (text !== undefined) result.textContent = text; if (className) result.className = className; return result;
};
const baseName = (path: string): string => {
  const trimmed = path.replace(/[\\/]+$/, '');
  const last = trimmed.split(/[\\/]/).pop() ?? '';
  return last && !last.startsWith('.') ? last : '';
};

export class SkillsPanel {
  private revision = 0;
  private installConfirmation: string | null = null;
  private copyConfirmation: string | null = null;
  private inventory: SkillsInventoryView | null = null;
  private copySource: { rootId: string; name: string } | null = null;
  private readonly removers: Array<() => void> = [];
  constructor(private readonly root: HTMLElement, private readonly api: DesktopApi,
    private readonly run: (message: string, action: () => Promise<void>) => Promise<void>,
    private readonly notice: (message: string) => void,
    private readonly ask: (description: string, action: () => Promise<void>) => void) {
    const on = (id: string, event: string, action: () => void) => {
      const target = this.get(id); target.addEventListener(event, action); this.removers.push(() => target.removeEventListener(event, action));
    };
    on('inventory-skills', 'click', () => void this.inventoryNow());
    on('pick-skills-source', 'click', () => void this.pickSource());
    on('confirm-skills-install', 'change', () => {
      this.installConfirmation = this.input('confirm-skills-install').checked ? this.installInputs() : null;
      this.applyControls();
    });
    on('confirm-skills-copy', 'change', () => {
      this.copyConfirmation = this.input('confirm-skills-copy').checked ? this.copyInputs() : null;
      this.applyControls();
    });
    for (const id of ['skills-source', 'skills-name', 'skills-target-root']) {
      for (const event of ['input', 'change']) on(id, event, () => {
        this.clearInstallConfirmation(); this.updateTargetNote(); this.applyControls();
      });
    }
    for (const event of ['input', 'change']) on('copy-target-root', event, () => {
      this.clearCopyConfirmation(); this.applyControls();
    });
    on('install-skill', 'click', () => void this.install());
    on('copy-skill', 'click', () => void this.copy());
  }
  dispose(): void { this.revision++; for (const remove of this.removers) remove(); this.removers.length = 0; }
  clearConfirmations(): void {
    this.revision++;
    this.clearInstallConfirmation(); this.clearCopyConfirmation();
    this.applyControls();
  }
  private clearInstallConfirmation(): void {
    this.installConfirmation = null; this.input('confirm-skills-install').checked = false;
  }
  private clearCopyConfirmation(): void {
    this.copyConfirmation = null; this.input('confirm-skills-copy').checked = false;
  }
  private rootPath(id: string): string | null {
    return this.inventory?.roots.find(root => root.id === id)?.path ?? null;
  }
  // Bind consent to the exact request, including the paths represented by root IDs.
  // Recheck at submission too: programmatic value updates need not emit DOM events.
  private installInputs(): string {
    const rootId = this.select('skills-target-root').value;
    return JSON.stringify(['install', this.input('skills-source').value, this.input('skills-name').value, rootId, this.rootPath(rootId)]);
  }
  private copyInputs(): string {
    const target = this.select('copy-target-root').value;
    return JSON.stringify(['copy', this.copySource?.rootId, this.copySource?.name,
      this.copySource ? this.rootPath(this.copySource.rootId) : null, target, this.rootPath(target)]);
  }
  private get(id: string): HTMLElement { return this.root.querySelector<HTMLElement>('#' + id)!; }
  private input(id: string): HTMLInputElement { return this.get(id) as HTMLInputElement; }
  private select(id: string): HTMLSelectElement { return this.get(id) as HTMLSelectElement; }
  private fillRootSelects(inventory: SkillsInventoryView): void {
    for (const id of ['skills-target-root', 'copy-target-root']) {
      const select = this.select(id); const previous = select.value;
      select.replaceChildren();
      for (const root of inventory.roots) {
        const option = document.createElement('option');
        option.value = root.id; option.textContent = root.label + (root.exists ? '' : '（根不存在，安装时创建）');
        select.add(option);
      }
      select.value = inventory.roots.some(root => root.id === previous) ? previous : (inventory.roots[0]?.id ?? '');
    }
    this.updateTargetNote();
  }
  private updateTargetNote(): void {
    const selected = this.select('skills-target-root').value;
    const root = this.inventory?.roots.find(item => item.id === selected);
    this.get('skills-target-note').textContent = root && !root.exists
      ? `该工具的技能根尚不存在：${root.path}。安装时将自动创建。`
      : root ? `技能根：${root.path}` : '';
  }
  private busy = false;
  private loaded = false;
  refreshControls(busy: boolean, loaded: boolean): void {
    this.busy = busy; this.loaded = loaded;
    this.applyControls();
  }
  private applyControls(): void {
    if (this.installConfirmation !== this.installInputs()) this.clearInstallConfirmation();
    if (this.copyConfirmation !== this.copyInputs()) this.clearCopyConfirmation();
    const disable = (id: string, condition: boolean) => { (this.get(id) as HTMLButtonElement).disabled = this.busy || !this.loaded || condition; };
    disable('inventory-skills', false);
    disable('pick-skills-source', false);
    disable('install-skill', !this.input('skills-source').value || !this.input('skills-name').value || !this.input('confirm-skills-install').checked || !this.select('skills-target-root').value);
    disable('copy-skill', !this.copySource || !this.input('confirm-skills-copy').checked || !this.select('copy-target-root').value);
    // DesktopApp resets all controls before delegating capability restrictions.
    for (const button of this.root.querySelectorAll<HTMLButtonElement>('#skills-roots button[data-skills-action-allowed]')) {
      button.disabled = this.busy || !this.loaded || button.dataset.skillsActionAllowed !== 'true';
    }
  }
  /** Fetches and renders without the busy gate; for use inside an outer run. */
  private async refreshQuiet(): Promise<void> {
    const inventory = await this.api.skillsInventory();
    this.clearInstallConfirmation(); this.clearCopyConfirmation();
    this.inventory = inventory; this.fillRootSelects(inventory);
    this.renderRoots(inventory); this.renderTrash(inventory);
  }
  private async inventoryNow(): Promise<void> {
    const revision = ++this.revision;
    await this.run('正在盘点本地技能目录…', async () => {
      await this.refreshQuiet();
      if (revision !== this.revision) return;
      const inventory = this.inventory!;
      const total = inventory.roots.reduce((sum, root) => sum + root.entries.length, 0);
      this.notice(`盘点完成：${inventory.roots.filter(root => root.exists).length} 个工具根、${total} 个技能、保管区 ${inventory.trash.length} 项。`);
    });
  }
  private async pickSource(): Promise<void> {
    await this.run('等待选择技能源目录…', async () => {
      const selected = await this.api.pickDirectory();
      if (selected === null) { this.notice('已取消选择。'); return; }
      this.clearInstallConfirmation();
      this.input('skills-source').value = selected;
      const name = this.input('skills-name');
      if (!name.value) name.value = baseName(selected);
      this.applyControls();
      this.notice('已选择源目录。尚未安装。');
    });
  }
  private async install(): Promise<void> {
    this.applyControls();
    if (this.busy || !this.loaded) return;
    const source = this.input('skills-source').value;
    const rootId = this.select('skills-target-root').value;
    const name = this.input('skills-name').value;
    if (!source || !rootId || !name || !this.input('confirm-skills-install').checked) return;
    this.clearInstallConfirmation(); this.applyControls();
    const revision = ++this.revision;
    await this.run('正在安装技能…', async () => {
      await this.api.skillsInstall(source, rootId, name, true);
      if (revision !== this.revision) return;
      this.input('skills-source').value = ''; this.input('skills-name').value = '';
      await this.refreshQuiet();
      this.notice(`技能已安装到 ${rootId}。`);
    });
  }
  private async copy(): Promise<void> {
    this.applyControls();
    if (this.busy || !this.loaded) return;
    const source = this.copySource;
    const targetRoot = this.select('copy-target-root').value;
    if (!source || !targetRoot || !this.input('confirm-skills-copy').checked) return;
    this.clearCopyConfirmation(); this.applyControls();
    const revision = ++this.revision;
    await this.run('正在跨根复制技能…', async () => {
      await this.api.skillsCopy(source.rootId, source.name, targetRoot, true);
      if (revision !== this.revision) return;
      this.copySource = null; this.get('copy-source-label').textContent = '尚未选择源技能。';
      await this.refreshQuiet();
      this.notice(`已复制到 ${targetRoot}（独立副本）。`);
    });
  }
  private chooseCopySource(rootId: string, name: string): void {
    const entry = this.inventory?.roots.find(root => root.id === rootId)?.entries.find(item => item.name === name);
    if (!entry || !canCopy(entry)) return;
    this.clearCopyConfirmation();
    this.copySource = { rootId, name };
    this.get('copy-source-label').textContent = `源：${rootId} / ${name}`;
    this.applyControls();
    this.notice('已选择复制源，请在上方选择目标根并确认。');
  }
  private uninstall(rootId: string, entry: SkillEntryView): void {
    if (entry.kind === 'omh_managed') { this.notice('该技能由 oh-my-harness 管理；请在终端用 omh 命令变更。'); return; }
    if (entry.kind === 'lkm_projected') { this.notice('该技能是本管理器的投影；请在终端用 atm skills unproject 撤除。'); return; }
    if (entry.kind === 'symlink') { this.notice('外部链接仅供查看，ATM 不会修改或移除。'); return; }
    if (entry.kind === 'other') { this.notice('普通文件不是技能目录，请手动处理。'); return; }
    const description = `卸载技能“${entry.name}”？它将移动到保管区，可随时恢复或彻底删除。`;
    this.ask(description, async () => {
      // The confirm-dialog already wraps this in the app's busy gate.
      await this.api.skillsUninstall(rootId, entry.name, true);
      await this.refreshQuiet();
      this.notice('技能已移入保管区。');
    });
  }
  private restore(trashId: string): void {
    this.ask(`恢复“${trashId}”到原工具根？原根已有同名条目时会被拒绝。`, async () => {
      await this.api.skillsRestore(trashId, true);
      await this.refreshQuiet();
      this.notice('技能已恢复到原根。');
    });
  }
  private purge(trashId: string): void {
    this.ask(`彻底删除保管区中的“${trashId}”？此操作不可恢复。`, async () => {
      await this.api.skillsPurge(trashId, true);
      await this.refreshQuiet();
      this.notice('保管区条目已彻底删除。');
    });
  }
  private entryButtons(rootId: string, entry: SkillEntryView): HTMLElement[] {
    const locked = entry.kind === 'omh_managed' || entry.kind === 'symlink';
    const projected = entry.kind === 'lkm_projected';
    const buttons: HTMLElement[] = [];
    const button = (text: string, action: () => void, className = 'text-button', allowed = true): HTMLButtonElement => {
      const element = document.createElement('button'); element.type = 'button'; element.textContent = text;
      element.className = className; element.dataset.skillsActionAllowed = String(allowed);
      element.disabled = this.busy || !this.loaded || !allowed;
      element.addEventListener('click', action); return element;
    };
    buttons.push(button('复制到…', () => this.chooseCopySource(rootId, entry.name), 'text-button', canCopy(entry)));
    if (entry.kind === 'directory') {
      buttons.push(button('卸载', () => this.uninstall(rootId, entry), 'text-button danger-text'));
    }
    if (locked) buttons.push(node('span', entry.kind === 'omh_managed' ? '由 OMH 管理' : '外部链接 · 只读', 'pill'));
    if (projected) {
      buttons.push(node('span', '由 ATM 投影管理', 'pill'));
      if (!canCopy(entry)) buttons.push(node('span', '链接投影不支持复制；追加投影请用 atm skills project。', 'help'));
    }
    return buttons;
  }
  private renderRoots(inventory: SkillsInventoryView): void {
    const output = this.get('skills-roots'); output.replaceChildren();
    for (const root of inventory.roots) {
      const card = node('article', '', 'card item');
      const heading = node('h4', `${root.label} · ${root.id}`);
      heading.append(node('span', root.exists ? `${root.entries.length} 项` : '根不存在', 'pill'));
      card.append(heading, node('p', root.path, 'monospace breakable help'));
      if (!root.exists) { output.append(card); continue; }
      if (!root.entries.length) { card.append(node('p', '该根存在但没有技能。', 'help')); output.append(card); continue; }
      for (const entry of root.entries.slice(0, 256)) {
        const line = node('div', undefined, 'item');
        const title = node('strong', entry.displayName && entry.displayName !== entry.name ? `${entry.name}（${entry.displayName}）` : entry.name);
        title.append(node('span', ` ${kindLabels[entry.kind] ?? '未知来源'}`, entry.kind === 'omh_managed' ? 'pill caution' : 'pill'));
        line.append(title);
        if (entry.description) line.append(node('p', entry.description, 'help'));
        if (entry.linkTarget) line.append(node('p', `链接目标：${entry.linkTarget}`, 'monospace breakable help'));
        const actions = node('div', undefined, 'item-actions');
        actions.append(...this.entryButtons(root.id, entry));
        line.append(actions);
        card.append(line);
      }
      output.append(card);
    }
  }
  private renderTrash(inventory: SkillsInventoryView): void {
    const output = this.get('skills-trash'); output.replaceChildren();
    if (!inventory.trash.length) { output.append(node('p', '保管区为空。', 'empty-state')); return; }
    for (const item of inventory.trash.slice(0, 128)) {
      const card = node('article', '', 'card item');
      card.append(node('h4', item.name), node('p', `${item.id} · 原 ${item.originPath}`, 'monospace breakable help'));
      const actions = node('div', undefined, 'item-actions');
      const button = (text: string, action: () => void, className: string) => {
        const element = document.createElement('button'); element.type = 'button'; element.textContent = text;
        element.className = className; element.addEventListener('click', action); return element;
      };
      actions.append(
        button('恢复到原根', () => this.restore(item.id), 'button secondary'),
        button('彻底删除', () => this.purge(item.id), 'text-button danger-text'),
      );
      card.append(actions);
      output.append(card);
    }
  }
}

