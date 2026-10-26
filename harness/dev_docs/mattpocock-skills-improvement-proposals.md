# Matt Pocock skills 最终合并方案

> Pre-rebuild historical design and validation record. Repository commit IDs, PR
> numbers, installed-state observations and CI results below refer to the private
> pre-rebuild archive. They are not evidence for this repository's new root or
> current installation. Upstream release pins and attribution remain applicable.

状态：本地源码已实施并验证，待提交、发布与正式环境激活。更新日期：2026-09-08。本文件取代此前的 7 项核心、11 项候选及全仓 14/16/5 草案，作为本轮实施范围与验收结果的唯一记录。

## 1. 最终决定

维护一个由本仓库负责的 Matt 本地选编版：**保留 20 项，退出分发 5 项**。保留项按维护优先级分为 11 项核心与 9 项专项；这只是文档分组，两组都在同一插件中分发，沿用各自显式/隐式触发边界，不增加启停配置、动态安装或另一份技能副本。

Watcher 的 4 项、Workflow 的 6 项继续保留。实施后全仓 canonical catalog 从 35 项变为 30 项：15 项核心用途、15 项专项用途。数量是逐项判断的结果，不是压缩指标。

保留既有插件目录和 `mattpocock-skills:` namespace；README 与显示说明明确为 OMH 本地派生版本，保留上游来源与许可。上游作为选择性吸收改进的来源，不再要求完整同步每个发布。

## 2. 证据与两份分析的取舍

