---
status: accepted
---

# Provider 出口代理绑定

日期：2026-10-29。用户已接受 Provider → 出口代理绑定的架构方向；具体数据模型、适配器和命令仍为 proposed，尚未实施。

## 背景

用户需要指定 provider 使用指定出口，其他 provider 保持独立。出口服务的部署是独立需求，本决策只定义 ATM 的绑定与应用适配。

本地基线为 `bba9d8b6adf9ebdac9c9bccd867f243dd2ed2acc`。ATM 负责凭据、精确配置和内容分发，尚无通用 provider 实例模型或推理网关；GLM 额度通过固定端点直连，Codex 额度由外部 app-server 发起。仅修改 ATM 自有 HTTP client 不能覆盖外部工具推理。

## 决策

采用稳定 provider 身份绑定命名 ProxyProfile。每个显式绑定选择 direct 或指定代理，代理失败报错、不静默直连；未配置的旧路径维持原行为并显示未管理。新增独立网络 service 供 CLI/桌面调用，复用安全存储；不把现有 key UUID、target UUID 或额度来源枚举重新解释为通用 provider 身份。

先实现自有 transport 与经证实的客户端适配。外部工具优先原生 provider 级配置；只有进程级能力时使用受限启动器并说明影响。多 provider 同进程无法隔离时明确不支持，确有需求再评估 loopback API 转发。连通性、额度和实际调用分别记录证据。

ATM 消费独立代理端点，不接管出口服务生命周期、系统 VPN 或默认路由。HTTP CONNECT/SOCKS 不能透明识别 HTTPS 路径；系统 IP 路由不能替代 provider 身份绑定。

## 后果与边界

网络状态需要版本化与明确迁移，既有持久化标识及历史证据保持。凭据不进入代理 URL、日志或明文配置；保留 TLS 校验和官方额度端点限制。第一阶段无需建立网关，但完整指定工具体验仍需该工具 adapter 验收。独立出口的路由和可用性由该服务验证，不以 ATM 的绑定状态替代。

本次仅记录方案；不实现代码、不变更真实网络/账户、不迁移用户数据、不提交或发布。详见 [设计、阶段与验收](../PROVIDER_PROXY_DESIGN.md)。
