# 平台集成与后续计划

本页记录集成范围及后续方案，不代表稳定发布或平台测试已经通过。实际结果以目标
提交的测试输出和 CI 为准；未执行与准入受阻均不能算作通过。

## 平台验收

Windows/Linux 的现有功能及技能刷新保护继续保留。macOS 增加原生存储、路径、进程、
桌面权限与隔离验证入口；各平台需要分别验收。真实 vault/Keychain、用户配置、账户
额度和真实引擎安装不作为测试输入。数据迁移、安装、签名和发布独立评估。

## 内置技能分发引擎（已收编）

oh-my-harness 引擎已整体收编进本仓库（`harness/`），ATM 成为唯一来源：独立仓库已归档，原 update 的 git 更新流程由 ATM 版本发布取代，install.sh/ps1 不再是入口。`atm harness bootstrap` 将内嵌源码物化为 manager home 的非 git 分发（身份=内容哈希），`atm harness sync` 在 ATM 升级后重物化并收编旧 git 安装。

引擎保有状态、收据、分发、修复及锁的所有权；统一盘点只统一展示，动作按明确 owner 分派：ATM 自有技能由 `atm <verb> skills`（本地模态）管理，引擎托管分发由 `--harness` 模态动词操作；外来或 owner 未知的内容只读，禁止双重管理或猜测接管。CLI（`atm`）是完整管理器，GUI 是可选 UI 端，两者共用同一物化引擎与 machine v1 协议。

已接入：记录态快照与 capabilities/诊断/生命周期结果、动词优先 CLI 表面（skills/hooks 对象 + `--harness` 模态）、物化/同步/收编流程、内容哈希漂移检测（漂移时指引 `atm harness sync`）、watcher 钩子对象级动词（install/uninstall/check）。嵌入模式下 update/recover/reclone 明确拒绝。未 bootstrap 时展示不可用并指引；未知健康保持未知，失败或超时不自动重试。实现与验证范围见 [README](../README.md)、`crates/atm-core/src/harness_machine.rs`、`crates/atm-core/src/harness_embed.rs`、`harness/scripts/atm_embed.py` 与 `apps/desktop/src/harness.ts`。

## 后续候选（尚未实施）

显式安装/升级引导仍待独立评估；静态 update 入口受能力和确认约束，不构成完整升级引导，recover 不受支持。打开 ATM 或一次普通确认不授权安装、升级、重克隆或更改 PATH。文件替换、
清空目录、事务恢复等额外风险转终端处理，不自动代答。这些后续候选不扩大当前集成的实现范围。
