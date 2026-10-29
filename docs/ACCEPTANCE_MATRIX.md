# 跨平台合成验收矩阵与操作手册

本页按当前实现区分文档声明、源码能力与实际验证。它是验收入口索引；
操作语义以代码为准。第 6 节保留 2026-10-25 历史执行记录；第 7 节是 2026-10-26
迁移时点的历史检查点；PR #6-#8 合并与 main 之后的原生 CI 证据见第 8 节。
不能复用旧 Python 引擎的平台通过声明。

## 1. 证据等级

| 等级 | 含义 | 使用边界 |
| --- | --- | --- |
| D：文档声明 | README / 平台说明中的支持范围 | 不代表测试通过 |
| C：源码具备 | 实现、平台分支或测试入口存在 | 不代表已在目标平台编译或运行 |
| T：实际执行 | 在明确平台和受测状态下运行，记录命令、结果和覆盖范围 | 不能由 Linux 结果推导 Windows/macOS 通过；跳过和提前返回不算执行对应行为 |

未执行的场景标为“未验证”，同时保留其 D/C 信息。[CI 工作流](../.github/workflows/rust-ci.yml)
存在不代表 CI 通过，CI 自身的精确提交检查仍需满足。未提交工作区要记录基线与改动范围，
不能只凭未变化的 HEAD 标识受测代码。已有检查覆盖最终受影响状态时可复用；相关代码、输入、
依赖、配置、环境或验收条件变化时重新评估覆盖，纯文档变化不自动要求重跑产品测试。
失败须保留原输出；后续通过不能抹去失败，未经诊断不能断言原因是主机负载。

## 2. 功能与平台矩阵

除明确标为当前 Rust 分发的两行外，下表“本次”指第 6 节历史 Linux 集成验证；并非当前全部工作区的测试结论。

| 功能 | D/C：当前实现与测试入口 | T：本次已验证 | 未验证边界 |
| --- | --- | --- | --- |
| Linux 安全存储 | Secret Service 存主密钥，AES-GCM 加密 vault/templates/backups；[linux.rs](../crates/atm-core/src/linux.rs)、[Linux 回归](../crates/atm-core/tests/linux.rs) | 内存密钥注入下的加解密、权限、配置替换与备份回归通过 | 真实 Secret Service 生命周期未运行；该测试在本次常规测试中为 ignored，CI 私有 keyring 作业会显式启用 |
| Windows 安全存储 | DPAPI CurrentUser 加密整包；[windows.rs](../crates/atm-core/src/windows.rs)、[parity 的 Windows 用例](../crates/atm-core/tests/parity.rs) | 原生合成执行已入 CI（desktop 作业 Windows core synthetic tests，见第 8 节） | 真实用户会话下的 DPAPI 未验证；文件替换与 WebView2 以 CI 合成/GUI 冒烟为界 |
| macOS 安全存储 | Keychain 专用条目 + AES-GCM；[macOS 说明](MACOS.md)、[macos.rs 测试](../crates/atm-core/tests/macos.rs) | 部分共享逻辑/模拟后端可在 Linux 测试；不构成 macOS 证据 | macOS 原生用例、真实 Keychain、GUI 未运行；CI 目标为 arm64，Intel/universal 未验证 |
| 批量更新、JSONC、模板与回滚 | [batch.rs](../crates/atm-core/src/batch.rs)、[JSONC parity](../crates/atm-core/tests/parity.rs)、[模板测试](../crates/atm-core/tests/templates.rs)：逐文件原子替换、完整加密备份、精确源字节和本地 schema 校验 | 共享核心与 Linux 回归通过，含 T01 新增冲突/确认/备份边界和 P01 无转义解析、Unicode/控制字节回归 | Windows/macOS 专属文件语义未验证；合成性能收益不等于 GUI 延迟收益 |
| Codex / GLM 额度 | [usage 测试](../crates/atm-core/tests/usage.rs)、[Codex 子进程测试](../crates/atm-core/tests/codex_process.rs)；未知值保留未知，固定端点/argv，主动查询 | 合成协议、错误和进程边界测试通过 | 未查询真实账户或额度端点 |
| 当前 Rust 分发记录与 GUI bridge | [harness.rs](../crates/atm-core/src/harness.rs)、[harness_machine.rs](../crates/atm-core/src/harness_machine.rs) 直接调用 Rust service | 13 项 bridge 测试通过；状态解析、确认/重复目标拒绝、无 Python 只读查询 | 当前 GUI 原生 IPC/真实客户端未验证；旧 machine subprocess 协议已退役 |
| 当前 Rust 内容分发与显式交接 | [distribution](../crates/atm-core/src/distribution/)、[CLI 测试](../crates/atm-cli/tests/cli.rs) | 6 项空 PATH/离线缓存 CLI 测试通过，涵盖静态生命周期、用户修改拒绝、显式解释器/来源验证 | 完整集成结果另记；真实旧 manager、Windows/macOS 原生迁移未验证 |
| 技能、回收站、投影与 CLI | [skills 测试](../crates/atm-core/tests/skills.rs)、[projection 测试](../crates/atm-core/tests/projection.rs)、[CLI 测试](../crates/atm-cli/tests/cli.rs) | Linux 临时目录中的复制、符号链接投影、所有权拒绝、回收恢复和 CLI 通过，含 T02 | macOS 虽共用 POSIX 实现，原生未测；Windows 为普通复制投影，foreign-slot 断言已修正但未在 Windows 运行；真实技能根未访问 |
| 前端 | [组件测试](../apps/desktop/tests)、TypeScript 与 Vite | 88 项通过，类型检查与前端构建通过 | 前端测试/构建不能代替 Tauri 原生启动和 GUI 验证 |

