//! CLI for local skills and Rust-owned harness distribution.
//! CLI and GUI share `distribution::Service`; only explicitly selected payload
//! runtimes may execute a declared Python interpreter.
use atm_core::distribution::{source, Service};
use atm_core::harness::{self};
use atm_core::harness_embed;
use atm_core::projection::{CheckItem, ProjectionRegistry};
use atm_core::skills::SkillsService;
use atm_core::{Error, Result};
use std::path::{Path, PathBuf};

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
  atm uninstall skills <ROOT> <NAME>                     # 本地卸载入保管区
  atm uninstall skills --harness <ID>[,<ID>...]          # 移除内置分发
  atm uninstall hooks --harness codex [--dry-run]        # 退役旧 skill-watcher 条目
  atm copy skills <SRC_ROOT> <NAME> <DST_ROOT>           # 跨根复制
  atm publish skills <SOURCE> --name <NAME> --to <ROOT>[,<ROOT>...]
  atm project skills <NAME> --to <ROOT>                  # 追加投影
  atm unproject skills <NAME> --from <ROOT> [--force]    # 撤除投影
  atm unpublish skills <NAME> [--with-projections]       # 移除发布源
  atm check skills [NAME] [--json]                       # 校验本地投影
  atm check skills --harness <ID>[,<ID>...] [--strict]   # 引擎校验（--strict 即 doctor）
  atm check hooks --harness codex                        # 旧 hook 退役诊断
  atm update skills [NAME] [--force]                     # 修复本地投影
  atm update skills --harness <ID>[,<ID>...]             # 重应用内置分发
  atm repair skills --harness <ID>[,<ID>...]             # 修复分发（不改 PATH）
  atm restore skills <TRASH_ID> / purge skills <TRASH_ID>
  atm harness bootstrap|sync [--home PATH]              # 校验并缓存随包内容，无需 Python
  atm harness adopt [--home PATH] [--retire-missing IDS] [--dry-run]
                                                      # 交接旧状态；仅显式退役根目录缺失的目标
  atm harness status|recover [--json] [--home PATH]
  atm harness migrate --to <ABS_HOME> [--source <ABS_PATH>] [--home PATH] [--python <ABS_PATH>] [--offline] [--dry-run]
  atm harness plan <install|refresh|remove|repair> --harness <ID>[,<ID>...]
  atm harness runtime prepare <GROUP> --python <ABS_PATH> [--external-venv <ABS_PATH>] [--offline]
  atm harness verify-source [--source <ABS_PATH>]       # 校验发布内容
  atm harness import --lock <ABS_PATH> [--archive <ABS_PATH>] [--home PATH]
                                                      # 仅导入固定版本缓存；另行 sync/apply
  atm harness fetch --lock <ABS_PATH> --output <ABS_PATH> # 构建/离线包准备，不改安装记录
  atm harness export --source <ABS_PATH> --output <ABS_PATH> --repository <URL> --revision <SHA> --url <URL> [--composition NAME]
  atm harness -- <known-command> ...                    # 同一 Rust 命令空间；无脚本逃生口
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
// Harness distribution and explicit hook configuration
// ---------------------------------------------------------------------------

