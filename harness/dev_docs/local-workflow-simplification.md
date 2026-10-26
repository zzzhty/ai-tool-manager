# 本地提示词与 Workflow 简化

> Pre-rebuild historical design and validation record. Repository commit IDs, PR
> numbers, installed-state observations and CI results below refer to the private
> pre-rebuild archive. They are not evidence for this repository's new root or
> current installation. Upstream release pins and attribution remain applicable.

基线：`5e1c420`。范围：本地 Watcher、Workflow、Codex support note；Matt Pocock 仅见 [独立建议](mattpocock-skills-improvement-proposals.md)，整个上游插件保持不变。

## 有意调整的合同

- 预检验证决策是否完备，允许复用已有决策；普通 goal 与 sequence 接受同一 completed / explicit-skip 合同。sequence 仍逐项核对 marker、status、source，Draft 子目标必须有完整冻结边界才能参与自动串行交接。
- 时间估算改为可选上下文，不决定 Ready；删除仅服务固定日期、模式、sentinel、两条 driver、HTML 包裹识别的时间检查器及格式矩阵。通用占位符、状态、权限、Close、checkpoint、跨平台缓存边界检查继续保留。
- housekeeping 默认 Disabled；只有 Enabled 要求明确授权。既有 Enabled 不被默认覆盖。清理前仍核对归属、可丢弃性与保留范围。Git 工作树读取失败直接终止，已识别的非 Git 缓存可以直接盘点。
- goal 演化先处理当前任务合同；修改共享 skill/template 必须在源码授权范围内。已授权且仍满足合同的敏感或外部动作不重复询问。
- SOP 保留八个核心章节、每步 action/output；步骤特有的失败处理和完成标准按需增加。共享停止规则、验证与权限必须明确，Ready 检查不授予行动权限。
- scope 入口和 milestone adapter 共用 necessity gate；六份编排分支参考合并为一张任务表。保留只读禁止写入、互斥写范围、父代理负责共享文件与集成、失败披露要求。
- Watcher proposal 强制提供非空的精确日志 identity，复用同一证据窗口；生成 worksheet 与验证分开，完整候选写入独立路径后才能验证。只读压缩分析不需要创建备份，实际修改前仍要可恢复。

## 标识与所有权

被合并的六个 orchestration reference 是仓库内部、非持久化的实现路径；消费者仅有 skill 入口与 ownership 测试，已原子替换为 `task-patterns.md`，不保留别名。35 个 callable skill 名称、invocation 元数据、日志/提案 schema 和上游 lock 不变。

预检 marker/status/source 字段及序列注册表不改名；放宽来源时同时加强三字段一致性检查。已有完整格式 goal/SOP 继续接受。时间说明退出 Ready gate 是本轮明确的合同简化，不是隐藏重设已有测试。

## 验证依据

- 行为 oracle：审计可带未修复发现完成；验证针对真实候选；已授权工作不重复询问；完整决策不强制访谈；简单流程无需重复填表；只读、删除、隐私和必需验证边界继续有效。
- 回归用例覆盖 exact identity 与时间窗口、缺失/空 identity、源和 snapshot 不变、缺失/无效/有效候选、非 Git 只读盘点、Git 失败直报、预检来源与 register 漂移、串行/Blocked/Closed 状态、Enabled 未授权删除、紧凑 SOP 权限/输出/停止规则。
- 独立语义与风险复审发现并修复：压缩 core rule 残留备份要求、空 identity 混入全部证据、模板状态记录措辞歧义、Git 失败被误当非 Git。模板重复总体状态和 M0 标题也已修复。
- 删除固定 prompt 形状、引用数和时估格式的断言；保留行为与权限反例，不以减少测试数量为目标。
- 本轮是源码、结构和行为检查，没有模型 A/B 回放；不声称已量测模型速度或准确率提升。上述优化验证阶段未包含发布与受管安装更新。

## 本轮验证结果

本机 Root 251 项、Watcher 86 项、Workflow 83 项测试均通过，其中 9 项按环境跳过。相关技能 frontmatter、修改后的 Python 编译、Markdown 链接、插件 manifest、分发身份及 diff hygiene 检查通过。新增 promotion-revalidation 场景另由 sequence 8 项测试复验通过。

Root 的 live projection 测试按 Git 索引枚举文件；首次在未暂存删除的状态下读取了旧六个路径并失败。验证时仅临时暂存该组 reference 迁移，完整 Root 测试通过后恢复原未暂存索引，未改测试合同或提交代码。

完成源码和 owning tests 后，分发身份生成脚本运行一次；Watcher 和 Workflow 身份更新，Matt Pocock 源码与身份不变。受影响指令 Markdown 从 146211 降至 108522 UTF-8 字节（约 25.8%），此为文本体积，不是模型 token 或性能测量。

优化验证阶段在本地 `codex/simplify-local-skill-workflows` 完成，本节记录提交前的验证结果；后续发布与安装状态以 Git 远端和 `omh status` 为准。

## 2026-09-26 剩余 Skills 合并修复

