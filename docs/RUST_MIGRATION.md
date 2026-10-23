本地 Codex/GLM 与 Linux 扩展见 [本地实现与验证记录](CODEX_GLM_LINUX.md)。以下说明保留 Windows V1 格式契约与历史互通边界；当前验证入口见第 2、5 节。

# Rust/Tauri 迁移、互通与验证边界

本说明描述 Rust/Tauri 的设计与有条件兼容边界。重建前的 C# 源码、开发分支和验证证据保留在私有历史档案；当前源码树不包含旧实现或旧 Git 历史。当前版本的测试结果应按本次提交重新核实。

实现完成、代码检查、测试通过和实际 Windows GUI 可用是不同结论。此文描述格式契约与验证边界，不替代所用精确提交的 CI 结果。私有档案中的旧截图和 C# 测试结果只覆盖历史基线；当前 [验证入口](验证报告.md) 不承接历史通过声明。

## 1. 数据格式契约

### 密钥库

两种实现使用 `%LOCALAPPDATA%\LocalKeyManager\vault.dpapi`，以 Windows DPAPI **CurrentUser** 加密整份 UTF-8 JSON：

- 固定附加 entropy 是 UTF-8 字节 `LocalKeyManager/v1/CurrentUser`。
- 使用 UI_FORBIDDEN，不设置 LOCAL_MACHINE。
- 明文根字段为 `Version`、`Keys`、`Targets`，`Version` 为 `1`。
- 每个 key 为 `Id`、`Name`、`Secret`、`UpdatedUtc`。
- 每个 target 为 `Id`、`Label`、`FilePath`、`Pointer`、`KeyId`、`BearerPrefix`、`ReplaceVariables`。
- 标识符使用 UUID/GUID 字符串；时间使用可互读的 ISO-8601/RFC3339 时间戳。修改操作可以更新时间或列表顺序，不能要求 JSON 或密文逐字节相同。
- 同一 `vault.lock` 阻止两个窗口同时打开该存储。切换版本前必须关闭另一个版本。

这不是跨机器密钥迁移格式。相同 entropy 不能替代 Windows 用户 DPAPI 凭据；换用户、换电脑、丢失用户配置或重置系统后不能保证可恢复。没有主密码、明文导出或远程恢复服务。

### 完整备份

两种实现都在同一存储下的 `backups` 目录写入 `.lkmbackup`。整个载荷使用相同 DPAPI 参数，明文 V1 字段为：

- `Version`: `1`
- `FilePath`: 已规范化的原文件绝对路径
- `OriginalBytes`: .NET `byte[]` 对应的 **Base64 字符串**，不是 JSON 数字数组
- `OriginalHash`: 原始完整字节的 SHA-256 大写十六进制字符串
- `ExpectedAfterHash`: 预计替换后完整字节的 SHA-256 大写十六进制字符串
- `CreatedUtc`: 创建时间

回滚恢复完整原始字节，包括编码、BOM、空白、注释和换行。当前文件必须匹配预计写入内容或原始内容；已有后续编辑时拒绝覆盖。回滚本身会先加密备份当前文件。Rust 只允许回滚自身已知 `backups` 目录中的备份。备份包含原绝对路径，因此移动配置或存储后不能假定可直接恢复。

历史备份可能不符合当前模板 schema。整文件回滚有意恢复历史原字节，不用当前 schema 修改或阻止这些字节；这是独立的回滚确认流程，仍受内容/时间/文件身份校验与后续编辑冲突保护。

### Rust 模板旁存文件

`templates.dpapi` 是单独的、CurrentUser 加密的 Rust 元数据文件，记录版本、已确认模板及 target ID 的绑定；不在 C# V1 模型中添加新字段。

- C# 可忽略此文件并继续读取 V1 vault/backup。
- C# **不会执行 Rust 的模板白名单和 schema 限制**。使用旧版应用会回到旧版的手动 JSON Pointer 行为。
- Rust 保存绑定时记录映射的路径、Pointer、key ID、Bearer 和变量替换选项。若 C# 或其他版本改变这些映射语义，Rust 拒绝静默沿用绑定，要求重新确认。
- `templates.required` 标记用于检测模板旁存文件被意外删除：标记存在而 `templates.dpapi` 缺失时拒绝启动。这不是对抗同用户篡改的安全边界；拥有文件访问权限的用户删除两者时不能由该标记检测。
- C# 删除/重建映射后，Rust 保留的孤立绑定仍对同一文件执行模板保护；不能靠更换 target ID 静默绕过。没有活动映射使用模板时，用户显式删除 Rust 模板可以同时清理对应孤立绑定。
- vault 与模板元数据是两个文件，不能声称是跨文件原子事务。写入顺序和漂移校验用于失败关闭；异常后应检查提示，重新保存/确认目标，不能删除旁存文件来当作修复步骤。
- 备份或保留迁移前存储时同时保留 `vault.dpapi`、`backups` 和存在的 `templates.dpapi` / `templates.required`。不要公开上传这些文件，也不要将它们当作跨用户的便携备份。

