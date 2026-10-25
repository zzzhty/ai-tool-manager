# 跨平台合成验收矩阵与操作手册

本页按当前实现区分文档声明、源码能力与实际验证。它是验收入口索引；
操作语义以代码为准，执行状态以第 6 节所列环境、受测代码范围和日志为准。

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

下表“本次”指第 6 节的 Linux 集成验证；所有平台原生验证状态分别列出。

| 功能 | D/C：当前实现与测试入口 | T：本次已验证 | 未验证边界 |
| --- | --- | --- | --- |
| Linux 安全存储 | Secret Service 存主密钥，AES-GCM 加密 vault/templates/backups；[linux.rs](../crates/atm-core/src/linux.rs)、[Linux 回归](../crates/atm-core/tests/linux.rs) | 内存密钥注入下的加解密、权限、配置替换与备份回归通过 | 真实 Secret Service 生命周期未运行；该测试在本次常规测试中为 ignored，CI 私有 keyring 作业会显式启用 |
| Windows 安全存储 | DPAPI CurrentUser 加密整包；[windows.rs](../crates/atm-core/src/windows.rs)、[parity 的 Windows 用例](../crates/atm-core/tests/parity.rs) | 无原生 Windows 执行证据 | DPAPI、Windows 文件替换、WebView2 均未验证 |
| macOS 安全存储 | Keychain 专用条目 + AES-GCM；[macOS 说明](MACOS.md)、[macos.rs 测试](../crates/atm-core/tests/macos.rs) | 部分共享逻辑/模拟后端可在 Linux 测试；不构成 macOS 证据 | macOS 原生用例、真实 Keychain、GUI 未运行；CI 目标为 arm64，Intel/universal 未验证 |
| 批量更新、JSONC、模板与回滚 | [batch.rs](../crates/atm-core/src/batch.rs)、[JSONC parity](../crates/atm-core/tests/parity.rs)、[模板测试](../crates/atm-core/tests/templates.rs)：逐文件原子替换、完整加密备份、精确源字节和本地 schema 校验 | 共享核心与 Linux 回归通过，含 T01 新增冲突/确认/备份边界和 P01 无转义解析、Unicode/控制字节回归 | Windows/macOS 专属文件语义未验证；合成性能收益不等于 GUI 延迟收益 |
| Codex / GLM 额度 | [usage 测试](../crates/atm-core/tests/usage.rs)、[Codex 子进程测试](../crates/atm-core/tests/codex_process.rs)；未知值保留未知，固定端点/argv，主动查询 | 合成协议、错误和进程边界测试通过 | 未查询真实账户或额度端点 |
| 内置引擎记录与机器协议 | [omh.rs](../crates/atm-core/src/omh.rs)、[omh_machine.rs](../crates/atm-core/src/omh_machine.rs)、[前端测试](../apps/desktop/tests/omh.test.ts) | 记录解析、合成协议/进程边界通过；已覆盖 operation.command、旧 kind/operation 字段兼容与 degraded 显示 | 未运行真实引擎安装（隔离 bootstrap E2E 需单独执行）；未将记录查询迁移为 machine status，也未改变命令 allowlist |
| 内嵌引擎物化与收编 | [atm_embed.py](../omh/scripts/atm_embed.py)、[omh_embed.rs](../crates/atm-core/src/omh_embed.rs)、[test_atm_embed.py](../omh/tests/test_atm_embed.py)、[omh_embed 测试](../crates/atm-core/tests/omh_embed.rs) | 物化/幂等 sync/旧 git 收编/拒绝条件/无 git 运行/漂移拒绝/argv 限幅通过（Python + Rust 双侧） | 真实 manager home 迁移需单独授权；Windows 仅经 CI 测试矩阵覆盖 |
| 技能、回收站、投影与 CLI | [skills 测试](../crates/atm-core/tests/skills.rs)、[projection 测试](../crates/atm-core/tests/projection.rs)、[CLI 测试](../crates/atm-cli/tests/cli.rs) | Linux 临时目录中的复制、符号链接投影、所有权拒绝、回收恢复和 CLI 通过，含 T02 | macOS 虽共用 POSIX 实现，原生未测；Windows 为普通复制投影，foreign-slot 断言已修正但未在 Windows 运行；真实技能根未访问 |
| 前端 | [组件测试](../apps/desktop/tests)、TypeScript 与 Vite | 88 项通过，类型检查与前端构建通过 | 前端测试/构建不能代替 Tauri 原生启动和 GUI 验证 |