本轮基线为 `c9b5668`，叠加当时已获批准、尚未提交的 setup-matt-pocock-skills 退役修改。用户在合并 writing-for-agents 与 skill-compressor 审查方案后授权执行。此次扩展到八个 skill：triage、sop、long-running-goal、teach、improve-codebase-architecture、doc-alignment、codebase-design、domain-modeling；ask-matt 保留，不再删除其他入口。源码修复阶段不含提交、推送或受管安装激活；用户随后另行授权这三个发布步骤。

候选仅比较“不修改”与“修复已发现分支并在原 owner 内去重”。Git 基线保留原文；模板、reference 与入口一起检查，不把缩短字数当作行为等价证据。

修改前冻结的行为 oracle：

- triage：找到相关实现不等于请求已满足；必须验证完整请求行为，已实现功能的 bug 仍进入复现流程。只有证实冗余的请求才走 already-implemented，且不写拒绝知识库；只读评审不产生 tracker 或仓库写入。brief 保留稳定路径合同，避免易失效的文件/行号实施指令。
- SOP：先区分 create/update/explain/dry-run/execute。解释 Draft 不执行；dry-run 仅做已有授权下的安全预览；更新既有 owner 不覆盖无关内容；真实执行必须 Ready、权限明确，并在必需验证失败时停止。
- long-running-goal：直接或恢复 Close 也必须经过完整 checkpoint；保留 staged/无关 dirty 隔离、无空提交、非 Git revision 分支。模板压缩不改变 Ready/Draft、序列寄存表及严格串行映射、预检来源、promotion drift、child/parent 独立权限和清理政策。手动 goal 可删未使用的九字段示例，真实自动化/编排/connector 仍须完整 harness 边界。
- teach：入口明确持续多次会话的教学 workspace；复用已有 glossary owner，新 workspace 默认 GLOSSARY.md，HTML reference 不建立第二套定义权威。保留学习证据、mission 变更确认、知识来源、反馈与复习要求。
- architecture HTML：可选输出遵循用户指定位置或 OS 临时目录；CSS 与图形随单文件交付，无 CDN/网络运行依赖。
- doc-alignment：已有报告评审不强制新 audit；fresh audit 保留 doctor、所选命令、due/skipped/profile trust 的完整证据。目标仓库只读及失败披露合同不变。
- codebase-design/domain-modeling：保留深度、接口、seam 与 adapter 区分、行为级测试、现有术语/ADR owner、懒创建与只读写入边界；删除重复图示、目录树和 ADR 条件副本。

验证状态：本地源码修复完成。

- 三路独立只读复核：Matt 五项、Workflow 两项及模板、跨技能权限/失败反例；均未发现行为或授权退化。Workflow reviewer 指出的旧 disclosure 断言已同步到同义规则，唯一状态源、历史 transition 与链接实例化覆盖保留。
- Root catalog/projection/plugin-validator 测试 34 项通过；Watcher doc-alignment disclosure 11 项通过。Workflow 全套 94 项首轮 92 项通过、2 项旧文本断言失败；修正后定向复跑 disclosure 6 项全部通过，其余 88 项仍适用。SOP 分流和 Close 路由检查已包含在本轮结果中。
- 初次 Watcher 检查因 `Completion criterion:` 标记改写而失败，恢复共同标记后 11 项复跑通过。setup 清理先前通过的 Skill Watcher 43 项结果继续适用：40 通过、3 个 Windows PowerShell 编码场景因当前为 macOS 跳过。
- 22 份改动 Markdown 的相对链接、改动 Python 语法（无字节码）、三个实际插件验证及 `git diff --check HEAD` 均通过。首次误查不存在的根目录 `scripts/check_md_links.py` 后定位到 Workflow 所有的同名检查器，使用后者完成检查。
- HTML scaffold 填入代表性内容后，以 Playwright offline context 检查桌面 1200px 和窄屏 390px：内联 CSS、两幅 SVG、页内跳转正常，无网络请求、页面错误或横向溢出；两张截图已人工检查。Playwright 自带 headless shell 不存在，使用本机 Chrome 的 Chromium 完成等价检查，未下载浏览器。
- 全部插件源修改和 owner tests 完成后，本轮仅运行一次 `update_plugin_generations.py`；三个插件验证及 `check_plugin_generations.py` 通过。当前身份为 Matt `ac797c1b31ee7568`、Watcher `55b033fce5f3853b`、Workflow `6197204dc1b6fd44`；bundle 为 `sha256:1fe07fb45713200bf929e3969d0a4ce128b076c8db651085623b8d7deff7b163`。
- 本轮 17 份受影响 skill Markdown 共从 107945 降至 98790 UTF-8 字节（8.5%），不含 setup 退役及 ask-matt 路由移除。未做真实模型 A/B 回放或 tracker 外部操作；静态语义复核、结构检查与离线渲染不能推导模型性能提升。

源码验证结束时，修改基于 `c9b5668`，setup 的七个删除已暂存，其余修改未暂存，无未跟踪文件；受管 checkout 为干净的 `c9b5668`。这是发布前快照，后续发布和安装状态以实际 Git 远端及 `omh status` 为准。