## 2. 当前测试与历史互通边界

当前源码树提供 Rust 核心、CLI 和桌面服务的合成测试：

```bash
cargo test --locked -p atm-core -p atm-cli -p atm --no-default-features --all-targets
```

平台相关测试只在适用系统执行；前端和原生 GUI 入口见 [README](../README.md) 与
[验证入口](验证报告.md)。普通测试使用假密钥及临时目录，不读取用户凭据或现有配置。

早期 C# ↔ Rust 双向互通脚本、C# fixture 项目和 Rust interop 测试已随旧实现归档，
不在当前源码树或 CI 中。不能将当前 Rust 测试通过解释为旧 C# 与当前版本的互通验证。
上文的 V1 字段、DPAPI entropy、Base64 原字节和回滚格式仍是保留的兼容契约。
如需恢复旧版迁移或回退支持，应先取得对应历史实现，在同一 Windows 测试用户下以
隔离假数据重新验证双向读写、备份回滚及损坏密文拒绝；本仓库当前不提供该验收入口。

## 3. 精确字节补丁的范围

Rust 保留与基线相同的核心目标：只改用户选中的现有 JSON/JSONC 字符串叶节点。

- 接受标准 JSON、行/块注释和尾随逗号；精确 JSON Pointer 支持转义属性名及数组索引。
- 拒绝缺失字段、非字符串目标、重复对象名、重复目标、非法结构和模糊定位。没有通配符、递归搜索、按值全局替换或自动创建字段。
- 支持严格 UTF-8（有/无 BOM）和带 BOM 的 UTF-16 LE/BE；拒绝 UTF-32、破损编码及不支持格式。配置限 16 MiB，JSON 深度限 64、节点限 100,000。
- 保留原文件所有非目标源字节。替换字符串本身按 JSON 正确转义；这是局部字符串 token 的编码，不是重写整份 JSON。
- 默认保护变量引用；用户逐映射明确开启后才替换。Bearer 前缀按映射选择，防止重复添加。
- 模板不放宽本机路径、符号链接/联接、多硬链接、备份、并发冲突和单次预览规则。
- 每个文件独立原子替换，不是跨文件事务；Windows 最终检查与路径替换之间仍存在很短竞态。进程中止可能留下同目录明文 `.lkm-*.tmp`，应用会报告能够检测到的清理失败。

## 4. 模板与 schema 的实际范围

### 候选、确认和来源

模板包含应用描述/文件名提示、格式版本、来源种类及来源版本、精确字段绑定、写入白名单、补丁选项默认值和 schema。应用名称只是提示，不授权自动找文件或写文件。

从一个用户选定的样本推断时，仅推断观察到的类型/结构和字符串位置；不会推断必填性或禁止额外字段，也不会把样本值复制成 `default`、`const` 或 `enum`。保存为可复用模板前，用户必须审查 schema 并明确选择字段白名单。候选结构并不是官方 schema，也不能证明样本具有完整代表性。

属性名、路径和文件名提示仍会保留。名称本身可能含用户名、租户名甚至误放的密钥；用户提供的 schema 字段名和 `pattern` 等约束也可能含敏感字面量。因此不能宣称模板完全匿名；应先检查，且模板默认仅加密保存在本机。没有内置官方 Z Code、VS Code 或 Visual Studio 模板，也没有从网络下载 schema 的流程。

### 严格的本地 2020-12 子集

根 schema 必须明确声明 `$schema: "https://json-schema.org/draft/2020-12/schema"`。schema 文本中的重复属性名会被拒绝。先限制规模、审查关键字/引用图、验证 schema 本身，再本地编译验证器。当前接受的约束类别包括：

