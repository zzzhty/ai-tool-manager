# 源码交接（历史快照说明）

本仓库的初始导入（2026-10-23，d1c90f0 世代）是一次经过审查的 Rust/Tauri 源码快照交接；
自那以后的开发走正常分支/PR 工作流（PR #1 起完整保留在 Git 历史），本页不再是当前进度入口。
早期交接提交、云端恢复过程、原 C# 基线及开发日志保留在私有历史档案，不随干净源码导入。

运行入口、权限边界与开发命令见 [README](../README.md)、[Rust 说明](RUST_MIGRATION.md)
和 [验证入口](验证报告.md)。仅用合成密钥与隔离配置验证；macOS 集成范围与独立验收见
[平台计划](pending-platform-work.md) 和 [macOS 入口](MACOS.md)；当前分发工作流见
[Harness 使用文档](HARNESS_USAGE.md)。