当前分发由 `distribution::Service` 执行。bootstrap/sync 验证和缓存 manifest 内容，
不创建 Python venv；静态 skills 的 install/update/uninstall/status 可在无 Python 环境使用。
只有显式选定的 payload runtime 需要声明的绝对解释器；外部 venv 只验证。准备 runtime
不启用 hook，启停由 Rust 安全合并 owned entries。CLI/GUI 共用 ownership 与 journal。
`atm harness adopt` 是旧状态的一次性交接，`recover` 是显式恢复；普通操作不调用旧引擎。
详细命令见 [README](../README.md)。

### 原生 GUI 入口与 PASS 的含义

| 平台 | 入口与前置条件 | 代码中已有的检查 | 本次状态 |
| --- | --- | --- | --- |
| Linux | [Test-LinuxGui.sh](../scripts/Test-LinuxGui.sh)；CI 私有 RUNNER_TEMP、X11/xvfb 与 D-Bus；二进制必须以 `--features smoke-tests` 构建 | WebKit 渲染、resize、合成 IPC；Linux/macOS 共用 [native_smoke.js](../apps/desktop/src-tauri/src/native_smoke.js) 驱动确认/取消/重复应用拒绝、写入与回滚、capability 拒绝；Rust 检查最终原文与两份备份 | CI linux-desktop 作业已执行（第 8 节） |
| Windows | [Test-TauriGui.ps1](../scripts/Test-TauriGui.ps1)；Windows、WebView2、原生 exe、隔离 LOCALAPPDATA 与 `--demo` | 启动、UIA 可访问性文本、小窗 resize 和截图；未驱动完整写入/回滚流程 | CI desktop 作业已执行（第 8 节） |
| macOS | [Verify-MacOS.sh](../scripts/Verify-MacOS.sh) → [Test-MacOSGui.py](../scripts/Test-MacOSGui.py)；macOS 图形会话、工具链/缓存，smoke-tests 构建 | 共用原生 IPC 流程；父进程额外独立观察磁盘写入/回滚、0600 备份、暂存与进程组清理 | CI macos-desktop 作业已执行（第 8 节）；无真实 Keychain 证明 |

