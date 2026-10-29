# ATM Provider 出口代理绑定设计

日期：2026-10-29。架构决策：**用户已选定 Provider → 出口代理绑定**；功能、命令和配置格式均尚未实施。本文定义后续实施边界，具体字段和阶段安排为 proposed。

ATM 负责把明确的 provider 实例绑定到命名出口，并向受支持的请求路径应用该选择。出口由独立代理服务提供。ATM 不因此成为现有的推理网关，也不接管系统 VPN 或默认路由。架构决策记录见 [ADR 0030](adr/0030-provider-egress-proxy-binding.md)。

## 1. 目标与场景

- 指定 provider 的 API 请求使用指定代理，其他 provider 独立选择出口；同一域名下的两个 provider 配置也能拥有不同绑定。
- 同一代理 profile 可供多个 provider 使用；改名、轮换 API key 或调整 URL 不应丢失 provider 身份。
- 明确区分 ATM 自有额度查询、连通性测试、外部 CLI 的额度和实际推理调用；只有对应路径已被适配并验证，才能声明已生效。
- 新绑定默认在代理失败时报错，不静默直连，不关闭 HTTPS 证书校验。

本期不包括：自动部署服务器、改动真实网络与凭据、全局透明代理、按 IP 劫持整机流量、默认接入浏览器、自动登录或调用收费模型、自动选择最快节点、故障后自动换出口、首次就建设通用 LLM 网关。

### 1.1 Provider URL 的边界

Provider 的 API base URL、登录账户服务端点与浏览器页面不是同一个配置目标。API 地址由工具 adapter 绑定；OAuth、账户额度、遥测和更新端点需分别列入 adapter 的端点类别，不能由一个 API URL 推导全部域名。浏览器代理属于独立需求，不自动视为 ATM provider 接入。

HTTP CONNECT 通常接收目标主机和端口，SOCKS 接收目标地址；加密后的 HTTPS 路径对这些代理不可见。因此“指定 URL”在这里优先表示**指定 provider 实例发起的连接**，不是透明匹配任意 HTTPS URL 路径。若同进程、同域名的不同请求必须使用不同出口，需要客户端原生 provider 级能力或后续显式 API 转发，不能用系统 IP 路由替代。

## 2. 源码基线与现状

本地 checkout：`/home/zzzhty/Projects/ai-tooling-manager`；分支 `main`；HEAD `bba9d8b6adf9ebdac9c9bccd867f243dd2ed2acc`；origin `git@github.com:zzzhty/ai-tooling-manager.git`。相对首次核对的 `664a912f`，新增提交仅修改桌面包依赖与样式，本文相关 core/CLI 源码未变。以下是该本地版本的源码观察，不代表未来外部 CLI 版本能力。

