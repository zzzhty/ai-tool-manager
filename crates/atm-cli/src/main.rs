//! `atm` command line: the full local manager for skills and the embedded
//! harness distribution engine. Verb-first grammar (`atm <verb> <object>`):
//! `--harness` selects the embedded engine modality, its absence selects local
//! skill management. No polling and no secret-store access (keys never appear
//! on this surface); only `atm harness bootstrap/sync` may fetch first-run
//! Python dependencies, everything else stays offline.
use atm_core::omh::{self};
use atm_core::omh_embed;
use atm_core::projection::{CheckItem, ProjectionRegistry};
use atm_core::skills::SkillsService;
use atm_core::{Error, Result};
use std::path::{Path, PathBuf};
use std::process::Command;

fn main() {
    std::process::exit(run());
}

fn run() -> i32 {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    match dispatch(&arguments) {
        Ok(code) => code,
        Err(error) => {
            eprintln!("error: {}: {}", error.code, error.message);
            1
        }
    }
}

const USAGE: &str = "用法（动词优先；--harness 选择内置引擎，省略则为本地技能管理）:
  atm list skills [--json] [--trash]                     # 盘点工具根与保管区
  atm install skills <SOURCE> --to <ROOT> [--name <NAME>]   # 本地复制安装
  atm install skills --harness <ID>[,<ID>...]            # 安装内置分发（指令随行）
  atm install hooks --harness codex [--dry-run]          # 安装 Codex watcher 钩子
  atm uninstall skills <ROOT> <NAME>                     # 本地卸载入保管区
  atm uninstall skills --harness <ID>[,<ID>...]          # 移除内置分发
  atm uninstall hooks --harness codex [--dry-run]
  atm copy skills <SRC_ROOT> <NAME> <DST_ROOT>           # 跨根复制
  atm publish skills <SOURCE> --name <NAME> --to <ROOT>[,<ROOT>...]
  atm project skills <NAME> --to <ROOT>                  # 追加投影
  atm unproject skills <NAME> --from <ROOT> [--force]    # 撤除投影
  atm unpublish skills <NAME> [--with-projections]       # 移除发布源
  atm check skills [NAME] [--json]                       # 校验本地投影
  atm check skills --harness <ID>[,<ID>...] [--strict]   # 引擎校验（--strict 即 doctor）
  atm check hooks --harness codex                        # watcher 诊断
  atm update skills [NAME] [--force]                     # 修复本地投影
  atm update skills --harness <ID>[,<ID>...]             # 重应用内置分发
  atm repair skills --harness <ID>[,<ID>...]             # 修复分发（不改 PATH）
  atm restore skills <TRASH_ID> / purge skills <TRASH_ID>
  atm harness bootstrap [--home PATH]                    # 物化内置引擎并建 venv（首次联网装依赖）
  atm harness sync [--home PATH]                         # 升级 ATM 后重物化 / 收编旧安装
  atm harness status [--json] [--home PATH]
  atm harness -- <engine-args...>                        # 引擎原始命令逃生口
  atm help";

fn dispatch(arguments: &[String]) -> Result<i32> {
    let (verb, rest) = match arguments.split_first() {
        Some((verb, rest)) => (verb.as_str(), rest),
        None => {
            println!("{USAGE}");
            return Ok(0);
        }
    };
    if verb == "help" || verb == "--help" || verb == "-h" {
        if !rest.is_empty() {
            return Err(usage_error());
        }
        println!("{USAGE}");
        return Ok(0);
    }
    if verb == "harness" {
        return dispatch_harness(rest);
    }
    let (object, rest) = match rest.split_first() {
        Some((object, rest)) => (object.as_str(), rest),
        None => return Err(usage_error()),
    };
    match (verb, object) {
        ("list", "skills") => list_skills(rest),
        ("install", "skills") => install_skills(rest),
        ("install", "hooks") => hooks_operation("install", rest),
        ("uninstall", "skills") => uninstall_skills(rest),
        ("uninstall", "hooks") => hooks_operation("uninstall", rest),
        ("copy", "skills") => copy_skills(rest),
        ("publish", "skills") => publish_skills(rest),
        ("project", "skills") => project_skills(rest),
        ("unproject", "skills") => unproject_skills(rest),
        ("unpublish", "skills") => unpublish_skills(rest),
        ("check", "skills") => check_skills(rest),
        ("check", "hooks") => hooks_operation("check", rest),
        ("update", "skills") => update_skills(rest),
        ("repair", "skills") => repair_skills(rest),
        ("restore", "skills") => trash_action(rest, "restore"),
        ("purge", "skills") => trash_action(rest, "purge"),
        _ => Err(Error::new("CLI_COMMAND", "未知命令组合；请查看 atm help。")),
    }
}

