# Coding harness skills 与 instructions 分发调查

- 日期：2026-08-22
- 范围：Codex、ZCode、Claude Code、GitHub Copilot、Gemini CLI；另外评估 OpenCode 与 Cursor 是否适合首版 registry。
- 来源标准：只采用产品官方文档或官方源代码文档。未被官方资料确认的行为明确标为“用户实测”或“未决”，不从目录存在推导 symlink/junction 支持。

## 结论摘要

1. 调查阶段曾建议把原 `direct` 目标命名为 `shared`，而不是 `universal`。后续领域建模否决了这个 partial harness：`~/.agents/skills` 虽被 Codex、GitHub Copilot、Gemini CLI、Cursor、OpenCode 官方文档列为用户级 skill source，却不能随同一个 target 分发 global instructions，而且可能与产品原生目录同时发现同名 skill。它最终只作为 registry 的 Excluded Skill Root。Claude Code 官方只列出 `~/.claude/skills`，ZCode 官方只列出 `~/.zcode/skills` 和外部导入流程；ZCode 能直接读取 `~/.agents/skills` 是本项目用户在当前部署中的实测，不是当前官方契约。
2. 最终设计使用一个 `--harness` 参数选择完整分发计划，而不是让用户分别组合 skills 与 instructions。Registry 内仍将两种 surface 结构化建模，但每个 harness entry 必须同时拥有 skills driver、instructions policy、root resolver、materialization、reconciliation 与 extras。默认 `codex` 调用现有 Codex marketplace/plugin install；其他 harness 使用各自原生目录和 global instructions 文件。
3. 首版支持 `codex`、`zcode`、`claude-code`、`copilot-cli`、`gemini-cli`、`opencode`。Gemini CLI 与 OpenCode 都有完整的文件级 global instructions，因此可作为完整 harness；它们对 `~/.agents/skills` 的官方支持只构成冲突检测依据，不构成第二条分发路径。
4. Cursor 建议先登记为候选而不开放 `--harness cursor`：它官方支持用户级 skills 和 `~/.agents/skills`，也有 plugin marketplace，但全局 User Rules 目前由 UI 管理，官方没有给出可由更新脚本安全写入的用户级 instructions 文件；因此它不能满足完整 harness 契约。
5. `copilot` 不能作为一个无差别的 harness 名称。首版应命名为 `copilot-cli`：CLI 有稳定的本地配置根、skills 目录和用户级 instructions 文件；Copilot cloud agent、code review 和各 IDE 对 instructions 的支持矩阵不同，不能承诺同一个本地分发结果。

实施决定由 ADR-0007 记录：Codex managed-stale plugin reconcile 默认启用，仅处理可证明属于所选 marketplace 的 config/cache；非空计划必须先列出并确认。Instructions replacement 仍要求实时人工确认，`--yes` 只能确认缺失文件创建和上述严格 prune 计划。`~/.agents/skills` 中的 catalog identity 会在任何 harness mutation 前阻断；清理必须通过独立命令预览并确认，不由 refresh 自动删除。当前自动化已覆盖 registry、路径解析、文件系统 projection 与 closure；各非 Codex harness 的真实 inventory/reload smoke test 仍属于本文末尾的部署验证清单，不能从文件系统测试外推为产品运行时结论。

## 官方能力矩阵

