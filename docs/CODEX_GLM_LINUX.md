# Linux 存储与额度接口

Linux 生产存储通过 Secret Service 的加密会话保存应用主密钥，使用 AES-256-GCM
加密 vault、模板侧车与备份。创建主密钥需要明确确认；锁定、重复或格式不合法的条目
会明确失败。生产数据目录需为用户所有且权限为 0700，文件为 0600；拒绝符号链接和
不受支持的共享文件系统。测试通过实例注入 TEST_ONLY 主密钥和临时目录。

Windows 使用当前用户 DPAPI；平台密文不能据此解释为可跨用户或跨操作系统互解。
具体存储边界与显式应用流程见 [Rust 说明](RUST_MIGRATION.md)。

Codex 额度从用户独立安装的 CLI 读取，按多桶 `rateLimitsByLimitId` 优先，兼容
`rateLimits`。只有有效百分比才计算剩余额度；`ordinaryUsageAllowed` 必须明确为
true 才展示普通额度窗口。API key 模式与订阅额度分开，不自动登录或刷新凭据。

GLM 通过所选地区的固定官方监控端点读取；不自动切换地区，也不把缺失字段解释为
无限额度。网络错误和许可边界由应用显示。公开 URL、依赖摘要与协议常量应保留。

## 验证

前端通过 `npm run check`、`npm test`、`npm run build` 验证。Rust 合成测试使用
`cargo test --locked -p atm-core -p atm-cli -p atm --no-default-features --all-targets`。
`scripts/Verify-Local.sh` 使用离线依赖缓存；原生 GUI 和 Secret Service 验证需要独立
的隔离环境。工作流存在、历史验证记录或前端测试通过都不证明当前提交的完整平台
验收成功。不得用真实 keyring、vault、登录目录或账户额度查询补做本地验证。

## 默认 ACL 与配置暂存

新 inode 可能继承父目录默认 ACL，即使从其他目录移入的原配置没有访问 ACL。配置写入会在写明文前检查新暂存文件的扩展元数据；遇到继承 ACL/扩展属性时以 `STAGING_SECURITY` 拒绝，保留原配置并由既有路径清理暂存，不自动清除 ACL 或更改目录权限。专项测试只使用临时目录与合成值；不能设置默认 ACL 的测试环境明确报告未验证。
