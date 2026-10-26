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

- [x] 阶段 1：更名、空 vault 身份；Python/--home；旧状态收编、同步恢复；CI 回归。
- [x] 阶段 2：完整 CLI/桌面/harness 分发包；脱离 checkout 的合成安装与升级验收。
- [x] 阶段 3：registry 单一工具定义；共用应用服务；vault/模板故障隔离。
- [x] 最终审查、源清单与相关本地检查；可用的原生平台 CI；GitHub 仓库改名与 remote 核对。

验收只用隔离合成状态和假凭据；不运行用户真实 harness 安装/迁移、不读写用户配置。
复用已覆盖最终状态的检查；新失败和受影响状态必须重新验证。
阶段 4 工具中心界面、阶段 5 配置档、本机真实安装切换均不在本轮范围。

实现已落地，最终代码提交为 `6a12df1f0482491a0a5c43592f3ffeaf67a23ca9`。
三平台完整 CI：[40289226524](https://github.com/zzzhty/ai-tooling-manager/actions/runs/40289226524)，7 个任务全部通过（Rust core、Linux Python 3.11/3.12、Windows Python 3.12，以及 Linux/Windows/macOS 三套原生桌面任务）。

- 仓库：GitHub 已更名为 `zzzhty/ai-tooling-manager`，repository id 保持 `1430854963`；origin 已同步。本地工作目录仍为 `ai-tool-manager`，保留当前桌面工作区绑定。
- 本地验证：Rust 核心/CLI/应用服务 203 项、前端 89 项、引擎 484 项（4 skip）、Watcher 87 项（3 skip）、Workflow 96 项通过；格式、clippy、类型检查、构建和原插件 generation 检查通过。独立真实 Secret Service 创建/重启后重新打开通过；本地引擎与解压包验收覆盖最终引擎改动。
- 分发验收：在 checkout 外解压，使用临时 home 和假配置完成自动发现 Python、bootstrap、ZCode 安装、Codex 本地投影、仅修改引擎脚本的升级、漂移修复及重新应用；断言已有收据、desired state、本地投影登记和用户配置保留。Linux x64、Windows x64、macOS arm64 的最终原生 GUI 和完整解压包验收均通过。
- 源与状态：源清单审计为 393 个 UTF-8 项目文件，无检测到的凭据模式；插件内容和 generation 身份未变更。没有读取或写入用户真实 vault、harness 安装或配置。

验收中修复的缺陷：发布引擎写收据仍依赖 Git HEAD；Windows 输出按 CP1252
误解码；旧测试调用已退役安装脚本；Git 后台维护干扰只读快照 fixture；
macOS 新 fixture 未设置 0600；完整引擎检查未显式拒绝 Windows junction。
对应行为和原安全门禁均保留或补齐，未放宽快照、权限和插件身份检查。

Windows 分发超时的对照证据：`40285800277` 在 240 秒内只完成 11 个
junction；`40287636123` 中空 PowerShell 与 junction 均约 22 秒；
`40288179284` 保留运行环境但隔离用户目录后为 0.31 秒；`40288834810`
确认缺失 `PSModuleAnalysisCachePath` 导致重复模块分析。验收脚本保留这一
运行时缓存变量，继续隔离用户配置路径，保留 240 秒超时及进程树清理。
生产投影方式未改，临时 CI 探针已移除。最终 Windows 分发安装耗时 10.9 秒，重新应用耗时 1.2 秒，完整生命周期通过。

阶段验收不等于稳定版本发布。便携包未签名，harness 仍需 Python 3.11+
及首次 bootstrap 安装依赖；原生 GUI 需要各平台运行库。代码位于上述工作
分支，未合并 main，也未执行本机真实安装切换。

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