| 位置 | 当前行为 | 设计影响 |
| --- | --- | --- |
| [model.rs](../crates/atm-core/src/model.rs) | `KeyEntry`、`TargetMapping`、version 1 `VaultDocument`；target 关联文件、JSON Pointer 与 key UUID | 没有通用 provider 实例注册表，不能把 key、target 或显示名直接当作 provider |
| [configuration.rs](../crates/atm-core/src/application/configuration.rs)、[batch.rs](../crates/atm-core/src/batch.rs) | 安全存储、精确字段配置、预览及应用 | 新网络配置通过共享 service 与精确 adapter 管理，不随意重写客户端配置 |
| [usage/mod.rs](../crates/atm-core/src/usage/mod.rs) | `usage::Provider` 只有 Codex / Glm，是额度来源分类；缓存按来源、地区、认证与凭据/账户证据隔离 | 保留原语义；新增稳定身份，不能直接扩大旧枚举充当所有业务 provider |
| [usage/glm.rs](../crates/atm-core/src/usage/glm.rs) | 固定两条官方 HTTPS 额度 URL、`no_proxy()`、不跟随重定向；连接 5 秒、总时限 12 秒；无自动重试 | 显式绑定才注入 transport；保留官方端点白名单与其余保护 |
| [usage/process.rs](../crates/atm-core/src/usage/process.rs)、[usage_service.rs](../crates/atm-core/src/application/usage_service.rs) | 启动用户选择的原生 `codex app-server`，指定账户目录，默认 24 秒 watchdog；父进程环境通常会被继承 | ATM 的 reqwest 设置无法改变该子进程流量；它也不是用户自行启动的所有 Codex 推理进程 |
| [atm-core/Cargo.toml](../crates/atm-core/Cargo.toml) | reqwest 0.12，启用 blocking / rustls-tls，未启用 socks feature | SOCKS 能力须单独实现和验证；不能只接受 URL 就宣布支持 |
| [storage.rs](../crates/atm-core/src/storage.rs)、[vault.rs](../crates/atm-core/src/vault.rs) | 平台 Protector、加密写入、锁与安全目录检查；Linux Secret Service，macOS Keychain，Windows DPAPI | 复用安全存储能力；后台 Linux 无会话 keyring 不能假设可用 |
| [CLI main.rs](../crates/atm-cli/src/main.rs)、[桌面 main.rs](../apps/desktop/src-tauri/src/main.rs) | CLI 目前主要提供 skills/harness；桌面调用额度服务 | 本文新 CLI 命令全部是草案；不将已有 skills 工具目录表当成网络能力表 |

ATM 当前主要管理密钥、配置与内容分发；没有透明承接外部工具推理请求的服务。相关既有约束见 [Linux 存储与额度接口](CODEX_GLM_LINUX.md)、[标识演进规则](agents/internal-identifier-evolution.md)和[验收矩阵](ACCEPTANCE_MATRIX.md)。

## 3. 数据模型与单一配置来源

以下是逻辑结构，尚非已发布 schema。新增网络 service 作为 CLI 与桌面的共同 owner；不把网络对象写入 OMH 内容、harness registry、receipt 或分发状态。

| 对象 | 拟议字段与约束 |
| --- | --- |
| `ProviderInstance` | 不可变随机 UUID `provider_id`；可改 `display_name`；provider 类型/协议；期望的 HTTPS `base_url` 与地区；可选 API credential 引用；`revision` |
| `ProxyProfile` | 不可变 UUID `proxy_id`；`display_name`；`protocol`、`host`、`port`；`dns_mode`；可选 `credential_ref`（代理用户名/密码均由安全存储读取）；连接/读取超时策略；`revision`；不含用户名密码 URL |
| `ProviderProxyBinding` | 一个 `provider_id` 只对应一个当前 route：`direct` 或 `explicit_proxy(proxy_id)`；`revision`；失败策略固定为 `error`；不自动尝试备用出口 |
| `ProviderAttachment` | 将 provider UUID 显式关联到受管理客户端实例/配置槽位和已知额度来源；记录 `adapter_id`、`tool_instance_ref`、工具原生 provider key / 精确配置位置、允许端点类别、适配器版本、配置指纹；一个物理槽位只有一个 owner |
| `RouteEvidence` | 内存中的配置版本、执行方式、测试对象、时间和结果；分别记录连通性、额度与真实调用，不保存正文或认证头 |

**身份规则：**既有 `TargetMapping.id`、key UUID、`usage::Provider`、文件路径和展示名称都保留原义。新 provider 由用户注册或经预览确认导入，不能按相同域名、相同 key 或相同显示名自动合并。一个 provider 可显式附着多个工具配置，多个 provider 也可共享同一个 key；共享 key 不共享路由。只改 URL/名称/凭据时保留 UUID、递增 revision 并使既有测试证据过期；移动配置文件必须显式重新关联，歧义不猜测。

基线没有通用 provider 对象，因此第一阶段只引入网络接入所需的最小注册表，不同时重构所有凭据、配置模板或工具目录模型。Codex 订阅额度若无法证明属于某个 API provider，作为明确的账户服务 attachment 处理；不得将 API provider 的绑定自动扩散到该账户。

