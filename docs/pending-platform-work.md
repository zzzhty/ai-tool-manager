# 平台集成与后续计划

## 2026-10-26：AI Tooling Manager 阶段 1—3

用户已授权实施、仓库更名与空 vault 身份替换。工作分支：
`codex/ai-tooling-manager-integration`；基线：`8108c0e`。
本页是本轮范围、进度和验证结果的唯一工作记录，不创建长期目标。

身份分类：当前展示名、私有 npm 包名、仓库发布引用改为
`AI Tooling Manager` / `ai-tooling-manager`；空 vault 的 DPAPI entropy、
Secret Service application、Keychain service 与桌面 identifier 一次切换。
`atm`、`atm-core`、`atm-cli`、`ATM_HOME`、`.atm`、存储路径和文件格式保持。
历史 CHANGELOG/验收证据保留原文。现有 harness 状态、收据、技能源/投影登记、
用户配置不重置。旧 OMH 状态仅在显式 sync 中按已知 schema 收编并保留备份。

引擎分发身份由物化/发布模块负责：现有 plugin bundle 不能覆盖 scripts、
registry、agents 的变更，marker 相等也无法证明目标未漂移；这两个已复现的
缺口需要完整受管理引擎内容契约，原插件 generation 门禁保持原范围。
完整检查用于物化、同步及引擎写入边界，status 继续只读记录态。

- [ ] 阶段 1：更名、空 vault 身份；Python/--home；旧状态收编、同步恢复；CI 回归。
- [ ] 阶段 2：完整 CLI/桌面/harness 分发包；脱离 checkout 的合成安装与升级验收。
- [ ] 阶段 3：registry 单一工具定义；共用应用服务；vault/模板故障隔离。
- [ ] 最终审查、源清单与相关本地检查；可用的原生平台 CI；GitHub 仓库改名与 remote 核对。

验收只用隔离合成状态和假凭据；不运行用户真实 harness 安装/迁移、不读写用户配置。
复用已覆盖最终状态的检查；新失败和受影响状态必须重新验证。
阶段 4 工具中心界面、阶段 5 配置档、本机真实安装切换均不在本轮范围。

实现已落地，正在完成目标提交的平台验收：

- GitHub 仓库已改为 `zzzhty/ai-tooling-manager`，repository id 保持 `1430854963`；origin 已同步。CLI 与存储目录不变。
- 本地 Rust 核心/CLI/应用服务 203 项通过（独立 keyring opt-in 未计入）；原生 clippy、前端类型检查/89 项测试/构建通过。
- 引擎 484 项（6 skip）、Watcher 87 项（3 skip）、Workflow 96 项通过；插件 generation 检查通过，未更改插件包身份。
- Linux 原生 WebKit GUI 通过；解压发布包在临时 home 完成真实 bootstrap、ZCode 安装、引擎脚本升级、同步漂移修复、本地投影及收据/配置保留验收。
- 发布包验收发现并修复了嵌入式安装写收据仍访问 Git HEAD 的缺陷。完整 Python 回归及最终原生包复验进行中。
- Windows/macOS 的 CI 结果与源清单检查待补；不将本地 Linux 通过等同于跨平台通过。

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
