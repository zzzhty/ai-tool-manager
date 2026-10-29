> 生成说明：2026-10-29 由多代理审计 workflow 沿 [设计稿](PROVIDER_PROXY_DESIGN.md) 产出（5 路现场核实 → 计划合成 → 双镜头对抗评审 → 定稿 v2）；计划中约 50 处 file:line 锚点经评审代理逐一核对，附录 A 记录全部评审处置。本计划为实施提案：§1 各决策点获用户批准前，不写任何实现代码或持久化文件。

# Provider 出口代理绑定 — 实施计划（P0–P4，文件级）· 修订定稿 v2

规格输入：`docs/PROVIDER_PROXY_DESIGN.md`（下称“设计稿”，行号按当前工作树核实）+ `docs/adr/0030-provider-egress-proxy-binding.md`。本计划不改架构，只落实施参数。所有 file:line 均在 HEAD `bba9d8b` 工作区核实（仅 README/source-manifest 有未提交改动，不影响所引源码行）；v1 稿中一处错误引用（CLI ConfigurationSession 先例）已更正，另新增一处 v1 未列的桌面接入点（`build.rs` 命令清单，本轮现场核实）。

**v2 修订来源**：合并两份对抗评审（2 blocker / 5 major / 其余 minor），处置明细见附录 A；blocker/major 全部落实，无静默忽略项。

---

## 0. 执行摘要

**阶段顺序与并行性**

| 顺序 | 阶段 | 依赖 | 可并行 |
| --- | --- | --- | --- |
| 1 | P1 模型与自有 HTTP（纯 ATM 内部路径） | 无 | 与 P0 并行 |
| 2 | P0 能力盘点（外部 CLI 证据，产出版本化能力表） | 文档收口：无；可选合成验证：P1 §7.2 MockProxy 或 P0 自带不入库的一次性观察脚本（开工时二选一） | 与 P1 并行 |
| 3 | P2 首个外部工具闭环（Codex） | **P0 能力表 + P1 network service** | — |
| 4 | P3 SOCKS/跨平台/远程认证代理 | P1（transport）/P2（launch） | 部分与 P2 后段并行 |
| 5 | P4 loopback 转发等 | 触发条件未满足则不做 | — |

P0 与 P1 主体无相互依赖；P0 的唯一硬产出（能力表）是 P2 的准入条件。v1 中“P0 合成验证用 P1 mock”造成的隐性依赖已显式化为上述二选一，P0 文档收口不被 P1 测试进度阻塞。

**关键决策点（详见 §1，§10 四项均有明确状态）**

1. §10.1 首个客户端 = **Codex app-server**（ATM 已在 `usage/process.rs:87-93` 直接 spawn），但**具体版本必须由用户指定**——main 分支证据未按 tag 锁定，0.157–0.164 间行为持续变动。【状态：建议已定；等待用户版本号+账户/API key 路径，缺任一项 P2 不得启动】
2. §10.2 首个 adapter = **进程级 env 启动器**（Codex 无原生 provider 级代理字段，证据见 §1.2）。【状态：建议已定；等待用户确认接受进程级覆盖影响（OAuth/遥测/更新）】
3. §10.3 侧车 schema/文件名：完整草案见 §3.1（含 v2 新增的引用完整性规则、超时字段消费语义、可见性规则）。【状态：草案就绪；**首次写入前需用户批准 schema**；批准即成持久化契约 v1】
4. §10.4 首期认证：HTTP CONNECT over `http://` 代理 + basic auth；**凭据仅允许 loopback 代理**（v2 收紧，见 §1.4）；HTTPS-to-proxy、远程认证代理、SOCKS 延后 P3。【状态：建议已定；等待用户确认实际代理是否需要认证】
5. 设计稿字面不一致/未覆盖处，统一列入 §1.5 用户确认清单（v2 扩充为 7 项：hub.rs 归属、`--dry-run`、demo check 行为、**侧车损坏阻断范围**、**侧车备份/恢复解释**、远程认证代理收紧、credential_ref 跨文件引用规则）。

**主要新增面**：`crates/atm-core/src/network/`（7 个新文件，P2 再加 2）、`application/network_service.rs`、`tests/network_store.rs`、`tests/network_transport.rs`（P2/P3 再加 2）、`apps/desktop/src/proxy.ts`；必改既有文件约 16 个，含三处设计稿未列的接入点：`capabilities/main.json`、`apps/desktop/src-tauri/build.rs:56-86`（tauri 命令清单，v2 新发现）、`macos.rs:111-115`。

---

## 1. 设计稿 §10 待决项处置

### 1.1 决策 1（§10.1）：首个实际客户端与请求范围 —— 建议 Codex app-server，版本待用户指定（阻塞门）

- ATM 已直接 spawn `codex app-server` 做额度查询（`crates/atm-core/src/usage/process.rs:87-93`：`Command::new(cli)` + `.env("CODEX_HOME", profile)`，其余环境继承），是唯一现成注入目标；app-server 与 CLI 共用 `Config::http_client_factory`（https://github.com/openai/codex/blob/main/codex-rs/app-server/src/lib.rs ）。
- 默认策略 `OutboundProxyPolicy::ReqwestDefault` = reqwest/hyper-util 的 curl 式环境变量语义，进程级 env 注入即可生效（https://github.com/openai/codex/blob/main/codex-rs/core/src/config/mod.rs ）。
- 请求范围：模型+认证流量经 app-server 的 reqwest client；账户端点（ChatGPT OAuth 等）按锁定版本逐一列入端点类别，不由 API URL 推导（设计稿 §1.1，:18）。已知缺口：`$CODEX_HOME/.env` 启动早期注入全部非 `CODEX_*` 变量（含代理变量，无日志）。
- **阻塞门**：P2 开工前用户必须提供 ① 实际安装的 Codex 版本号（能力表按 release tag 重新取证）；② 目标路径是账户（ChatGPT OAuth）还是 API key 模式。

### 1.2 决策 2（§10.2）：第一个外部 adapter —— 受限启动器（env 注入）

- 证据：`ModelProviderInfo` 字段全集无任何 proxy 字段（https://github.com/openai/codex/blob/main/codex-rs/model-provider-info/src/lib.rs L147 起）；codex workspace 的 reqwest 未启用 socks feature → 无 provider 级代理、仅 http(s) 代理、SOCKS 不支持。按设计稿 §5 表（:101）落入“仅支持进程级代理的外部 CLI → ATM 专属启动器”。
- 冲突检测项（P2 必做）：① `~/.codex/config.toml` `[features].respect_system_proxy`（单数键，复数键被静默忽略）；② `$CODEX_HOME/.env` 内代理键。
- 【状态：等待用户确认接受进程级覆盖影响该进程全部 HTTP 流量；不接受则该路径标“不支持”。】

### 1.3 决策 3（§10.3）：网络侧车 schema/文件名/typed credential —— 草案见 §3.1，批准前不落盘