### 3.1 存储与迁移

建议新增独立、版本化的加密 `network` 侧车文件，放在 `storage::data_directory()` 管理的应用数据目录，复用 `Protector`、私有目录、加密原子替换及同一配置锁。文件名和 JSON 字段在实施时确定；**不升级或隐式重写 version 1 vault、模板格式、既有 UUID 与历史记录**。该目录与 harness 的 `~/.atm` manager home 不应混为一谈。

代理认证使用新侧车内受类型限制的 secret 记录或经审查的统一 secret 服务，profile 只持有 `credential_ref`；复用加密机制而不是把代理密码塞进可随意导出到工具的 API key 列表。若最终决定扩展旧 vault，必须先盘点消费者并单列迁移、兼容与回滚步骤。此文只选架构，不授权数据迁移。

侧车读取失败、未知版本或引用缺失必须阻止对应受管理操作，不能当作“尚未配置”。只读启动不创建文件、不打开账户、不迁移已有配置。首次明确保存后生成版本 1 网络状态；加密备份也只能按已有平台解密边界恢复。

### 3.2 配置优先级与默认行为

1. 已显式绑定的 provider 使用该绑定；同一 adapter 的多个潜在来源若冲突，预览报错，不能凭顺序悄悄覆盖。
2. 连通性检查可显式试用一个未保存 profile；结果标为测试路由，不能变成长期绑定，也不能证明实际调用已生效。
3. 无绑定表示 `legacy/unmanaged`，维持原行为：GLM 额度继续直连；外部工具继续自己的配置和环境。它不是隐含 `direct`，UI 不宣称它已受保护。
4. 新建绑定必须明确选 `direct` 或具体 profile。ATM 自有 direct client 禁用自动系统代理发现；explicit client 也禁用自动发现后只安装所选代理，不让 `NO_PROXY` 或父环境意外绕过。
5. 外部 CLI 只在经验证的 adapter 中设置所需环境/原生字段。显式 direct 要清理该子进程的代理覆盖并检测原生配置冲突；显式 proxy 要处理大小写代理变量和 `NO_PROXY`。不能验证时标为未支持/冲突，拒绝受管理启动，不声称全机强制隔离。

不设置通用“全局默认代理”。解除绑定回到 legacy 可能恢复客户端原有直连，故回滚预览必须展示后果；安全恢复默认是暂停受影响的受管理调用，保持代理要求。

## 4. 传输与安全语义

### 4.1 协议、DNS、超时和失败

首个实现支持 **HTTP CONNECT 用于 HTTPS API**。代理地址和 provider URL 分开校验；profile endpoint 只允许明确 scheme、host、port，不接受 userinfo、path、query、fragment 或任意脚本。到远程 HTTP 代理的认证信息若未被 TLS 或独立加密通道保护会暴露，因此首期远程 HTTP 代理只用于已确认的私有加密通道，默认示例使用 loopback；具体出口服务部署属于独立需求。

第二步增加 `socks5h` 等明确远端 DNS 语义，并启用/验证 reqwest socks 功能。普通 `socks5` 的本地解析与远端解析不可混写。HTTP CONNECT 应把目标域名交给代理；测试目标域名解析发生位置，区分代理服务器本身的主机名解析。开启代理不代表整个操作系统 DNS 都被接管。HTTPS-to-proxy 的支持如需新增，必须另测代理证书和目标证书链。

拟议超时：连接代理/握手 5 秒；额度继续总时限 12 秒；连通性测试总时限可取 15 秒。流式推理应分开设置连接、首响应/空闲读取和取消策略，建议初始空闲读取预算 120 秒，最终按客户端协议实测调整；不得把额度的 12 秒硬上限套到长流。外部 CLI 的时限只有在原生能力已证实时才能设置，UI 标出不可控部分。现有 Codex 额度 24 秒 watchdog 单独保留。