Linux 脚本输出 `LINUX_NATIVE_GUI_SMOKE=PASS`，Windows 输出 `TAURI_GUI_SMOKE=PASS`，
macOS 输出 `MACOS_NATIVE_GUI_SMOKE=PASS`。这些标记只代表对应脚本和当前版本检查到的范围，
不代表三平台全部功能通过。

## 3. 合成验证与演示操作

### Linux 本地离线检查

在仓库根目录、依赖和工具链已就绪的环境执行；此命令会写构建缓存与假数据目录。
`Verify-Local.sh` 会在自己的子进程环境中关闭真实对象 opt-in：

```bash
bash scripts/Verify-Local.sh
```

脚本执行 fmt、Clippy、Rust 测试、前端 check/test/build、diff check 与工作树源码审计，
Cargo 使用 `--locked --offline`。默认隔离 CARGO_HOME 必须已有所需依赖；若使用已有可信
缓存，可明确设置 CARGO_HOME。缺缓存/依赖时报告未执行，不把下载失败当产品测试通过。
还原 npm/Cargo 依赖可能联网，单独记录。脚本不会建立原生 GUI 或真实 keyring 验证证据。

技能测试的显式 `SkillsService::new(home, ...)` / `ProjectionRegistry::at_root(..., home)`
仅从给定 home 解析各工具根，忽略 `CLAUDE_CONFIG_DIR`、`COPILOT_HOME`、`CODEX_HOME`、
`GEMINI_CLI_HOME`、`OPENCLAW_STATE_DIR`、`PI_CODING_AGENT_DIR`；显式投影入口也不继承
引擎管理目录覆盖。应用的 `from_environment()` 仍尊重这些环境配置，不能用它创建合成 fixture。
回归以独立子进程注入外部假目录并检查目录未变，不在并行 Rust 测试中修改全局环境。

当前 harness bridge 测试不再提供真实 Python 引擎 opt-in。`ATM_SKILLS_LIVE=1` 的真实
本地盘点入口仍须单独授权，`Verify-Local.sh` 强制关闭。先用 `Prepare-Content.py`
生成锁定的 OMH payload，再运行本地验证。内容作者测试由独立 OMH 仓库维护；ATM CI
从锁定 revision 运行其 Python 测试。本地验证使用明确的 runner 检查已导入 runtime，
静态 CLI 使用空 PATH。缺依赖导致必要检查失败，不能记为通过。

### 原生平台流程

- Linux 私有 keyring：遵循 [linux-desktop CI 作业](../.github/workflows/rust-ci.yml) 的完整
  私有目录和 D-Bus 设置；[Test-LinuxKeyring.sh](../scripts/Test-LinuxKeyring.sh) 要求
  `CI=true`、`ATM_ISOLATED_KEYRING_TEST=1`、受限 `ATM_TEST_ROOT`。它会创建并重开专用
  TEST_ONLY keyring，成功输出 `SECRET_SERVICE_LIFECYCLE=PASS`。不在个人桌面会话直接执行。
- Linux GUI：遵循同一 CI 作业的 smoke-tests 构建与 `xvfb-run -a dbus-run-session` 包装。
  不通过手动伪造 CI 环境来绕过隔离前置条件。