struct Parsed {
    positionals: Vec<String>,
    harness: Vec<String>,
    retire_missing: Vec<String>,
    flags: Vec<&'static str>,
    values: Vec<(&'static str, String)>,
}

/// Strict option parser: unknown or duplicated options and misplaced values
/// are rejected before any mutating service operation is touched.
fn parse(rest: &[String], options: &[&'static str]) -> Result<Parsed> {
    let mut parsed = Parsed {
        positionals: Vec::new(),
        harness: Vec::new(),
        retire_missing: Vec::new(),
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
        // Value options consume the following token, never an inline value.
        match argument {
            "--harness" | "--to" | "--from" | "--name" | "--home" | "--source" | "--python"
            | "--external-venv" | "--retire-missing" | "--output" | "--repository"
            | "--revision" | "--url" | "--composition" | "--lock" | "--archive" => {
                index += 1;
                let value = rest.get(index).ok_or_else(usage_error)?;
                if value.is_empty() || value.starts_with('-') {
                    return Err(usage_error());
                }
                let key: &'static str = match argument {
                    "--harness" => "--harness",
                    "--to" => "--to",
                    "--from" => "--from",
                    "--home" => "--home",
                    "--source" => "--source",
                    "--python" => "--python",
                    "--external-venv" => "--external-venv",
                    "--retire-missing" => "--retire-missing",
                    "--output" => "--output",
                    "--repository" => "--repository",
                    "--revision" => "--revision",
                    "--url" => "--url",
                    "--composition" => "--composition",
                    "--lock" => "--lock",
                    "--archive" => "--archive",
                    _ => "--name",
                };
                parsed.values.push((key, value.clone()));
                if matches!(argument, "--harness" | "--retire-missing") {
                    let targets = if argument == "--harness" {
                        &mut parsed.harness
                    } else {
                        &mut parsed.retire_missing
                    };
                    for target in value.split(',').map(str::trim) {
                        if target.is_empty()
                            || target.len() > 64
                            || targets.iter().any(|existing| existing == target)
                        {
                            return Err(usage_error());
                        }
                        targets.push(target.to_owned());
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

fn print_result(value: &serde_json::Value) -> Result<i32> {
    println!(
        "{}",
        serde_json::to_string_pretty(value).map_err(|_| usage_error())?
    );
    Ok(
        if value.get("passed").and_then(serde_json::Value::as_bool) == Some(false) {
            1
        } else {
            0
        },
    )
}

fn run_distribution(operation: &str, targets: &[String], dry_run: bool) -> Result<i32> {
    let service = Service::from_environment()?;
    if matches!(operation, "check" | "doctor") {
        for target in targets {
            atm_core::tool_catalog::find(target)?;
        }
        return print_result(&service.diagnose()?);
    }
    let plan = service.plan(operation, targets)?;
    if dry_run {
        print_result(&serde_json::to_value(plan).map_err(|_| usage_error())?)
    } else {
        print_result(&service.apply(plan)?)
    }
}

fn install_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--to", "--name", "--harness", "--dry-run"])?;
    if !parsed.harness.is_empty() {
        if !parsed.positionals.is_empty()
            || value_of(&parsed, "--to").is_some()
            || value_of(&parsed, "--name").is_some()
        {
            return Err(usage_error());
        }
        return run_distribution("install", &parsed.harness, has_flag(&parsed, "--dry-run"));
    }
    if parsed.positionals.len() > 1 || has_flag(&parsed, "--dry-run") {
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
    let parsed = parse(rest, &["--harness", "--dry-run"])?;
    if !parsed.harness.is_empty() {
        if !parsed.positionals.is_empty() {
            return Err(usage_error());
        }
        return run_distribution("remove", &parsed.harness, has_flag(&parsed, "--dry-run"));
    }
    if has_flag(&parsed, "--dry-run") {
        return Err(usage_error());
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
    let service = Service::from_environment()?;
    match kind {
        "install" => print_result(&service.hooks(true, has_flag(&parsed, "--dry-run"))?),
        "uninstall" => print_result(&service.hooks(false, has_flag(&parsed, "--dry-run"))?),
        _ => print_result(&service.check_hooks()?),
    }
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
        return run_distribution(operation, &parsed.harness, false);
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
    let parsed = parse(rest, &["--force", "--harness", "--dry-run"])?;
    if !parsed.harness.is_empty() {
        if !parsed.positionals.is_empty() {
            return Err(usage_error());
        }
        if has_flag(&parsed, "--force") {
            return Err(usage_error());
        }
        return run_distribution("refresh", &parsed.harness, has_flag(&parsed, "--dry-run"));
    }
    let name = parsed.positionals.first().map(String::as_str);
    if parsed.positionals.len() > 1 || has_flag(&parsed, "--dry-run") {
        return Err(usage_error());
    }
    let items = registry()?.refresh(name, has_flag(&parsed, "--force"))?;
    report_checks(&items);
    finish_checks(&items)
}

fn repair_skills(rest: &[String]) -> Result<i32> {
    let parsed = parse(rest, &["--harness", "--dry-run"])?;
    if !parsed.positionals.is_empty() || parsed.harness.is_empty() {
        return Err(usage_error());
    }
    run_distribution("repair", &parsed.harness, has_flag(&parsed, "--dry-run"))
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

fn distribution_service(parsed: &Parsed) -> Result<Service> {
    let manager = match value_of(parsed, "--home") {
        Some(path) if Path::new(&path).is_absolute() => PathBuf::from(path),
        Some(_) => return Err(usage_error()),
        None => harness::manager_home_from_environment()?,
    };
    let user = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(usage_error)?;
    Service::new(manager, user).map(Service::with_environment)
}

fn selected_source(parsed: &Parsed) -> Result<PathBuf> {
    match value_of(parsed, "--source") {
        Some(path) if Path::new(&path).is_absolute() => Ok(PathBuf::from(path)),
        Some(_) => Err(usage_error()),
        None => source::locate(),
    }
}

fn dispatch_harness(rest: &[String]) -> Result<i32> {
    harness_embed::bound_engine_args(rest)?;
    let (subcommand, rest) = match rest.split_first() {
        Some((subcommand, rest)) => (subcommand.as_str(), rest),
        None => {
            println!("{USAGE}");
            return Ok(0);
        }
    };
    if subcommand == "--" {
        return dispatch_harness_namespace(rest);
    }
    if subcommand == "runtime" {
        return prepare_runtime(rest);
    }
    if subcommand == "migrate" {
        let parsed = parse(
            rest,
            &[
                "--home",
                "--to",
                "--source",
                "--python",
                "--offline",
                "--dry-run",
            ],
        )?;
        if !parsed.positionals.is_empty() {
            return Err(usage_error());
        }
        let destination = PathBuf::from(value_of(&parsed, "--to").ok_or_else(usage_error)?);
        if !destination.is_absolute() {
            return Err(usage_error());
        }
        let service = distribution_service(&parsed)?;
        let plan = service.plan_relocation(&destination, &selected_source(&parsed)?)?;
        if has_flag(&parsed, "--dry-run") {
            return print_result(&serde_json::to_value(plan).map_err(|_| usage_error())?);
        }
        let python = value_of(&parsed, "--python").map(PathBuf::from);
        return print_result(&service.relocate(
            plan,
            python.as_deref(),
            has_flag(&parsed, "--offline"),
        )?);
    }
    if matches!(subcommand, "export" | "fetch" | "import") {
        return content_operation(subcommand, rest);
    }
    if subcommand == "plan" {
        let parsed = parse(rest, &["--home", "--harness"])?;
        let [operation] = parsed.positionals.as_slice() else {
            return Err(usage_error());
        };
        if !matches!(
            operation.as_str(),
            "install" | "refresh" | "remove" | "repair"
        ) || parsed.harness.is_empty()
        {
            return Err(usage_error());
        }
        let plan = distribution_service(&parsed)?.plan(operation, &parsed.harness)?;
        return print_result(&serde_json::to_value(plan).map_err(|_| usage_error())?);
    }
    let options: &[&str] = match subcommand {
        "bootstrap" | "sync" => &["--home", "--source", "--json"],
        "adopt" => &[
            "--home",
            "--source",
            "--json",
            "--dry-run",
            "--retire-missing",
        ],
        "status" | "recover" => &["--home", "--json"],
        "verify-source" => &["--source", "--json"],
        _ => {
            return Err(Error::new(
                "CLI_COMMAND",
                "未知 harness 子命令；请查看 atm help。",
            ))
        }
    };
    let parsed = parse(rest, options)?;
    if !parsed.positionals.is_empty() {
        return Err(usage_error());
    }
    if subcommand == "verify-source" {
        let bundle = source::load(&selected_source(&parsed)?)?;
        return print_result(
            &serde_json::json!({"identity":bundle.identity,"releaseVersion":bundle.release,"files":bundle.files.len()}),
        );
    }
    let service = distribution_service(&parsed)?;
    let value = match subcommand {
        "adopt" if has_flag(&parsed, "--dry-run") => {
            service.preview_adopt(&selected_source(&parsed)?, &parsed.retire_missing)?
        }
        "adopt" => service.adopt(&selected_source(&parsed)?, &parsed.retire_missing)?,
        "bootstrap" | "sync" => service.bootstrap(&selected_source(&parsed)?, false)?,
        "status" => service.status()?,
        "recover" => service.recover()?,
        _ => unreachable!(),
    };
    print_result(&value)
}

fn content_operation(operation: &str, args: &[String]) -> Result<i32> {
    let options: &[&str] = match operation {
        "export" => &[
            "--source",
            "--output",
            "--repository",
            "--revision",
            "--url",
            "--composition",
        ],
        "fetch" => &["--lock", "--output"],
        "import" => &["--lock", "--archive", "--home"],
        _ => unreachable!(),
    };
    let parsed = parse(args, options)?;
    if !parsed.positionals.is_empty() {
        return Err(usage_error());
    }
    let required = |key: &str| value_of(&parsed, key).ok_or_else(usage_error);
    let path = |key: &str| -> Result<PathBuf> {
        let path = PathBuf::from(required(key)?);
        if !path.is_absolute() {
            return Err(usage_error());
        }
        Ok(path)
    };
    if operation == "export" {
        return print_result(&source::hub::export(
            &path("--source")?,
            &path("--output")?,
            &required("--repository")?,
            &required("--revision")?,
            &required("--url")?,
            &value_of(&parsed, "--composition").unwrap_or_else(|| "default".into()),
        )?);
    }
    let lock = source::hub::read_lock(&path("--lock")?)?;
    if operation == "fetch" {
        let output = path("--output")?;
        let bundle = source::hub::fetch(&lock, &output)?;
        return print_result(
            &serde_json::json!({"source":output,"contentIdentity":bundle.identity,"releaseVersion":bundle.release}),
        );
    }
    let archive = value_of(&parsed, "--archive").map(PathBuf::from);
    print_result(&distribution_service(&parsed)?.import_content(&lock, archive.as_deref())?)
}

/// The old `harness --` namespace accepts a bounded set of Rust operations.
/// No arbitrary process, Python script, or legacy machine protocol is reachable.
fn dispatch_harness_namespace(rest: &[String]) -> Result<i32> {
    let (operation, args) = rest.split_first().ok_or_else(usage_error)?;
    if operation == "status" {
        let parsed = parse(args, &["--json"])?;
        if !parsed.positionals.is_empty() {
            return Err(usage_error());
        }
        return print_result(&Service::from_environment()?.status()?);
    }
    if !matches!(
        operation.as_str(),
        "install" | "refresh" | "remove" | "repair" | "check" | "doctor"
    ) {
        return Err(Error::new(
            "CLI_COMMAND",
            "该旧引擎命令已退役；请使用 atm help 列出的 Rust 命令。",
        ));
    }
    let parsed = parse(args, &["--harness", "--dry-run", "--yes", "--json"])?;
    let targets = if parsed.harness.is_empty() {
        &parsed.positionals
    } else {
        if !parsed.positionals.is_empty() {
            return Err(usage_error());
        }
        &parsed.harness
    };
    if targets.is_empty() && !matches!(operation.as_str(), "check" | "doctor") {
        return Err(usage_error());
    }
    run_distribution(operation, targets, has_flag(&parsed, "--dry-run"))
}

fn prepare_runtime(rest: &[String]) -> Result<i32> {
    let parsed = parse(
        rest,
        &[
            "--home",
            "--python",
            "--external-venv",
            "--offline",
            "--json",
        ],
    )?;
    let [verb, group] = parsed.positionals.as_slice() else {
        return Err(usage_error());
    };
    if verb != "prepare" {
        return Err(usage_error());
    }
    let python = value_of(&parsed, "--python")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(usage_error)?;
    let external = value_of(&parsed, "--external-venv").map(PathBuf::from);
    if external.as_ref().is_some_and(|path| !path.is_absolute()) {
        return Err(usage_error());
    }
    print_result(&distribution_service(&parsed)?.prepare_runtime(
        group,
        &python,
        external.as_deref(),
        has_flag(&parsed, "--offline"),
    )?)
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
                "engine_managed" => "内置分发管理",
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
