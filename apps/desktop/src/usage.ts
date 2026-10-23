import { displayDate } from './safety';
import type { DesktopApi, GlmPlanKind, GlmRegion, KeyView, SnapshotView, UsageSnapshot, UsageStatus } from './types';
const statuses: Record<UsageStatus, string> = {
  ok: '已查询', unknown: '未知', unsupported_auth: '此凭据模式不支持', unsupported_plan_type: '此套餐类型暂不支持',
  unsupported_version: 'CLI 协议版本不支持', expired: '凭据过期', authentication_failed: '认证失败',
  rate_limited: '服务限流', stale: '过期快照 · 非实时', unavailable: '服务暂不可用', protocol_error: '响应无法安全识别',
};
const sources: Record<string, string> = { official_app_server: 'Codex 官方 app-server', official_plugin_compat: '官方 usage 插件兼容接口（可能变更）', synthetic_demo: 'TEST_ONLY 演示数据' };
const warnings: Record<string, string> = {
  cached_snapshot_not_live: '这是此前的观测值，请主动重新查询。',
  glm_cycle_compat_interpretation: 'GLM 周期按已知插件兼容资料解释，可能随服务更新变化。',
  cycle_unknown: '部分额度的周期未知。', reset_unknown: '部分额度的重置时间未知。', usage_unknown: '部分用量未知。',
  plan_unknown: '套餐名称未知。', personal_plugin_only: '官方插件覆盖个人版；首版不支持团队查询。',
  api_balance_not_supported: 'API 余额与订阅额度独立，当前查询入口不支持 API 余额。',
  account_changed: 'CLI 帐号发生变化，额度已隐藏。', account_identity_missing: '无法确认 CLI 帐号绑定，额度已隐藏。',
  external_refresh_blocked: 'CLI 请求外部刷新凭据；请由用户在 CLI 中处理。',
  account_cache_disabled: '帐号信息不足以复用此前额度；本次结果仅代表本次查询。',
  ordinary_usage_not_allowed: 'Codex 后端未允许普通用量，额度窗口已隐藏。',
  ordinary_usage_permission_unknown: 'Codex 普通用量许可未知，额度窗口已隐藏。',
  cli_version_unknown: 'CLI 没有报告版本信息。', method_not_found: 'CLI 缺少所需协议方法，请检查版本。',
  redirect_blocked: '官方服务返回重定向，查询已停止。', server_rate_limited: '服务限流，不能推断额度耗尽。',
};
const node = (tag: string, text: string, className?: string): HTMLElement => {
  const result = document.createElement(tag); result.textContent = text; if (className) result.className = className; return result;
};
const percent = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100 ? value : null;
const plans = new Set(['free', 'go', 'plus', 'pro', 'prolite', 'promax', 'team', 'self_serve_business_prolite', 'self_serve_business_usage_based', 'business', 'ent26', 'enterprise_cbp_automation', 'enterprise_cbp_usage_based', 'enterprise', 'edu', 'edu_plus', 'edu_pro', 'lite', 'max']);