- `type`、对象属性、必填项、依赖项、额外属性和属性名约束
- 数组元素/前缀元素、长度、唯一性和 `contains` 约束
- 数值界限和倍数、字符串长度/正则/已支持格式
- `allOf` / `anyOf` / `oneOf`、`not`、`if` / `then` / `else`
- `$defs` 及指向同一文档中已识别 schema 节点的 fragment JSON Pointer `$ref`

完整关键词白名单以 `crates/atm-core/src/templates.rs` 的 `inspect_schema` 为准。其他草案、嵌套方言、未知关键词、远端或外部文件引用、锚点、URI 编码引用、循环引用和过深引用都会被拒绝，不会忽略后继续。`default`、`examples`、`example`、`const`、`enum`、`title`、`description` 和 `$comment` 不进入可复用 schema。正则使用受限引擎，未知/不支持的格式与无法编译的正则不降级；这并不是任意标准 schema 都可接受的完整实现。

绑定模板的文件只允许白名单内、绑定中列出的现有字符串位置。准备阶段在内存里生成同样的精确字节补丁，再对**整份待写配置**进行严格 schema 验证；失败时不写入。结构/约束漂移提示不会包含原始配置值或验证器原始错误。未绑定模板的原有手动映射保留原 JSON Pointer 工作流。

## 5. Windows 验证与安全试用

先安装/准备开发工具，而不是让测试脚本悄悄安装：Rust stable 的 Windows MSVC 工具链、Visual Studio C++ Build Tools/Windows SDK、Node 22、WebView2 运行时。使用仓库锁文件还原依赖；npm/Cargo 还原可以联网，运行中的配置/schema 处理不联网。当前 Rust 构建不依赖旧 C# 项目或 .NET SDK。

```powershell
npm ci
npm run check
npm test
npm run build
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo test --locked -p atm-core -p atm-cli --all-targets
cargo test --locked -p atm
npm run tauri:build
.\scripts\Test-TauriGui.ps1
.\target\release\atm-desktop.exe --demo
```

`--demo` 必须保持隔离假数据模式；不带此参数才使用默认真实存储。GUI 冒烟使用独立的进程级 `LOCALAPPDATA`，验证 Windows 窗口、实际渲染控件和小窗口尺寸，并产生合成截图。它不等于完整人工可用性测试，也不覆盖所有文件选择器、可访问性、DPI、显示器和操作系统组合。前端 DOM 测试不能代替 WebView2 集成测试。

在缺少 Windows 环境时，可运行支持的平台无关 Rust/前端检查，但 DPAPI、文件锁、替换、跨语言互通和 GUI 必须标为未执行。不能因为 Linux 的 `cargo test` 通过而宣布 Windows 可用。

## 6. 历史同用户迁移与回退条件

以下是保留的历史流程，当前仓库缺少第 2 节所述的互通验收入口，不能直接据此宣称迁移或回退可用。

1. 核对要使用的精确提交，要求 C# 基线测试、Rust/前端检查、Windows 核心测试、双向互通、Tauri 构建和隔离 GUI 冒烟均有对应结果。先运行 `--demo`，仅使用假数据检查交互。
2. 关闭所有管理器窗口，保留原 C# 发布包。由用户自行保留本机存储目录中的加密文件及备份；不要解密、导出、上传或拿真实配置当测试夹具。
3. 在同一 Windows 用户下打开 Rust 版。正常 V1 存储不需要格式转换；先核对遮罩密钥列表、映射和备份，再选择目标生成预览。没有自动扫描、自动应用或自动迁移真实配置。
4. 如读取、版本或完整性校验失败，停止使用该文件，不允许“尝试修复”覆盖原存储。保留失败副本，在原 C# 版能正常读取的前提下由用户检查条目；不可通过忽略验证、解密导出或改版本号绕过问题。
5. 需要回退时先关闭 Rust，再以同一用户启动原 C# 版。V1 vault/backup 应按已通过的互通范围可读，保留 Rust `templates.dpapi` 和 `templates.required`。牢记 C# 不执行模板约束；对真实文件的每次写入仍须重新预览确认。
6. 从 C# 再回 Rust 时，检查模板绑定漂移提示。若旧版编辑改变了路径/字段/key 关联/选项，重新检查并明确保存绑定。用户配置的后续手工编辑仍会阻止回滚；没有强制覆盖模式。

以上是有条件的同用户兼容迁移方案，不是已经替用户迁移真实数据的声明。本次开发和测试仅使用合成假数据。