- 文件名：`network.atmvault`（linux/macos）/ `network.dpapi`（windows），经新增 `storage::network_filename()`（仿 `storage.rs:82-88`）；与 vault/templates 同目录（`storage::data_directory()`，storage.rs:39-73）。
- 防丢失标记：`network.required`，内容 `ai-tooling-manager/network-sidecar/v1\n`（复刻 `template_store.rs:106-128` 机制）；侧车缺失+标记存在 → `NETWORK_STORE_MISSING` fail-closed。
- **引用完整性两级结构（v2 修订，回应评审 blocker）**：
  - **侧车内引用**（`ProxyProfile.credential_ref` → 本侧车 credentials；`Route::ExplicitProxy` → 本侧车 proxies）：`NetworkStore::validate()` 闭环校验，不需打开 vault——侧车自身自包含。
  - **跨文件引用**（`ProviderInstance.credential_ref` → vault KeyEntry UUID，设计稿 §3:45 明列此字段）：**写入时校验**（`register_provider`/`update_provider` 对照已打开 vault 的 key 集合，凭据缺失 → `KEY_MISSING` 拒绝写）；**删除时守卫**（`Configuration::delete_key`（configuration.rs:187-189，现直接透传 `vault.delete_key`）增加网络引用检查：key 被任何 ProviderInstance 引用 → `KEY_IN_USE` 并列出引用的 provider。守卫放在 Configuration 服务层而非 vault.rs，避免 vault→network 反向依赖；vault.rs:254-261 现有 targets-only 检查保持不动）。带外替换 vault 文件造成的残留悬空（与现有 targets 同窗口）：读面 `list_providers` 标 `credential_missing`，该 provider 的受管理查询/检查报 `PROVIDER_CREDENTIAL_MISSING`（满足设计稿 §3.1:61“引用缺失必须阻止对应受管理操作”），legacy 路径不受影响。
- **managed GLM 查询的凭据来源（v2 澄清，消除 v1 “仅提示性”与 `check --scope usage` 的矛盾）**：`ProviderInstance.credential_ref` 是受管理查询的权威认证来源（GLM kind 注册时必填）；`check provider --scope usage` 与桌面受管理查询调用 `configuration.usage_credential(provider.credential_ref)`（configuration.rs:129-139 现有接口）；为 None（仅可能出现在非 GLM kind）→ `PROVIDER_CREDENTIAL_MISSING`。认证来源不因选择代理而改变（设计稿 §4.2:87）。
- revision 策略：每对象自带单调递增 `revision: u64`（创建=1，每次修改 +1）；文档无全局 revision；RouteEvidence 与 usage 缓存作用域按对象 revision 过期。
- 【状态：字段草案 §3.1；**用户批准前不写入任何文件**。批准即持久化契约 v1 定稿，此后字段变更按 `docs/agents/internal-identifier-evolution.md` 走显式迁移清单。】

### 1.4 决策 4（§10.4）：首期代理认证与 CONNECT 范围 —— basic auth + 仅 `http://`；**凭据仅限 loopback（v2 收紧）**

- P1 只接受 `http://host:port`；`https://` 代理（HTTPS-to-proxy）不做（需另测代理证书链，设计稿 §4.1:79），与**远程认证代理**一并列入 P3+。
- 认证：reqwest `Proxy::basic_auth`；凭据从侧车解密后仅短生命周期内存持有（`Zeroizing`），不进 URL/env/日志。
- **远程明文凭据门（v2 新增，落实设计稿 §4.1:77 红线）**：`add proxy` / `update proxy` / `check proxy` 试用，凡携带凭据且 host ∉ {`127.0.0.1`, `::1`, `localhost`}（字面比较，不做 DNS 解析）→ 脱敏错误 `PROXY_REMOTE_CREDENTIAL` 拒绝；无凭据的远程 `http://` 代理允许保存，视图携带“明文通道”警示。远程认证代理（经 TLS 或已确认私有加密通道）延后 P3 与 HTTPS-to-proxy 同期实现，避免把确认记录固化进 v1 schema。测试：network_store.rs / network_transport.rs 各加拒绝与警示用例。
- 显式 `.proxy(...)`/`.no_proxy()` 后 reqwest 自动关闭系统/env 代理发现（reqwest 0.12.28 `async_impl/client.rs:1415,1427-1431`），无需额外 API 即满足设计稿 §3.2-4。
- 外部 adapter 不注入解密密码（设计稿 §4.2:91）：P2 启动器只配无密码 loopback 代理或标不支持。
- 【状态：建议已定；等待用户确认实际代理是否需要认证（决定验收重点是 407 还是隧道路径）。】

### 1.5 计划发现的补全决策（设计稿未覆盖或字面不一致；v2 扩充为 7 项，全部挂用户确认）

- **(a) hub.rs 归属**：`distribution/source/hub.rs:579-603` 下载 client 无 `.no_proxy()`，会顺从 `HTTP(S)_PROXY/ALL_PROXY` env；与设计稿 §3.2-4 字面冲突且 §2 现状表未列。但 hub 下载属内容分发域（URL/digest 由 `content/omh.lock.json` 锁定、`import_bytes` 校验、无凭据），顺从 env 代理不是本设计泄密面；强制 `no_proxy()` 反而破坏依赖 HTTP_PROXY 的用户。**建议：P1 不碰 hub.rs；设计稿 §2 表补记“hub 下载 = legacy/unmanaged（digest 保护，无凭据）”。**
- **(b) CLI 参数名**：`--preview` → `--dry-run`（仓库惯例，`crates/atm-cli/src/main.rs:33,47,50`）；命令对象复数（`list proxies`/`list providers`）与 `skills`/`hooks` 惯例一致（main.rs:84-99）。
- **(c) demo 模式行为**：check（provider/proxy）→ `synthetic_demo` 合成结果，绝不联网（`apps/desktop/src-tauri/src/main.rs:287-295,318-339` 先例）；add/update/delete/register/bind/unbind → `demo_refusal()`（main.rs:394-399）。
- **(d) 侧车损坏的阻断范围（v2 新增）**：NetworkStore 挂入 `Configuration::open`（§3.2）后，侧车损坏/不可读会阻断**全部配置类命令**（密钥/目标/模板），宽于设计稿 §3.1:61“阻止对应受管理操作”的字面，与 TemplateStore 先例一致（`tests/application.rs:19-51` 同构：读取失败 → 整个配置服务不可构造）。**显式提交用户确认**；若用户要求窄作用域，改用“读路径按命令降载”的独立变更，不默认采用。
- **(e) 侧车备份/恢复的解释（v2 新增，修正 v1 对 batch.rs 的错误归因）**：`batch.rs:437-451` `save_backup` 是 BatchUpdater 对**外部客户端配置文件**的逐文件备份，与网络侧车无关（v1 §8 表述有误，已改）。设计稿 §9:188“新网络侧车与凭据先保留加密备份，不删除原 vault”按以下解释落实并请用户确认：① 回滚路径 = **原位保留侧车文件**（侧车本身即加密备份；不识别它的旧版本二进制只会忽略它；不删除、不降级明文、不动原 vault）；② **不实现每次保存的滚动备份文件**（新备份文件引入 macOS `initialize_storage` 枚举、权限与恢复歧义，而原子替换已保证写中断不损坏）；③ 侧车丢失/删除时**凭据=重新录入**，写入用户文档与 §8 迁移/回滚测试行；④ 未来 v1→v2 格式迁移时才引入“迁移前自动加密备份”及对应测试。若用户要求字面“每次变更前备份”，单列工作项。
- **(f) 远程认证代理收紧**：见 §1.4（属于 §10.4 的实施参数收紧，P1 只做 loopback 凭据）。
- **(g) credential_ref 跨文件引用规则**：见 §1.3（属于 §10.3 schema 语义的一部分，随 schema 一并批准）。

---

## 2. P0 能力盘点（可与 P1 并行）