export class UsagePanel {
  private revision = 0;
  private connected = false;
  private busy = false;
  private loaded = false;
  private keys: KeyView[] = [];
  private readonly removers: Array<() => void> = [];
  constructor(private readonly root: HTMLElement, private readonly api: DesktopApi,
    private readonly run: (message: string, action: () => Promise<void>) => Promise<void>,
    private readonly notice: (message: string) => void) {
    const on = (id: string, event: string, action: () => void) => {
      const target = this.get(id); target.addEventListener(event, action); this.removers.push(() => target.removeEventListener(event, action));
    };
    on('connect-codex', 'click', () => void this.connectCodex());
    on('disconnect-codex', 'click', () => void this.run('正在断开本次 CLI 连接…', async () => {
      await this.api.disconnectCodexCli(); this.connected = false; this.reset('codex');
      this.get('codex-connection').textContent = '尚未连接 CLI。'; this.notice('本次连接已断开。');
    }));
    for (const id of ['codex-cli', 'codex-profile']) on(id, 'input', () => { this.connected = false; this.reset('codex'); this.get('codex-connection').textContent = '路径已变化，请重新确认。'; this.refreshControls(this.busy, this.loaded); });
    for (const id of ['glm-region', 'glm-key', 'glm-plan-kind']) on(id, 'change', () => { this.reset('glm'); this.refreshControls(this.busy, this.loaded); });
    for (const id of ['confirm-codex-query', 'confirm-glm-query', 'confirm-storage']) on(id, 'change', () => this.refreshControls(this.busy, this.loaded));
    on('query-codex', 'click', () => void this.queryCodex());
    on('query-glm', 'click', () => void this.queryGlm());
    on('connect-storage', 'click', () => {
      if (!this.input('confirm-storage').checked) return;
      this.input('confirm-storage').checked = false;
      void this.run('正在连接系统安全存储…', async () => { await this.api.initializeStorage(true); this.notice('安全存储已连接。现在可以保存密钥与加密备份。'); });
    });
  }
  private get(id: string): HTMLElement { return this.root.querySelector<HTMLElement>('#' + id)!; }
  private input(id: string): HTMLInputElement { return this.get(id) as HTMLInputElement; }
  private select(id: string): HTMLSelectElement { return this.get(id) as HTMLSelectElement; }
  private reset(provider: 'codex' | 'glm'): void {
    this.revision++; this.input('confirm-' + provider + '-query').checked = false;
    this.get(provider + '-usage-result').replaceChildren(node('p', '未知 · 尚未查询。', 'empty-state'));
  }
  clearConfirmations(): void { this.revision++; for (const id of ['confirm-codex-query', 'confirm-glm-query', 'confirm-storage']) this.input(id).checked = false; }
  dispose(): void { this.clearConfirmations(); for (const remove of this.removers) remove(); this.removers.length = 0; }
  setSnapshot(snapshot: SnapshotView): void {
    const select = this.select('glm-key'); const selected = select.value;
    const before = this.keys.find(k => k.id === selected)?.updatedUtc;
    this.keys = snapshot.keys;
    const first = document.createElement('option'); first.value = ''; first.textContent = '请选择密钥'; select.replaceChildren(first);
    for (const key of this.keys) { const option = document.createElement('option'); option.value = key.id; option.textContent = key.name; select.add(option); }
    select.value = this.keys.some(k => k.id === selected) ? selected : '';
    if (before !== this.keys.find(k => k.id === select.value)?.updatedUtc) this.reset('glm');
    const mac = snapshot.storageKind === 'macos_keychain';
    const linux = snapshot.storageKind === 'linux_secret_service';
    this.get('storage-label').textContent = snapshot.demo ? '演示模式 · 临时假数据' : mac ? 'Keychain · AES-GCM' : linux ? 'Secret Service · AES-GCM' : snapshot.storageKind === 'windows_dpapi' ? 'DPAPI · 当前用户' : '本机系统安全存储';
    this.get('storage-connect').hidden = !(mac || linux) || !!snapshot.demo;
    this.get('storage-connect-title').textContent = mac ? 'macOS Keychain 安全存储连接' : 'Linux 安全存储连接';
    this.get('storage-connect-description').textContent = mac
      ? '需要可用且已解锁的 macOS Keychain。首次连接会创建本应用专用随机主密钥；已有加密数据缺少主密钥时不会创建替换密钥。密钥库和备份依赖该条目，请勿删除。'
      : '需要可用且已解锁的会话 keyring。首次连接会创建本应用专用的随机主密钥，密钥库和备份依赖该条目；请勿删除。';
    this.get('storage-confirm-label').textContent = mac ? '我确认在 macOS Keychain 中创建或连接本应用主密钥。' : '我确认在系统 keyring 中创建或连接本应用主密钥。';
    if (mac) {
      this.input('codex-cli').placeholder = '/absolute/path/to/codex';
      this.input('codex-profile').placeholder = '/absolute/path/to/codex-profile';
    }
  }
  refreshControls(busy: boolean, loaded: boolean): void {
    this.busy = busy; this.loaded = loaded;
    const disable = (id: string, condition: boolean) => { (this.get(id) as HTMLButtonElement).disabled = busy || !loaded || condition; };
    disable('connect-codex', !this.input('codex-cli').value || !this.input('codex-profile').value);
    disable('disconnect-codex', !this.connected);
    disable('query-codex', !this.connected || !this.input('confirm-codex-query').checked);
    disable('query-glm', !this.input('confirm-glm-query').checked || (this.select('glm-plan-kind').value === 'personal' && !this.select('glm-key').value));
    disable('connect-storage', !this.input('confirm-storage').checked);
  }
  private async connectCodex(): Promise<void> {
    const cli = this.input('codex-cli').value; const profile = this.input('codex-profile').value;
    if (!cli || !profile) return;
    await this.run('正在确认 CLI 路径…', async () => {
      await this.api.configureCodexCli(cli, profile, true); this.connected = true; this.reset('codex');
      this.get('codex-connection').textContent = 'CLI 路径已确认。查询使用此目录的帐号；每次都需勾选确认。';
      this.notice('CLI 路径已确认，尚未查询额度。');
    });
  }
  private async queryCodex(): Promise<void> {
    if (!this.connected || !this.input('confirm-codex-query').checked) return;
    this.input('confirm-codex-query').checked = false; const revision = ++this.revision;
    await this.run('正在主动查询 Codex 额度…', async () => {
      const result = await this.api.queryCodexUsage(true);
      if (revision === this.revision) { this.render('codex', result); this.notice('Codex 查询已结束，请核对来源和状态。'); }
    });
  }
  private async queryGlm(): Promise<void> {
    if (!this.input('confirm-glm-query').checked) return;
    const region = this.select('glm-region').value as GlmRegion;
    const kind = this.select('glm-plan-kind').value as GlmPlanKind;
    const key = kind === 'personal' ? this.select('glm-key').value : null;
    if (kind === 'personal' && !key) return;
    this.input('confirm-glm-query').checked = false; const revision = ++this.revision;
    await this.run('正在主动查询 GLM 额度…', async () => {
      const result = await this.api.queryGlmUsage(region, kind, key, true);
      if (revision === this.revision) { this.render('glm', result); this.notice('GLM 查询已结束，请核对来源和状态。'); }
    });
  }
  private render(provider: 'codex' | 'glm', s: UsageSnapshot): void {
    const output = this.get(provider + '-usage-result'); output.replaceChildren();
    output.append(node('p', statuses[s.status] ?? '未知', 'pill'));
    output.append(node('p', '来源：' + (sources[s.source] ?? '未知来源'), 'help'));
    output.append(node('p', '凭据用途：' + (s.authKind === 'api_key' ? 'API 余额（独立）' : s.authKind === 'chatgpt_oauth' ? 'ChatGPT 订阅 OAuth' : 'Coding Plan 密钥'), 'help'));
    if (provider === 'glm') output.append(node('p', '地区：' + (s.region === 'china' ? '中国 · 智谱' : s.region === 'international' ? '国际 · Z.ai' : '未知'), 'help'));
    output.append(node('p', '观测时间：' + (s.observedAt ? displayDate(s.observedAt) : '尚无观测值'), 'help'));
    if (s.checkedAt) output.append(node('p', '本次查询时间：' + displayDate(s.checkedAt), 'help'));
    const allowed = ['ok', 'unknown', 'stale'].includes(s.status);
    output.append(node('p', '套餐：' + (allowed && s.planName && plans.has(s.planName) ? s.planName : '未知')));
    if (allowed) {
      for (const [i, w] of (s.windows ?? []).slice(0, 128).entries()) {
        const card = node('article', '', 'item'); const remaining = percent(w.remainingPercent); const used = percent(w.usedPercent);
        const kind = w.kind === 'unknown_quota' ? '未知额度' : w.kind === 'tool_quota' ? '工具额度' : w.kind === 'model_credit_quota' ? '模型积分额度' : provider === 'codex' ? '订阅额度' : '模型额度';
        const title = provider === 'codex' && /^(Codex|其他额度桶 [1-9][0-9]?) · (primary|secondary)$/.test(w.label) ? w.label.replace('primary', '主窗口').replace('secondary', '副窗口') : kind + ' ' + (i + 1);
        card.append(node('h4', title));
        card.append(node('p', '剩余：' + (remaining === null ? '未知' : remaining.toFixed(1) + '%') + ' · 已用：' + (used === null ? '未知' : used.toFixed(1) + '%')));
        const duration = w.windowDurationMins;
        card.append(node('p', '周期：' + (typeof duration === 'number' && Number.isSafeInteger(duration) && duration > 0 && duration <= 5256000 ? duration + ' 分钟' : '未知'), 'help'));
        card.append(node('p', '重置：' + (w.resetsAt ? displayDate(w.resetsAt) : '未知'), 'help'));
        if (s.status === 'stale') card.append(node('p', '过期快照 · 请主动重新查询', 'help'));
        output.append(card);
      }
      if (provider === 'codex' && s.credits) {
        const balance = s.credits.balance;
        if (typeof balance === 'number' && Number.isFinite(balance) && balance >= 0 && balance < 1e12) output.append(node('p', '订阅附加积分：' + balance + '（与 API 余额独立）', 'help'));
      }
    }
    for (const warning of new Set(s.warnings ?? [])) if (warnings[warning]) output.append(node('p', warnings[warning], 'help'));
  }
}