代理连接失败、认证失败、DNS 失败、TLS 失败、超时都返回可诊断且脱敏的错误；不选择 direct、不尝试另一地区、不自动重发推理 POST。报错后由用户显式重新操作。已经送出的模型请求即使取消或断线仍可能计费，不能以“未收到回答”断言未执行。

### 4.2 目标限制和凭据

- GLM 仍只允许源码中的两条固定官方 HTTPS 额度端点，仍禁止重定向。选择代理改变传输，不改变请求目标、地区或认证来源。
- 对 API 请求默认拒绝携带凭据的跨源重定向；adapter 有明确业务需要时逐跳校验 scheme/host/port 和端点类别，移除敏感头，拒绝 HTTPS 降级。不得把 provider key 转发到代理认证字段，或把 `Proxy-Authorization` 发给上游 API。
- 保留目标 TLS 校验、SNI 与 host；不做 MITM、不安装代理 CA、不提供“跳过证书校验”捷径。CONNECT/SOCKS 隧道中的目标 HTTPS 内容仍由客户端与 provider 的 TLS 保护。
- 密码只通过安全输入进入加密存储和短生命周期内存，采用既有 `Zeroizing`/脱敏 DTO 模式；不得进入 profile URL、命令参数、日志、命令历史、明文配置、诊断包或前端 snapshot。日志仅含 ID、端点类别、状态码和时间，不含完整查询串、token 或请求正文。
- 部分 CLI 只能从含认证信息的代理 URL/环境读取密码。环境同样可能被同用户进程或转储读取；首期不把解密密码注入这种 adapter。可采用无密码 loopback 代理、工具受支持的安全认证接口，或将能力标为不支持。
- 删除仍有引用的 profile/credential 应拒绝并列出绑定，先显式解绑或迁移；profile 更新后取消旧连接池/证据，防止旧隧道继续被新请求复用。进行中的请求固定其开始时版本，切换不重放。

## 5. 各请求路径的适配顺序

| 路径 | 第一选择 | 能力与限制 |
| --- | --- | --- |
| ATM GLM 额度 / 自有连通性请求 | 在 core transport 注入已解析 route | ATM 可直接控制；仍需官方端点、授权及错误处理边界 |
| ATM 启动的 Codex 额度 app-server | 独立子进程 adapter | 需要核验选定 Codex 版本的代理变量/配置、账户端点和优先级；不代表用户的推理会话 |
| 外部 CLI 有原生 provider 级代理字段 | 精确写入该字段，或使用原生 provider 专属 client | 首选；必须按版本核验字段含义、DNS、凭据和是否作用于全部相关请求 |
| 仅支持进程级代理的外部 CLI | ATM 专属启动器向该进程注入经过验证的设置 | 会影响该进程内其他 HTTP 流量；需展示 OAuth/额度/更新等影响，不能保证多 provider 独立 |
| 同进程多个 provider 且无原生分流 | 暂列不支持；确有需求才考虑本地 API 转发 | 通用 `HTTPS_PROXY` 无法区分 provider 身份，同主机/不同账户更不能靠域名解决 |
| 用户从其他终端自行启动或未受管理的工具 | 展示未接管 | 保存绑定不会自动改变已存在进程，也不会全局修改 shell 配置 |

目前对 Codex、Claude Code、Gemini CLI、OpenCode、Z Code 等工具的原生 provider 代理字段、环境变量支持和流式协议，**均不在此文中宣称已验证**。ATM 中列有工具或能管理其 skills，不证明它支持网络代理。每个 adapter 的发布记录应包含工具版本、官方/源码证据、可覆盖流量、环境优先级和合成/真实验证级别。

启动器使用绝对可执行文件路径与 argv，遵循现有 Windows shim 限制，不拼接 shell 命令、不改父进程环境。Linux/macOS 的环境变量大小写、Windows 路径/大小写规则、带空格路径和退出信号分别测试；只修改已拥有字段，检查预览后的并发改动，保留其他用户配置。

