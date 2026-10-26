# Long Running Goal Template

本文件是 continuation-ready long-running goal 文档模板。使用时复制到项目的 active goal directory，例如 `<goal-dir>/<goal_slug>_long_running_goal_plan.md`，再替换所有 `<...>` 占位符；不要直接在本模板中记录具体任务进度。

整体状态：`Draft`

## 使用说明

复制到现有 active goal directory，替换占位符，按实际工作增删阶段并同步状态表。读取并完成 `components/planning-preflight.md` 的必经组合流程及直到 Close 的授权覆盖检查；复用答案不免除流程。记录完成、有效旧 preflight 复用或用户明确跳过的来源。时间估算可选，清理默认 Disabled。执行进度只在目标文件中维护。

## Goal 摘要

目标名称：`<Goal Name>`

目标描述：

1. `<用 1-3 条描述本 goal 要完成什么。>`
2. `<说明最终用户或系统行为的目标态。>`
3. `<说明不属于本 goal 的边界。>`

目标 owner：`<owner / team / agent>`

目标路径：`<goal-dir>/<goal_slug>_long_running_goal_plan.md`

Planning root：`<planning-root>`

Goal directory：`<goal-dir>`

Continuation contract：`<同一或另一个 agent 不依赖聊天历史即可从本文件继续执行的关键约束。>`

Planning preflight marker：`<preflight:<goal_slug>:<yyyymmdd>-<short-id> / preflight:<goal_slug>:skip:<yyyymmdd>-<short-id>>`

Planning preflight status：`<Done / Skipped by explicit user instruction>`

Preflight source：`<grilling + domain-modeling / grill-with-docs / existing decisions / user skip>`

Preflight evidence：`<Completed: 来源及实际检查结果 / Reused: 已完成 preflight id、来源及当前覆盖结果 / User skip: 用户明确跳过的来源；使用可定位 Markdown 链接或带日期的 user request/message/turn 引用>`

Resolved decisions：`<summary or doc paths>`

Open decisions：`<none or explicit runtime hard stops>`

Docs written：`<写入或复用的文档路径 / Not applicable: 原因>`

## Preflight Time Assessment

可选：仅在有助于计划或排期时记录剩余耗时区间及依据；未知时说明原因，否则删除本节。估算不影响 Ready。

## Task Temporary Cache / Housekeeping

Close housekeeping policy：`Disabled`

启用 Enabled 时才补充 Housekeeping decision source，记录用户明确确认及上下文。

Task temporary cache root strategy：`<Enabled/Disabled: resolve the host platform/runtime standard temporary root, allocate a goal-owned namespace beneath it, and record the exact owner root before first use; Not applicable: no task temporary cache root will be created.>`

Recorded task temporary cache roots：`<one fully resolved owner-labeled absolute path entry per root / Resolve and record before first use / None created / Not applicable>`

Housekeeping boundary：`<Enabled uses watcher:housekeeping only for inventoried task-owned disposable candidates; Disabled preserves and reports; Not applicable creates no root; durable evidence lives outside the roots.>`

## 当前基线

M0 设计冻结时按实际情况填写，可增删条目；不为凑数量制造事实：

- `<当前代码 / 文档 / runtime、已交付或验证的能力、保留的 compatibility / legacy surface、失败断点与风险、范围外运行产物或依赖。>`

已读取的当前事实源：

- `<实际使用的 instructions、README、current guide/status、architecture/contract/validation/runbook、TODO/goal/archive/issue/PR；按需列出可定位来源。>`

## Loop Blueprint / Harness 边界

手动分阶段 goal 只保留执行模式及 `Not applicable: manual staged execution` 原因，删除下方未使用的九字段示例。包含自动触发、重复循环、sub-agent 编排、worktree 并行、connector 读写或外部系统副作用时，不能用 manual 分类省略边界：必须在执行前填写以下九字段；单个不适用字段说明原因。

执行模式：`<Manual staged execution / Loop-shaped execution / Automated loop>`

1. Trigger / 心跳：
   - `<什么事件启动或恢复循环；例如用户命令、schedule、hook、CI、issue、goal-tool。>`
2. Inputs / 输入源：
   - `<循环读取哪些事实源；例如 TODO index、issue、CI log、report、runtime state、checkpoint evidence。>`
3. Triage and orchestration / 分拣与编排：
   - `<finding 如何变成任务，优先级如何确定，哪些角色或 agent 负责探索、实现、验收。>`
4. Worktree and isolation / 隔离策略：
   - `<是否使用当前 checkout、独立 worktree、独立 branch、串行锁定文件，或其他防撞策略。>`
5. Skills and context / 必读上下文：
   - `<每个角色必须读取的 skill、runbook、project doc、spec 或历史决策。>`
6. Connector read/write boundaries / 外部系统读写边界：
   - `<可读/可写的 connector、API、ticket、PR、CI、Slack 等；哪些写入已预授权；哪些具体后续动作在 Deferred approval gates 中等待批准；边界未明确时保持 Draft。>`