// ---------------------------------------------------------------------------
// Embedded engine and watcher delegation
// ---------------------------------------------------------------------------

struct Parsed {
    positionals: Vec<String>,
    harness: Vec<String>,
    flags: Vec<&'static str>,
    values: Vec<(&'static str, String)>,
}

/// Strict option parser: unknown or duplicated options and misplaced values
/// are rejected before any service or child process is touched.
fn parse(rest: &[String], options: &[&'static str]) -> Result<Parsed> {
    let mut parsed = Parsed {
        positionals: Vec::new(),
        harness: Vec::new(),
        flags: Vec::new(),
        values: Vec::new(),
    };
    let mut index = 0;
    while index < rest.len() {
        let argument = rest[index].as_str();
        if argument.starts_with('-') {
            let option = options
                .iter()
                .find(|candidate| **candidate == argument)
                .ok_or_else(usage_error)?;
            if parsed.flags.contains(option) {
                return Err(usage_error());
            }
            parsed.flags.push(option);
        } else {
            parsed.positionals.push(argument.to_owned());
            index += 1;
            continue;
        }
        // Options in this grammar never take values inline; only --harness,
        // --to, --from, --name consume the following token.
        match argument {
            "--harness" | "--to" | "--from" | "--name" => {
                index += 1;
                let value = rest.get(index).ok_or_else(usage_error)?;
                if value.is_empty() || value.starts_with('-') {
                    return Err(usage_error());
                }
                let key: &'static str = match argument {
                    "--harness" => "--harness",
                    "--to" => "--to",
                    "--from" => "--from",
                    _ => "--name",
                };
                parsed.values.push((key, value.clone()));
                if argument == "--harness" {
                    for target in value.split(',').map(str::trim) {
                        if target.is_empty()
                            || target.len() > 64
                            || parsed.harness.iter().any(|existing| existing == target)
                        {
                            return Err(usage_error());
                        }
                        parsed.harness.push(target.to_owned());
                    }
                }
            }
            _ => {}
        }
        index += 1;
    }
    if parsed.positionals.iter().any(String::is_empty) {
        return Err(usage_error());
    }
    Ok(parsed)
}

fn value_of(parsed: &Parsed, key: &str) -> Option<String> {
    parsed
        .values
        .iter()
        .find(|(candidate, _)| *candidate == key)
        .map(|(_, value)| value.clone())
}

fn has_flag(parsed: &Parsed, flag: &str) -> bool {
    parsed.flags.contains(&flag)
}

fn run_engine(operation: &str, targets: &[String], extra: &[&str]) -> Result<i32> {
    let home = omh::manager_home_from_environment()?;
    let mut args: Vec<String> = vec![operation.to_owned()];
    args.extend(targets.iter().cloned());
    args.extend(extra.iter().map(|value| (*value).to_owned()));
    let (python, argv) = omh_embed::harness_invocation(&home, &args)?;
    spawn_interactive(&python, &argv)
}

/// Interactive passthrough: stdio inherited, the engine owns prompts and
/// output; its exit code propagates exactly.
fn spawn_interactive(program: &Path, args: &[String]) -> Result<i32> {
    let status = Command::new(program)
        .args(args)
        .status()
        .map_err(|_| Error::new("OMH_CLI_FAILED", "无法启动 harness 引擎子进程。"))?;
    Ok(status.code().unwrap_or(1))
}

fn install_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--to", "--name", "--harness"])?;
    if !parsed.harness.is_empty() {
        if !parsed.positionals.is_empty() || value_of(&parsed, "--to").is_some() {
            return Err(usage_error());
        }
        return run_engine("install", &parsed.harness, &[]);
    }
    if parsed.positionals.len() > 1 {
        return Err(usage_error());
    }
    let source = parsed.positionals.first().ok_or_else(usage_error)?;
    let target = value_of(&parsed, "--to").ok_or_else(usage_error)?;
    let name = value_of(&parsed, "--name")
        .or_else(|| {
            Path::new(source)
                .file_name()
                .map(|value| value.to_string_lossy().into_owned())
        })
        .ok_or_else(usage_error)?;
    let service = SkillsService::from_environment()?;
    let installed = service.install(Path::new(source), &target, &name)?;
    println!("已安装：{installed}");
    Ok(0)
}