| 项 | 内容 |
| --- | --- |
| 交付物 | 版本化 adapter 能力表：**新增** `docs/adapters/codex-egress.md`（登记 source-manifest） |
| 内容 | 锁定 release tag + 取证日期；能力矩阵按设计稿 §5 行：原生 provider 级字段=无、进程级 env=是（优先级表）、SOCKS=否、base_url=流量目标改写非代理；端点类别清单（模型/认证/遥测/更新）；冲突源清单（`[features].respect_system_proxy` 单数键、`$CODEX_HOME/.env` 代理键）；证据全部为 tag 锁定源码/官方文档链接 |
| 已有证据底子 | main 分支证据已核实（§1.1/1.2 引用），P0 按用户指定版本重新锁定 tag 取证 |
| 合成验证 | 依赖二选一（开工时定）：用 P1 §7.2 MockProxy + `#[ignore]`+env 门（`secret_service_ci.rs:12` 模式）跑指定版本 app-server 的 env 注入观察；或 P0 自带**不入库**的一次性 loopback 观察脚本先行，MockProxy 落地后补录。结果记入能力表 |
| 不做 | 不改真实账户/网络/配置；不写产品代码 |
| 完成条件 | 表内无“未知能力被宣布支持”；每个能力行有 tag 锁定证据或标“未验证” |
| 阻塞 | §1.1 阻塞门（版本+路径范围）未解则 P0 无法收口，连带阻塞 P2 |

---

## 3. P1 模型与自有 HTTP

### 3.1 数据结构字段草案（`crates/atm-core/src/network/model.rs`，新增）

全部 `#[derive(Clone, Serialize, Deserialize)]` + `#[serde(rename_all = "camelCase", deny_unknown_fields)]`（TemplateStore 风格，template_store.rs:19-33）：

```rust
pub enum ProxyProtocol { HttpConnect }            // P1 唯一值；P3 增 Socks5h/Socks5（schema 前向兼容：字段已在 v1）
pub enum DnsMode { Proxy }                        // P1 唯一值；P3 增 Local 并与 socks5/socks5h 强制配对校验
pub enum FailurePolicy { Error }                  // v1 固定值（设计稿 §3:47）

pub struct ProxyCredential {
    pub id: Uuid,                 // 不可变随机 v4
    pub label: String,            // ≤64 字符，无控制字符（vault.rs validate 风格）
    pub username: Secret,         // model.rs:9 的 Secret(Zeroizing) 包装，Debug=[REDACTED]
    pub secret: Secret,
    pub updated_utc: String,
}

pub struct ProxyProfile {
    pub id: Uuid,                 // 不可变随机 v4；改名/换端口/换凭据不换 id（设计稿 §3:51）
    pub display_name: String,     // ≤64，无控制字符，大小写不敏感查重
    pub protocol: ProxyProtocol,
    pub host: String,             // 仅 host；校验拒绝 userinfo/path/query/fragment（glm.rs:63-79 风格）
    pub port: u16,                // 1..=65535
    pub dns_mode: DnsMode,
    pub credential_ref: Option<Uuid>,   // 必须引用本侧车 credentials 内现存 id（侧车内引用完整性）
    pub connect_timeout_secs: u32,      // 默认 5；仅连通性检查消费（见下方消费语义）
    pub total_timeout_secs: u32,        // 默认 15（v2 更名自 read_timeout_secs，语义=连通性总时限）；仅连通性检查消费
    pub revision: u64,
    pub updated_utc: String,
}

pub enum ProviderKind { Glm }     // P1 唯一；P2 增 CodexAccount 等。不扩 usage::Provider（设计稿 §2:30）

pub struct ProviderInstance {
    pub provider_id: Uuid,
    pub display_name: String,
    pub kind: ProviderKind,
    pub region: Region,           // 复用 usage::Region（glm.rs:26-31）
    pub base_url: String,         // GLM：恒等于官方端点常量；仅展示与漂移检测，不作请求目标（设计稿 §4.2:87）
    pub credential_ref: Option<Uuid>,  // vault KeyEntry UUID；跨文件引用：写入时校验+删除守卫（§1.3）；GLM kind 必填
    pub revision: u64,
    pub updated_utc: String,
}

pub enum Route { Direct, ExplicitProxy(Uuid) }   // ExplicitProxy 必须引用现存 profile（validate）

pub struct ProviderProxyBinding {
    pub provider_id: Uuid,        // 同时是 map key：一个 provider 只有一个当前 route（设计稿 §3:47）
    pub route: Route,
    pub failure_policy: FailurePolicy,
    pub revision: u64,
    pub updated_utc: String,
}

pub struct ProviderAttachment { /* P1 不提供创建入口；字段按设计稿 §3:48 */ }

pub struct NetworkDocument {      // 侧车根文档
    pub version: u32,             // =1；≠1 → NETWORK_STORE 硬错误（vault.rs:124 先例）
    pub providers: BTreeMap<Uuid, ProviderInstance>,    // ≤100
    pub proxies: BTreeMap<Uuid, ProxyProfile>,           // ≤100
    pub credentials: BTreeMap<Uuid, ProxyCredential>,    // ≤200
    pub bindings: BTreeMap<Uuid, ProviderProxyBinding>,  // key=provider_id，≤100
    pub attachments: BTreeMap<Uuid, ProviderAttachment>, // P1 恒空
}
```

**v2 修订三点（均须随 §1.3 一并获用户批准）**：

1. **可见性（clippy 合规）**：`Secret` 是 `pub(crate)`（model.rs:9）、`mod model` 私有（lib.rs:12），`KeyEntry` 亦 `pub(crate)`（model.rs:18）。因此 lib.rs 声明 **`pub(crate) mod network;`**；域类型（NetworkDocument/ProxyProfile/ProxyCredential 等）全部 `pub(crate)`；对外仅暴露 **`pub` 的 View 类型**（纯数据、Serialize、零 secret，KeyView 先例 model.rs:56-63 + lib.rs:27 re-export），由 `application::network_service` 公开签名引用，避免 `private_interfaces`/E0446 触发 CI `clippy --all-targets -D warnings`（rust-ci.yml:90,220,310）。
2. **超时字段消费语义（消除死字段）**：`connect_timeout_secs`/`total_timeout_secs` 由**连通性检查**消费（默认 5/15，钳制 1..=120，设计稿 §4.1:81“连通性测试总时限可取 15 秒”）；**GLM 额度路径不读 profile 字段**，维持固定 5s/12s（glm.rs:97-98；设计稿 §4.1:81“额度**继续**总时限 12 秒”）。两处消费关系写入 schema 批准材料。
3. **credential 生命周期**：v1 不提供 credential 共享入口——`add/update proxy` 总是新建 credential；替换/移除引用后，无引用的 credential **随同一次保存自动剪枝**（悬空 credential 不可积累）；`validate()` 只校验存活引用。由此设计稿 §4.2:92“删除仍有引用的 credential 应拒绝”由剪枝规则结构性满足（不存在可独立删除的被引用 credential），并在 schema 说明中记为行为契约。

**attachments 恒空集合随 v1 落盘**：设计稿 §3:48 已承诺、P2 已排期；v1 即含空集合可避免下一阶段对持久化格式的可避免破坏（旧读新写会被 `deny_unknown_fields` 拒绝）。P1 不暴露任何 attachments 变更 API。

### 3.2 侧车文件机制（`crates/atm-core/src/network/store.rs`，新增；蓝本 template_store.rs:19-157）