7. Independent verification / 独立验收：
   - `<由哪个 sub-agent、脚本、测试、reviewer 或 gate 检查 producer 的输出；不得只信自评。>`
8. Runtime hard stops / 运行时硬停止：
   - `<授权或语义决策边界立即停止受影响动作；技术失败按 skill 的 adaptive recovery 执行，原生 Goal 明确报告的前两次失败依据证据改变策略，第三次关联原生 Codex Goal hard stop，普通命令失败不可直接计为原生失败；不得重置原生计数或绕过访问拒绝。>`
9. Durable learning / 经验沉淀：
   - `<哪些结果要写回 skill、TODO、report、validation log、runbook、automation memory 或 current doc。>`

## Pre-Approval / YOLO 边界

Ready 前按阶段至 Close 盘点实际动作、目标、范围、条件及授权来源，复用既有授权，在 grilling 中解决未覆盖部分。仅用户明确保留或规则要求最终审阅的决定进入 Deferred approval gates；边界未明确时保持 `Draft`。

Authorization evidence：`<可定位 Markdown 链接或带日期的 user request/message/turn 引用，逐项说明已批准动作、目标、范围、条件及适用阶段；清理引用独立 Housekeeping policy/source，不在此处扩大权限>`

1. Pre-approved YOLO local operations / 预授权本地操作：
   - `<本 goal 范围内默认允许的非破坏性本地动作，例如 code/docs/source skill edits、rebuild、refresh、reinstall、dependency restore、tests、lint、formatting、link checks、plugin/cache refresh、project-owned generated-artifact cleanup；不要在此处推导任务临时缓存清理授权。>`
2. Pre-approved external reads/writes / 预授权外部读写：
   - `<已允许读取或写入的 connector、API、issue、PR、CI、automation、hook、message surface；无外部写入时写 Not applicable。>`
3. Runtime hard stops / 运行时硬停止：
   - `<授权或语义决策边界立即停止受影响动作；技术失败按 skill 的 adaptive recovery 执行，原生 Goal 明确报告的前两次失败依据证据改变策略，第三次关联原生 Codex Goal hard stop，普通命令失败不可直接计为原生失败；不得重置原生计数或绕过访问拒绝。>`
4. Non-stops / 不应中断的事项：
   - `<普通阶段边界、checkpoint、耗时区间超出后的 rebaseline、可记录风险、rebuild、refresh、reinstall、失败但有明确本地下一步的验证、策略合同更新、docs sync 等。>`

## Deferred approval gates

没有延后批准的动作时删除本节。按 `components/planning-preflight.md` 记录具体动作、目标、范围、条件及有来源的延期依据，将准备工作放在此前阶段。Pending 阻止所属阶段开工、In Progress/Done 和最终关闭；先核实既有来源，已覆盖则直接记录 Approved，禁止仅因进入新阶段重问。保留真实最终审批 gate。

| Milestone | Action | Status | Approval evidence | Deferral basis |
| --- | --- | --- | --- | --- |
| <已有的 M 编号或 Close> | <具体动作、目标、范围及条件> | Pending | None | <User decision: 来源及保留的决定 / Required review: 规则来源及待审阅材料> |

## Goal 执行合同

1. 依据 `workflow:long-running-goal` 的执行与关闭流程推进，并保留本文件冻结的权限、验收和硬停止边界。Ready 之后仍需用户请求执行。
2. 状态只维护整体状态和阶段状态表。阶段按顺序开始；完成记录必须包含行为、命令结果、文档、回滚和剩余风险。运行必需验证，通过 review gate 后应用 `components/checkpoint.md`，再确认 `components/milestone-scope-gate.md` 并推进。
3. 只在已授权范围内更新当前 goal；修改 reusable skill/template 需要相应源码授权。不得静默放宽验收或掩盖失败。
   - 阶段入口和上下文恢复后比对动作、目标、范围、条件及最新授权变更；已覆盖权限继续使用，只询问未覆盖增量或已记录最终审批。
4. Close 使用本文件冻结的 housekeeping policy、当前文档同步与归档规则；缺少清理授权时保留缓存。

Checkpoint evidence format：

```text placeholder-example
Checkpoint component: <Pending / Done>
Checkpoint type: <git commit / current HEAD / artifact revision / not applicable>
Revision: <commit hash / HEAD hash / artifact path / issue or task revision / n/a>
Changed files: <milestone-scoped paths or none>
Validation recorded: <commands and pass/fail result>
Out-of-scope dirty changes: <none or excluded paths>
```

## 设计原则

- `<按需列出领域 ownership/模块、API/UI/runtime、compatibility/legacy、failure handling/fail-fast、测试与验证边界；不适用项省略。>`

## 目标结构

### `<Target Area>`