fn uninstall_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--harness"])?;
    if !parsed.harness.is_empty() {
        if !parsed.positionals.is_empty() {
            return Err(usage_error());
        }
        return run_engine("remove", &parsed.harness, &[]);
    }
    let (root, name) = match parsed.positionals.as_slice() {
        [root, name] => (root.clone(), name.clone()),
        _ => return Err(usage_error()),
    };
    let service = SkillsService::from_environment()?;
    let trash = service.uninstall(&root, &name)?;
    println!("已卸载到保管区：{trash}");
    Ok(0)
}

fn hooks_operation(kind: &str, rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--harness", "--dry-run"])?;
    if !parsed.positionals.is_empty() {
        return Err(usage_error());
    }
    let targets = &parsed.harness;
    if targets.len() != 1 || targets[0] != "codex" {
        return Err(Error::new(
            "CLI_ARGUMENT",
            "hooks 目前仅支持 --harness codex。",
        ));
    }
    let home = omh::manager_home_from_environment()?;
    let repo = home.join("repo");
    let mut args: Vec<String> = Vec::new();
    match kind {
        "install" => {
            args.push("install-hook".into());
            if !has_flag(&parsed, "--dry-run") {
                args.push("--apply".into());
            }
            let python = home.join(if cfg!(windows) {
                "venv/Scripts/python.exe"
            } else {
                "venv/bin/python"
            });
            args.push("--python".into());
            args.push(python.to_string_lossy().into_owned());
        }
        "uninstall" => {
            args.push("uninstall-hook".into());
            if !has_flag(&parsed, "--dry-run") {
                args.push("--apply".into());
            }
        }
        _ => args.push("doctor".into()),
    }
    args.push("--repo-root".into());
    args.push(repo.to_string_lossy().into_owned());
    let (python, argv) = omh_embed::watcher_invocation(&home, &args)?;
    spawn_interactive(&python, &argv)
}

fn check_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--json", "--harness", "--strict"])?;
    if !parsed.harness.is_empty() {
        if parsed.positionals.len() > 1 || value_of(&parsed, "--to").is_some() {
            return Err(usage_error());
        }
        if !parsed.positionals.is_empty() {
            return Err(usage_error());
        }
        let operation = if has_flag(&parsed, "--strict") {
            "doctor"
        } else {
            "check"
        };
        return run_engine(operation, &parsed.harness, &[]);
    }
    if has_flag(&parsed, "--strict") {
        return Err(usage_error());
    }
    if parsed.positionals.len() > 1 {
        return Err(usage_error());
    }
    let name = parsed.positionals.first().map(String::as_str);
    let items = registry()?.check(name)?;
    if has_flag(&parsed, "--json") {
        println!(
            "{}",
            serde_json::to_string_pretty(&items).unwrap_or_default()
        );
        return finish_checks(&items);
    }
    report_checks(&items);
    finish_checks(&items)?;
    println!("全部投影正常。");
    Ok(0)
}

fn update_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--force", "--harness"])?;
    if !parsed.harness.is_empty() {
        if !parsed.positionals.is_empty() {
            return Err(usage_error());
        }
        return run_engine("refresh", &parsed.harness, &[]);
    }
    let name = parsed.positionals.first().map(String::as_str);
    if parsed.positionals.len() > 1 {
        return Err(usage_error());
    }
    let items = registry()?.refresh(name, has_flag(&parsed, "--force"))?;
    report_checks(&items);
    finish_checks(&items)
}