- `NetworkStore::load_with_protector(directory, protector)`：无文件且无 `network.required` → 默认空 store（=legacy，设计稿 §3.2-3）；无文件但有标记 → `NETWORK_STORE_MISSING` fail-closed；密文 >2MiB / 明文 >1MiB → `NETWORK_STORE`；解析失败 → `NETWORK_STORE`“未修改原文件”。
- `validate()`：version==1、计数上限、map key==对象 id、侧车内引用存在、绑定数 ≤ provider 数、host/port/display_name 校验、**loopback-凭据规则**（credential_ref 存在 ⇒ host ∈ loopback 集合，§1.4）。
- `save(directory)`：validate → `encrypted_write_with`（vault.rs:68-98 零改动复用）→ 首次保存前建 `network.required` 标记（create_new + macOS 0600）、首存失败回滚标记（template_store.rs:108-128 原样）→ **同事务内执行悬空 credential 剪枝**（§3.1-3）。
- **接入 `Configuration`（configuration.rs:113-125 `open` 序列）**：`Configuration` 增字段 `network: NetworkStore`（`open()` 在 `Vault::open_with_protector` 之后加载）；同时 `Configuration::delete_key`（:187-189）增加网络引用守卫（§1.3）。后果与先例（`tests/application.rs:19-51`）：读取失败 → 整个配置服务不可构造 → 全部配置类命令报错，skills/harness 不受牵连；vault.lock = 同一配置锁，写操作天然串行。**已知并发后果（写进用户文档）**：桌面打开配置后持锁至退出（configuration.rs:46-57 缓存；锁随 Vault 存续），期间 CLI 网络命令得 `VAULT_BUSY`。fail-closed、可预期，P1 接受；实测痛则后备“读路径免锁 raw `encrypted_read_with`”需用户确认后单列。
- **必改隐藏接入点 ①**：`macos.rs:111-115` `initialize_storage` 的加密文件枚举加入 `storage::network_filename()` 与 `"network.required"`——否则 macOS 密钥丢失时确认初始化会新建密钥使旧侧车永久不可解密（macos_keychain.rs:48-53 防替换守卫依赖该枚举）。
- **Linux 不加对称守卫**（决策）：Linux `initialize_storage`（linux.rs:81-136）本就不检查数据文件；密钥丢失风险与现有 vault 相同，维持现状并记入已知平台风险。
- **CLI 首次触碰配置服务（v2 新增说明）**：现有 CLI 无任何命令构造 Configuration/Protector（main.rs:735-741 仅 SkillsService/ProjectionRegistry 的 from_environment）；网络命令将是 CLI **首个依赖平台安全存储**的面——Linux 无桌面时 `STORAGE_UNAVAILABLE`、桌面持锁时 `VAULT_BUSY` 在 P1 即暴露（非 P3）。正确先例引用：`ConfigurationSession::new(directory, protector, demo)` 见桌面 main.rs:784；`from_environment` 构造先例见 skills.rs:481。cli.rs 黑盒补这三类失败路径用例（§7.1）。

### 3.3 路由解析与 transport 注入点

**`crates/atm-core/src/network/transport.rs`（新增）**：

```rust
pub(crate) enum RouteSpec { Direct, Proxy { endpoint: String, authorization: Option<(Secret, Secret)> } }
pub fn validate_proxy_endpoint(host: &str, port: u16) -> Result<()>;   // scheme∈{http}、无 userinfo/path/query/fragment
pub fn build_client(spec: &RouteSpec, connect_secs: u32, total_secs: u32, extra_roots: &[Certificate]) -> Result<reqwest::blocking::Client>;
```

builder 配方照抄 glm.rs:93-100：`https_only(true)` + `redirect(Policy::none())` + 双超时；差异仅在代理段：`Direct` → `.no_proxy()`；`Proxy` → `.proxy(Proxy::all(&endpoint).basic_auth(user, pass))`。`extra_roots` 生产恒空，仅供测试注入测试 CA（§7.2），不暴露到 IPC/CLI。

**GLM 注入点（`crates/atm-core/src/usage/glm.rs:88-100`）**：`OfficialHttps` 从单元结构改为携带 `route: RouteSpec`（`direct()`/`routed(spec)`）；builder 链按 route 切换 `.no_proxy()`/`.proxy(...)`；`https_only/Policy::none/5s/12s` 与端点白名单原样保留。`Transport` trait（glm.rs:85-87）不动 → `tests/usage.rs` MockHttp（:25-45）与 15+ 协议级测试零扰动。客户端仍每请求新建（无持久池；进行中请求固定其开始时版本）。

**缓存作用域扩展（设计稿 §6:148）——零 core 改动**：`usage/mod.rs:205-209` scoped key 末段为调用方字符串；GLM 查询方把 `"{key_uuid}:{updated_utc}"`（configuration.rs:138）扩为 managed provider 时 `"{provider_id}:{binding.revision}:{key_uuid}:{updated_utc}"`，legacy 时不变。旧 revision 条目 key 不可达，内存态无害。

### 3.4 证据与连通性检查

**`crates/atm-core/src/network/evidence.rs`（新增，内存态）**：

```rust
pub enum EvidenceKind { Connectivity, Usage, RealCall }
pub enum EvidenceMethod { Managed, Trial }        // v2 新增：Trial = 未保存 profile 试用（设计稿 §3.2-2:66）
pub struct RouteEvidence { provider_id: Option<Uuid> /* Trial 时为 None */, binding_revision, profile_revision,
                           kind, method, target_category: &'static str, checked_at, outcome }
```

- `EvidenceLog { per_provider: BTreeMap<Uuid, Vec<RouteEvidence>>, trials: Vec<RouteEvidence> /* 上限 20 */ }`；读取按当前 binding/profile revision 惰性过期；不存正文/认证头。Trial 证据在视图中恒标“测试路由”，不能变成长期绑定（§3.2-2）。

**`crates/atm-core/src/network/check.rs`（新增）**：

- `pub fn connectivity(spec: &RouteSpec, target: &str, confirmed: bool) -> Result<ProbeOutcome>`：非计费 GET（无 Authorization 默认）；超时取 profile 的 connect/total 值（§3.1-2）；生产调用方传 `glm::CHINA_ENDPOINT/INTERNATIONAL_ENDPOINT`，测试传 loopback mock。
- 错误码（脱敏，error.rs `&'static str` 模式）：`PROXY_CONNECT_FAILED / PROXY_AUTH_FAILED / PROXY_DNS_FAILED / TARGET_TLS_FAILED / CHECK_TIMEOUT / CHECK_NETWORK / PROXY_REMOTE_CREDENTIAL`。
- **前置披露（v2 新增，落实设计稿 §6:135）**：任何出站 check 在确认材料中必须展示三要素——目标端点类别（如“GLM 官方额度端点·国际”）、是否携带 API 凭据、路由（代理名+协议 / 直连 / 测试路由）；CLI 确认提示与桌面 confirmed 弹窗同文案，proxy.test.ts 断言披露文案存在。

### 3.5 共享服务（`crates/atm-core/src/application/network_service.rs`，新增；UsageService 模板 usage_service.rs:16-19）

