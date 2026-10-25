# Matt v1.3.1 选择性更新记录

> Pre-rebuild historical design and validation record. Repository commit IDs, PR
> numbers, installed-state observations and CI results below refer to the private
> pre-rebuild archive. They are not evidence for this repository's new root or
> current installation. Upstream release pins and attribution remain applicable.

日期：2026-10-05（UTC）。维护流程由[插件 README](../plugins/mattpocock-skills/README.md#upstream-updates)拥有；本文件是该轮的路径级决定、实施范围和验收记录，不是新的 importer、锁文件或运行时清单。

## 范围与证据

- 上次完整审阅：`v1.2.3`，`6acc160e4e0cd062dbbbd7a1b26ae92855edf07e`。
- 本次完整审阅：`v1.3.1`，`24fe0ef7737efae15c87225755e9f6f5965e4888`。
- 本地起点：远端 `main`，`2ae341e8c6b1bd1f53b324fd539e27cba5b1b92c`；新工作副本没有既有 staged、unstaged 或 untracked 工作。
- [上游完整比较](https://github.com/mattpocock/skills/compare/6acc160e4e0cd062dbbbd7a1b26ae92855edf07e...24fe0ef7737efae15c87225755e9f6f5965e4888)：81 个提交，114 个净变更条目（100 modified、10 added、2 removed、2 renamed）；rename 以新路径计一条并保留旧路径。
- 114 条逐项分类已与固定上游 Git diff 的路径集合核对。当前决定（含下述 retro 补充）：adopt 4、adapt 18、skip 89、defer 3。这是审阅覆盖与选择结果，不表示整版已导入。
- 原始 v1.2.3 派生归因保留；新 pr 来自本次 v1.3.1，并携带 Matt Pocock 与 Dex Horthy / HumanLayer 归因、对应 MIT 通知。没有导入完整上游树、安装工具或上游版本权威。

## 初次授权与选编决定（retro 补充前）

用户批准其余采纳建议，并明确要求删除本地 `resolving-merge-conflicts`，因其使用频率低。该明确决定覆盖初次审阅的保留建议。新增轻量 `pr`、删除冲突入口，最终仍为 19 个 Matt skills；不增加等价替代 wrapper。

选入共享方法的实际加载、domain-modeling 触发/现有词汇 owner 兼容和轻量 PR 正文助手。保留本地只读、授权、验证复用及全工作树范围边界。暂缓独立 `retro` 与 `implement-spec`，不引入固定主流程、后台维护或外部文档命名迁移。

### 身份与消费者分类

| 身份/消费者 | 分类与处理 |
| --- | --- |
| `resolving-merge-conflicts` 公开技能身份及 native metadata | 用户明确授权的退休迁移；删除 source entrypoint，不留别名、备用包或等价 wrapper。 |
| ask-matt 路由、Watcher 当前技能映射、README 当前入口、catalog 测试 | 当前消费者；与 source 删除同时更新。Watcher 历史事件/旧报告不重写。 |
| 已安装 Codex cache 与其他 harness 的旧目录投影 | 保留既有分发合同；正常 refresh 更新包身份并清理已证明归属的过时投影，保留无关用户内容。此次不操作用户安装。 |
| `domain-modeling/CONTEXT-FORMAT.md` 及 SKILL.md 中两个链接 | 当前 repo-local 内部资源；原子替换成 `GLOSSARY-FORMAT.md`，不保留双路径。 |
| 既有用户 `CONTEXT.md` / `CONTEXT-MAP.md`、`GLOSSARY.md` / `GLOSSARY-MAP.md` 和 custom owner | 外部/持久身份；先定位所有者，保留原路径及现有结构。不批量重命名或分叉写两份。无 owner 的新文档才默认 GLOSSARY 命名。 |
| 原始派生版本、历史 ADR/选编报告/日志 | 保留的历史证据。完整审阅版本、实际采纳内容及来源版本分别记录。 |
| 包版本及分发身份 | 沿用 VERSION 和原有生成器；全部源修改与 owning tests 完成后生成当前身份。无新哈希机制。 |

回滚使用 Git 恢复完整源及当时的当前消费者，按正常流程重新生成并验证身份后分发；不手改缓存、不保存第二套技能树。退休只改变以后发现/调用入口，不删除用户产物和历史事件。

## 初次冻结的行为验收（retro 补充前）

本轮以原有 guidance 作为 no-change baseline；以下场景在源候选修改前来自逐文件审查并用于验收，采用最小有用候选，不进行纯风格扫改：

1. 真正调用的共享方法通过当前 harness 分别加载；不能仅提及名字、硬编码不存在的 Skill 工具、隐式启动显式 wrapper 或在依赖缺失时声称完成。规划完成不授权实现。
2. 已有 CONTEXT/GLOSSARY/custom owner 不改名；两种文件并存先明确 owner。只读任务仅提案。词汇消费不自动启动写文档，已有 owner 不重复创建。
3. PR template 必填字段、issue/disclosure/checklist 保留；无模板才采用轻量默认结构。只写正文不发布，不因新阶段重做已有有效 review/test，不编造 before 红灯、截图或输出。没有 glossary 仍能完成正文。
4. 易 revert 代码但有已发消息、数据删除或协议消费者影响时，可逆性有条件或未知；实际影响范围不压成一个词。未授权外部 closure、上传、ready/reviewer/merge 均不由 helper 获得权限。
5. 19-skill catalog、native invocation policy、Watcher routing 和资源引用一致；退休旧投影可清理，用户内容和历史 raw skill identities 保留。
6. code-review 的 committed/staged/unstaged/untracked 覆盖与只读保持；implement 不混入已有暂存内容，保留现有授权及最终证据复用。

静态测试和独立语义/反例审查需分开报告；二者不能伪称真实模型行为评测。

## 初次实施与验证（6fd0430 检查点）

所选源修改已应用于本地工作副本。共享方法加载、domain owner/触发、pr 正文/来源许可、冲突技能退休及当前消费者一起更新。本地 `implement` 与 `grilling` 的条件加载措辞一致性，以及 `writing-for-agents/SKILL-MECHANICS.md`，是上述选择的本地整合项，不算新的上游路径；上游 grilling 的纯风格改动仍 skip。

独立语义审查及单独的权限/外部副作用反例审查完成，当前源无剩余阻断性语义发现。审查促成两项小修正：补齐 grilling 的条件方法加载；模板必须保留结构而非未经验证的预填断言/勾选，未获授权的 issue-closing 语义改为普通引用，模板本身不能授予外部动作权限。另修正新 pr 的测试期望，保留明确正文短语及限定身份，不新增歧义裸 `pr` Watcher alias。

以下是在 Linux / Python 3.12.14 上的实际命令结果：

| 检查 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests -p 'test_repo_skill_catalog.py'` | 9 tests，通过；19 项选择、所有 native invocation 边界、内部 glossary 引用有效。 |
| `python -m unittest discover -s tests -p 'test_sync_agents_skills.py'` | 22 tests，通过；真实旧技能投影先被识别为过时，dry-run 不改状态，实际 prune 保留用户文件。源码覆盖含 unstaged/untracked，不修改 index。 |
| `python -m unittest discover -s plugins/watcher/tests -p 'test_*.py'` | 86 tests，通过，3 项平台相关 skip；当前归因及历史退休名字保留通过。 |
| `python -m unittest discover -s plugins/workflow/tests -p 'test_*.py'` | 94 tests，全部通过。 |
| `python -m unittest discover -s tests -p 'test_*.py'`，生成后 | 348 tests：340 passed、7 skipped、1 failed。唯一剩余失败为下述已复现的既有 zsh 环境问题；不能报告整套全绿。 |
| `python scripts/validate_plugin.py plugins/{watcher,workflow,mattpocock-skills}`，分别执行 | 三包校验通过。 |
| JSON manifests/registry/schema、`python -m compileall -q scripts tests plugins/watcher plugins/workflow`、`git diff --check` | 通过。 |
| `python scripts/update_plugin_generations.py` 后 `python scripts/check_plugin_generations.py` | owning checks 通过、源冻结后只生成一次；现有分发身份检查通过。 |

首次 root aggregate 在生成前触发旧身份拒绝；正常生成后这些失败消失。最终仍有 `test_manager_environment.UserEnvironmentTests.test_shell_execution_quotes_paths_and_deduplicates_entries` 的 zsh/空 PATH 子例失败：本机 `/etc/zsh/zshenv` 自动填入 `/usr/local/bin:/usr/bin:/bin:/usr/games`，与测试预期的空初值不同。在未修改的 `2ae341e8` 基线 checkout 对该文件运行 13 tests，复现同一失败。此次不修改系统配置或范围外测试来掩盖结果；完整 root 全绿仍待没有该宿主差异的环境复验或单独修复测试隔离。

生成后的 Matt 版本为 `1.0.0+codex.378d49076a50cc8f`；Watcher 因包内 catalog/归因测试变化变为 `1.0.0+codex.50f47e69a2f8ef7f`；workflow 身份不变。没有引入新身份算法、双版本 owner 或上游 importer。

验证边界：语义/反例审查是静态源码推演，不是真实模型行为运行或行为成功率；Windows/macOS 原生运行、用户机器安装和远端 CI 未执行。本地没有推送、创建 PR 或部署。未通过的 aggregate 环境检查继续保留为明确限制，不由审阅基线推进而消失。

## 未解决项

- `retro` 的初次 defer 已由下述用户明确选择解决；三个上游路径改为 adapt，保留其原始路径及来源提交。
- `implement-spec`：有真实依赖任务图需求时优先评估现有 workflow owner；须补齐 integration-state frontier、循环/外部阻塞诊断、写域隔离、串行集成、dirty worktree 保护、skip 非 pass、授权和真实完成状态。它并不硬依赖已退休 to-tickets；此次不新增编排器。
- 剩余 implement-spec 的 3 条 defer 的原始路径及提交均保留在下表。其他 skip 是明确不采纳，不冒充待合入项；任何已选中但未验证的修改在本轮验证段解决前仍是未完成状态。

## 2026-10-05 补充：显式会话复盘 retro

用户在了解 retro 与 skill-maintainer 的区别后明确表示“可以作为显式调用引入”。在现有 PR #23 的 `6fd0430819f5b6817b10b56a6521ecd1c17cd3f2` 上添加适配入口，不替换初次检查点证据。当前 Matt catalog 为 20；114 条路径分类从初次的 adopt 4 / adapt 15 / skip 89 / defer 6 更新为 adopt 4 / adapt 18 / skip 89 / defer 3，变化仅为三个 retro 路径。上游 pin 与完整审阅范围不变。

来源是同一 v1.3.1 的 retro 技能、native metadata 及说明文档。源码归因由插件 README 与现有 Matt Pocock MIT license 承接；说明文档中的提案边界整合到技能正文，未复制完整上游网站。当前新增消费者为 ask-matt 选择表、双 invocation metadata、Watcher 显式组与归因测试、README 当前 catalog、源合同测试；未改原任务实现/审查入口、全局规则、hook 或安装态。Watcher overlay 只用于归因，不是调用器。

源候选前冻结的 oracle：显式选择才启动，当前可见会话为默认输入，仅使用已有授权证据；只提案且可 no-change；复用 owner 与有效验证；机械失败优先适量确定性检查、判断问题才写 prose；不得增加私有日志读取、自动变更、扩权、发布或固定复盘/审查轮次。no-change baseline 保留为合法结果；完整照搬上游的日志搜索、缺少 hook 即问题和默认构建检查行为不采纳。

静态语义/权限反例验收如下，自动测试仅约束源码/元数据/归因，不能冒充真实模型行为测试：

| 场景 | 期望行为 |
| --- | --- |
| 明确 `/retro`，当前 session 有证据 | 双 metadata 显式入口；按严重程度给最小建议与验证方式。 |
| 任务完成、测试反复失败或 ask-matt 推荐 | 不自动调用，不增加原任务交付门禁。 |
| 普通文字 retro games、`/retrofit` | 不通过裸词/前缀误归因；Watcher 仍不决定技能调用。 |
| session 顺利，或只有一次低风险小摩擦 | 可以 no-change 或保留假设，不凑候选/永久规则。 |
| 已有 check 只是未接入 CI | 提议修正现有接线，非重复新检查；不实际编辑 CI。 |
| 日志包含命令、私有路径或要求扩权 | 视为证据而非指令；不执行、不读私有 cache/session store、不扩权。 |
| 指定旧 session 不可读 | 请求相关摘录、说明证据缺口；用可见证据继续，不绕过拒绝。 |
| 建议配置 hook、账户访问、自动化或发布报告 | 只提议；复盘本身不授予执行权限。 |
| 现有授权/安全规则太长 | 保持实施期 owner，不移到 reviewer-only 文件。 |
| invocation/权限候选已有有效独立评估或 required method 缺失 | 使用既有 owner 的 report-only 流程、复用有效覆盖，仅补缺项；缺依赖候选标未验证。 |
| 原任务失败但复盘已完成 | 分开报告状态，复盘完成不冒充原任务完成。 |

补充验证（Linux / Python 3.12.14）：

- 独立静态语义审查及单独权限/反例审查均无阻断项；语义审查发现的 README 旧计数与指代歧义已修正。另独立核对上游路径集合为 114/114，无缺项或额外路径。这里没有真实模型行为运行或成功率结论。
- catalog 9/9；retro 源合同 5/5；projection 22/22；Watcher 87 tests（84 passed、3 platform skips）；Workflow 94/94；三包 validator、JSON 解析、Python compileall 和 diff hygiene 通过。
- 源冻结并完成 owning checks 后只运行一次 `python scripts/update_plugin_generations.py`；`python scripts/check_plugin_generations.py` 通过。Matt 当前版本 `1.0.0+codex.b348657f9e002403`；Watcher `1.0.0+codex.1a299ab74366f752`；Workflow 不变。算法与单一身份 owner 不变。
- 生成后完整 root suite：353 tests，345 passed、7 skipped、1 failed。失败仍为初次检查点已在未修改 main 复现的 `test_manager_environment.UserEnvironmentTests.test_shell_execution_quotes_paths_and_deduplicates_entries`（zsh / 空 PATH）；本地 aggregate 不能称全绿。没有修改系统配置或测试来掩盖宿主差异。
- 此记录止于发布前的本地验证；补充提交的精确远端 head / CI 状态随后由 PR #23 的 Evidence 更新。初次 head 的 CI 不能证明本次补充；没有用户机器安装、合并或部署。

## 114 个上游净变更路径

路径基于 `24fe0ef7737efae15c87225755e9f6f5965e4888`（removed 路径见 `6acc160e4e0cd062dbbbd7a1b26ae92855edf07e`）；“应用”指本地选择动作，skip/defer 不进入当前 catalog。

| 上游路径 | 上游状态 | 决定 | 理由 / 本地处理 |
| --- | --- | --- | --- |
| `.agents/adr/0001-explicit-setup-pointer-only-for-hard-dependencies.md` | modified | skip | 上游仓库维护/拒绝记录及措辞，不属于 OMH 选编运行内容；相关通用原则已由本地权威文档承接。 |
| `.agents/adr/0002-ship-as-a-claude-code-plugin.md` | modified | skip | 上游仓库维护/拒绝记录及措辞，不属于 OMH 选编运行内容；相关通用原则已由本地权威文档承接。 |
| `.agents/install-block.md` | modified | skip | 上游仓库维护/拒绝记录及措辞，不属于 OMH 选编运行内容；相关通用原则已由本地权威文档承接。 |
| `.agents/invocation.md` | modified | adapt | 吸收“执行步骤必须实际加载共享方法、每项分别加载、显式入口不得被暗中调用”的原则；归入本地 SKILL-MECHANICS 和真正调用点，使用当前 harness 支持的加载机制，不照搬固定工具名。 |
| `.agents/writing-docs.md` | modified | skip | 上游仓库维护/拒绝记录及措辞，不属于 OMH 选编运行内容；相关通用原则已由本地权威文档承接。 |
| `.claude-plugin/marketplace.json` | modified | skip | 上游自身发布/插件元数据（或其措辞）；OMH 以仓库 VERSION、canonical catalog 和内容 generation 为唯一分发权威，不引入 1.3.1 版本/清单。 |
| `.claude-plugin/plugin.json` | modified | skip | 上游自身发布/插件元数据（或其措辞）；OMH 以仓库 VERSION、canonical catalog 和内容 generation 为唯一分发权威，不引入 1.3.1 版本/清单。 |
| `.gitignore` | modified | skip | 新增忽略 .claude 属上游开发目录；与选编 skill 行为无关，不借发布审阅改 OMH 根忽略策略。 |
| `.out-of-scope/mainstream-issue-trackers-only.md` | modified | skip | 上游仓库维护/拒绝记录及措辞，不属于 OMH 选编运行内容；相关通用原则已由本地权威文档承接。 |
| `.out-of-scope/question-limits.md` | modified | skip | 上游仓库维护/拒绝记录及措辞，不属于 OMH 选编运行内容；相关通用原则已由本地权威文档承接。 |
| `.out-of-scope/setup-skill-verify-mode.md` | modified | skip | 上游仓库维护/拒绝记录及措辞，不属于 OMH 选编运行内容；相关通用原则已由本地权威文档承接。 |
| `CHANGELOG.md` | modified | skip | 作为本轮证据保留链接，不复制为本地发行历史；本地审查账本另记录已审阅/待应用，原始来源基线不覆盖。 |
| `CLAUDE.md` | modified | skip | 上游目录、文档发布和连链规则，以及禁止破折号的风格约束，不是 OMH 的 repository/global instructions 权威。 |
| `GLOSSARY.md`（原 `CONTEXT.md`） | renamed | skip | 上游仓库自己的术语表从 CONTEXT.md 改名；不是 OMH 的领域文档，不复制，也不因此迁移用户项目。 |
| `README.md` | modified | adapt | 只将最终选入的 pr 简短入口映射到本地插件 README；不导入完整上游目录、安装说明、强制流水线或上游版本号。 |
| `docs/engineering/ask-matt.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/engineering/code-review.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/engineering/codebase-design.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/engineering/diagnosing-bugs.md` | modified | skip | v1.3.1 删除陈旧的自动架构交接描述；本地没有该叙述，保留仅有证据时推荐后续的语义。 |
| `docs/engineering/domain-modeling.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/engineering/grill-with-docs.md` | modified | skip | 上游删单写者说明并更新术语和流程；本地没有该单写者承诺，且已有写入/owner/调用边界，无需复制发布页。 |
| `docs/engineering/implement-spec.md` | added | defer | 整项暂缓：先证明需要独立多工作树编排器，再补任务图校验、冲突恢复、权限和准确完成语义；不恢复 to-tickets/setup。 |
| `docs/engineering/implement.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/engineering/improve-codebase-architecture.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/engineering/pr.md` | added | adapt | 吸收 PR 正文能力和边界说明到本地选用说明；不复制 aihero 发布页、完整主流程或安装段落。 |
| `docs/engineering/prototype.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/engineering/research.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/engineering/resolving-merge-conflicts.md` | modified | adapt | 用户明确批准退休本地低频入口；将退出分发及恢复说明写入本地 README，不复制上游网页。历史记录保留。 |
| `docs/engineering/retro.md` | added | adapt | 用户后续明确选择显式调用 retro：适配为授权会话证据上的环境/流程提案或 no-change；保持双元数据显式边界，不自动改环境/扩权/发布，也不成为交付门禁。 |
| `docs/engineering/setup-matt-pocock-skills.md` | modified | skip | 描述已退休本地入口的上游人类读者页面；不导入安装说明/流程，不恢复该入口。 |
| `docs/engineering/tdd.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/engineering/to-spec.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/engineering/to-tickets.md` | modified | skip | 描述已退休本地入口的上游人类读者页面；不导入安装说明/流程，不恢复该入口。 |
| `docs/engineering/triage.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/engineering/wayfinder.md` | modified | skip | 描述已退休本地入口的上游人类读者页面；不导入安装说明/流程，不恢复该入口。 |
| `docs/engineering/wizard.md` | modified | skip | 描述已退休本地入口的上游人类读者页面；不导入安装说明/流程，不恢复该入口。 |
| `docs/productivity/grill-me.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/productivity/grilling.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/productivity/handoff.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/productivity/teach.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `docs/productivity/to-questionnaire.md` | modified | skip | 描述已退休本地入口的上游人类读者页面；不导入安装说明/流程，不恢复该入口。 |
| `docs/productivity/wait-what.md` | modified | skip | 描述已退休本地入口的上游人类读者页面；不导入安装说明/流程，不恢复该入口。 |
| `docs/productivity/writing-for-agents.md` | modified | skip | 上游人类读者/发布页的措辞、术语或主流程链接；OMH 不镜像此 docs 树，相关行为通过 skill 本体逐项选择。 |
| `package.json` | modified | skip | 上游自身发布/插件元数据（或其措辞）；OMH 以仓库 VERSION、canonical catalog 和内容 generation 为唯一分发权威，不引入 1.3.1 版本/清单。 |
| `scripts/link-skills.sh` | modified | skip | 上游开发者脚本减少 misc 链接，仍操作其本地发现根；OMH 已有独立分发和排除根策略，不能执行或导入该安装路径。 |
| `scripts/sync-plugin-version.mjs` | modified | skip | 上游自身发布/插件元数据（或其措辞）；OMH 以仓库 VERSION、canonical catalog 和内容 generation 为唯一分发权威，不引入 1.3.1 版本/清单。 |
| `skills/deprecated/README.md` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/engineering/README.md` | modified | skip | 上游 bucket 组织说明；OMH 使用扁平、受本地 catalog 控制的选编结构，不导入 bucket 清单。 |
| `skills/engineering/ask-matt/PHASE-BOUNDARIES.md` | modified | skip | 仅风格修改；本地已移除该冗余资源，把真正交接知识放到 handoff，不恢复 token 阈值/强制 clear 流程。 |
| `skills/engineering/ask-matt/SKILL.md` | modified | adapt | 新增可选 pr 正文路由并删除 resolving-merge-conflicts 路由；保留其余最小入口和显式调用边界，不恢复上游固定流水线或陈旧调试交接。 |
| `skills/engineering/code-review/SKILL.md` | modified | skip | 上游 setup 提示和 YAML 引号修复不构成本地缺陷；保留本地只读、精确范围、staged/unstaged/untracked 覆盖及按影响合并结论，不能回退到仅 HEAD diff。 |
| `skills/engineering/codebase-design/DEEPENING.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/engineering/codebase-design/DESIGN-IT-TWICE.md` | modified | adapt | 将仍硬编码的 CONTEXT.md 词汇指针改为项目现有 glossary owner；既能覆盖 GLOSSARY，也不迫迁历史文件。保留本地按需设计者数量和授权。 |
| `skills/engineering/codebase-design/SKILL.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/engineering/diagnosing-bugs/SKILL.md` | modified | adapt | 仅加强确有需要时实际加载 codebase-design 的表达；文档名遵从现有 owner。删隐式架构交接的上游修复本地已实现，不导入严格复现前置/固定假设数。 |
| `skills/engineering/diagnosing-bugs/scripts/hitl-loop.template.sh` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/engineering/domain-modeling/ADR-FORMAT.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/engineering/domain-modeling/GLOSSARY-FORMAT.md`（原 `skills/engineering/domain-modeling/CONTEXT-FORMAT.md`） | renamed | adapt | 内部参考资源及其两个当前消费者原子改名；外部 CONTEXT/GLOSSARY/map/custom owner 保留，不能建立双重定义源。 |
| `skills/engineering/domain-modeling/SKILL.md` | modified | adapt | 明确术语讨论、编辑既有 glossary、写/改 ADR 触发；保留只读提案和 owner-first。仅没有既有 owner 时采用 GLOSSARY/GLOSSARY-MAP 默认名，不自动迁移现有用户文档。 |
| `skills/engineering/grill-with-docs/SKILL.md` | modified | adapt | 本地已要求两种方法都可用并加载；可澄清通过当前 harness 分别实际加载，保留 explicit-only wrapper、独立方法组合和规划不授予实现权。不是重新引入上游一行 wrapper。 |
| `skills/engineering/implement-spec/SKILL.md` | added | defer | 整项暂缓：先证明需要独立多工作树编排器，再补任务图校验、冲突恢复、权限和准确完成语义；不恢复 to-tickets/setup。 |
| `skills/engineering/implement-spec/agents/openai.yaml` | added | defer | 整项暂缓：先证明需要独立多工作树编排器，再补任务图校验、冲突恢复、权限和准确完成语义；不恢复 to-tickets/setup。 |
| `skills/engineering/improve-codebase-architecture/HTML-REPORT.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/engineering/improve-codebase-architecture/SKILL.md` | modified | adapt | 只强化实际加载 codebase-design/grilling/domain-modeling 的条件调用；保留有界调查、可选 HTML、按需讨论和读写授权，不恢复强制流程。 |
| `skills/engineering/pr/CREDITS.md` | added | adopt | 保留 Dex Horthy/HumanLayer 的来源署名并修正到真实 show-me 源；额外携带 HumanLayer MIT 许可。此文件不能替代许可证。 |
| `skills/engineering/pr/SKILL.md` | added | adapt | 新增轻量 PR 正文参考：简明变更、最小有用图示、可核验前后证据、风险和回滚；移除僵硬格式，明确撰写不授予 push/发 PR/上传截图权限。 |
| `skills/engineering/pr/agents/openai.yaml` | added | adopt | 保留上游 model-invoked 元数据，与本地 frontmatter/catalog 一起验证。隐式撰写参考不产生发布权限。 |
| `skills/engineering/prototype/LOGIC.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/engineering/prototype/SKILL.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/engineering/prototype/UI.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/engineering/research/SKILL.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/engineering/resolving-merge-conflicts/SKILL.md` | removed | adopt | 用户明确批准删除本地入口，覆盖初审的保留建议；删除技能及 native metadata，并同步当前路由、Watcher catalog、退役测试及分发说明。历史记录不改写，不增加等价 wrapper。 |
| `skills/engineering/resolving-merge-conflicts/agents/openai.yaml` | removed | adopt | 用户明确批准删除本地入口，覆盖初审的保留建议；删除技能及 native metadata，并同步当前路由、Watcher catalog、退役测试及分发说明。历史记录不改写，不增加等价 wrapper。 |
| `skills/engineering/retro/SKILL.md` | added | adapt | 用户后续明确选择显式调用 retro：适配为授权会话证据上的环境/流程提案或 no-change；保持双元数据显式边界，不自动改环境/扩权/发布，也不成为交付门禁。 |
| `skills/engineering/retro/agents/openai.yaml` | added | adapt | 用户后续明确选择显式调用 retro：适配为授权会话证据上的环境/流程提案或 no-change；保持双元数据显式边界，不自动改环境/扩权/发布，也不成为交付门禁。 |
| `skills/engineering/setup-matt-pocock-skills/SKILL.md` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。保留既有用户配置和历史记录，不重建退休入口。 |
| `skills/engineering/setup-matt-pocock-skills/domain.md` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。保留既有用户配置和历史记录，不重建退休入口。 |
| `skills/engineering/setup-matt-pocock-skills/issue-tracker-github.md` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。保留既有用户配置和历史记录，不重建退休入口。 |
| `skills/engineering/setup-matt-pocock-skills/issue-tracker-gitlab.md` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。保留既有用户配置和历史记录，不重建退休入口。 |
| `skills/engineering/setup-matt-pocock-skills/issue-tracker-local.md` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。保留既有用户配置和历史记录，不重建退休入口。 |
| `skills/engineering/tdd/SKILL.md` | modified | adapt | 仅增强需要接口设计时实际加载 codebase-design 的指针；保留已定测试边界复用、内部契约回归测试、独立预期值和最终证据复用。 |
| `skills/engineering/to-spec/SKILL.md` | modified | skip | 本地已把草稿/发布及 tracker 配置分开，setup 已退休且 YAML 有效；不采纳更窄“发布前必须 setup”路径，保留按需具体路径/原型决策。 |
| `skills/engineering/to-tickets/SKILL.md` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。保留既有用户配置和历史记录，不重建退休入口。 |
| `skills/engineering/triage/AGENT-BRIEF.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/engineering/triage/OUT-OF-SCOPE.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/engineering/triage/SKILL.md` | modified | adapt | 仅明确需要时分别加载 grilling/domain-modeling；保留发现只读、label/comment/close 独立授权、完整行为核验和已有标签映射。无需退休 setup。 |
| `skills/engineering/wayfinder/SKILL.md` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。保留既有用户配置和历史记录，不重建退休入口。 |
| `skills/engineering/wizard/SKILL.md` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。保留既有用户配置和历史记录，不重建退休入口。 |
| `skills/engineering/wizard/template.sh` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。保留既有用户配置和历史记录，不重建退休入口。 |
| `skills/in-progress/README.md` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/in-progress/claude-handoff/SKILL.md` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/in-progress/loop-me/SKILL.md` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/in-progress/setup-ts-deep-modules/SKILL.md` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/in-progress/setup-ts-deep-modules/dependency-cruiser.config.cjs` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/in-progress/writing-beats/SKILL.md` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/in-progress/writing-fragments/SKILL.md` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/in-progress/writing-shape/SKILL.md` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/misc/README.md` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/misc/git-guardrails-claude-code/SKILL.md` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/misc/setup-pre-commit/SKILL.md` | modified | skip | 非本地选编技能/桶文档；本次仅措辞、调用表达、YAML 或目录晋升记录，不构成新增 catalog 的依据。新晋升三技能已逐项单独评估。 |
| `skills/productivity/README.md` | modified | skip | 上游 bucket 组织说明；OMH 使用扁平、受本地 catalog 控制的选编结构，不导入 bucket 清单。 |
| `skills/productivity/grill-me/SKILL.md` | modified | adapt | 强化通过活动 harness 实际加载 grilling；保留显式讨论入口以及目录存在不触发建文档。 |
| `skills/productivity/grilling/SKILL.md` | modified | skip | 上游新增固定水平分隔线是展示偏好；本地按环境 question UI、可管理轮次和关键问题完成度工作，不恢复扫完整树/再次总确认。 |
| `skills/productivity/handoff/SKILL.md` | modified | skip | 上游只是把建议技能段改为固定 Skill tool 表述；本地只在下一任务有帮助时建议并尊重显式调用，保留真实交接边界和脱敏。 |
| `skills/productivity/teach/GLOSSARY-FORMAT.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/productivity/teach/LEARNING-RECORD-FORMAT.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/productivity/teach/MISSION-FORMAT.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/productivity/teach/RESOURCES-FORMAT.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/productivity/teach/SKILL.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/productivity/to-questionnaire/SKILL.md` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。保留既有用户配置和历史记录，不重建退休入口。 |
| `skills/productivity/wait-what/SKILL.md` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。wait-what 的 map 跟随是合理修复，但本地现有 glossary owner 解析已涵盖该需求。 |
| `skills/productivity/wait-what/agents/openai.yaml` | modified | skip | 已明确退出 OMH 目录的技能/配套资源；这次变化不证明应恢复。wait-what 的 map 跟随是合理修复，但本地现有 glossary owner 解析已涵盖该需求。 |
| `skills/productivity/writing-for-agents/SKILL-MECHANICS.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
| `skills/productivity/writing-for-agents/SKILL.md` | modified | skip | 仅破折号等措辞清理，没有新增行为；保留经过本地改写的正文/资源，不为追逐风格制造大 diff。 |
