/** Static, trusted markup only. All file names, labels and IPC values use textContent. */
export const layout = `
<a class="skip-link" href="#main">跳到工作区</a>
<header class="app-header">
  <div class="identity"><span class="app-mark" aria-hidden="true">⌘</span><div><h1>AI Tool Manager</h1><p>ATM · LOCAL AI TOOL MANAGER <span class="version">RUST · 0.2</span></p></div></div>
  <span class="local-badge"><span aria-hidden="true">●</span> 本机加密 · 按需查询</span>
</header>
<div class="app-shell">
  <aside class="sidebar" aria-label="工作区导航">
    <nav id="navigation">
      <button type="button" data-panel="keys" aria-current="page"><span aria-hidden="true">01</span> 命名密钥库 <span id="key-count" class="count">0</span></button>
      <button type="button" data-panel="targets"><span aria-hidden="true">02</span> 目标与批量更新 <span id="target-count" class="count">0</span></button>
      <button type="button" data-panel="templates"><span aria-hidden="true">03</span> 结构模板 <span id="template-count" class="count">0</span></button>
      <button type="button" data-panel="backups"><span aria-hidden="true">04</span> 加密备份与回滚</button>
      <button type="button" data-panel="usage"><span aria-hidden="true">05</span> 套餐与额度</button>
      <button type="button" data-panel="omh"><span aria-hidden="true">06</span> OMH 管理器状态</button>
      <button type="button" data-panel="skills"><span aria-hidden="true">07</span> 本地技能管理</button>
    </nav>
    <div class="sidebar-note"><strong>先预览，再应用</strong><p>仅处理你选择的文件与精确字段。不自动扫描配置或寻找密钥。</p></div>
  </aside>
  <main id="main" tabindex="-1">
    <div id="notice" class="notice" role="status" aria-live="polite" aria-atomic="true">正在连接本地密钥库…</div>
    <section id="panel-keys" class="panel" aria-labelledby="keys-heading">
      <div class="section-heading"><div><p class="eyebrow">01 / VAULT</p><h2 id="keys-heading">命名密钥库</h2><p>用用途命名。已保存的密钥始终完全遮罩。</p></div><button id="refresh" class="button secondary" type="button">刷新状态</button></div>
      <div class="two-columns">
        <section class="card" aria-labelledby="saved-keys-heading"><div class="card-heading"><h3 id="saved-keys-heading">已保存的密钥</h3><span id="storage-label" class="subtle">本机系统安全存储</span></div><div id="keys-list" class="item-list"></div></section>
        <section class="card" aria-labelledby="key-form-heading"><h3 id="key-form-heading">添加密钥</h3>
          <form id="key-form" autocomplete="off">
            <label for="key-name">名称</label><input id="key-name" name="key-name" required maxlength="80" placeholder="例如：开发环境 / Z Code" autocomplete="off">
            <label for="key-secret">密钥 <span id="key-secret-optional" class="subtle"></span></label><input id="key-secret" name="key-secret" type="password" required maxlength="8192" autocomplete="new-password" spellcheck="false" autocapitalize="off" aria-describedby="key-help">
            <p id="key-help" class="help">保存、取消编辑或离开应用时会清空输入。不会回填已保存的密钥。</p>
            <div class="actions"><button class="button primary" id="save-key" type="submit">保存密钥</button><button class="button secondary" id="reset-key" type="button">清空 / 取消</button></div>
          </form>
        </section>
      </div>
      <div id="storage-connect" class="info-block" hidden><strong id="storage-connect-title">系统安全存储连接</strong><p id="storage-connect-description">首次连接须由用户确认；密钥库和备份依赖本应用专用主密钥，请勿删除。</p><label class="check-line"><input id="confirm-storage" type="checkbox"><span id="storage-confirm-label">我确认在系统安全存储中创建或连接本应用主密钥。</span></label><button id="connect-storage" class="button secondary" type="button">连接安全存储</button></div>
      <div class="info-block"><strong>本机加密的边界</strong><p>密钥库与备份使用本机系统保护的主密钥加密。Windows 使用当前用户 DPAPI，Linux 使用 Secret Service 与 AES-GCM。应用在处理时需要短暂持有明文；目标配置按目标应用要求写入明文。同一用户下的恶意进程仍可能访问它。</p></div>
    </section>
    <section id="panel-targets" class="panel" aria-labelledby="targets-heading" hidden>
      <div class="section-heading"><div><p class="eyebrow">02 / TARGETS</p><h2 id="targets-heading">目标与批量更新</h2><p>每条映射只绑定一个已存在的字符串字段。</p></div></div>
      <div class="two-columns target-columns">
        <section class="card" aria-labelledby="targets-list-heading"><div class="card-heading"><h3 id="targets-list-heading">目标映射</h3><button id="select-all" class="text-button" type="button">全选</button></div><div id="targets-list" class="item-list"></div><div class="selection-bar"><span id="selection-count">已选择 0 项</span><button id="preview-selected" class="button primary" type="button">生成遮罩预览</button></div></section>
        <section class="card" aria-labelledby="target-form-heading"><h3 id="target-form-heading">添加目标映射</h3>
          <form id="target-form" autocomplete="off">
            <label for="target-label">工具 / 用途</label><input id="target-label" required maxlength="80" placeholder="例如：VS Code / 测试服务器">
            <label for="target-path">本机配置文件</label><div class="input-action"><input id="target-path" required readonly placeholder="手动选择已知 JSON / JSONC 文件"><button id="pick-target" class="button secondary" type="button">选择文件</button></div>
            <label for="target-template">字段来源</label><select id="target-template"><option value="">手动填写精确字段</option></select>
            <label for="target-pointer" id="pointer-label">JSON Pointer</label><input id="target-pointer" required placeholder="/servers/demo/env/API_KEY" aria-describedby="pointer-help"><select id="template-pointer" aria-labelledby="pointer-label" hidden></select>
            <p id="pointer-help" class="help">/ 写成 ~1，~ 写成 ~0；数组用精确索引。须以 / 开头，且只能指向已存在的字符串。</p>
            <label for="target-key">命名密钥</label><select id="target-key" required aria-describedby="target-key-help"><option value="">请选择密钥</option></select><p id="target-key-help" class="help">先在密钥库中添加密钥，再建立映射。</p>
            <label class="check-line"><input id="target-bearer" type="checkbox"><span>在值前加 Bearer 前缀</span></label>
            <label class="check-line"><input id="protect-variables" type="checkbox" checked><span>保护现有变量占位符（推荐）</span></label>
            <p class="help">默认保留 &dollar;{…}、$(…)、{{…}} 和 %…% 引用。取消保护后，预览会标明替换。</p>
            <div class="actions"><button id="save-target" class="button primary" type="submit">保存映射</button><button id="reset-target" class="button secondary" type="button">清空 / 取消</button></div>
          </form>
        </section>
      </div>
    </section>
    <section id="panel-templates" class="panel" aria-labelledby="templates-heading" hidden>
      <div class="section-heading"><div><p class="eyebrow">03 / STRUCTURE</p><h2 id="templates-heading">结构模板</h2><p>从你选择的配置推导结构，确认后才能保存和绑定。</p></div></div>
      <div class="two-columns">
        <section class="card" aria-labelledby="saved-templates-heading"><h3 id="saved-templates-heading">已确认的模板</h3><div id="templates-list" class="item-list"></div></section>
        <section class="card" aria-labelledby="infer-heading"><h3 id="infer-heading">推导模板候选</h3><p class="help">只返回 Schema 结构与候选字段，不读取已保存的密钥，也不把配置值带回界面。字段名和路径本身也可能包含私人信息，请一并检查。模板不自动写入任何配置。</p>
          <label for="template-source">样本配置文件</label><div class="input-action"><input id="template-source" readonly placeholder="选择用于推导的 JSON / JSONC 文件"><button id="pick-template" class="button secondary" type="button">选择文件</button></div><div class="actions"><button id="infer-template" class="button primary" type="button">推导结构</button></div>
          <form id="template-form" hidden autocomplete="off">
            <p class="info-block warning">这是从样本观察到的候选结构，不代表官方规范。推导不会把字段设为必填，也不会禁止未知字段；请自行检查并收紧所需约束。</p>
            <label for="template-name">模板名称</label><input id="template-name" required maxlength="80" placeholder="例如：团队开发工具结构">
            <fieldset class="candidate-fields"><legend>允许绑定的字符串字段</legend><div id="candidate-fields"></div></fieldset>
            <label for="template-schema">Schema（可调整结构约束）</label><textarea id="template-schema" rows="10" spellcheck="false" autocapitalize="off" aria-describedby="schema-help"></textarea><p id="schema-help" class="help">仅支持离线 JSON Schema 2020-12 的明确子集；不支持的关键词会被拒绝。不要粘贴密钥、配置值、default、examples、const 或 enum。后端会再次检查。</p>
            <label class="check-line confirmation"><input id="confirm-template" type="checkbox"><span>我已检查结构和允许绑定的字段，确认保存此模板。</span></label>
            <div class="actions"><button id="save-template" class="button primary" type="submit">确认并保存模板</button><button id="cancel-template" class="button secondary" type="button">丢弃候选</button></div>
          </form>
        </section>
      </div>
    </section>
    <section id="panel-backups" class="panel" aria-labelledby="backups-heading" hidden>
      <div class="section-heading"><div><p class="eyebrow">04 / RECOVERY</p><h2 id="backups-heading">加密备份与回滚</h2><p>回滚恢复整个文件的原始字节，也先备份当前内容。</p></div><button id="refresh-backups" class="button secondary" type="button">刷新备份</button></div>
      <div class="info-block warning"><strong>后续修改受到保护</strong><p>若文件已有后续编辑，会拒绝整文件回滚。回滚按历史原始字节恢复，不受当前 Schema 约束。仅列出本管理器的加密备份，不提供强制覆盖。</p></div><div id="backups-list" class="item-list"></div>
    </section>
    <section id="panel-usage" class="panel" aria-labelledby="usage-heading" hidden>
      <div class="section-heading"><div><p class="eyebrow">05 / PLAN &amp; USAGE</p><h2 id="usage-heading">套餐与额度</h2><p>仅支持 Codex 与 GLM。每次查询均由你主动确认；默认不轮询。</p></div></div>
      <div class="two-columns">
        <section class="card" aria-labelledby="codex-heading">
          <h3 id="codex-heading">Codex · ChatGPT 订阅</h3>
          <p class="help">读取官方 Codex CLI 的帐号与额度。订阅额度与 API 余额分开；API key 模式显示不支持。</p>
          <label for="codex-cli">原生 Codex 可执行文件（绝对路径）</label><input id="codex-cli" autocomplete="off" spellcheck="false" placeholder="/path/to/codex 或 C:/.../codex.exe">
          <label for="codex-profile">已配置的 CLI 帐号目录（CODEX_HOME）</label><input id="codex-profile" autocomplete="off" spellcheck="false" placeholder="由你指定现有 CLI 帐号目录">
          <p class="help">Windows 的 npm cmd/bat shim 需要选择安装目录中的原生 codex.exe。路径只在本次应用会话内保存。</p>
          <div class="actions"><button id="connect-codex" class="button secondary" type="button">确认 CLI 路径</button><button id="disconnect-codex" class="text-button" type="button">断开本次连接</button></div>
          <p id="codex-connection" class="help">尚未连接 CLI。</p>
          <label class="check-line confirmation"><input id="confirm-codex-query" type="checkbox"><span>我确认本次 CLI 查询可能联网并使用该目录的已登录帐号；CLI 可能自行刷新 OAuth。</span></label>
          <button id="query-codex" class="button primary" type="button">查询 Codex 额度</button>
          <div id="codex-usage-result" class="item-list" aria-live="polite"><p class="empty-state">未知 · 尚未查询。</p></div>
        </section>
        <section class="card" aria-labelledby="glm-heading">
          <h3 id="glm-heading">GLM Coding Plan</h3>
          <label for="glm-region">服务地区</label><select id="glm-region"><option value="china">中国 · 智谱</option><option value="international">国际 · Z.ai</option></select>
          <label for="glm-plan-kind">凭据用途</label><select id="glm-plan-kind"><option value="personal">个人 Coding Plan</option><option value="team">团队 Coding Plan（首版不支持）</option><option value="api_balance">API 余额（首版不支持）</option></select>
          <label for="glm-key">本次查询使用的命名密钥</label><select id="glm-key"><option value="">请选择密钥</option></select>
          <p class="help">使用所选地区的官方 usage 插件兼容接口。接口可能变更；401/403 表示认证失败，429 表示限流，均不能视作没有套餐或额度为零。</p>
          <label class="check-line confirmation"><input id="confirm-glm-query" type="checkbox"><span>我确认本次使用所选密钥向此地区的官方服务发送只读额度请求。</span></label>
          <button id="query-glm" class="button primary" type="button">查询 GLM 额度</button>
          <div id="glm-usage-result" class="item-list" aria-live="polite"><p class="empty-state">未知 · 尚未查询。</p></div>
        </section>
      </div>
      <div class="info-block"><strong>如何读额度</strong><p>未知值保持未知。百分比代表该来源报告的窗口用量；不换算固定 token 或请求次数。GLM 周期包含兼容解释，未知周期会明确标注。工具额度独立显示。网络失败时旧快照标为过期快照，认证失败时隐藏旧额度。</p></div>
    </section>
    <section id="panel-omh" class="panel" aria-labelledby="omh-heading" hidden>
      <div class="section-heading"><div><p class="eyebrow">06 / OMH</p><h2 id="omh-heading">Oh My Harness 状态</h2><p>独立安装的 harness 技能分发器。读取记录态快照，按需调用独立 OMH CLI；不轮询。</p></div><button id="query-omh" class="button secondary" type="button">查询 OMH 状态</button></div>
      <div id="omh-status-result" class="item-list" aria-live="polite"><p class="empty-state">未知 · 尚未查询。</p></div>
      <div class="card"><h3>OMH 诊断</h3><p>按需校验当前安装分发内容与运行环境；doctor 将警告也视为失败。诊断可能启动客户端子进程，其行为由客户端决定，不保证离线。</p><button id="omh-check" type="button" class="button secondary" disabled>校验安装（check）</button> <button id="omh-doctor" type="button" class="button secondary" disabled>严格校验（doctor）</button><p id="omh-diagnostic-result" aria-live="polite">尚未运行诊断。</p></div>
      <div class="card"><h3>OMH 生命周期</h3><p id="omh-capability-note" class="help">先查询状态与 CLI 能力。旧版本或不支持的操作保持禁用。</p><label>操作<select id="omh-operation"><option value="install">安装</option><option value="refresh">刷新</option><option value="remove">移除</option><option value="update">更新</option><option value="repair">修复所选分发（仅现有管理器）</option></select></label><fieldset id="omh-targets"><legend>明确选择目标 harness</legend></fieldset><button id="omh-preview" type="button" class="button secondary" disabled>预览并确认操作</button></div>
      <div class="info-block"><strong>独立 CLI 的边界</strong><p>ATM 不直接改写 OMH 状态、收据或链接。能力支持的操作需选择目标并预览确认，再交由独立 OMH CLI 执行。需要替换现有指令文件的操作会停止并要求在终端确认，不会自动回答 yes。修复仅使用现有健康运行时和检出，不能恢复事务、重新安装运行时或改 PATH。更新仅在 CLI 能力支持且完成目标选择与确认后可用；恢复等未支持的操作请用终端 omh 完成。状态仅为记录态快照，不代表实时健康。</p></div>
    </section>
    <section id="panel-skills" class="panel" aria-labelledby="skills-heading" hidden>
      <div class="section-heading"><div><p class="eyebrow">07 / SKILLS</p><h2 id="skills-heading">本地技能管理</h2><p>盘点各工具的技能目录；按需操作，不轮询、不联网。</p></div><button id="inventory-skills" class="button secondary" type="button">盘点技能</button></div>
      <div class="two-columns">
        <section class="card" aria-labelledby="skills-install-heading">
          <h3 id="skills-install-heading">从本机目录安装</h3>
          <p class="help">只接受含 SKILL.md 的普通目录（不含链接）。超过 512 个文件、8 MB 或 8 层嵌套会被拒绝。</p>
          <label for="skills-source">技能源目录</label><div class="input-action"><input id="skills-source" readonly placeholder="选择含 SKILL.md 的文件夹"><button id="pick-skills-source" class="button secondary" type="button">选择文件夹</button></div>
          <label for="skills-name">安装名称</label><input id="skills-name" required maxlength="64" placeholder="默认使用文件夹名">
          <label for="skills-target-root">目标工具根</label><select id="skills-target-root"></select>
          <p id="skills-target-note" class="help"></p>
          <label class="check-line confirmation"><input id="confirm-skills-install" type="checkbox"><span>我已确认安装名称与目标根；同名条目不会被覆盖。</span></label>
          <button id="install-skill" class="button primary" type="button">安装技能</button>
        </section>
        <section class="card" aria-labelledby="skills-copy-heading">
          <h3 id="skills-copy-heading">跨根复制</h3>
          <p class="help">把某个根里已盘点的技能复制为另一根的独立副本；同名拒绝。在下方列表点“复制到…”选择源。</p>
          <p id="copy-source-label" class="help">尚未选择源技能。</p>
          <label for="copy-target-root">目标工具根</label><select id="copy-target-root"></select>
          <label class="check-line confirmation"><input id="confirm-skills-copy" type="checkbox"><span>我确认创建独立副本（后续两份内容各自独立）。</span></label>
          <button id="copy-skill" class="button primary" type="button">复制技能</button>
        </section>
      </div>
      <div id="skills-roots" class="item-list" aria-live="polite"><p class="empty-state">未知 · 尚未盘点。</p></div>
      <div class="section-heading"><div><p class="eyebrow">TRASH</p><h3>已卸载（保管区）</h3><p>卸载的目录技能保存在本管理器数据目录，可恢复或彻底删除。</p></div></div>
      <div id="skills-trash" class="item-list" aria-live="polite"><p class="empty-state">尚未盘点。</p></div>
      <div class="info-block"><strong>技能管理的边界</strong><p>由 oh-my-harness 管理的链接在此只读；变更请用终端 omh 命令（本工具不会改动其链接）。安装到某根的同名技能若与日后 omh 的投影冲突，由 omh 侧的既有同名保护拒绝，双方内容都不受影响。安装不访问网络，也不接受压缩包；目标根不存在时会自动创建。</p></div>
    </section>
    <section id="preview-section" class="card preview-section" aria-labelledby="preview-heading" hidden tabindex="-1">
      <div class="card-heading"><div><p class="eyebrow">REVIEW / 一次性预览</p><h2 id="preview-heading">遮罩预览</h2></div><span class="pill">所有值完全遮罩</span></div>
      <div id="preview-files" class="item-list"></div>
      <p id="apply-warning" class="help">逐文件原子替换，并非跨文件事务；部分失败不会自动撤销已成功的文件。配置变化可能被目标应用监测并触发重载。应用开始后不能取消。</p>
      <label class="check-line confirmation"><input id="confirm-preview" type="checkbox"><span id="confirm-preview-label">我已检查本次文件和字段，确认将密钥写入所选配置。</span></label>
      <div class="actions"><button id="apply-preview" class="button primary" type="button">应用本次预览</button><button id="cancel-preview" class="button secondary" type="button">取消预览</button></div>
    </section>
    <section id="results-section" class="card results-section" aria-labelledby="results-heading" hidden tabindex="-1"><div class="card-heading"><h2 id="results-heading">本次操作结果</h2><span class="pill">按文件核对</span></div><div id="results-list" class="item-list"></div></section>
    <footer>密钥与备份留在本机。目标配置可能保存明文；请只选择你信任的文件。</footer>
  </main>
</div>
<dialog id="confirm-dialog" aria-labelledby="dialog-title" aria-describedby="dialog-description"><h2 id="dialog-title">确认操作</h2><p id="dialog-description"></p><div class="actions"><button id="dialog-cancel" class="button secondary" type="button">取消</button><button id="dialog-confirm" class="button danger" type="button">确认操作</button></div></dialog>
`;