```rust
pub struct NetworkService { evidence: EvidenceLog }
impl NetworkService {
    // —— 读面（v2 补齐：provider/binding 枚举是桌面选择器、四状态列、PROXY_REFERENCED/dry-run 后果的数据源）——
    pub fn list_proxies(&self, conf: &Configuration) -> Result<Vec<ProxyProfileView>>;
        // 视图：id/name/protocol/host/port/loopback 标记/凭据在位(布尔+mask)/connect+total 超时/revision
        //      /引用者（provider 名单，设计稿 §6:137“显示使用者与协议/DNS方式”）/非 loopback 明文警示
    pub fn list_providers(&self, conf: &Configuration) -> Result<Vec<ProviderView>>;
        // 视图：id/name/kind/region/base_url/credential_state(Present(mask)|Missing)/当前 route(direct|proxy 名|legacy)
        //      /binding.revision/四状态证据摘要（配置/连通性/额度/实际调用，设计稿 §6:139-148）
    // —— proxy 生命周期 ——
    pub fn add_proxy(&mut self, conf: &mut Configuration, name, host, port, credential: Option<(String,String)>) -> Result<ProxyProfileView>;
    pub fn update_proxy(&mut self, conf, proxy_id, name?, host?, port?, credential: Option<Option<(String,String)>>) -> Result<ProxyProfileView>;
        // v2 新增：同 id 变更（设计稿 §3:51“只改 URL/名称/凭据时保留 UUID”）——revision+1、过期证据；
        // credential=Some(Some(..)) 替换/新建凭据、Some(None) 移除；保存时剪枝悬空凭据；loopback-凭据规则适用
    pub fn delete_proxy(&mut self, conf, proxy_id) -> Result<()>;   // 仍被 binding 引用 → PROXY_REFERENCED 并列出绑定（§4.2:92）
    // —— provider 生命周期 ——
    pub fn register_provider(&mut self, conf, name, kind, region, key_ref: Option<Uuid>) -> Result<ProviderView>;
        // 不按域名/key/名称自动合并（§3:51）；key_ref 写入时对照 vault 校验存在（§1.3）；GLM kind 必填
    pub fn update_provider(&mut self, conf, provider_id, name?, key_ref?) -> Result<ProviderView>;
        // v2 新增：改名/re-point 凭据——revision+1、过期证据、key_ref 校验
    // —— 绑定 ——
    pub fn bind_provider(&mut self, conf, provider_id, route: Route) -> Result<BindingView>;   // revision+1、过期证据
    pub fn unbind_provider(&mut self, conf, provider_id, dry_run: bool) -> Result<UnbindPreview|()>;  // dry_run 展示回 legacy 后果（§3.2:71）
    pub fn resolve(&self, conf, provider_id) -> Result<ResolvedRoute>;   // Legacy | Managed(RouteSpec)；Legacy ≠ 隐含 direct（§3.2-3:67）
    // —— 检查 ——
    pub fn check_connectivity(&mut self, conf, provider_id, confirmed) -> Result<CheckView>;        // 出网；spawn_blocking 由调用方负责
    pub fn check_proxy_trial(&mut self, host, port, credential: Option<(String,String)>, confirmed) -> Result<CheckView>;
        // v2 新增（设计稿 §3.2-2:66）：未保存 profile 试用——内存 RouteSpec、绝不落盘、证据 method=Trial；
        // loopback-凭据规则适用；前置披露三要素
}
```

- 桌面持 `Arc<Mutex<NetworkService>>`（UsageService 先例 main.rs:813）；CLI 每命令构造（先例：桌面 main.rs:784 `ConfigurationSession::new`；skills.rs:481 from_environment 风格）。
- `application/mod.rs:1-4` 增 `pub mod network_service;`。

### 3.6 CLI 命令清单（`crates/atm-cli/src/main.rs`）

| 命令 | 接入点 | 说明 |
| --- | --- | --- |
| `atm add proxy --name N --endpoint http://host:port [--proxy-user U --credential-stdin]` | dispatch（main.rs:83-101）+ USAGE（:27-59） | 密码 stdin 单行读入；非 loopback+凭据 → `PROXY_REMOTE_CREDENTIAL` |
| `atm update proxy <proxy-id> [--name N] [--endpoint http://host:port] [--proxy-user U --credential-stdin \| --remove-credential]` | v2 新增 | 同 id 变更，返回新 revision |
| `atm list proxies [--json]` | 照 `list skills` 双模式（main.rs:380-389）；`--json` 走 print_result（:211-223） | 含引用者名单与明文警示 |
| `atm list providers [--json]` | **v2 新增** | provider + route + 凭据状态 + 四状态摘要 |
| `atm register provider --name N --kind glm --region china\|international --key <uuid>` | P1 kind 仅 glm；`--adapter/--target` 留给 P2 | key 写入时校验 |
| `atm update provider <provider-id> [--name N] [--key <uuid>]` | **v2 新增** | 改名/re-point |
| `atm bind provider <provider-id> --proxy <proxy-id>\|--direct` | 返回新 binding + 受影响面板提示 | |
| `atm unbind provider <provider-id> [--dry-run]` | `--dry-run` 替代设计稿 `--preview`（§1.5b） | 展示回 legacy 后果 |
| `atm delete proxy <proxy-id>` | 被引用 → `PROXY_REFERENCED` 列绑定 | |
| `atm check provider <provider-id> --scope connectivity\|usage` | **确认提示先打印三要素披露（§3.4）再执行**；scope=usage 经解析 route + `usage_credential(provider.credential_ref)` 跑 GLM 额度（均非计费） | |
| `atm check proxy --endpoint http://host:port [--proxy-user U --credential-stdin]` | **v2 新增（§3.2-2 试用入口）** | 不落盘；输出标“测试路由” |
| （P2）`atm run provider <id> -- <abs-cli> <args>` | 透传需在 parse() 前按字面 `--` 预切分（main.rs:505-516,661-692 先例） | |