- Windows：在已有依赖的隔离测试环境依次完成 `npm run check`、`npm test`、
  `npm run build`、Rust 检查和 `npm run tauri:build`；每一步成功后再运行
  `./scripts/Test-TauriGui.ps1`（PowerShell 7）。完整入口见 [README](../README.md#构建与验证)。
- macOS：在已有工具链、缓存与图形会话下运行 `bash scripts/Verify-MacOS.sh`。
  它包含本地检查、smoke-tests workspace 检查与原生 GUI，不签名发布、安装或迁移用户数据。

### 演示存储边界

构建出的 `atm-desktop` / `atm-desktop.exe` 加 `--demo` 会创建新的隔离临时目录，
使用假配置/额度数据，拒绝真实引擎操作和技能变更。Linux/macOS 使用内存密钥；
**Windows 演示使用真实 DPAPI API 加密合成数据**，不是内存密钥实现，见
[demo_protector](../crates/atm-core/src/storage.rs)。三者均不打开默认真实 vault，
但演示结果不证明真实用户目录、生产密钥生命周期、长期运行或跨机器迁移可用。

## 4. 兼容身份与平台差异

| 维度 | Linux | Windows | macOS |
| --- | --- | --- | --- |
| 生产保护后端 | Secret Service + AES-GCM | DPAPI CurrentUser | Keychain + AES-GCM |
| vault/templates | `.atmvault` | `.dpapi` | `.atmvault`，平台专用头 |
| 默认数据根 | `$XDG_DATA_HOME/atm`，回退 `~/.local/share/atm` | `%LOCALAPPDATA%/atm` | `~/Library/Application Support/atm` |
| 技能投影 | 符号链接 | 普通复制，按文件比对与所有权登记刷新 | 符号链接 |

这些历史目录、密文格式和 keyring identity 是兼容标识，不随 ATM 显示名称更名。
密文不是可直接跨平台/跨用户恢复的备份。[安全说明](../README.md#安全与结果含义)仍适用。

## 5. 源码审计范围

[Verify-Local.sh](../scripts/Verify-Local.sh) 检查工作树中 tracked 和未忽略 untracked 文件，
与 [source-manifest.json](../scripts/source-manifest.json) 精确对应，再检查 UTF-8、包装头和
明显凭据模式。新增未忽略的项目源文件须登记；被忽略的构建产物不登记。任务日志保存在
仓库外，不能靠删除源码或弱化清单获得通过。

[Audit-TrackedSource.ps1](../scripts/Audit-TrackedSource.ps1) 的 Head/Staged 模式读取对应
Git blob。未暂存文档应由工作树审计检查，不能拿 Head 结果证明它已验证，也无需为验证先暂存。

## 6. 历史集成验证状态（2026-10-25）

2026-10-25 验证时，受测状态为基线 `3156a541537ec0e4530f464ab2ce5a6a33bf30da` 加当时未提交的 T01/T02、
引擎 command/degraded 修正、P01 JSONC 优化/回归，以及最终复审后的显式技能根隔离修复；
不是该基线提交本身的通过声明。环境为 Linux x86_64、rustc/cargo 1.95.0。
修复后完整 `Verify-Local.sh` 退出 0：Rust **185 passed / 1 ignored**，前端 **88 passed**，
fmt、Clippy、tsc、build 与 93 文件审计通过。ignored 为私有 Secret Service 生命周期；
另有上述 opt-in 空返回。

该次完整验证的父环境注入了六个外部假技能根，并显式开启三个 live opt-in；脚本关闭
opt-in 后验证通过，六个假目录内容保持不变。HOME/XDG 与引擎路径同样指向临时目录，
没有使用真实对象测试输入。此前的隔离反例与修复前失败均保留在外置记录中。
日志由本地集成执行记录管理：`.glm53-batch/integration-steps-0-2/RESULT.md` 与
`logs/fix-atm-owner-hostile-env.log`（仓库外）。文档另核对链接和工作树源码审计。
原 D03 的 170 项/前端未运行记录只属于原任务快照，保留在原成果目录，不作为当前验收状态。

以下仍未验证：三平台原生 GUI、Linux 私有真实 keyring、Windows DPAPI 与专属文件用例、
macOS Keychain/原生文件行为、真实引擎安装、真实技能根和额度端点；macOS Intel/universal
及分发签名也无本次证据。历史 CI 绿勾和历史 C# 报告不能替代这些验证。

## 7. Rust 分发迁移时点局部证据（2026-10-26，历史检查点）

受测基线 `df63e0c6bc4acb29d8df508b9f2b62c62b87fdda` 加
`codex/harness-rust-migration` 未提交工作区，Linux x86_64。当前已执行：

- `cargo check --locked --offline -p atm-cli --tests` 通过。
- `cargo test --locked --offline -p atm-core --test harness --test harness_embed --test harness_machine --test harness_process`：13 项通过。
- `cargo test --locked --offline -p atm-cli --test cli -- --skip rust_distribution`：11 项保留的本地 CLI 回归通过。
- `cargo test --locked --offline -p atm-cli --test cli rust_distribution`：6 项通过；CLI 子进程 PATH 为空，临时 Unicode/空格路径，删除来源后仍从完整缓存完成生命周期。
- `python3 -m py_compile scripts/Package-Release.py scripts/Test-Distribution.py` 与 `bash -n scripts/Verify-Local.sh` 通过。
- `cargo clippy --locked --offline -p atm-cli --all-targets -- -D warnings`、CI YAML 解析及所改文件 `git diff --check` 通过。
- `scripts/Test-Distribution.py --cli-only` 对合成 debug CLI-only 抽取包通过空 PATH/离线缓存生命周期；证据保存在 `/tmp/atm-cli-only-migration-smoke-ete939c9/smoke.log`。未包含桌面发布二进制，不是完整 release 或 GUI 验证。

首次 payload fixture 使用词法 `../../` 路径，来源校验正确拒绝；fixture 改为规范绝对路径
后通过。真实内容的 Codex 规划回归随后发现 `agents/operating-principles.md` 未进入封存清单；补齐来源库存后完整 CLI 17 项通过。完整 Rust/前端/payload 集成和发布包验证应以最终交付报告补充，以上计数不包含它们。
新分发的 Windows/macOS 原生行为、真实 Codex 集成、真实旧状态交接、真实 venv 和用户配置
均未执行；旧 CI 通过记录不填补这些边界。本轮没有部署、提交、推送或刷新真实 ATM 入口。

## 8. 合并与 main 的原生 CI 证据（2026-10-27/28）

本节取代第 6/7 节“三平台原生 GUI、Windows DPAPI 合成用例、完整发布包抽取未执行”清单中
已由 CI 覆盖的部分；真实客户端、真实用户会话与真实外部环境仍按第 6 节边界对待。
引用任一 run 必须核对其精确提交：

- run [40441691206](https://github.com/zzzhty/ai-tooling-manager/actions/runs/40441691206)（PR #6 head 430e19e，7/7）：Windows 路径保留、原生 GUI/keyring 与完整包。
- run [40519377781](https://github.com/zzzhty/ai-tooling-manager/actions/runs/40519377781)（PR #7 head 8ea55b1，10/10）：ATM 0.2.0 绑定 OMH 1.1.0，含三平台 cli-only 与锁定源 Python 作业。
- run [40624948561](https://github.com/zzzhty/ai-tooling-manager/actions/runs/40624948561)（PR #8 head，10/10）：OMH 源锁刷新至 revision b0ea608。
- run [40627262161](https://github.com/zzzhty/ai-tooling-manager/actions/runs/40627262161)（main ebc046d）：全部作业通过。

作业覆盖：`cli-only`（三平台 CLI-only 包空 PATH/离线生命周期）、`core`（fmt/clippy 与合成测试）、
`python-payloads`（锁定 OMH 源的内容语义测试）、`linux-desktop`（真实隔离 Secret Service 生命周期
Test-LinuxKeyring.sh、原生 GUI 冒烟、完整包抽取）、`desktop`（Windows：Windows core synthetic
tests `cargo test --locked -p atm-core -p atm-cli --all-targets`、桌面服务元数据测试、Tauri 构建
与 Test-TauriGui.ps1 冒烟、包抽取）、`macos-desktop`（Verify-MacOS.sh 原生隔离验证与包抽取）。
CI 定义存在不等于通过；工作流或受测源码再变更后需重新对应精确提交。真实客户端加载/调用、
真实用户会话存储、真实外部 venv 与真实安装交接仍未验证。