内置引擎（物化于 manager home 的 `<home>/repo`）在三平台均以管理目录内的 venv Python 加
`repo/scripts/omh.py` 绝对路径执行：Windows 为 `venv/Scripts/python.exe`，Linux/macOS 为
`venv/bin/python`，不经 shell shim。记录查询仍使用 `status --json`；能力/诊断/变更走
machine v1。CLI 表面为动词优先语法（`atm install/update/uninstall/check/repair skills
--harness …`、`atm install/uninstall/check hooks --harness codex`、维护组 `atm harness
bootstrap|sync|status` 与 `atm harness --` 逃生口）；实际可用性仍取决于当前引擎
capabilities、明确目标和确认要求；recover/update 在嵌入模式明确拒绝。详情见
[README](../README.md#内置技能分发引擎harness)。

### 原生 GUI 入口与 PASS 的含义

| 平台 | 入口与前置条件 | 代码中已有的检查 | 本次状态 |
| --- | --- | --- | --- |
| Linux | [Test-LinuxGui.sh](../scripts/Test-LinuxGui.sh)；CI 私有 RUNNER_TEMP、X11/xvfb 与 D-Bus；二进制必须以 `--features smoke-tests` 构建 | WebKit 渲染、resize、合成 IPC；Linux/macOS 共用 [native_smoke.js](../apps/desktop/src-tauri/src/native_smoke.js) 驱动确认/取消/重复应用拒绝、写入与回滚、capability 拒绝；Rust 检查最终原文与两份备份 | 未执行 |
| Windows | [Test-TauriGui.ps1](../scripts/Test-TauriGui.ps1)；Windows、WebView2、原生 exe、隔离 LOCALAPPDATA 与 `--demo` | 启动、UIA 可访问性文本、小窗 resize 和截图；未驱动完整写入/回滚流程 | 未执行 |
| macOS | [Verify-MacOS.sh](../scripts/Verify-MacOS.sh) → [Test-MacOSGui.py](../scripts/Test-MacOSGui.py)；macOS 图形会话、工具链/缓存，smoke-tests 构建 | 共用原生 IPC 流程；父进程额外独立观察磁盘写入/回滚、0600 备份、暂存与进程组清理 | 未执行；无真实 Keychain 证明 |

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
OMH 管理目录覆盖。应用的 `from_environment()` 仍尊重这些环境配置，不能用它创建合成 fixture。
回归以独立子进程注入外部假目录并检查目录未变，不在并行 Rust 测试中修改全局环境。

`ATM_TEST_OMH_CHECKOUT`、`LKM_OMH_LIVE=1` 和 `LKM_SKILLS_LIVE=1` 分别启用真实
引擎 checkout、真实引擎安装和真实技能盘点；`LKM_OMH_PYTHON_STRICT=1` 要求
Python 工具依赖可用（否则 Verify-Local 的引擎套件判失败）。未设置时对应三个测试提前返回并计 passed；
因此通过总数包含这些空返回，不能据此宣称真实对象已测。`Verify-Local.sh` 强制关闭三项；
若直接运行 Cargo，须由调用者在测试子进程中关闭它们。真实对象验证必须单独明确选择入口。

### 原生平台流程

- Linux 私有 keyring：遵循 [linux-desktop CI 作业](../.github/workflows/rust-ci.yml) 的完整
  私有目录和 D-Bus 设置；[Test-LinuxKeyring.sh](../scripts/Test-LinuxKeyring.sh) 要求
  `CI=true`、`LKM_ISOLATED_KEYRING_TEST=1`、受限 `LKM_TEST_ROOT`。它会创建并重开专用
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
使用假配置/额度数据，拒绝真实 OMH 和技能变更。Linux/macOS 使用内存密钥；
**Windows 演示使用真实 DPAPI API 加密合成数据**，不是内存密钥实现，见
[demo_protector](../crates/atm-core/src/storage.rs)。三者均不打开默认真实 vault，
但演示结果不证明真实用户目录、生产密钥生命周期、长期运行或跨机器迁移可用。

## 4. 兼容身份与平台差异

| 维度 | Linux | Windows | macOS |
| --- | --- | --- | --- |
| 生产保护后端 | Secret Service + AES-GCM | DPAPI CurrentUser | Keychain + AES-GCM |
| vault/templates | `.lkmvault` | `.dpapi` | `.lkmvault`，平台专用头 |
| 默认数据根 | `$XDG_DATA_HOME/local-key-manager`，回退 `~/.local/share/local-key-manager` | `%LOCALAPPDATA%/LocalKeyManager` | `~/Library/Application Support/LocalKeyManager` |
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

## 6. 本次集成验证状态（2026-10-25）

2026-10-25 验证时，受测状态为基线 `3156a541537ec0e4530f464ab2ce5a6a33bf30da` 加当时未提交的 T01/T02、
OMH command/degraded 修正、P01 JSONC 优化/回归，以及最终复审后的显式技能根隔离修复；
不是该基线提交本身的通过声明。环境为 Linux x86_64、rustc/cargo 1.95.0。
修复后完整 `Verify-Local.sh` 退出 0：Rust **185 passed / 1 ignored**，前端 **88 passed**，
fmt、Clippy、tsc、build 与 93 文件审计通过。ignored 为私有 Secret Service 生命周期；
另有上述 opt-in 空返回。

该次完整验证的父环境注入了六个外部假技能根，并显式开启三个 live opt-in；脚本关闭
opt-in 后验证通过，六个假目录内容保持不变。HOME/XDG 与 OMH 路径同样指向临时目录，
没有使用真实对象测试输入。此前的隔离反例与修复前失败均保留在外置记录中。
日志由本地集成执行记录管理：`.glm53-batch/integration-steps-0-2/RESULT.md` 与
`logs/fix-atm-owner-hostile-env.log`（仓库外）。文档另核对链接和工作树源码审计。
原 D03 的 170 项/前端未运行记录只属于原任务快照，保留在原成果目录，不作为当前验收状态。

以下仍未验证：三平台原生 GUI、Linux 私有真实 keyring、Windows DPAPI 与专属文件用例、
macOS Keychain/原生文件行为、真实 OMH 安装、真实技能根和额度端点；macOS Intel/universal
及分发签名也无本次证据。历史 CI 绿勾和历史 C# 报告不能替代这些验证。
