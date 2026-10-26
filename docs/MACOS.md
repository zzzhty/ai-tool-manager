# macOS 支持与隔离验证

macOS 使用 Darwin 文件系统接口和 Security.framework，不复用 Linux 的系统调用 ABI。
原生 GUI、文件替换和密文包均需按当前提交验证；源码存在不代表已通过跨平台验收。

## 存储与兼容边界

数据目录使用 `$HOME/Library/Application Support/atm`；macOS 主密钥的 service/account 固定为
`com.ai-tooling-manager.desktop.storage.v1` / `macos-aes-gcm-master-v1`。
`vault.atmvault`、`templates.atmvault` 和加密备份使用 AES-256-GCM，认证头为
`LKM-MACOS-V1\0`。Linux/Windows 既有身份与格式不变；不承诺跨电脑或跨平台解密。

读取不创建 Keychain 条目。初始化必须明确确认；缺失、重复、无效、锁定、拒绝访问及
初始化竞态均失败关闭。已有加密数据缺主密钥时，不创建替代密钥。不自动解锁、不覆盖
条目、不回退明文，也不通过 shell/argv 传递主密钥。

普通测试及 `--demo` 注入内存密钥，不访问真实 Keychain。真实 Keychain 生命周期、
用户数据迁移、安装、Developer ID 签名、公证与分发需要独立授权和验收。

## 文件、工具与进程

数据目录要求本人所有且 0700，加密文件与暂存要求 0600；不修复既有宽权限。
逐组件打开路径并拒绝用户链接、跳转、多硬链接及非普通文件。仅接受经过所有者与精确
目标验证的系统路径别名，以及本地 APFS/HFS+；网络/FUSE/未知文件系统拒绝。

同目录暂存后以目录 fd 锚定原子替换，保留普通模式、组和可审计扩展属性；不支持额外
ACL、资源叉或超出预算的元数据。内容、文件身份和时间戳变化使预览失效。最后校验与
替换之间仍有外部写入竞态，不保证跨文件事务。APFS 大小写语义按文件身份处理。

工具路径尊重 HOME 和各工具显式环境变量，不扫描登录凭据或 shell dotfiles。Codex
可执行文件及帐号目录须由用户指定为绝对路径。harness 分发由 ATM 内部 Rust service
直接执行，CLI 与 GUI 共用；bootstrap/sync 和静态技能无需 Python。仅显式选定的 Python
payload 通过绝对解释器路径准备独立 venv；准备不会启用 hooks。旧 Python 状态交接使用
`atm harness adopt`，中断恢复使用 `atm harness recover`。本次 Rust 分发迁移尚不能由
此前 macOS 原生 CI 通过记录推导为已验证；没有新增后台轮询或真实安装切换。

## 可复现入口

需要已有 Rust stable/rustfmt/clippy、Node 和 macOS SDK，以及锁定依赖缓存。缺少依赖时
明确报告未运行，不自行安装系统软件。准备完成后运行：

```bash
bash scripts/Verify-MacOS.sh
```

该入口执行 portable/source 检查、原生静态检查与合成测试，然后只用 Cargo 构建原生
可执行文件。它显式使用 incognito 窗口配置，不执行 bundler、签名、安装或发布。
`tauri.macos.conf.json` 与源生成图标保留应用包构建配置；包构建不是本入口的验证声明。

Python 父进程只复制新构建的测试二进制至临时目录，以显式 `--demo`、临时 HOME/data/
config/引擎根启动，核对同一 PID 的 argv/env。真实 WebView/Rust IPC 覆盖遮罩预览、
明确确认、应用、取消/重放拒绝与整文件回滚；另一个无 capability 的窗口必须产生真实
拒绝回执。控件点击等待 busy 解除；失败记录有限阶段并非零退出，不吞异常后等待超时。

父进程独立观察磁盘原文→假新值→原文，核对两个 0600 加密备份和暂存清理，并清理
受控进程组与临时数据。结果只含合成状态；不借助可能自动重启应用的 GUI 观察工具。
CI 的 arm64 门禁不代表 Intel/universal 已测；额度和引擎测试不代表真实账户或安装已测。