- `<本区域的目标行为、必须保留的兼容边界、必须移除的旧行为和 Future 边界。>`

按实际目标区域复制小节，不预设区域或条目数量。

## 非目标 / Future 边界

- `<明确不处理的事项；按需扩展。>`

## 阶段计划

保留 M0 基线审查，按实际需要复制 M1 并顺序编号；状态表须与正文一一对应。每阶段在执行后补证据，不预填成功。

### M0 - <基线 / contract review>

范围：<冻结本阶段范围、明确不做的事项。>

Review gate：<可观察的验收条件和必需 validation 命令。>

执行证据：<实际改动、行为、命令结果、文档同步、rollback、剩余风险；触及 Loop 时记录 harness evidence。>

Checkpoint evidence：<按上述格式记录 M0 证据。>

### M1 - <实施结果>

范围：<本阶段结果、必要影响及非目标。>

Review gate：<可观察的验收条件和必需 validation 命令。>

执行证据：<实际改动、行为、命令结果、文档同步、rollback、剩余风险；触及 Loop 时记录 harness evidence。>

Checkpoint evidence：<按上述格式记录 M1 证据。>

## 阶段状态表

| 阶段 | 状态 | Review | Checkpoint |
|---|---|---|---|
| M0 `<阶段名称>` | Not Started | Pending | Pending |
| M1 `<阶段名称>` | Not Started | Pending | Pending |
| Close | Not Started | Pending | Pending |

## Close Gate

所有 M 阶段完成后，若 Close 有延后批准节点，先通过该节点；随后将 Close 行和整体状态设为 `In Progress` 并补齐以下证据。只有本 gate 全部通过后，才将 Close 行设为 `Done / Passed / Done`、整体状态设为 `Closed`。

Close 前必须满足：

1. 所有阶段均为 `Done`。
2. 所有 Review gate 均为 `Passed`。
3. 所有 checkpoint evidence 均已完成并记录。
4. active current docs、validation log、runtime/test checklist 或相关索引已同步。
5. 所有必须执行的测试命令均记录实际结果。
6. `git diff --check -- <changed-paths>` 通过。
7. Markdown 链接检查按需通过。
8. 若存在 Loop Blueprint，所有触及 harness 的阶段都已记录对应证据。
9. 已按显式 task temporary cache / housekeeping policy 处理：无 root 时明确记录“没有创建 task temporary cache roots”；concrete roots 记录每个 exact root 和处置动作；仅 Enabled 要求移除 / 保留 / 失败 / residual size，Disabled 的容量记录可省略或写 unknown 并说明原因；durable evidence 位于缓存根目录之外。
10. 未解决风险已记录，并明确是否进入 Future。
11. 已完整应用 `components/checkpoint.md` 并记录 close checkpoint evidence；当选用 git commit 时使用 `<goal_slug> close: <summary>` 或本项目约定格式。

Close 执行证据：

1. 代码证据：
   - `<Close 时填写最终关键文件。>`
2. 行为证据：
   - `<Close 时填写最终行为结论。>`
3. 测试证据：
   - `<Close 时填写最终命令和结果。>`
4. 文档证据：
   - `<Close 时填写文档同步。>`
5. 回滚证据：
   - `<Close 时填写整体回滚策略。>`
6. 剩余风险：
   - `<Close 时填写 Future / residual risk。>`
7. Harness evidence：
   - `<Close 时填写 Loop Blueprint 最终结论；手动 goal 写 Not applicable。>`
8. Temporary cache / housekeeping evidence：
   - Recorded policy：`<Enabled / Disabled / Not applicable>`
   - Exact roots / Roots outcome：`<逐项重复 goal-owned absolute path / None created>`
   - Action：`<Enabled 的 watcher:housekeeping 有界动作 / Disabled 的 preserved or retained 动作 / no-roots disposition>`
   - Removed size：`<仅 Enabled concrete roots 必填，例如 0 B；其他情况删除此行或按需记录>`
   - Preserved size：`<仅 Enabled concrete roots 必填，例如 0 B；其他情况删除此行或按需记录>`
   - Failed size：`<仅 Enabled concrete roots 必填，例如 0 B；其他情况删除此行或按需记录>`
   - Residual size：`<仅 Enabled concrete roots 必填，例如 0 B；其他情况删除此行或按需记录>`

Checkpoint evidence：

```text
<Fill the Checkpoint evidence format for Close.>
```

## 当前风险

- `<执行前已知风险与处置；按实际情况扩展，未知不得填成无风险。>`

## 推荐 Goal Prompt

```text
使用 workflow:long-running-goal 执行 <goal-path>。重读目标文件，检查 Ready 合同，从状态表继续；遵守其中冻结的权限、必需验证、checkpoint、硬停止与 Close 规则。
```

## 相关文档

- `<实际相关的 current、architecture、API、validation 或 runbook 文档；按需扩展。>`