解析器改动：新增值选项同步登记 main.rs:144-147 与各命令选项白名单；provider-id/proxy-id 走 positional（:193-195 已拒空串）；错误输出沿用 `error: {code}: {message}`（:16-25）。**环境隔离（v2 强调）**：cli.rs 的 env_remove 列表（:60-73，现无任何代理变量）须补 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY` 及小写形态，保证新命令行为确定。

### 3.7 桌面命令与前端清单

**Rust（`apps/desktop/src-tauri/src/main.rs`）**：

- 新命令（全部 `authorized(&window)?` + `lock(&state)?`，main.rs:40,51）：`list_proxies`、`add_proxy`、`update_proxy`、`delete_proxy`、`list_providers`、`register_provider`、`update_provider`、`bind_provider`、`unbind_provider(dry_run)`、`check_provider(provider_id, scope, confirmed)`、`check_proxy(endpoint_host, endpoint_port, credential?, confirmed)`（async+confirmed 门+spawn_blocking，照 query_glm_usage main.rs:258-311 范式；确认弹窗含三要素披露）。
- `Service`（main.rs:34-39）加 `network: Arc<Mutex<NetworkService>>`，run() :811-815 初始化。
- `query_glm_usage`（main.rs:258-311）加参数 `provider_id: Option<Uuid>`：selected+bound → `resolve()` → `OfficialHttps::routed/direct`，缓存作用域串按 §3.3 扩展，凭据经 `usage_credential(provider.credential_ref)`；未选 → 现路径不变（`&mut glm::OfficialHttps` 改 `OfficialHttps::direct()`）。
- **三处命令注册点一个都不能少（v2 修正为三处）**：① `generate_handler![...]`（main.rs:816-846）；② `capabilities/main.json` 逐条新增 `allow-` 前缀权限条目（如 `allow-list-proxies`；main.rs:857-898 smoke-denied 实证 ACL 层存在）；③ **`build.rs:56-86` `tauri_build::AppManifest::new().commands(&[...])` 清单同步追加**（v1 遗漏，本轮核实该清单是命令清单的生成源之一）。
- demo 行为：list/check（含试用）→ `synthetic_demo`；写操作 → `demo_refusal()`（§1.5c）。

**前端**：

- `src/types.ts`：`ProxyProfileView/ProviderView/BindingView/CheckOutcomeView/UnbindPreview` + `DesktopApi` 方法签名；DTO 不含任何 secret（types.ts:1 契约）。
- `src/api.ts`：invoke 包装（api.ts:6-43 模式）。
- **新增** `src/proxy.ts`：`ProxyPanel` 类（harness.ts:19-54 构造器签名、revision 丢弃过期异步、`Record<string,string>` 白名单词表渲染四状态列：配置/连通性/额度/实际调用；legacy 显示“未管理”且不得宣称受保护，§3.2-3）。proxy 面板含“保存前试用”（`check_proxy`）入口。
- `src/layout.ts`：nav 按钮 `data-panel="proxy"` + `<section id="panel-proxy" hidden>`。
- `src/app.ts`：`Panel` 类型（:8）、switchPanel 数组（:126）、refreshControls 豁免选择器（:183-185）、构造/dispose 接入。
- `src/usage.ts`：GLM 查询前可选 provider 选择器 + 路由展示（直连/代理名/未管理）。

### 3.8 P1 工作项依赖与验收

依赖链：3.1/3.2 → 3.3 → 3.4 → 3.5 → 3.6/3.7（并行）→ 文档与 ACCEPTANCE_MATRIX 收尾。

P1 完成条件 = §7.3 中归 P1 的**输入级**条目全绿：身份与配置（改名、key 轮换、共享 key 同域名、悬空引用、并发修改）、HTTP CONNECT、失败保护（不直连+不重放）、TLS/端点（含跨源重定向/敏感头）、凭据与存储（含 loopback-凭据门、备份共存解释的行为）、独立证据、迁移/回滚（缺失侧车、损坏/未来版本、回滚共存、侧车被改写 fail-closed）；多 provider 隔离与环境优先级达“自有路径”级。**文件移动（随 attachment）与用户修改客户端文件（指纹恢复）显式归 P2**（v2 拆分，见 §7.3）。旧配置行为不变（无 provider 选择时 GLM/CLI/桌面现路径字节级不变，由既有 15+ usage 测试与 CLI 测试守护）。

---

## 4. P2 首个外部工具闭环（Codex）

前置：P0 能力表收口（§1.1 阻塞门）+ P1 network service。

| 工作项 | 文件 | 核心改动 |
| --- | --- | --- |
| 能力驱动 adapter | **新增** `crates/atm-core/src/network/adapter.rs` | `AdapterCapability`（版本+证据级）；Codex adapter：冲突检测 `[features].respect_system_proxy`（单数键）与 `$CODEX_HOME/.env` 代理键 → `ConflictReport`（检测失败/冲突 → 拒绝受管理启动，§3.2-5:69） |
| 受限启动器 | **新增** `crates/atm-core/src/network/launch.rs` | env 注入：explicit proxy → 设 `HTTPS_PROXY/HTTP_PROXY/NO_PROXY`（按 P0 优先级表）；explicit direct → 移除全部大小写代理变量；绝对路径 argv、不拼 shell、不改父进程环境（设计稿 §5:107） |
| 复用子进程策略 | `usage/process.rs:87-93` | `StdioRpc::launch` 增可选 env overlay（watchdog/进程组/Job 对象 :122-133,264-327 原样复用） |
| Attachment 落地 | `network/model.rs` + `application/network_service.rs` | ProviderAttachment 变更 API（一槽一 owner、漂移显式重确认，TEMPLATE_MAPPING_DRIFT 同构 template_store.rs:131-156）；**文件移动 = 显式重新关联**（§3:51，覆盖 §8“文件移动”输入）；CLI `register provider --adapter/--target` 与 `run provider -- --` |
| 实际调用状态 | `network/evidence.rs` | kind=RealCall：启动会话观察，不作流量宣称 |
| 精确字段预览与回滚 | `application/configuration.rs`/`batch.rs` | adapter 写外部配置文件走既有 preview/apply/**外部文件备份**（batch.rs:437-451 正是用武之地）+ 文件指纹恢复，“拒绝覆盖用户后改内容”（§9:188）——覆盖 §8“用户修改客户端文件”输入 |

P2 完成条件（v2 补齐验收行）：§7.3 归 P2 的输入级条目全绿——环境优先级（启动器全矩阵）、进程与平台（unix 腿）、多 provider 隔离（完整含“同进程缺失被拒”）、独立证据（完整）、**身份与配置之“文件移动”**、**迁移/回滚之“用户修改客户端文件”**；指定工具非计费合成流量证明 A→proxy/B→direct 隔离（双 mock 代理）；真实调用由用户显式触发。

## 5. P3 SOCKS、跨平台与远程认证代理

| 工作项 | 文件 | 核心改动 |
| --- | --- | --- |
| socks feature | `crates/atm-core/Cargo.toml:22` | reqwest features += `"socks"`。已核实零依赖图影响：reqwest 0.12.28 `socks = []` 空 feature（registry Cargo.toml:173），实现已在入图的 hyper-util 0.1.21；Cargo.lock 不变，CI `--locked` 不受影响 |
| 协议/DNS 语义 | `network/model.rs` + `transport.rs` | `ProxyProtocol::{Socks5h,Socks5}`；强制配对 socks5h↔`DnsMode::Proxy`、socks5↔`DnsMode::Local`（§4.1:79）；映射依据 reqwest 0.12.28 `connect.rs:540-543` |
| DNS 证据 | `network/check.rs` | client 侧 scheme 断言 + mock SOCKS 服务端记录收到域名 vs IP |
| 远程认证代理 | `network/{model,transport,check}.rs` | 解除 §1.4 loopback-凭据限制的**受控路径**：HTTPS-to-proxy（另测代理证书+目标证书链，§4.1:79）或已确认私有加密通道（显式确认记录，届时按标识演进流程入 schema）；在此之前维持 `PROXY_REMOTE_CREDENTIAL` 拒绝 |
| 平台腿 | **新增** `crates/atm-core/tests/network_platform_windows.rs`（v2 定名，登记 source-manifest）+ `rust-ci.yml` 视需要 | Windows 路径/大小写/信号；fixture 须原生可执行（StdioRpc 拒 cmd/bat/ps1 shim，process.rs:38-52——建议复用 atm 自身二进制或 Rust probe）；Linux 无桌面（`#[ignore]`+env 门 + DBUS 缺失 probe，linux.rs:327-346 模式）；凭据锁定、进程恢复按平台解密边界 |

§7.3 归属：SOCKS/DNS、Linux 无桌面（完整）、进程与平台（Windows 腿）、远程认证代理新用例。

## 6. P4 按需扩展（仅列准入条件）

- loopback API 转发：仅当 P2 后仍存在“同进程多 provider 无法隔离”的实证需求（设计稿 §5.1 全部门槛：仅 127.0.0.1、固定上游映射、非开放代理、SSE/取消/背压/不重放验收）。
- 更多工具 adapter：各自走 mini-P0 → mini-P2。
- §7.3 归属：流与取消（仅此阶段）。

---

## 7. 测试计划

### 7.1 复用（零新建）