### 5.1 仅必要时加入本地 API 转发

此项为后续有条件阶段，首期不实施。区别于 CONNECT 隧道：CLI 把 base URL 指向 loopback 服务时，该服务会处理上游 API token 与提示词/响应正文，必须单独评审。

- 只监听 `127.0.0.1`（需要 IPv6 时显式增加 `::1`），禁止 `0.0.0.0`/公网；使用最小权限用户及随机本地授权 token，拒绝无授权请求和不受支持的 Origin，防止浏览器或其他本地进程滥用。loopback 本身不能隔离同用户恶意进程。
- 每个受管理路由明确映射 provider ID 与固定上游 base URL；不接受请求携带任意上游地址，不成为开放代理。处理私网/元数据地址和重定向边界；确需私有 provider 另作显式配置。
- 明确选定一种上游认证模式：安全存储注入或经 adapter 验证的透传，不能将本地访问 token 当作 provider token；不落正文/认证头，不缓存敏感响应，不改写模型协议以掩盖不支持。
- 流式读取和转发 SSE，保留顺序、事件、错误及必要头；设置缓冲/并发上限和背压；客户端断开及时取消上游。校验慢消费者、首字节延迟、长连接、心跳、截断及取消。WebSocket/其他双向协议另列能力，不能以 SSE 成功代替。
- 不在网络失败后透明重放推理请求；除非上游具有已验证幂等契约并获明确策略授权。记录“可能已执行”的结果类别，避免重复计费。

## 6. CLI 与桌面交互草案

下面全部为 proposed，不可作为当前 ATM 的可执行命令；保留现有 CLI 的动词优先风格，参数最终由 schema/adapter 设计确定。

```text
atm add proxy --name cloud-exit --endpoint http://127.0.0.1:1055
atm list proxies --json
atm register provider --adapter <verified-adapter> --target <explicit-target>
atm bind provider <provider-id> --proxy <proxy-id>
atm bind provider <provider-id> --direct
atm check provider <provider-id> --scope connectivity
atm check provider <provider-id> --scope usage
atm run provider <provider-id> -- <absolute-cli-path> <args>
atm unbind provider <provider-id> --preview
```

`add/bind` 仅准备配置；涉及写外部文件时继续走预览、变更检查与显式应用。认证从安全提示输入，不接受明文密码 argv。`check` 默认先做本地校验；出站检查要求用户主动触发并显示目标、是否用凭据及端点性质，不调用生成模型。`run` 是用户实际启动工具，工具可能计费；它不是保存配置后的自动动作。

桌面建议提供“出口代理”列表和 provider 详情中的“出口”选择，选择直连或命名 profile，显示使用者与协议/DNS方式。应用前列出受影响的客户端实例、端点类别、执行方式和进程级限制。删除/修改 profile 时显示受影响绑定，原本不受支持的路径继续显示未覆盖。

每个 provider 分列：

| 状态项 | 可用文字示例 | 证据边界 |
| --- | --- | --- |
| 配置 | 已保存 / 待应用 / 冲突 / 未管理 | 只证明本地配置状态 |
| 连通性 | 未测试 / 代理可达 / 目标 TLS 通过 / 失败 | TCP 端口可达不等于目标服务可用；不以第三方 IP 查询替代目标路径 |
| 额度 | 未适配 / 未查询 / 代理请求成功 / 过期缓存 | 不代表推理已使用代理；缓存失效不能变成实时成功 |
| 实际调用 | 未接管 / 原生字段已应用待验证 / 仅启动器生效 / 已观察 / 不支持 | 绑定工具版本、配置 revision、启动会话和观察时间；不作永久保证 |

改 proxy、provider URL、账户、凭据、CLI 版本或绑定后，失效相关测试证据和连接池；额度缓存作用域扩展到 provider ID、绑定/profile revision，但保留账户证明与旧缓存语义，不能因两个 provider 共享域名而复用数据。

