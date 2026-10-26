export const MASK = '••••••••';
export const NIL_UUID = '00000000-0000-0000-0000-000000000000';

const messages: Record<string, string> = {
  STORAGE_UNAVAILABLE: '系统安全存储不可用；请在系统中启用并解锁 Keychain/keyring。不会回退到明文。',
  STORAGE_LOCKED: '系统安全存储已锁定或需要交互授权；请在系统中处理后再操作。',
  STORAGE_NOT_CONNECTED: '请先勾选确认并连接本机安全存储。',
  STORAGE_PERMISSIONS: '应用数据目录须由本人拥有且权限为 0700；未更改现有目录权限。',
  STORAGE_ACCESS_DENIED: '系统安全存储拒绝访问；未更改条目或访问控制。',
  STORAGE_KEY_MISSING: '加密数据存在但系统主密钥缺失；不会创建替换密钥，请恢复原主密钥。',
  STORAGE_KEY: '应用主密钥缺失、重复或无效；未覆盖任何系统安全存储条目。',
  STORAGE_FORMAT: '此平台无法读取所选加密文件；macOS、Linux 与 Windows 的保护方式不互通。',
  STORAGE_CRYPTO: '加密完整性验证或解密失败，原文件未修改。',
  STAGING_SECURITY: '无法安全保留目标权限或扩展属性，未替换。',
  CLI_PATH: '请选择原生 Codex 可执行文件的绝对路径。', CLI_PROFILE: '请选择已经由用户配置的 CLI 帐号目录。',
  CLI_SHIM: '请选择 Codex 原生可执行文件；cmd/bat/PowerShell shim 不受支持。',
  CLI_UNAVAILABLE: '无法启动所选原生 Codex CLI，请检查路径和安装。', CLI_NOT_CONNECTED: '请先确认 CLI 路径和帐号目录。',
  USAGE_CREDENTIAL: '查询密钥包含不支持的字符或为空。', USAGE_REGION: '请选择智谱中国或 Z.ai 国际地区。',
  HARNESS_NOT_INSTALLED: '未检测到可用的 harness 引擎安装；可在终端运行 atm harness bootstrap 后再次查询。',
  HARNESS_TIMEOUT: 'atm-harness 超时，已终止；操作结果可能不完整，请核对状态，不会自动重试。',
  HARNESS_RUNTIME: 'harness 引擎运行时不可用；请在终端运行 atm harness -- repair --rebuild 后重试。',
  HARNESS_CLI_FAILED: 'atm-harness 状态查询返回失败；请在终端运行 atm harness status 核对。',
  HARNESS_PROTOCOL: 'atm-harness 状态输出无法安全识别，已丢弃。',
  HARNESS_CONFIRMATION_REQUIRED: '引擎需要额外确认；未授权自动替换现有指令文件，请在终端处理。',
  HARNESS_BUSY: 'harness 已有操作正在运行，请稍后手动刷新状态。',
  HARNESS_UNSUPPORTED: '当前 harness 不支持该机器接口操作，请在终端处理。',
  HARNESS_REQUEST: 'harness 操作或目标无效，请重新选择。',
  HARNESS_OPERATION_FAILED: '引擎操作未完成，可能有部分变更；请核对状态并在终端诊断。',
  HARNESS_HOME: '无法确定用户主目录，无法定位 harness 引擎。',
  SKILLS_PROTECTED: '共享 .agents/skills 目录不由 ATM 管理；已拒绝访问。',
  SKILLS_SOURCE: '请选择包含 SKILL.md 的本机普通技能目录。',
  SKILLS_UNAUDITABLE: '技能目录包含链接或非常规文件，内容无法完整审计，已拒绝。',
  SKILLS_LIMIT: '技能超出大小、文件数或嵌套深度的安全上限。',
  SKILLS_NAME: '技能名称不合法：不得为空、以点开头或包含路径/控制字符。',
  SKILLS_TAKEN: '目标已存在同名条目；不会覆盖，请先处理现有条目。',
  SKILLS_FOREIGN_LINK: '外部链接只读，ATM 不会修改或移除。',
  SKILLS_ENGINE_LOCKED: '该条目由内置引擎管理；请在终端用 atm harness 命令变更。',
  SKILLS_TRASH: '保管区条目无效，请重新盘点。',
  SKILLS_MISSING: '条目已不存在，请重新盘点。',
  SKILLS_HOME: '无法确定用户主目录，无法盘点技能。',
  DEMO_READONLY: '演示模式不修改任何本机目录；请用真实模式管理技能。',

  TEMPLATE_LITERAL: 'Schema 禁止样本值、默认值、常量、枚举与自由文本注释，请只保留结构约束。',
  SCHEMA_DRIFT: '完整配置不符合模板约束，已拒绝写入。请检查配置结构是否发生漂移。',
  SCHEMA_DIALECT: 'Schema 方言不受支持；只接受离线 2020-12 的明确子集。',
  SCHEMA_UNSUPPORTED: 'Schema 含不支持的关键词；请使用允许的结构约束。',
  SCHEMA_REFERENCE: 'Schema 引用无效或超出支持范围。',
  SCHEMA_EXTERNAL_REF: '禁止外部 Schema 引用；模板必须完全离线。',
  TEMPLATE_WRITE_DENIED: '写入字段不在模板白名单内，已拒绝修改。',
  TEMPLATE_CONFIRM_REQUIRED: '模板尚未确认，不能用于写入。',
  TEMPLATE_MAPPING_DRIFT: '目标映射与已保存模板绑定不一致，已拒绝写入。请重新确认映射。',
  TEMPLATE_STORE_MISSING: '模板存储缺失，已拒绝写入。请检查本机模板数据。',
  MAPPING_DRIFT: '目标映射发生变化，请重新确认模板绑定。',
  STORE_MISSING: '模板存储缺失，无法继续写入。',

  UI_SCOPE: '请使用已打包的本地主窗口。浏览器开发页不能操作密钥库。',
  STATE_BUSY: '本地状态不可用，请关闭并重新启动管理器。',
  KEY_NAME: '名称须为 1–80 个可显示字符。', KEY_DUPLICATE: '已有同名密钥，请换一个名称。',
  KEY_MISSING: '密钥已不存在，请刷新后重新选择。', KEY_VALUE: '密钥不能为空，且不能包含控制字符或首尾空白。',
  KEY_IN_USE: '请先修改或删除引用此密钥的目标映射。', TARGET_LABEL: '工具用途须为 1–80 个可显示字符。',
  TARGET_DUPLICATE: '此文件的同一字段已注册，请编辑已有映射。', TARGET_MISSING: '目标映射已不存在，请刷新。',
  POINTER_FORMAT: '请填写精确 JSON Pointer，以 / 开头；不支持点路径或通配符。',
  POINTER_ESCAPE: 'JSON Pointer 转义无效：/ 写作 ~1，~ 写作 ~0。',
  FIELD_MISSING: '字段不存在；不会自动创建字段或父路径。', FIELD_TYPE: '目标字段必须是字符串。',
  JSON_INVALID: 'JSON / JSONC 结构无效，文件未修改。', JSON_DUPLICATE: '配置含重复属性，无法安全编辑。',
  ACCESS_DENIED: '权限不足或文件只读。', FILE_MISSING: '文件已移除或路径失效，请重新选择或预览。',
  FILE_IO: '文件访问失败，可能被占用或存储空间不足。', FILE_CHANGED: '文件自预览后变化，已拒绝写入。请重新预览。',
  PATH_LOCAL: '请选择支持的本机普通文件；网络路径和特殊路径不受支持。',
  PATH_UNSAFE: '路径不满足安全要求；不支持链接、目录联接或特殊文件。',
  PREVIEW_EXPIRED: '预览已失效、取消或使用。请重新生成预览。', PREVIEW_INVALID: '预览无效，请重新生成。',
  CONFIRM_REQUIRED: '请先查看遮罩预览并勾选确认。',
  BACKUP_SCOPE: '只能回滚本管理器列出的备份。', BACKUP_FORMAT: '备份格式或完整性无效，无法回滚。',
  ROLLBACK_CONFLICT: '文件已有后续编辑，已拒绝整文件回滚；不会强制覆盖。',
  DATA_SIZE: '文件超出安全大小限制。', VAULT_FORMAT: '密钥库格式或引用无效，原文件未修改。',
  TEMPLATE_IN_USE: '请先解除引用此模板的目标映射。', TEMPLATE_MISSING: '模板已不存在，请重新选择。',
  TEMPLATE_NAME: '请输入有效且不重复的模板名称。', TEMPLATE_DUPLICATE: '已有同名模板。',
  CANDIDATE_EXPIRED: '模板候选已失效，请重新推导。', TEMPLATE_ALLOWLIST: '所选字段不在模板允许绑定的字段内。',
  TEMPLATE_AMBIGUOUS: '同一文件绑定多个不同模板，请统一后重试。', SCHEMA_LIMIT: 'Schema 超出安全大小或深度限制。',
  TEMPLATE_EXPIRED: '模板候选已失效，请重新推导。', TEMPLATE_CANDIDATE: '模板候选已失效，请重新推导。',
  TEMPLATE_SCHEMA: 'Schema 无效或含不支持的结构，请检查后重试。',
  SCHEMA_INVALID: 'Schema 无效或配置不符合模板约束。', TEMPLATE_FIELDS: '请选择模板允许绑定的精确字符串字段。',
};

/** Never reflect an arbitrary IPC exception: it could contain a typed secret. */
export function safeError(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'code' in error && typeof error.code === 'string') {
    return messages[error.code] ?? '操作被安全检查阻止。请检查所选文件、字段或模板后重试。';
  }
  return '未能确认操作结果。不会自动重试；请刷新检查状态，再决定下一步。';
}

export function pointerIsValid(pointer: string): boolean {
  return pointer.startsWith('/') && !/~(?:[^01]|$)/.test(pointer);
}

export function displayDate(value: string | null): string {
  if (!value) return '时间不可用';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间不可用' : date.toLocaleString('zh-CN', { hour12: false });
}

export function schemaText(schema: unknown): string {
  return typeof schema === 'string' ? schema : JSON.stringify(schema, null, 2);
}

export const outcomeLabels: Record<string, string> = {
  applied: '已写入并验证', skipped: '已跳过', conflict: '冲突，未写入', failed: '未完成',
  appliedUnverified: '已写入，需核查', outcomeUnknown: '结果未确认，需核查',
};