| 既有模式 | 位置 | 用途 |
| --- | --- | --- |
| Transport/Rpc trait mock（协议级零网络） | `tests/usage.rs:25-97` | GLM 协议语义测试原样保留；route 注入不扰 trait |
| 加密侧车测试蓝本（加密落盘、标记 fail-closed、demo_protector） | `template_store.rs:221-268`；`tests/application.rs:19-51` | network 侧车存储测试照抄；**并发修改用例**：持锁期间二次 `Configuration::open` → `VAULT_BUSY`（flock 先例 linux.rs:348-360） |
| 版本化文档损坏/未知版本测试风格 | vault 测试（linux.rs/macos.rs 内） | 迁移/回滚行 P1 输入 |
| CLI 黑盒 + env 隔离 + `CARGO_BIN_EXE_atm` | `crates/atm-cli/tests/cli.rs:8-78` | 新命令测试；env_remove **补全部大小写代理变量**（:60-73 现缺）；**v2 补**：CLI 首次暴露的 `STORAGE_UNAVAILABLE/VAULT_BUSY/NETWORK_STORE_MISSING` 黑盒用例 |
| Python 假 CLI fixture（空格路径、watchdog、进程树击杀、confirmed 门） | `tests/codex_process.rs:15-130` | P2 启动器测试（unix 腿） |
| storage probe 子进程模式 | `tests/linux.rs:327-346` + `tests/support/storage_probe.rs` | 锁定存储/无 D-Bus 探测 |
| CI-only `#[ignore]`+env 门 + dbus-run-session | `tests/secret_service_ci.rs:12` + `scripts/Test-LinuxKeyring.sh` | 真实 keyring 相位测试 |
| live 显式 opting | `tests/skills.rs:378`（`ATM_SKILLS_LIVE=1`） | CLI check 真实出网 happy path（默认关，CI 关） |
| vitest + happy-dom + DesktopApi 全 mock + secret 不入 DOM | `apps/desktop/tests/*.test.ts` | 新 `tests/proxy.test.ts`；**断言 check 确认披露三要素文案与 legacy“未管理”文案** |

### 7.2 新建（从零；已核实仓库无 TcpListener/httpmock/wiremock/TLS fixture 先例）

1. **`crates/atm-core/tests/network_transport.rs`**（自含 helper，遵循“每集成测试自含”惯例；P3 复用再提升 `#[path="support/..."]`）：
   - **MockProxy**：`TcpListener` 绑 `127.0.0.1:0`、每连接一线程、裸 HTTP 解析 `CONNECT`、记录目标与 `Proxy-Authorization` 头、**按探测统计请求计数**、可脚本化结局：200 隧道 / 407 / 拒绝 / 畸形 / 半关闭。
   - **MockTlsTarget**：loopback TLS 服务。dev-dependencies 需 **rcgen**（新 crate，与 Cargo.lock 同提交）+ **rustls**（已在依赖图，声明即用）；测试 CA 经 `build_client(..., extra_roots)` 注入，不写系统信任（设计稿 §8:164）。
   - 关键断言面：目标 TLS 保留；`Proxy-Authorization` 不串上游；认证不落日志/DTO；direct client 在 `HTTPS_PROXY` 环境下 proxy log 为空（错误环境回退）；代理故障五模式均报脱敏错误码且不直连；**v2 补：① 五种故障模式下 attempts == 1（不透明重放，§8:173）；② 跨源重定向**——MockTlsTarget 脚本化 307 → client 拒绝（Policy::none 结构性拒绝之上的可观察错误断言），第二 mock 断言重定向目标上未收到任何 `Authorization/Proxy-Authorization` 且请求数为 0（§8:174“无敏感头跨源”）**；③ 非 loopback+凭据在 transport 层的拒绝传播**。
   - 测试目标 URL 走 `check::connectivity` 的 target 参数与 `build_client`（绕开 GLM 白名单）。
2. **`crates/atm-core/tests/network_store.rs`**：侧车往返/加密/标记/损坏/v2/悬空引用/引用删除拒绝/上限/锁定存储/**并发 VAULT_BUSY**/**loopback-凭据拒绝**/**悬空 credential 剪枝**/`credential_ref` 跨文件写入校验与 `delete_key` 守卫/**回滚共存（旧版本忽略语义=文件原样保留+重读成功）与侧车被改写 → fail-closed**/update_proxy·update_provider 的 revision 递增与证据过期。
3. **P2 追加**：双 MockProxy（A/B 隔离）；**`crates/atm-core/tests/network_launch.rs`**（env 优先级全矩阵：大小写、NO_PROXY、`.env` 冲突检测，配 cli.rs env 隔离骨架）；adapter 指纹恢复与“用户改写拒绝覆盖”（batch.rs 备份链）。
4. **P3 追加**：mock SOCKS5 服务端（记录域名/IP 证解析位置）；**`tests/network_platform_windows.rs`**（定名见 §5）；远程认证代理（HTTPS-to-proxy 证书链用例）。

### 7.3 设计稿 §8 验收矩阵 → 阶段归属（v2 改为输入级拆分）

| §8 行（:168-180） | 输入级归属 | 主要载体 |
| --- | --- | --- |
| 身份与配置（:168） | P1：改名、key 轮换、两个相同域名/共享 key、悬空 profile、**并发修改**；P2：**文件移动**（attachment 重关联） | network_store.rs / network_launch.rs+adapter |
| 多 provider 隔离（:169） | P1（自有路径 A/B）；P2（完整含“同进程缺失被拒”） | network_transport.rs / network_launch.rs |
| HTTP CONNECT（:170） | P1 | network_transport.rs |
| SOCKS / DNS（:171） | P3 | P3 SOCKS 测试 |
| 环境优先级（:172） | P1（自有 client 忽略 env）；P2（启动器全矩阵） | network_transport.rs / network_launch.rs |
| 失败保护（:173） | P1（不直连 + **attempts==1 不重放** + 错误环境回退） | network_transport.rs |
| TLS/端点（:174） | P1（错误证书/主机名不匹配/降级/假 GLM 域名——后者 usage.rs:560-580 已覆盖；**跨源重定向+无敏感头跨源 v2 补齐**） | network_transport.rs + 既有 usage.rs |
| 凭据与存储（:175） | P1（锁定存储、日志/DTO/导出、profile 含 userinfo、**备份恢复=回滚共存+篡改 fail-closed**；loopback-凭据门） | network_store.rs + network_transport.rs |
| 独立证据（:176） | P1（证据分离 + Trial 标记）；P2（CLI 未接管列） | network_store/service 测试 |
| 流与取消（:177） | P4 | — |
| 进程与平台（:178） | P2（unix）；P3（Windows 腿） | codex_process.rs + network_platform_windows.rs |
| Linux 无桌面/后台调用（:179） | P1（存储锁定 probe + **CLI STORAGE_UNAVAILABLE 面**）；P3（完整：代理失联、恢复） | linux probe / secret_service_ci 模式 |
| 迁移/回滚（:180） | P1（缺失新侧车、损坏/未来版本、**恢复备份=回滚共存**、用户改写**侧车**→fail-closed）；P2（**用户修改客户端文件**=指纹恢复） | network_store.rs / batch 备份链测试 |

---

## 8. 仓库规则合规清单