## 7. 分阶段实施与文件接入点

| 阶段 | 最小可交付 | 主要接入点（新增项均为 proposed） | 完成条件 |
| --- | --- | --- | --- |
| P0 能力盘点 | 确定第一款 CLI/版本与 API 或账户路径，确认代理协议和环境优先级 | adapter 能力记录与合成验证；不修改真实账户/网络 | 一个可复现的版本化能力表，无未知能力被宣布支持 |
| P1 模型与自有 HTTP | 稳定 provider、ProxyProfile、binding、安全侧车、HTTP CONNECT、GLM transport 与非计费连通性；CLI/桌面共用 service | 新 `crates/atm-core/src/network/`、新 `application/network_service.rs`；现有 `model.rs`/`vault.rs`/`storage.rs` 做边界复用；`usage/glm.rs`、`application/usage_service.rs`、`usage/mod.rs`；桌面 `src-tauri/src/main.rs`、`src/api.ts`、`src/types.ts`、`src/usage.ts`；CLI `src/main.rs` | 仅自有路径声明生效；旧配置行为不变；不得把此阶段当成完整推理代理交付 |
| P2 首个外部工具闭环 | 核验一种原生 provider adapter，缺失时实现一个受限启动器；接入实际调用状态 | 新 network adapter/launch 模块；Codex 额度专用 `usage/process.rs` 仅复用子进程策略；`application/configuration.rs`/`batch.rs` 的精确字段预览与保护 | 指定工具的非计费合成流量证明 provider A/B 隔离；用户选择时再验证真实调用。该阶段才闭合首个外部工具需求 |
| P3 SOCKS 与跨平台适配 | SOCKS 远端 DNS、无桌面 CLI 与三平台路径/环境/安全存储边界 | `atm-core/Cargo.toml` 的 feature 与锁文件；network transport/launch；平台合成测试 | DNS、断线、凭据锁定、进程恢复和平台回滚通过；原生实测与合成结果分开 |
| P4 按需求扩展 | 更多经验证的工具；确有多 provider 同进程障碍时才加入 loopback API 转发 | 独立评审的转发模块与安全/协议验收；不预先建立第二套万能 provider 系统 | SSE/取消/背压/鉴权/不重放和计费边界全部满足 |

出口服务部署是独立需求，本方案只消费明确的代理端点，不要求 ATM 常驻桌面，也不接管代理服务生命周期。新增文件进入 [source-manifest.json](../scripts/source-manifest.json)，遵守既有标识分类与兼容策略。此表说明未来接入点，本次不新建代码模块或测试实现。

## 8. 验收矩阵

默认使用临时 HOME/XDG、合成 provider、假 key、本地 mock API/代理和测试 CA；保持真实配置、keyring、网络与账户不变。真实服务检查另行主动执行，**不得自动发送有计费的推理请求**。测试 CA 只用于合成 client，不写系统信任。

