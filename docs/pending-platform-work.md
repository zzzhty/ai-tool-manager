# 平台集成与后续计划

## 当前：ATM 0.2.0 绑定 OMH 1.1.0 与独立 CLI 包（2026-10-28）

OMH 负责技能源、脚本、组合与版本；ATM 固定其发布锁，使用同一 Rust 核心导入并分发。
`harness/` 是忽略提交的生成 payload，完整作者源码已移至独立 OMH 仓库。
当前接口、恢复约束与测试归属见 [使用说明](HARNESS_USAGE.md) 和
[ADR 0029](adr/0029-locked-content-and-manager-home-handoff.md)。skill-watcher hooks 已退役。
PR #7 将 ATM 0.2.0 绑定 OMH 1.1.0 并提供 CLI-only 打包（CI 新增三平台 cli-only 与锁定源
Python 作业），PR #8 在 OMH 历史重组后把源锁刷新到 revision b0ea608；main 原生验证全绿
（run 40627262161：cli-only/core/python-payloads/linux-desktop/desktop/macos-desktop）。
真实 Home 的 manager-home 迁移已按显式 preview/apply 完成（本机 `~/.atm/state/relocation.json`
记录 completed）；其内容仍持有 1.2.0 锁下安装的身份，1.1.0 重选仍待显式执行。
真实 Home 的备份、发布包与执行检查点保存在本机忽略提交的交接目录
`~/.local/state/atm-deployments/`；不把历史 CI 套用到后续改动。

## 历史：harness Rust 分发迁移（2026-10-26）

本轮基线为 `df63e0c6bc4acb29d8df508b9f2b62c62b87fdda`，隔离工作分支
`codex/harness-rust-migration`，工作区位于
`/home/zzzhty/Documents/Codex/2026-10-26/task-4/ai-tooling-manager`。
Home 源仓库为 `/home/zzzhty/Projects/ai-tooling-manager`；不复用旧路径、不建兼容链接。
本轮不提交、不推送、不发布、不刷新真实程序入口、不操作真实 harness/venv 或独立 OMH 仓库。

Rust service 取代 Python 分发器：版本化 manifest、来源/版本校验、缓存、计划/应用、
目标适配、receipt、锁、journal、按需 Python payload runtime 与独立 hook 启停。
CLI 和 GUI 直接调用同一 service。静态内容 bootstrap/sync 无需 Python；
旧状态交接仅走显式 `atm harness adopt`，中断恢复走 `atm harness recover`。
Watcher 运行组件移入 `runtimes/watcher`，四个交互维护 skills 保留在 maintenance 包。
历史身份映射保留，用户日志不改写。源码和覆盖范围以当前未提交差异为准。

已执行的局部验证：Rust bridge 13 项、保留的本地 CLI 11 项，以及新的空 PATH/离线缓存
CLI 6 项通过；package/smoke 脚本语法检查通过。首次 CLI payload fixture 因 `../../`
非规范路径被来源校验拒绝，修正 fixture 使用 canonical path 后通过。
真实内容的 Codex 规划回归发现遗漏的 agent-support 文件，补入封存清单后通过；完整 CLI 17 项通过。完整集成测试与发布包验证由本轮最终结果记录。新 Rust 分发的 Windows/macOS 原生执行、
真实客户端集成、真实旧安装交接和真实 Python 环境均未由这些 Linux 合成测试证明。

下方阶段 1—3、CI 链接与路径记录属于迁移前历史，原文保留；其中 Python bootstrap、
旧目录、旧脚本及此前三平台通过声明不再是当前使用指令或本轮验证证据。

## 历史：2026-10-26 AI Tooling Manager 阶段 1—3

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

## 当前入口与后续验收

当前命令与 runtime 分组见 [README](../README.md) 和 [Harness 工作流](HARNESS_USAGE.md)。
程序不调用旧 `machine.py`/`engine.py`。源码中的 Python 仅服务于 payload 或开发验证。
记录态与操作结果经 `harness.rs` / `harness_machine.rs` 转成 GUI 既有视图；能力与用户确认
不能绕过 ownership、用户修改保护或 journal 恢复边界。

Windows/macOS 原生合成执行（Windows core synthetic tests、Tauri GUI 冒烟、完整发布包抽取；
macOS Verify-MacOS 与包抽取）与 Linux 真实隔离 keyring/GUI 已由 main 原生 CI 覆盖
（PR #6 head run 40441691206、PR #7 40519377781、PR #8 40624948561、main 40627262161）。
继续需要独立证据：Codex 实际客户端发现与启停、真实外部 venv/wheel 安装、
Git-marketplace 旧状态所有权转换。已有 CI 定义不是通过声明；凭据、网络设置、
PATH、签名与发布不在常规改动权限内。