| Harness / surface | 用户级 skills | `~/.agents/skills` | 用户级 instructions | 项目级 instructions | root/home override | 原生分发机制 |
| --- | --- | --- | --- | --- | --- | --- |
| Codex | `$HOME/.agents/skills` | 官方支持 | `$CODEX_HOME/AGENTS.md`（也支持 override） | 从 repo root 到 CWD 的 `AGENTS.override.md` / `AGENTS.md` 链 | `CODEX_HOME` 是 Codex 配置根 | Codex marketplace/plugin；CLI `/plugins` |
| ZCode Agent | `~/.zcode/skills` | 官方未文档化；用户实测可读 | `~/.zcode/AGENTS.md` | 当前 Workspace 根 `AGENTS.md` | 未发现文档化 override | ZCode plugin store/personal marketplace；skills 外部导入支持 symlink 或 copy |
| Claude Code | `${CLAUDE_CONFIG_DIR:-~/.claude}/skills` | 官方未列出 | `${CLAUDE_CONFIG_DIR:-~/.claude}/CLAUDE.md` | `./CLAUDE.md` 或 `./.claude/CLAUDE.md`，向上遍历并按需读取子目录 | `CLAUDE_CONFIG_DIR` 是配置根本身 | Claude plugin marketplace；standalone skills |
| GitHub Copilot CLI | `${COPILOT_HOME:-~/.copilot}/skills` | 官方支持 | `${COPILOT_HOME:-~/.copilot}/copilot-instructions.md` | `.github/copilot-instructions.md`、`AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 等 | `COPILOT_HOME` 是配置根本身 | CLI plugin marketplace / GitHub repo；`copilot skill add` |
| Gemini CLI | `${GEMINI_CLI_HOME:-$HOME}/.gemini/skills` | 官方支持 | `${GEMINI_CLI_HOME:-$HOME}/.gemini/GEMINI.md` | 分层 `GEMINI.md`；文件名可配置为 `AGENTS.md` | `GEMINI_CLI_HOME` 替代 user home，随后仍追加 `.gemini` | Extensions/gallery；`gemini skills install/link` |
| OpenCode | `~/.config/opencode/skills` | 官方支持 | `~/.config/opencode/AGENTS.md` | 项目根/向上发现 `AGENTS.md` | `OPENCODE_CONFIG_DIR` 是额外 config source，不是全局 home 替换 | 本地或 npm plugins；显式 skill source |
| Cursor | `~/.cursor/skills` | 官方支持 | 官方仅说明 Customize → Rules 中的 User Rules，未给出可写文件 | 项目 `.cursor/rules` 或根/子目录 `AGENTS.md` | 未发现文档化配置根 override | Cursor/Agent Plugins 与 marketplace |

上表中的路径语义来自各产品官方资料，细节和边界如下。

## 逐 harness 核对

### Codex

Codex 官方 skill 文档把 `$HOME/.agents/skills` 定义为用户级 skill source，并明确 Codex 支持 symlinked skill folders。项目级 skills 从 CWD 向 repo root 的各级 `.agents/skills` 发现；skill 同名时不会合并，可能同时出现在 selector 中。官方同时把 plugins 定义为跨表面分发 reusable skills/connectors 的方式。[Build skills](https://learn.chatgpt.com/docs/build-skills)

全局 instructions 在 Codex home 中：先读 `AGENTS.override.md`，否则读 `AGENTS.md`。`CODEX_HOME` 覆盖默认 `~/.codex`。项目层从 repo root 走到 CWD，每层依次查 `AGENTS.override.md`、`AGENTS.md` 和配置的 fallback 名称。[Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

Codex CLI 支持从 marketplace 安装 plugin，安装后需要新会话才能使用其中 skills/tools；IDE extension 当前不支持 plugins。[Plugins](https://learn.chatgpt.com/docs/plugins)

对 registry 的约束：

- `codex` 必须继续表示 marketplace/plugin driver，而不是 `$CODEX_HOME/skills` 目录映射。
- `$HOME/.agents/skills` 是 Codex 官方 authoring/discovery source，但本项目不再向它分发 catalog。
- Codex plugin skills 与该 discovery root 中的同名 skills 同时暴露时可能形成多个 runtime identity；因此 refresh/check 要求 registry 声明的 Excluded Skill Root 中不存在仓库 catalog identity。

### ZCode Agent

ZCode 官方文档定义用户级 skill 路径为 `~/.zcode/skills/<name>/SKILL.md`。Settings → Skills 的外部导入会扫描其他 agent 的 skill directories，用户可选择 Symlink 或 Copy，并选择 Global 或当前 Project 目标。[ZCode Skill](https://zcode.z.ai/en/docs/skill)

当前官方页面没有把 `~/.agents/skills` 列为 ZCode runtime source。用户已在实际环境验证 ZCode 可直接读取该目录；该事实只用于解释冲突风险，不作为本项目的分发契约。验证记录必须：

- 将证据标为“用户实测”，不要写成跨版本官方保证；
- 在独立 smoke test 中实际确认 ZCode inventory；
- 始终使用 `zcode` 原生 target（`~/.zcode/skills`）作为本项目契约路径。

ZCode instructions 当前只有两级：`~/.zcode/AGENTS.md` 和当前 Workspace 的 `AGENTS.md`；ZCode 先附加 global，再附加 workspace。官方明确说 `CLAUDE.md` 只在 onboarding 时作为一次性迁移来源，不在 runtime 持续读取。[ZCode Agent](https://zcode.z.ai/en/docs/agents)

ZCode 有完整 plugin store 和 personal marketplace，可从 GitHub、Git URL、本地 marketplace 文件/目录等来源安装。ZCode plugin 首选 `.zcode-plugin/plugin.json`，也兼容 `.claude-plugin/plugin.json`；官方没有说明 `.codex-plugin/plugin.json` 可直接使用。[ZCode Plugin](https://zcode.z.ai/en/docs/plugin)

未发现官方文档化的 ZCode home/root 环境变量。因此 registry 应把 `.zcode` 建模为 `user-home-relative` 固定解析规则，不发明 `ZCODE_HOME`。

### Claude Code

Claude Code 官方定义项目 skills 为 `.claude/skills/<name>/SKILL.md`、用户 skills 为 `~/.claude/skills/<name>/SKILL.md`，另可由 plugin 提供 namespaced skills。官方 skill source 列表没有 `~/.agents/skills`。[Extend Claude with skills](https://code.claude.com/docs/en/slash-commands)

用户 instructions 为 `~/.claude/CLAUDE.md`；项目 instructions 可位于 `./CLAUDE.md` 或 `./.claude/CLAUDE.md`，另有 `CLAUDE.local.md`。Claude 从 CWD 向上读取，子目录文件在访问相应文件时按需加载。Claude Code 官方明确说它原生读取 `CLAUDE.md`，不是 `AGENTS.md`；已有项目 `AGENTS.md` 可由 `CLAUDE.md` import 或在项目中建立 symlink，但这条项目示例不能外推为所有平台、所有用户目录的 symlink 保证。[How Claude remembers your project](https://code.claude.com/docs/en/memory)

`CLAUDE_CONFIG_DIR` 直接替代默认 `~/.claude` 配置目录；settings、credentials、history、plugins 等都位于该根下。因此 registry resolver 必须把环境变量值当作最终配置根，不再追加 `.claude`。[Environment variables](https://code.claude.com/docs/en/env-vars)

Claude Code 有 plugin marketplace。Standalone `.claude/skills` 适合个人/项目配置，plugin skills 使用 `plugin-name:skill-name` namespace；plugin format 要求 `.claude-plugin/plugin.json`。[Create plugins](https://code.claude.com/docs/en/plugins) [Discover plugins](https://code.claude.com/docs/en/discover-plugins)

对首版 registry，`claude-code` 可以安全定义原生 skill/instructions 路径；是否使用 symlink、copy 或 CLI/plugin 安装必须由 driver 和平台测试决定，不能仅因目录可读就假定 symlink/junction 得到支持。

### GitHub Copilot

#### Copilot CLI

Copilot CLI 官方支持个人 skills `~/.copilot/skills` 和共享 alias `~/.agents/skills`；项目 skills 可放在 `.github/skills`、`.claude/skills` 或 `.agents/skills`。CLI 还支持 `/skills add` / `copilot skill add` 添加其他 skill location；目录输入会注册为 custom skill source，文件或 URL 输入会复制到个人或项目目录。[Adding agent skills for GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills) [CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)

CLI 用户级 instructions 是 `~/.copilot/copilot-instructions.md`，并可增加 `~/.copilot/instructions/**/*.instructions.md`。项目/agent instructions 支持 `.github/copilot-instructions.md`、`.github/instructions/**/*.instructions.md`、`AGENTS.md`、`CLAUDE.md` 和 `GEMINI.md`。`COPILOT_CUSTOM_INSTRUCTIONS_DIRS` 还能增加额外目录。[Adding custom instructions for GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions)

`COPILOT_HOME` 直接替代整个 `~/.copilot` 配置目录，其中包括 `skills/`、`copilot-instructions.md` 和 installed plugin state；不要在环境变量值后再次追加 `.copilot`。[GitHub Copilot CLI configuration directory](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference)

Copilot CLI 具备 plugin install/update/list/uninstall，并支持 marketplace 或直接 GitHub repository。[Comparing Copilot CLI customization features](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/comparing-cli-features)

#### Cloud agent / code review / IDE

Agent Skills 可用于 Copilot cloud agent、code review、CLI、Copilot app，以及 VS Code/JetBrains 的 agent mode；官方同样列出项目 `.agents/skills` 和个人 `~/.agents/skills`。[About agent skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills)

但 instructions 支持按 surface 分裂。例如 Copilot CLI 有本地个人 instructions 文件；cloud agent、code review、VS Code、Visual Studio、JetBrains、Eclipse、Xcode 各自支持的 repository-wide、path-specific、agent、personal instructions 组合不同。[Custom instructions support matrix](https://docs.github.com/en/copilot/reference/custom-instructions-support)

因此首版 registry 只应开放 `copilot-cli`。`copilot` 这个宽泛名称会错误承诺 cloud/IDE 也读取脚本分发的 `$COPILOT_HOME/copilot-instructions.md`。

### Gemini CLI

Gemini CLI 官方把 skills 分为 built-in、extension、user、workspace 四级。用户级路径为 `~/.gemini/skills` 或 `~/.agents/skills` alias；workspace 路径为 `.gemini/skills` 或 `.agents/skills`。同层内 `.agents/skills` 优先于 `.gemini/skills`。[Agent Skills](https://geminicli.com/docs/cli/skills/) [Managing Agent Skills](https://geminicli.com/docs/cli/using-agent-skills/)

Gemini CLI 还提供 `gemini skills install` 和 `gemini skills link`，并可用 `--scope workspace` 切换作用域。该 CLI 能力比未经验证的原始 symlink 假设更适合作为可选 driver。[Managing Agent Skills](https://geminicli.com/docs/cli/using-agent-skills/)

全局 instructions 默认位于 `~/.gemini/GEMINI.md`；项目和子目录也使用分层 `GEMINI.md`。`context.fileName` 可把发现文件名配置为 `AGENTS.md` 或一个名称列表。[Provide context with GEMINI.md files](https://geminicli.com/docs/cli/gemini-md/)

`GEMINI_CLI_HOME` 的语义不同于 `CODEX_HOME`、`CLAUDE_CONFIG_DIR`、`COPILOT_HOME`：它替代 Gemini CLI 认为的 user system home，CLI 随后在该目录下创建 `.gemini`。例如 `GEMINI_CLI_HOME=/srv/user-a` 对应配置根 `/srv/user-a/.gemini`，不是 `/srv/user-a`。[Gemini CLI configuration](https://geminicli.com/docs/get-started/configuration/)

Gemini extensions 可以打包 prompts、MCP、commands、hooks、subagents 和 skills，并通过 gallery 或 GitHub/local path 安装；它是原生扩展体系，但不是当前 Codex marketplace manifest 的同义格式。[Gemini CLI extensions](https://geminicli.com/docs/extensions/) [Extension reference](https://geminicli.com/docs/extensions/reference/)

未决边界：官方文档确认 `~/.agents/skills` alias，也确认 `GEMINI_CLI_HOME` 替代 home 后追加 `.gemini`；但没有在同一契约中明确 `GEMINI_CLI_HOME` 是否也重定位 `.agents/skills` alias。本项目只把 OS home 下的 `~/.agents/skills` 声明为 Excluded Skill Root，不为该 alias 建立 projection，也不自行推导另一个排除路径。

### OpenCode（建议首版纳入）

OpenCode 官方从 `~/.config/opencode/skills`、`~/.claude/skills` 和 `~/.agents/skills` 加载全局 skills；项目层从 `.opencode/skills`、`.claude/skills` 和 `.agents/skills` 加载并向上遍历到 git worktree。[OpenCode Agent Skills](https://opencode.ai/docs/skills)

全局 instructions 是 `~/.config/opencode/AGENTS.md`，项目使用 `AGENTS.md`；如果不存在相应 `AGENTS.md`，当前文档还描述了 Claude Code `CLAUDE.md` fallback。`opencode.json` 的 `instructions` 数组可另外加载本地 glob 或 URL。[OpenCode Rules](https://opencode.ai/docs/rules/)

`OPENCODE_CONFIG_DIR` 不是 `CODEX_HOME` 式的配置根替换。官方说明它是一个额外的 custom config directory，并在标准 global/project sources 之后加载其中 agents、commands、modes、plugins 等组件；标准 global config 仍是 `~/.config/opencode`。[OpenCode Config](https://opencode.ai/docs/config)

OpenCode plugins 是本地 JavaScript/TypeScript modules 或配置中的 npm packages；它们不等同于本仓库 Codex plugin package。首版应只使用 native skill directory，不尝试自动转换 plugin，也不向 shared discovery root 重复投影。[OpenCode Plugins](https://opencode.ai/docs/plugins/)

OpenCode 同时具有原生 skills 目录和文件级 global `AGENTS.md`，所以比 Cursor 更适合首版完整 harness 自动化。

### Cursor（候选，建议暂缓完整纳入）

Cursor 官方从 `.agents/skills`、`.cursor/skills`、`~/.agents/skills`、`~/.cursor/skills` 加载 skills，也兼容 Claude/Codex 目录。[Cursor Agent Skills](https://cursor.com/docs/skills)

项目 instructions 支持 `.cursor/rules` 与项目根/子目录 `AGENTS.md`。全局 User Rules 在 Customize → Rules 中定义；当前官方页面未提供稳定的用户级 rules 文件路径。[Cursor Rules](https://cursor.com/docs/rules)

Cursor 支持 Agent Plugins 与 Cursor Plugins、Marketplace、team marketplaces，并支持本地 `~/.cursor/plugins/local` 开发目录。[Cursor Plugins](https://cursor.com/docs/plugins)

Cursor 的 `~/.agents/skills` 发现能力不能替代完整 harness。由于缺少可安全管理的 file-backed global instructions 契约，首版不应开放 `--harness cursor`；等官方提供文件入口或本项目决定接受 UI/manual driver 后再加入。

## 对 registry 的具体建议

Registry 应是纯结构化 JSON。它只引用代码中 allowlist 的 resolver/driver 名称，不包含任意 shell、PowerShell 或命令模板。下面保留调查阶段的双参数备选结构作为决策过程记录；该结构未被采用：

```json
{
  "schemaVersion": "2026-08-22",
  "defaults": {
    "skillsTarget": "codex",
    "instructionsHarness": "codex"
  },
  "sharedSkillTargets": {
    "shared": {
      "driver": "skill-directory-projection",
      "root": {
        "resolver": "user-home-relative",
        "path": ".agents/skills"
      },
      "instructionsPolicy": "forbidden"
    }
  },
  "harnesses": {
    "codex": {
      "root": {
        "resolver": "env-or-user-home-relative",
        "environment": "CODEX_HOME",
        "fallbackPath": ".codex"
      },
      "skills": {
        "driver": "codex-marketplace"
      },
      "instructions": {
        "driver": "file-content-sync",
        "relativePath": "AGENTS.md"
      }
    },
    "zcode": {
      "root": {
        "resolver": "user-home-relative",
        "path": ".zcode"
      },
      "skills": {
        "driver": "skill-directory-projection",
        "relativePath": "skills"
      },
      "instructions": {
        "driver": "file-content-sync",
        "relativePath": "AGENTS.md"
      }
    },
    "claude-code": {
      "root": {
        "resolver": "env-or-user-home-relative",
        "environment": "CLAUDE_CONFIG_DIR",
        "fallbackPath": ".claude"
      },
      "skills": {
        "driver": "skill-directory-projection",
        "relativePath": "skills"
      },
      "instructions": {
        "driver": "file-content-sync",
        "relativePath": "CLAUDE.md"
      }
    },
    "copilot-cli": {
      "root": {
        "resolver": "env-or-user-home-relative",
        "environment": "COPILOT_HOME",
        "fallbackPath": ".copilot"
      },
      "skills": {
        "driver": "skill-directory-projection",
        "relativePath": "skills"
      },
      "instructions": {
        "driver": "file-content-sync",
        "relativePath": "copilot-instructions.md"
      }
    },
    "gemini-cli": {
      "root": {
        "resolver": "env-home-plus-relative",
        "environment": "GEMINI_CLI_HOME",
        "relativePath": ".gemini"
      },
      "skills": {
        "driver": "skill-directory-projection",
        "relativePath": "skills"
      },
      "instructions": {
        "driver": "file-content-sync",
        "relativePath": "GEMINI.md"
      }
    },
    "opencode": {
      "root": {
        "resolver": "user-home-relative",
        "path": ".config/opencode"
      },
      "skills": {
        "driver": "skill-directory-projection",
        "relativePath": "skills"
      },
      "instructions": {
        "driver": "file-content-sync",
        "relativePath": "AGENTS.md"
      }
    }
  }
}
```

最终采用的结构以 `.agents/harnesses/registry.json` 和 ADR-0007 为准：`defaults.harness` 只有一个默认值，每个 `harnesses` entry 同时拥有 root candidates、skills、instructions、reconciliation 和 extras；用户只传 `--harness`。`excludedSkillRoots` 单独声明不得包含仓库 catalog identity 的 discovery roots，它不是可选择的分发 target。

执行代码应：

- allowlist `codex-marketplace`、`directory-projection`、`managed-file` 和 `settings-derived-file` driver；
- 只解析结构化 root candidates，并严格区分“环境变量是最终 config root”与“环境变量替代 home 后追加产品目录”；
- 拒绝 unknown keys、unknown driver、绝对路径逃逸、空 root、文件/目录类型不匹配；
- 从 registry 解析唯一默认 harness；所有 harness 必须拥有 instructions，不能接受第二个 instructions 选择参数；
- 在任何 skills 或 instructions mutation 前检查所有 `excludedSkillRoots`，但只通过独立、显式确认的低层命令清理 repository-owned entries；
- 把 product-native plugin/extension capability 记录为 metadata 或后续 driver，不因“产品有 marketplace”就自动转换当前 Codex package；
- 不在 shell、PowerShell、Python 三处重复 harness 路径常量。

## 首版执行边界

### 建议首版开放

| Harness | Skills driver | 同一计划中的 instructions | 理由 |
| --- | --- | --- | --- |
| `codex` | 现有 Codex marketplace/plugin install | `codex` | 保持默认与当前 plugin 行为 |
| `zcode` | `~/.zcode/skills` native distribution | `zcode` | 官方路径稳定；用户实测的额外 discovery 不作为分发契约 |
| `claude-code` | `${CLAUDE_CONFIG_DIR:-~/.claude}/skills` native distribution | `claude-code` | 官方原生路径完整，专用 target 必要 |
| `copilot-cli` | `${COPILOT_HOME:-~/.copilot}/skills` 或官方 CLI registration | `copilot-cli` | 本地 surface 契约完整；避免泛化到 IDE/cloud |
| `gemini-cli` | `${GEMINI_CLI_HOME:-$HOME}/.gemini/skills` 或官方 `skills link` | `gemini-cli` | 完整 root、skills、instructions 契约 |
| `opencode` | `~/.config/opencode/skills` native distribution | `opencode` | 原生 skills 与文件级 AGENTS 契约完整 |

### 建议暂缓

- `cursor`：虽然能发现 `~/.agents/skills`，但没有官方 file-backed global User Rules 路径，因此无法满足一个完整 harness 计划的自动化契约。
- 泛化 `copilot`：必须先按 CLI/cloud agent/code review/IDE surface 拆分；首版只做 `copilot-cli`。
- 非 Codex marketplace drivers：各产品虽然都有 plugin/extension 能力，但 manifest、identity、安装状态和命令不同。先用原生 skills surface，后续逐 harness 增加 package driver。

## 安全与 closure 要求

1. `~/.agents/skills` 是 Excluded Skill Root，不是 harness；任何 harness refresh 都不得向它投影或自动清理，也不得因它存在而改变 Codex plugin prune 范围。
2. 每个 harness target 的 source、target、materialization 和 ownership 必须独立验证。官方给出一个目录不等于官方保证 POSIX symlink、Windows symlink 或 junction 都可被 runtime 发现。
3. 新 driver 上线前至少做：普通目录、POSIX symlink、Windows junction/copy（按支持范围）、同名冲突、运行时 inventory/reload 的 smoke test；没有证据的 materialization 应 fail closed。
4. Prune 只能删除能够证明由本仓库管理的 entry，必须保留用户自有 skills、系统/built-in skills 和其他 marketplace state。
5. 当同一产品同时读取 `~/.agents/skills` 与 native roots 时，同名 skill 可能被覆盖、重复显示或形成多个 identity。Closure 必须把仓库 catalog 在 Excluded Skill Root 中的重复暴露视为失败。
6. Instructions 替换继续采用人工二次确认：先显示 harness、source、target、现有文件类型和差异；目录/reparse-point/未知类型直接拒绝。本文没有验证任何产品对用户级 instructions symlink 的通用支持，因此实现不应从项目级示例外推。

## 未决问题与验证清单

1. ZCode：锁定当前已实测版本，并验证 `~/.agents/skills` 的直接发现、刷新方式、同名优先级；官方目前只承诺 `~/.zcode/skills` 和外部导入。
2. ZCode：确认是否存在未公开但受支持的 root override；在官方契约出现前不增加 `ZCODE_HOME`。
3. Gemini CLI：设置 `GEMINI_CLI_HOME` 时，`~/.agents/skills` alias 是否仍指向 OS home，还是跟随替代 home。官方资料没有把这两个行为明确连接起来。
4. Copilot：若未来要支持 IDE/cloud global instructions，必须分别研究每个 surface 的 storage/API；不能复用 `COPILOT_HOME/copilot-instructions.md` 结论。
5. Cursor：是否出现官方、稳定、file-backed 的 User Rules 路径；在此之前不建立 Cursor harness，也不向 excluded root 分发本仓库 skills。
6. OpenCode：Windows 与 XDG 环境下 global config root 的正式跨平台 resolver 需要在实现前用官方源码/运行时再验证；`OPENCODE_CONFIG_DIR` 不应被误当作全局 root override。
7. Packaging：评估是否为 ZCode/Claude Code/Copilot/Gemini/Cursor 分别维护原生 manifest，或继续只把 Codex 作为 marketplace target。没有显式迁移设计前，不为 `.codex-plugin` 添加兼容别名或自动转换。