输入为[服务器统计共享入口](https://chatgpt.com/share/6a9f41a0-c2bc-83ea-92c5-65d26cb3b7c3?ogimg=plain)、任务“评估保留Skills”中的原始附件 `skill-usage-statistics-2026-09-08.md`、[已完成的并行分析](https://chatgpt.com/s/t_6a9f442a07e08191a6698c7e58974e86)，以及本仓库全部 25 项 Matt 技能、22 份 Markdown 引用、2 个 shell 模板的源码审查。

统计覆盖北京时间 2026-07-07 至 2026-09-08：995 个已归因轮次、273 个 session；近 30 天为 451 轮。Matt primary 分别为 382 与 186 轮。

- 采纳并行分析对既有入口的重视：handoff、grill-with-docs、implement 继续独立保留；短正文不是删除理由。
- 保留源码审查发现的明确问题，实施针对性修订。没有成功率数据，不妨碍修复未提交修改漏审、无条件 stage-all、重复确认等已有证据支持的问题。
- writing-for-agents 上调为核心用途：全量 primary 为 31，近 30 天为 3；本仓库的产品正是 harness/skills，不能只按应用开发服务器近期频率排序。
- 将“默认/按需”改为维护与用途分组，避免为精简引入一套分发配置机制。退出项从 canonical catalog 移除，不另外复制进插件的隐藏或备用目录；恢复来源是 Git 历史和已记录的上游基线。
- 不合并具有不同产物或用户意图的技能；正文中的共同方法复用一个所有者，常用入口保持简短。

本方案 11 项 Matt 核心对应 `361/382 = 94.5%` 的历史 primary、`172/186 = 92.5%` 的近 30 天 primary。全仓 15 项核心对应 `956/995 = 96.1%`、`432/451 = 95.8%`。所有退出项在该报告中均为零 effective，因此保留的 30 项包含全部已记录 primary 对应的技能名称。

这些是名称集合对历史归因的覆盖，不是任务成功率、正文执行次数或删减后的能力保证。近 30 天核心 primary 用总量减去集合外 effective 推得；集合外技能全量 supporting 均为零，故这一减法成立。995 个 task_outcome 全为 unknown，不能据此声称速度、准确率或 token 成本已改善。

## 3. 完整名单

### Matt 核心 11 项：保留并优先修订

下表近 30 天为 effective；全量 primary 与 supporting 分列，避免混成执行频率。

| 技能 | 全量 primary | 全量 supporting | 近 30 天 effective | 处理重点 |
| --- | ---: | ---: | ---: | --- |
| `handoff` | 151 | 0 | 69 | 独立保留；普通交接不要求先创建 long-running-goal。复用既有产物链接，保留必要上下文、下一步与隐私处理。 |
| `grilling` | 64 | 45 | 59 | 关键决策已明确即可结束，沿用已有答案；不要求穷尽所有分支或无条件委派。 |
| `grill-with-docs` | 43 | 0 | 19 | 保留“讨论并记录决策”入口，继续组合 grilling 与 domain-modeling，不复制两者正文。 |
| `writing-for-agents` | 31 | 0 | 3 | 保留行为保持、信息放置和渐进披露方法；触发与平台说明只保留当前有效、必要的部分。 |
| `codebase-design` | 21 | 10 | 16 | 设计原则的唯一所有者；测试边界按独立行为价值选择，删除旧测试须有实际替代覆盖。 |
| `implement` | 12 | 0 | 7 | 向 code-review 明确传入本次实现范围；沿用已确认测试决策，提交动作依照已有授权。 |
| `domain-modeling` | 11 | 43 | 28 | 维护术语与需要持久保存的决策；不要求每次局部修改重新建模。 |
| `improve-codebase-architecture` | 10 | 0 | 3 | 保留寻找架构改进机会的入口；HTML、多代理、多份设计按任务需要选择。 |
| `triage` | 9 | 0 | 2 | 保留已有 issue/PR 入口及必要 tracker 约定；复用已知信息，已授权的明确状态修改不重复确认。 |
| `code-review` | 7 | 12 | 12 | 完整覆盖指定提交、暂存区、工作区；保留 Standards/Spec 两个视角，去重并按影响排序。 |
| `tdd` | 2 | 9 | 6 | 保留逐个行为的 red/green 反馈；不重问已确认边界，不一概禁止有独立价值的内部行为测试。 |

### Matt 专项 9 项：保留，按具体场景触发

| 技能 | 全量 primary | 近 30 天 effective | 处理重点 |
| --- | ---: | ---: | --- |
| `ask-matt` | 7 | 5 | 压缩为选择保留技能的简短路由表；移除已退出技能的路径及强制主流程。 |
| `research` | 4 | 4 | 保留主来源研究与持久 Markdown 产物；委派方式按任务规模及当前权限决定。 |
| `prototype` | 3 | 2 | 保留以可运行原型回答设计问题的方法；只在实际会话或目录边界需要时交接。 |
| `diagnosing-bugs` | 2 | 1 | 可先用代码、配置和日志形成可证伪假设；复现最小化、假设数量和回归检查与问题匹配。 |
| `grill-me` | 2 | 0 | 保留简短的普通盘问入口，复用 grilling；不因存在 cwd 就要求写文档。 |
| `setup-matt-pocock-skills` | 1 | 1 | 保留剩余 tracker 流程所需配置；复用已有配置，移除专用于退出流程的章节。 |
| `teach` | 1 | 0 | 保留连续学习场景，不混入普通开发任务。 |
| `to-spec` | 1 | 1 | 综合已有讨论，按复杂度组织需求；不强制极长用户故事或重新访谈，发布遵循已有授权。 |
| `resolving-merge-conflicts` | 0 | 0 | 保留专项能力并修复 stage-all/always-resolve；只处理本次冲突，有无关修改时不带入提交。 |

### Matt 退出分发 5 项

五项在全量、近 30 天与近 7 天均为零 effective。以下源码和维护判断共同支持退出，零使用不是唯一理由。

| 技能 | 退出理由 | 对应工作如何处理 |
| --- | --- | --- |
| `to-questionnaire` | 独立问卷工作流没有观察到需求，其常规产物可由普通文档任务完成。 | 有具体问卷请求时直接起草；发送仍按用户授权。 |
| `to-tickets` | 当前没有采用这套拆票流水线的证据，保留会延长 ask-matt 的强制流程与配置维护。 | 根据实际任务和现有 tracker 拆分；不把原技能全文搬进 implement。 |
| `wait-what` | 对上一条回答重新解释属于普通会话操作，独立入口的增益有限。 | 用户提出澄清要求时直接响应。 |
| `wayfinder` | 引入另一套决策地图、标签和会话推进流程，当前无使用需求。 | 普通规划沿用现有环境；long-running-goal 仍须用户明确选择，不自动替代所有复杂任务。 |
| `wizard` | 需维护生成 shell、凭据和第三方工具交互，且已复现必需写入失败却报告完成的问题，当前没有使用需求。 | 遇到人类必须操作的步骤时提供具体步骤；重复场景再按实际需求编写脚本或 SOP。 |

实施时从源目录与分发 catalog 移除这五项，不新增兼容入口、备用技能包或复制模板。Git 历史与上游来源保留，未来有具体需求时可重新选入。既有任务、工单、用户数据和统计日志不因技能退出而删除。

### Watcher / Workflow 10 项

| 用途 | 保留技能 |
| --- | --- |
| 核心 4 项 | `watcher:housekeeping`、`watcher:doc-alignment`、`workflow:long-running-goal`、`workflow:sop` |
| 专项 6 项 | `watcher:skill-compressor`、`watcher:skill-maintainer`、`workflow:orchestrate-subagents`、`workflow:prompt-strategy-loop`、`workflow:scope-discipline`、`workflow:summary-in-html` |

本轮采用已完成的[本地优化](local-workflow-simplification.md)，不因历史频率再重写这些技能。尤其是 scope-discipline：零入口归因不等于共享 necessity gate 未被使用，保留其现有职责。

## 4. 合并共同方法，保持明确入口

| 内容 | 唯一所有者 | 其他入口如何使用 |
| --- | --- | --- |
| 盘问方法 | `grilling` | grill-me 作为普通入口；grill-with-docs 组合 domain-modeling；triage/架构调查仅在决策缺口需要时调用。 |
| 领域术语与 ADR | `domain-modeling` | 其他技能直接引用已有术语与决策，确有新增知识时维护。 |
| 模块设计与测试边界原则 | `codebase-design` | tdd 与架构调查引用原则，各自只描述执行动作。 |
| 审查方法 | `code-review` | implement 只负责说明要审查的修改范围，不复制 reviewer rubric。 |
| 普通会话交接 | `handoff` | ask-matt 删除重复的硬编码上下文决策树；long-running-goal 继续拥有其专用合同和继续执行状态。 |
| 全局授权、委派与验证边界 | `agents/global-instructions.md` | 各技能只保留任务特有规则；既有明确授权沿用，不把每一步变成新确认门槛。 |

不强行合并 grilling/domain-modeling、codebase-design/架构调查、handoff/long-running-goal。这些组合分别区分讨论与持久知识、设计方法与调查产物、普通交接与正式目标合同。

ask-matt 改为“用户意图 → 合适入口”的路由，不再拥有 idea → interview → spec → tickets → implement 的必经路径。已有清晰任务可直接执行；已有明确决策不再重新收集。删除固定 150k 上下文阈值、prototype 必须独立目录、cwd 必须触发文档模式等假设。其 PHASE-BOUNDARIES.md 中有价值的交接说明归入 handoff，退休独立的重复决策树，遵循当前环境的上下文管理能力。

## 5. 所有权与分发迁移

这是一次正式的“上游原样镜像 → 本地维护选编”迁移，应在同一可审查变更中完成，不能先改正文再用新的 hash 让旧镜像校验通过。

1. 用 ADR 记录所有权变化、选编名单、上游 `v1.2.3` / `6acc160e4e0cd062dbbbd7a1b26ae92855edf07e` 基线、兼容影响与回退方法。改写 root/scoped AGENTS 中的镜像路由及插件 README，保留许可和来源。
2. 退役 `scripts/update_mattpocock_skills.py` 的完整导入路径及 `.codex-plugin/upstream-lock.json`。来源版本转为 README 中的事实记录；上游更新使用 Git 差异进行选择性采纳，不新建补丁叠加器或自动合并服务。
3. `scripts/check_harness.py` 的 Matt 特判改为通用本地插件验证。对导入器和锁的所有当前调用、README 命令与测试同步调整；有独立价值的目录安全、引用完整性、schema 和缓存一致性覆盖迁入现有所属检查。历史 ADR 保留并标明被新决定取代，不改写历史事实。
4. Matt 成为本地拥有的插件后，按现有规则由仓库 `VERSION` 加内容 generation 定义版本，不增加另一份版本配置。当前数值基线将从上游 1.2.3 转为仓库 1.0.0；这是版本权威迁移，需要在安装检查中确认加载目标 generation，而非继续选择旧上游包。
5. 技能与所有引用最终确定后运行 owning tests，再运行一次 `scripts/update_plugin_generations.py`，随后验证单一当前分发身份。现有分发内容身份、缓存一致性和跨平台路径合同继续保留。

已发现的退出项消费者为 ask-matt、setup 主文档及其 GitHub/GitLab/local tracker 参考。清理其中的路由、示例和 Wayfinding operations 专属段落，保留 triage/to-spec 仍使用的配置与通用 tracker 能力。元数据目录、marketplace、校验入口和安装投影一并随 canonical catalog 对齐。

技能名称属于已发布接口，历史日志与用户项目配置属于持久状态：保留 20 项名称不变；退出 5 项的直接调用在新分发中将不可用，明确列入迁移说明。清理本仓库当前消费者，不擅自修改外部项目的配置、旧工单、日志或归档。

当前元数据要求 legacy_names 指向现存 catalog 身份，因此同时移除 `to-issues → to-tickets` 等指向退出项的当前映射，保留指向仍存在技能的映射。历史报告继续按日志原始名称展示退出项及其次数，允许其没有当前 logical group；不能把未知或退出名称过滤为未归因，也不新建历史身份注册库或可调用兼容入口。原始日志不重写。

回退依靠已提交基线和既有 manager 生命周期，保留当时完整源与分发身份；不维持第二套并行运行的技能树。既有镜像校验在上述所有者变更真正实施前继续有效。

## 6. 实施顺序与验收

建议作为一个完整源码变更实施，先全部完成本地修订和验证，再处理发布与环境激活。

1. **确定迁移基线并修改所有者。** 盘点当前 diff、外部引用类别与相关校验；按上一节完成本地派生所有权转换。
2. **修复已确认的行为错误。** 首先处理 implement/code-review 的审查范围、冲突处理的暂存边界、TDD 与设计原则的测试冲突，以及只读 review 自动 setup 的越权路径。
3. **精简保留技能并移除退出项。** 沿用已有决定、缩短 ask-matt、按需选择委派/HTML/访谈，清理所有当前引用。wizard 退出后不继续维护其脚本。
4. **验证并生成分发身份。** 使用现有检查和下表中的行为场景，不建立固定字数、标题数、技能评分或提示词快照门槛。
5. **发布与激活。** 源码方案验收后，按用户当时授权提交、推送、更新指定环境；核对远端提交、受管源码、安装 catalog、目标 generation 与工作树状态。本轮本地实施尚未执行这些发布和正式环境激活动作。

| 验收场景 | 必须观察到的结果 |
| --- | --- |
| 新分支仅有未提交实现；或旧提交与暂存/未暂存修改混合 | 审查包含调用方指定的全部修改，不因 HEAD 未更新漏审。 |
| 冲突现场存在无关 staged/unstaged 文件 | 不把无关内容带入提交；缺少产品决定时保留现场，不盲目选择、不擅自 abort。 |
| 已确认设计和测试边界后调用 implement/to-spec/tdd | 直接沿用决定；仅对影响当前工作的新缺口提问。 |
| 只读 review 缺少 tracker 配置 | 使用已提供任务和仓库事实完成可做的审查，不创建配置、标签或发送消息。 |
| 更高层测试新增后仍有独立隐私/schema/错误处理覆盖 | 保留尚未被替代的回归测试，不按“内部/浅层”标签一概删除。 |
| 用户只要求普通交接或普通盘问 | handoff/grill-me 可独立使用，不强制创建 goal、文档体系或重新访谈。 |
| 在不同 harness 安装或刷新 | catalog 为 30 项，Matt 为 20 项；退出项无残留投影、保留项及资源可解析，缓存身份匹配。 |
| 解析包含旧名或已退出技能的历史日志 | 保留历史记录及可解释身份，不把过去的使用改成未归因或删除。 |

沿用 README 的相关验证入口：插件/frontmatter、catalog、引用、Watcher 元数据、分发身份及受影响的跨平台生命周期检查。可自动检查的确定性错误写入所属测试；指令行为用冻结的上述场景做比例适当的语义复核。不得声称静态检查等于模型执行评测。

## 7. 统计问题与当前边界

本地方案基线为 `8a252783d9c4bddbd7569daf151e7fb150aa7cd1`。服务器报告列出的 `f6ce916826255a135a6c2c37c3007eb466d165f2` 不在本地对象库，GitHub compare 返回 404；未确定两者祖先关系或服务器激活状态。统计仅作历史使用基线，不作本轮优化前后对照。

当前仓库 supporting 元数据只有四个入口关系：grill-me → grilling、grill-with-docs → grilling/domain-modeling、implement → code-review、improve-codebase-architecture → codebase-design。没有无条件带入 doc-alignment 或 tdd 的当前关系。历史 336/9 次 supporting 不能直接解释为现版本的执行流程；归因记录也不负责真正加载技能。

工作服务器的 housekeeping 高归因值得结合真实触发场景调查，但本地新 goal 合同已将 housekeeping 默认设为 Disabled。先确认服务器版本，避免重复修订已改变的合同。历史名称报表归并、任务结果 unknown、工具失败缺分母的问题单独记录，不作为本次选编实施的前置遥测工程，也不通过改 supporting 元数据美化次数。

## 8. 实施与验收记录（2026-09-08）

在 `codex/curate-mattpocock-skills` 完成源码迁移：[ADR 0012](../docs/adr/0012-maintain-a-local-mattpocock-selection.md) 记录所有权和兼容边界。Matt 保留 20 项、退出 5 项，catalog 为 30 项；保留项的名称、frontmatter 调用开关及 native policy 与基线一致（10 项显式、10 项隐式）。上游 importer/lock 已删除，公共方法归属及退出项当前引用已同步。

独立语义复核和风险复核按第 6 节冻结场景比较基线与候选。复核发现并修复了原型参考中的越界整合步骤、既有暂存内容进入提交的风险、领域文档重复 owner、存储测试示例与原则矛盾、HTML 参考重复术语规则；整改已定向复查通过。保留完整原流程的基线无法满足这些场景；未再构造无实质取舍的多份压缩候选。

通用校验迁移还暴露了两项实际问题，并在现有所有者处解决：

- 本机官方 plugin validator 要求所有 `disable-model-invocation` 为 false，与已批准保留的跨 harness 调用策略不兼容。Python、Unix 和 PowerShell 生命周期现在默认使用现有仓库 validator，显式 `PLUGIN_VALIDATOR` 仍可覆盖；失败不会改用其他工具重试。没有修改安装在用户环境中的校验器，也没有把调用标志改为 false。
- 原有效的 native YAML 字段/schema、必需界面字段和资源路径约束已迁入 `repo_skill_catalog.validate_skill_invocation`，插件验证复用同一函数。补充了 `allow_implicit_invocations` 拼写错误不能静默开启隐式调用的反例，以及显式校验工具非零失败不得重试的回归。

| 检查 | 结果 |
| --- | --- |
| 根目录 unittest 全套 | 235 项：229 通过、6 项 Windows 专属检查跳过。 |
| Watcher unittest 全套 | 86 项：83 通过、3 项 Windows 编码检查跳过。 |
| 三个插件、catalog、native policy、资源 | 仓库插件验证通过；30 项可发现；20 项 Matt 的 36 处相对 Markdown 资源链接可解析。 |
| 历史统计 | 五项退出技能及旧 to-issues 原始名称仍保留计数，不改写历史事件；仍存技能的旧名映射有效。 |
| 实际 Codex CLI 隔离安装 | 临时环境先安装旧 Matt 1.2.3 的 25 项，再安装候选；三个活动包为 20/4/6 项，精确版本和缓存内容一致，Matt 成功切换到数值较低的新版本权威。 |
| 原生目录隔离投影 | 30 项投影通过；清除五个指向已退出源的旧链接，保留无关个人技能。 |
| 分发身份与 diff | 包内容完成并经 owning tests 后生成一次；最终 identity 和 git diff --check 通过。 |

首轮源码实施验收时的分发版本为 Matt `1.0.0+codex.32c73595527d6856`、Watcher `1.0.0+codex.ec7a0b31b889a82e`、Workflow `1.0.0+codex.b1791581f2372ef1`。Watcher generation 的变化来自 catalog/历史归因集成测试调整，其技能正文未重写；Workflow 内容和身份未改变。生成后仅继续完善包外的生命周期校验代码与验收文档，包内容身份保持一致。

首轮测试遇到的尚未生成身份、尚未暂存删除导致的 Git 索引投影问题均在正常收尾后消除；新增测试对 teach 别名的错误假设也已修正，保留原短语匹配规则。最终仓库门禁全部通过。系统 skill-creator 的 quick_validate.py 对 10 项隐式技能通过，对 10 项显式技能因原有 disable-model-invocation/argument-hint 字段拒绝；此工具不适配已批准的双 harness 元数据，本次以实际安装和仓库原生 schema/policy 检查验证该合同，未伪称该 quick validator 全通过。

以上指令行为结论来自静态语义及反例复核，不是模型执行成功率评测；安装结论来自实际隔离 CLI 与 POSIX 投影检查，Windows 运行覆盖仍受平台限制。临时安装状态已清除。正式受管仓库仍在 `8a252783d9c4bddbd7569daf151e7fb150aa7cd1` 且干净；没有提交、推送、创建发布、刷新日常安装或改动工作服务器。

## 9. 后续上游更新流程补充（2026-09-08）

按用户补充要求，将原有“选择性采纳”的原则具体化为[插件 README 中的更新流程](../plugins/mattpocock-skills/README.md#upstream-updates)，scoped AGENTS 和 root README 统一路由到该所有者。完整导入器继续退役，未新增自动覆盖器、补丁叠加器或运行时版本配置；omh update 分发本仓库已完成选编的版本。

新增[上游审查记录](mattpocock-upstream-review.md)，以原始 v1.2.3 提交初始化进度。每轮对比上游增量及本地适配，逐项采纳、适配、跳过或暂缓；完整分类才推进审查进度，暂缓、已选中待应用及验证未通过的条目继续保留。原始来源、审查进度与实际合入结果分别记录，不把“已审查”当成整版已合入。

独立定向语义复核发现并修复了“只比较时建议采纳但未应用的项可能随游标推进而遗漏”的问题，复查通过。19 项相关测试（catalog 7、分发身份 7、插件验证 5）、14 处文档链接与 diff 检查通过。本轮文档变更后按规则重新生成一次 Matt 包身份，当前为 `1.0.0+codex.ac2426f67fdb924a`；Watcher 与 Workflow 身份保持不变。本轮未检查更新的上游发布，未重复实际模型评测或隔离安装，未提交、推送或激活正式环境。