fn repair_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--harness"])?;
    if !parsed.positionals.is_empty() || parsed.harness.is_empty() {
        return Err(usage_error());
    }
    run_engine("repair", &parsed.harness, &["--no-path"])
}

// ---------------------------------------------------------------------------
// Local skill management (same atm-core services as the GUI)
// ---------------------------------------------------------------------------

fn list_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--json", "--trash"])?;
    if !parsed.positionals.is_empty() {
        return Err(usage_error());
    }
    if has_flag(&parsed, "--trash") {
        return trash(has_flag(&parsed, "--json"));
    }
    inventory(has_flag(&parsed, "--json"))
}

fn copy_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &[])?;
    let (source_root, name, target_root) = match parsed.positionals.as_slice() {
        [source, name, target] => (source.clone(), name.clone(), target.clone()),
        _ => return Err(usage_error()),
    };
    let service = SkillsService::from_environment()?;
    let copied = service.copy_to(&source_root, &name, &target_root)?;
    println!("已复制：{copied}");
    Ok(0)
}

fn publish_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--name", "--to"])?;
    let source = parsed.positionals.first().ok_or_else(usage_error)?;
    if parsed.positionals.len() > 1 {
        return Err(usage_error());
    }
    let name = value_of(&parsed, "--name").ok_or_else(usage_error)?;
    let raw = value_of(&parsed, "--to").ok_or_else(usage_error)?;
    let mut targets: Vec<String> = Vec::new();
    for target in raw.split(',').map(str::trim) {
        if target.is_empty() || targets.iter().any(|existing| existing == target) {
            return Err(usage_error());
        }
        targets.push(target.to_owned());
    }
    let projected = registry()?.publish(Path::new(source), &name, &targets)?;
    for item in projected {
        println!("已投影：{item}");
    }
    Ok(0)
}

fn project_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--to"])?;
    let name = parsed.positionals.first().ok_or_else(usage_error)?;
    if parsed.positionals.len() > 1 {
        return Err(usage_error());
    }
    let target = value_of(&parsed, "--to").ok_or_else(usage_error)?;
    if target.contains(',') {
        return Err(usage_error());
    }
    let projected = registry()?.project(name, &target)?;
    println!("已投影：{projected}");
    Ok(0)
}

fn unproject_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--from", "--force"])?;
    let name = parsed.positionals.first().ok_or_else(usage_error)?;
    if parsed.positionals.len() > 1 {
        return Err(usage_error());
    }
    let target = value_of(&parsed, "--from").ok_or_else(usage_error)?;
    registry()?.unproject(name, &target, has_flag(&parsed, "--force"))?;
    println!("已撤除投影：{target}/{name}");
    Ok(0)
}

fn unpublish_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--with-projections"])?;
    let name = parsed.positionals.first().ok_or_else(usage_error)?;
    if parsed.positionals.len() > 1 {
        return Err(usage_error());
    }
    let torn = registry()?.unpublish(name, has_flag(&parsed, "--with-projections"))?;
    println!("已发布源 {name} 移除；撤除投影 {} 项。", torn.len());
    Ok(0)
}

fn trash_action(rest: &[String], action: &str) -> Result<i32> {
    let parsed = parse(rest, &[])?;
    let id = parsed.positionals.first().ok_or_else(usage_error)?;
    if parsed.positionals.len() > 1 {
        return Err(usage_error());
    }
    let service = SkillsService::from_environment()?;
    if action == "restore" {
        let restored = service.restore(id)?;
        println!("已恢复：{restored}");
    } else {
        service.purge(id)?;
        println!("已彻底删除：{id}");
    }
    Ok(0)
}

// ---------------------------------------------------------------------------
// Maintenance group
// ---------------------------------------------------------------------------