- **source-manifest**（`scripts/source-manifest.json`）：新跟踪文件全部登记：`crates/atm-core/src/network/{mod,model,store,transport,evidence,check,adapter,launch}.rs`（后两个 P2）、`crates/atm-core/src/application/network_service.rs`、`crates/atm-core/tests/{network_store,network_transport,network_launch,network_platform_windows}.rs`（后两个 P2、末个 P3）、`apps/desktop/src/proxy.ts`、`apps/desktop/tests/proxy.test.ts`、`docs/adapters/codex-egress.md`。`docs/ACCEPTANCE_MATRIX.md` 为既有跟踪文件，按阶段**增行**（见下）而非新登记。
- **ACCEPTANCE_MATRIX 增行（v2 新增）**：P1/P2/P3 收尾工作项各含“为网络/代理能力按 D/C/T 分级增行”（文件头规定的三级语义），未执行场景标“未验证”。
- **标识演进**（`docs/agents/internal-identifier-evolution.md`）：`provider_id/proxy_id/credential_id` 为全新持久化身份（首引入，无迁移）；`NetworkDocument version=1` 为持久化契约，后续字段变更走显式清单；不扩 `usage::Provider`；错误码（NETWORK_*、PROXY_*、CHECK_*、PROVIDER_*、PROXY_REMOTE_CREDENTIAL、PROXY_REFERENCED、PROVIDER_CREDENTIAL_MISSING）为 repo-local 非持久化，原子新增；不改任何既有 UUID/路径语义。
- **不迁移 vault**：零 vault schema 改动；`macos.rs:111-115` 枚举扩充是守卫清单扩展，非数据迁移；`Configuration::delete_key` 增网络引用检查是行为守卫，非 schema 变更。**备份表述（v2 修正）**：网络侧车无 per-save 备份机制（§1.5e 解释获用户确认后生效）；`backups/*.atmbackup`（batch.rs:437-451）仅用于 P2 起 adapter 对外部客户端文件的备份/恢复，与侧车无关。
- **distribution 域边界**：hub.rs 不动（§1.5a）；网络对象不写入 OMH 内容/harness registry/receipt（设计稿 §3:41）。

## 9. 未决证据缺口（不阻塞 P1）

1. Codex `respect_system_proxy` 引入版本与 0.93 SOCKS 传闻（社区，与源码矛盾已否）——P0 按 tag 复核。
2. reqwest 0.13.5（tauri 侧）socks 语义未核对——仅当桌面改用 tauri 自带 client 才需补查。
3. 每请求新建 blocking client 的 runtime 开销仅源码级确认（reqwest blocking/client.rs:1366-1376）——P1 不引入复用；未来引入需另行决策。
4. `hub.rs::fetch` 真实下载分支无测试覆盖（distribution_hub.rs:112-115 仅缓存早退）——采纳 §1.5a 则无影响；若用户要求改 hub.rs，需先补 mock server 回归网。
5. 设计稿与 ADR 0030 目前是未跟踪文件，本计划按其文本作为既定架构输入；P1 第一个 PR 应将它们一并入库。

---

## 附录 A：评审处置记录（v2）

| 评审项 | 级别 | 处置 |
| --- | --- | --- |
| R2-1 credential_ref 跨文件引用违反 §3.1 且将冻结进 v1 | blocker | 采纳：§1.3 两级引用结构（写入校验 + `Configuration::delete_key` 守卫 + 悬空展示/阻断语义 + managed 查询凭据来源澄清），§3.1/§3.5/§7.2 落实。不采用“删除字段”方案：设计稿 §3:45 明列“可选 API credential 引用”，删字段反而偏离设计 |
| R2-2 远程 HTTP 代理凭据无门 | blocker | 采纳：§1.4 loopback-凭据硬规则 + `PROXY_REMOTE_CREDENTIAL` + 测试；远程认证代理移 P3（§5），作为收紧型实施参数随 §10.4 向用户说明 |
| R1-1 缺 provider/binding 读取面 | major | 采纳：`list_providers()` + `atm list providers` + 桌面 `list_providers`（§3.5/3.6/3.7，三处注册点同步） |
| R1-2 缺改名/修改/凭据轮换与删除 API | major | 采纳（评审建议①）：`update_proxy/update_provider` + 剪枝式 credential 生命周期（§3.1-3、§3.5、§3.6），P1 验收行按输入拆分后可达标 |
| R1-3 缺未保存 profile 试用入口 | major | 采纳：`check_proxy_trial` + `atm check proxy` + EvidenceMethod::Trial（§3.4/§3.5/§3.6），不落盘 |
| R2-3 侧车备份/恢复无工作项 | major | 采纳（评审建议②分支）：修正 batch.rs 错误归因；§1.5e 向用户提交解释性决策（回滚=原位保留即加密备份、无 per-save 备份、凭据丢失=重录、格式迁移时才引入备份）；测试补回滚共存/篡改 fail-closed（§7.2/§7.3） |
| R2-4 §8 行未按输入拆分、P1 出口不可达 | major | 采纳：§7.3 改输入级拆分；文件移动/用户修改客户端文件归 P2 并入 P2 完成条件（§4）；并发修改补 VAULT_BUSY 测试（§7.1/7.2） |
| R1-4 / R2-9 ConfigurationSession 引用错误 + CLI 首触配置服务 | minor | 采纳：引用更正（桌面 main.rs:784、skills.rs:481）；§3.2 新增 CLI 平台存储依赖说明与 cli.rs 失败路径用例 |
| R1-5 超时字段悬空 | minor | 采纳：字段更名 `total_timeout_secs` 并写死消费语义（connectivity 消费、usage 固定 5s/12s），随 schema 批准（§3.1-2） |
| R1-6 失败作用域宽于 §3.1 字面 | minor | 采纳：列入 §1.5(d) 用户确认清单 |
| R1-7 远程凭据门（同 R2-2） | minor | 已由 blocker 处置覆盖 |
| R1-8 备份表述错误（同 R2-3） | minor | 已由 major 处置覆盖 |
| R1-9 / R2-8 P0-P1 依赖矛盾 | minor | 采纳：§0/§2 显式二选一（MockProxy 复用或 P0 自带不入库脚本） |
| R2-5 check 前置披露 | minor | 采纳：§3.4 三要素披露 + proxy.test.ts 断言 |
| R2-6 跨源重定向/敏感头无断言 | minor | 采纳：§7.2 用例（307 拒绝 + 重定向目标零请求零敏感头） |
| R2-7 不重放无断言 | minor | 采纳：§7.2 attempts==1 断言 |
| R2-10 pub(crate) Secret 可见性/clippy | minor | 采纳：`pub(crate) mod network` + pub View 类型 re-export（§3.1-1），已核实 model.rs:9/lib.rs:12 与 rust-ci.yml:90,220,310 |
| R2-11 ACCEPTANCE_MATRIX 增行 + P3 fixture 未命名 | minor | 采纳：§8 增行工作项；fixture 定名 `tests/network_platform_windows.rs` 并入 manifest 清单 |
| R1-missing 悬空 credential_ref 展示 | missing | 采纳：`ProviderView.credential_state=Missing` + `PROVIDER_CREDENTIAL_MISSING` 阻断受管理操作（§1.3/§3.5） |

其余 missing 项均由上表对应条目覆盖；两份评审的 overall 结论（证据核实、红线落实）与本计划自查一致，无驳回项。

## 附录 B：定稿自查

- P0–P4 结构完整：§2/§3/§4/§5/§6，各阶段有交付物、接入点、完成条件、依赖。
- 设计稿 §10 四个待决项状态明确：§1.1【建议已定，等用户版本（阻塞 P2）】、§1.2【建议已定，等用户确认进程级影响】、§1.3【草案就绪，批准前不落盘】、§1.4【建议已定，等用户确认认证需求】；另有 §1.5(a)–(g) 七项补全决策挂用户确认。
- 验收矩阵映射齐全：设计稿 §8 全部 13 行（:168-180）在 §7.3 逐行映射到阶段与测试载体，输入级拆分后无遗漏、无 P1 不可达条目。
- v1→v2 变更全部可追溯到评审条目（附录 A），blocker/major 无静默忽略。

传输说明：v1 计划文本送达评审时，capabilities 权限条目处有一处被 harness 中和的控制标记（`allow-<` 后的 `<` 被替换为 `<\`）；该处实为 Tauri 权限命名（allow- 前缀 + 命令名），非指令内容，本稿已按原义书写且不再含该形态。