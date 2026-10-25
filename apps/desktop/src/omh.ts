import { displayDate } from './safety';
import type { DesktopApi, OmhStatusView, OmhCapabilities, OmhOperation } from './types';

/** Only this safe vocabulary is ever rendered; everything else stays 未知. */
const managerStates: Record<string, string> = { ready: '记录就绪', degraded: '记录降级', installing: '安装中', broken: '已损坏', missing: '记录缺失' };
const sources: Record<string, string> = { recorded: '记录态快照 · 非实时', synthetic_demo: 'TEST_ONLY 演示数据' };

const node = (tag: string, text: string, className?: string): HTMLElement => {
  const result = document.createElement(tag); result.textContent = text; if (className) result.className = className; return result;
};
const known = (value: string | null | undefined, vocabulary: Record<string, string>): string => {
  if (!value) return '未知';
  const label: string | undefined = vocabulary[value];
  return label ?? '未知';
};
const shortRevision = (value: string | null): string =>
  value && /^[0-9a-f]{7,64}$/i.test(value) ? value.slice(0, 7) : '未知';

export class OmhPanel {
  private revision = 0;
  private capabilities: OmhCapabilities | null = null;
  private busy = false;
  private loaded = false;
  private readonly button: HTMLButtonElement;
  private readonly removers: Array<() => void> = [];
  constructor(private readonly root: HTMLElement, private readonly api: DesktopApi,
    private readonly run: (message: string, action: () => Promise<void>) => Promise<void>,
    private readonly notice: (message: string) => void,
    private readonly ask: (description: string, action: () => Promise<void>) => void) {
    this.button = root.querySelector<HTMLButtonElement>('#query-omh')!;
    const query = () => void this.query();
    this.button.addEventListener('click', query);
    this.removers.push(() => this.button.removeEventListener('click', query));
    for (const [id, event, action] of [
      ['omh-check', 'click', () => void this.diagnose('check')],
      ['omh-doctor', 'click', () => void this.diagnose('doctor')],
      ['omh-operation', 'change', () => this.applyControls()],
      ['omh-targets', 'change', () => this.applyControls()],
      ['omh-preview', 'click', () => this.preview()],
    ] as const) {
      const target = this.get(id); target.addEventListener(event, action);
      this.removers.push(() => target.removeEventListener(event, action));
    }
  }
  refreshControls(busy: boolean, loaded: boolean): void { this.busy = busy; this.loaded = loaded; this.applyControls(); }
  private selected(): string[] { return Array.from(this.root.querySelectorAll<HTMLInputElement>('#omh-targets input:checked')).map(input => input.value); }
  private applyControls(): void {
    this.button.disabled = this.busy || !this.loaded;
    for (const operation of ['check', 'doctor']) (this.get('omh-' + operation) as HTMLButtonElement).disabled = this.busy || !this.loaded || !this.capabilities?.operations[operation]?.supported;
    const operation = (this.get('omh-operation') as HTMLSelectElement).value;
    (this.get('omh-preview') as HTMLButtonElement).disabled = this.busy || !this.loaded || !this.capabilities?.operations[operation]?.supported || !this.selected().length;
    (this.get('omh-operation') as HTMLSelectElement).disabled = this.busy;
    (this.get('omh-targets') as HTMLFieldSetElement).disabled = this.busy;
  }
  private async loadCapabilities(): Promise<void> {
    this.capabilities = null;
    const output = this.get('omh-targets'); output.replaceChildren(node('legend', '明确选择目标 harness'));
    try {
      this.capabilities = await this.api.omhCapabilities();
      for (const name of this.capabilities.harnesses) {
        const label = node('label', name); const input = document.createElement('input');
        input.type = 'checkbox'; input.value = name; label.prepend(input); output.append(label);
      }
      for (const option of (this.get('omh-operation') as HTMLSelectElement).options) option.disabled = !this.capabilities.operations[option.value]?.supported;
      const operation = this.get('omh-operation') as HTMLSelectElement;
      if (operation.selectedOptions[0]?.disabled) operation.value = Array.from(operation.options).find(option => !option.disabled)?.value ?? '';
      this.get('omh-capability-note').textContent = '已识别 machine v1。仅启用 CLI 明确支持的操作；需要交互确认的情况会停止。';
    } catch {
      this.get('omh-capability-note').textContent = '引擎能力不可用或版本不支持 machine v1。生命周期操作已禁用；可在终端使用 atm harness。';
    }
    this.applyControls();
  }
  private async diagnose(operation: 'check' | 'doctor'): Promise<void> {
    if (this.busy || !this.capabilities?.operations[operation]?.supported) return;
    await this.run(`正在运行 OMH ${operation} 诊断…`, async () => {
      this.get('omh-diagnostic-result').textContent = `${operation} 诊断中…`;
      try {
        const result = await this.api.omhDiagnose(operation);
        this.get('omh-diagnostic-result').textContent = result.passed
          ? `${operation} 本次诊断通过。这是该命令本次观测的结果，不保证持续健康。`
          : `${operation} 发现问题或未完成（退出码 ${result.exitCode}）。请在终端运行 atm harness -- ${operation} 查看详情。`;
      } catch (error) {
        this.get('omh-diagnostic-result').textContent = `${operation} 诊断未完成，结果未知。请在终端用 atm harness 核对。`;
        throw error;
      }
    });
  }
  private preview(): void {
    const operation = (this.get('omh-operation') as HTMLSelectElement).value as OmhOperation;
    const harnesses = this.selected();
    if (this.busy || !this.capabilities?.operations[operation]?.supported || !harnesses.length) return;
    const revision = this.revision;
    this.ask(`确认由 ATM 内置 harness 引擎执行 ${operation}？目标：${harnesses.join('、')}。该操作会变更这些目标的引擎托管资源；不会授权任意指令文件替换。${operation === 'repair' ? '修复仅限现有管理器中的已安装分发，不授权事务恢复、重建运行时或 PATH 变更。' : ''}需要额外确认时将停止并提示终端处理。`, async () => {
      if (revision !== this.revision) return;
      try {
        await this.api.omhExecute(operation, harnesses, true);
        this.notice('OMH 操作已完成；以下仅为最新记录态快照。');
      } finally {
        // Refresh even on failure: an interrupted operation can have partial effects.
        try { this.render(await this.api.omhStatus()); }
        catch { this.reset(); }
        await this.loadCapabilities();
      }
    });
  }
  dispose(): void { this.revision++; for (const remove of this.removers) remove(); this.removers.length = 0; }
  private get(id: string): HTMLElement { return this.root.querySelector<HTMLElement>('#' + id)!; }
  private reset(): void { this.revision++; this.capabilities = null; this.applyControls(); this.get('omh-status-result').replaceChildren(node('p', '未知 · 尚未查询。', 'empty-state')); }
  private async query(): Promise<void> {
    const revision = ++this.revision;
    await this.run('正在读取 oh-my-harness 记录态快照…', async () => {
      let result: OmhStatusView;
      try { result = await this.api.omhStatus(); }
      catch (error: unknown) {
        this.reset();
        const code = typeof error === 'object' && error !== null && 'code' in error ? (error as { code: unknown }).code : undefined;
        if (code === 'OMH_NOT_INSTALLED') {
          this.get('omh-status-result').replaceChildren(node('p', '未检测到 harness 引擎安装。可在终端运行 atm harness bootstrap 后再次查询。', 'empty-state'));
          this.notice('未检测到 harness 引擎安装；保持未知。');
          return;
        }
        throw error;
      }
      if (revision !== this.revision) return;
      this.render(result);
      await this.loadCapabilities();
      this.notice('harness 分发状态已读取。这是记录态快照，不代表实时健康；请用 atm check skills --harness … 做实时校验。');
    });
  }
  private render(s: OmhStatusView): void {
    const output = this.get('omh-status-result'); output.replaceChildren();
    const head = node('article', '', 'item');
    head.append(node('p', s.installed ? known(s.managerStatus, managerStates) : '记录缺失', 'pill'));
    head.append(node('p', '来源：' + (sources[s.source] ?? '未知来源'), 'help'));
    if (s.installed) {
      head.append(node('p', '版本：' + (s.releaseVersion ?? '未知') + ' · 通道：' + (s.channel ?? '未知') + ' · 修订：' + shortRevision(s.revision)));
      if (s.repository) head.append(node('p', '仓库：' + s.repository, 'help breakable'));
      if (s.operationKind) head.append(node('p', '存在进行中的操作记录：' + s.operationKind + '。请在终端运行 atm harness status 查看详情。', 'help'));
      if (s.worktreeClean === null) head.append(node('p', '工作区状态：未检查（记录态快照不做实时检查）。', 'help'));
    }
    output.append(head);
    for (const harness of s.harnesses.slice(0, 64)) {
      const item = node('article', '', 'item');
      const label = node('h4', harness.name);
      if (harness.status && Object.hasOwn(managerStates, harness.status)) {
        label.append(node('span', ' ' + managerStates[harness.status], 'pill'));
      } else {
        label.append(node('span', ' 未知', 'pill'));
      }
      item.append(label);
      if (harness.root) item.append(node('p', '目标目录：' + harness.root, 'help breakable'));
      item.append(node('p', '版本：' + (harness.releaseVersion ?? '未知') + ' · 记录时间：' + displayDate(harness.updatedAt), 'help'));
      output.append(item);
    }
  }
}