fn dispatch_harness(rest: &[String]) -> Result<i32> {
    let (subcommand, rest) = match rest.split_first() {
        Some((subcommand, rest)) => (subcommand.as_str(), rest),
        None => {
            println!("用法：atm harness bootstrap|sync|status [--home PATH] 或 atm harness -- <engine-args>");
            return Ok(0);
        }
    };
    if subcommand == "--" {
        if rest.is_empty() || rest.iter().any(|arg| arg == "--home") {
            return Err(usage_error());
        }
        // Raw engine passthrough: everything after `--` goes to omh.py verbatim.
        // The manager home comes from the environment to keep one --home source.
        let home = omh::manager_home_from_environment()?;
        let (python, argv) = omh_embed::harness_invocation(&home, rest)?;
        return spawn_interactive(&python, &argv);
    }
    let parsed = parse(rest, &["--home", "--json"])?;
    let home = match value_of(&parsed, "--home") {
        Some(path) if Path::new(&path).is_absolute() => PathBuf::from(path),
        Some(_) => return Err(usage_error()),
        None => omh::manager_home_from_environment()?,
    };
    match subcommand {
        "bootstrap" | "sync" => {
            if !parsed.positionals.is_empty() || has_flag(&parsed, "--json") {
                return Err(usage_error());
            }
            let (python, argv) = omh_embed::embed_invocation(subcommand, &home)?;
            spawn_interactive(&python, &argv)
        }
        "status" => {
            if !parsed.positionals.is_empty() {
                return Err(usage_error());
            }
            let mut engine_args = vec!["status".to_owned()];
            if has_flag(&parsed, "--json") {
                engine_args.push("--json".into());
            }
            let (python, argv) = omh_embed::harness_invocation(&home, &engine_args)?;
            spawn_interactive(&python, &argv)
        }
        _ => Err(Error::new(
            "CLI_COMMAND",
            "未知 harness 子命令；可用 bootstrap、sync、status，或 atm harness -- <args>。",
        )),
    }
}

// ---------------------------------------------------------------------------
// Shared helpers (unchanged semantics from the previous skills-only CLI)
// ---------------------------------------------------------------------------

fn usage_error() -> Error {
    Error::new("CLI_ARGUMENT", "参数不足或无效；请查看 atm help。")
}

fn service() -> Result<SkillsService> {
    SkillsService::from_environment()
}

fn registry() -> Result<ProjectionRegistry> {
    ProjectionRegistry::from_environment()
}

fn report_checks(items: &[CheckItem]) {
    for item in items {
        let status = match item.status {
            "ok" => "正常",
            "broken_link" => "断链",
            "modified_copy" => "副本已修改",
            other => other,
        };
        let detail = item
            .detail
            .as_deref()
            .map(|text| format!("（{text}）"))
            .unwrap_or_default();
        println!(
            "[{status}] {} -> {}/{}{detail}",
            item.source, item.root_id, item.link_name
        );
    }
}

fn finish_checks(items: &[CheckItem]) -> Result<i32> {
    if items.iter().all(|item| item.status == "ok") {
        Ok(0)
    } else {
        Err(Error::new(
            "PROJECTION_BROKEN",
            "存在断链或被修改的投影；可用 atm update skills 修复（被修改副本需 --force 覆盖）。",
        ))
    }
}

fn inventory(json: bool) -> Result<i32> {
    let snapshot = service()?.inventory()?;
    if json {
        println!(
            "{}",
            serde_json::to_string_pretty(&snapshot).unwrap_or_default()
        );
        return Ok(0);
    }
    for root in &snapshot.roots {
        if !root.exists {
            println!("{:<12} 根不存在  {}", root.id, root.path);
            continue;
        }
        println!("{:<12} {} 项  {}", root.id, root.entries.len(), root.path);
        for entry in &root.entries {
            let kind = match entry.kind {
                "omh_managed" => "内置分发管理",
                "lkm_projected" => "ATM 投影",
                "symlink" => "链接",
                "directory" => "目录",
                _ => "文件",
            };
            let description = entry.description.as_deref().unwrap_or("");
            println!("  - {:<28} [{kind}] {description}", entry.name);
        }
    }
    println!("保管区 {} 项。", snapshot.trash.len());
    Ok(0)
}

fn trash(json: bool) -> Result<i32> {
    let snapshot = service()?.inventory()?;
    if json {
        println!(
            "{}",
            serde_json::to_string_pretty(&snapshot.trash).unwrap_or_default()
        );
        return Ok(0);
    }
    if snapshot.trash.is_empty() {
        println!("保管区为空。");
        return Ok(0);
    }
    for item in &snapshot.trash {
        println!("{}  原 {}", item.id, item.origin_path);
    }
    Ok(0)
}