| 项目 | 必测输入/故障 | 通过标准 |
| --- | --- | --- |
| 身份与配置 | 改名、key 轮换、两个相同域名/共享 key、文件移动、悬空 profile、并发修改 | UUID 与绑定稳定；不猜测合并；未知引用/冲突明确失败 |
| 多 provider 隔离 | A 代理、B direct/legacy；同域名、同进程能力缺失 | A/B 到各自 mock 出口；不支持的同进程情形被拒绝而非假成功 |
| HTTP CONNECT | 域名:443、认证失败、代理拒绝、错误响应、断开的隧道 | 目标 TLS 保留；认证不串给上游；错误不转直连 |
| SOCKS / DNS | `socks5h`、本地解析对照、IPv4/IPv6、远端 DNS 故障、代理主机名 | 记录解析位置；unsupported 协议立即拒绝；不会悄悄本地解析 |
| 环境优先级 | 大小写 HTTP(S)/ALL_PROXY、NO_PROXY、已有原生代理配置 | 显式绑定可预测且冲突可见；只修改子进程，不污染其他 CLI |
| 失败保护 | 代理停止、拒绝认证、DNS/握手失败、请求中断；错误环境回退 | 受管理 client 不直连且不重放；用 mock 目标和代理日志证明。代理内部出口策略由独立服务验收，不以 ATM 端口连通性保证它 |
| TLS/端点 | 错误证书、主机名不匹配、降级、跨源重定向、假 GLM 额度域名 | 全部拒绝；官方额度白名单不变，无敏感头跨源 |
| 凭据与存储 | 锁定安全存储、日志/DTO/导出、profile 含 userinfo、备份恢复 | 不明文降级；失败不泄密；平台/用户解密边界保持 |
| 独立证据 | 连通性成功但额度失败；额度成功但 CLI 未接管；旧缓存/旧 revision | 三类结果独立展示，缓存明确过期，不能推导真实推理成功 |
| 流与取消 | 慢 SSE、120 秒附近静默、客户端取消、出口中断、背压、半条事件 | 不全量缓冲、不乱序、及时释放连接、无透明 POST 重放；不支持的双向协议明确报告 |
| 进程与平台 | Linux/macOS/Windows 绝对路径、空格路径、大小写、argv 注入、信号退出 | 无 shell 拼接；只作用选定实例；孤儿进程和 watchdog 行为受控 |
| Linux 无桌面/后台调用 | 会话 keyring 不可用、代理失联、业务进程重启、凭据锁定 | 无明文降级、不依赖 GUI 常驻；进程恢复不重放请求；系统网络设置不变 |
| 迁移/回滚 | 缺失新侧车、损坏/未来版本、恢复备份、用户修改客户端文件 | 无绑定保持旧行为；错误不当作无配置；仅恢复已拥有且未被用户改写的字段 |

## 9. 风险与回滚

最主要风险是把进程级代理误称为 provider 级隔离，以及把代理端口在线误称为实际调用已生效。通过能力表、分路径证据、故障注入和阻止不支持的受管理启动处理。外部 CLI 升级后能力证据失效，不能永久信任曾经使用的环境变量。

出口服务是独立依赖；ATM 保证自身的显式代理选择和失败策略，不以绑定配置证明出口服务内部的路由或可用性。实际计费、登录/地区策略和端点变化仍由 provider/client 的真实行为决定，不能承诺换出口即可保证账户服务可用。

回滚先停止受影响的新会话，保留受保护绑定；关闭新增 adapter/启动器，按预览和文件指纹恢复本次拥有的客户端字段，拒绝覆盖用户后改内容。新网络侧车与凭据先保留加密备份，不删除原 vault。独立出口服务由其自身流程维护；ATM 回滚不改动系统 VPN 或路由。恢复 legacy/direct 必须显式选择并告知流量路径变化；回滚失败不能自动降级直连。

## 10. 待实施前确认的决策

1. 首个实际客户端与版本、API 或账户服务的具体请求范围；不默认推导域名集。
2. 第一个外部 adapter 选择及原生能力证据；进程级覆盖的额外端点是否可接受。
3. 网络侧车的正式 schema/文件名与 typed credential 接口；不默认迁移 vault。
4. 首期代理认证方式与 HTTP CONNECT 覆盖范围；SOCKS、远端 DNS 和具体工具长流超时在对应阶段确认。

Provider → 出口绑定架构已确定；以上待决项是实施参数，不影响本设计先落盘。

## 11. 参考

- [ATM README](../README.md)：当前产品职责与入口。
- [Linux 存储与额度接口](CODEX_GLM_LINUX.md)：安全存储和官方额度约束。
- [标识演进规则](agents/internal-identifier-evolution.md)：新增身份与持久化契约的变更边界。
- [验收矩阵](ACCEPTANCE_MATRIX.md)：源码能力、合成验证与真实平台证据分级。
- [ADR 0030](adr/0030-provider-egress-proxy-binding.md)：本次已接受的架构决策。
