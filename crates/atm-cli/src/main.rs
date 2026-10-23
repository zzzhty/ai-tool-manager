//! `atm` command line: bounded, scriptable access to the local skill manager.
//! Same atm-core implementation as the GUI; no network, no polling, no
//! secret-store access (keys never appear on this surface).
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
        Ok(()) => 0,
        Err(error) => {
            eprintln!("error: {}: {}", error.code, error.message);
            1
        }
    }
}

const USAGE: &str = "用法:
  atm skills inventory [--json]
  atm skills publish <SOURCE_DIR> --name <NAME> --to <ROOT>[,<ROOT>...]
  atm skills project <NAME> --to <ROOT>
  atm skills unproject <NAME> --from <ROOT> [--force]
  atm skills check [NAME] [--json]
  atm skills refresh [NAME] [--force]
  atm skills unpublish <NAME> [--with-projections]
  atm skills install <SOURCE_DIR> <ROOT> [NAME]
  atm skills uninstall <ROOT> <NAME>
  atm skills copy <SRC_ROOT> <NAME> <DST_ROOT>
  atm skills trash [--json]
  atm skills restore <TRASH_ID>
  atm skills purge <TRASH_ID>
  atm help";

fn dispatch(arguments: &[String]) -> Result<()> {
    let (command, rest) = match arguments.split_first() {
        Some((command, rest)) => (command.as_str(), rest),
        None => {
            println!("{USAGE}");
            return Ok(());
        }
    };
    if command == "help" || command == "--help" || command == "-h" {
        if !rest.is_empty() {
            return Err(usage_error());
        }
        println!("{USAGE}");
        return Ok(());
    }
    if command != "skills" {
        return Err(Error::new("CLI_COMMAND", "未知命令；目前仅支持 skills。"));
    }
    let (subcommand, rest) = rest.split_first().ok_or_else(usage_error)?;
    let subcommand = subcommand.as_str();
    // Validate the complete command before constructing services or touching
    // disk. In particular, a misplaced flag must never broaden a named action.
    let (minimum, maximum, options): (usize, usize, &[&str]) = match subcommand {
        "inventory" | "trash" => (0, 0, &["--json"]),
        "check" => (0, 1, &["--json"]),
        "refresh" => (0, 1, &["--force"]),
        "publish" => (1, 1, &["--name", "--to"]),
        "project" => (1, 1, &["--to"]),
        "unproject" => (1, 1, &["--from", "--force"]),
        "unpublish" => (1, 1, &["--with-projections"]),
        "install" => (2, 3, &[]),
        "uninstall" => (2, 2, &[]),
        "copy" => (3, 3, &[]),
        "restore" | "purge" => (1, 1, &[]),
        other => {
            return Err(Error::new(
                "CLI_COMMAND",
                Box::leak(format!("未知 skills 子命令：{other}。").into_boxed_str()),
            ));
        }
    };
    let mut positionals: Vec<String> = Vec::new();
    let mut force = false;
    let mut with_projections = false;
    let mut json = false;
    let mut name: Option<String> = None;
    let mut to: Vec<String> = Vec::new();
    let mut seen_options = Vec::new();
    let mut index = 0;
    while index < rest.len() {
        let argument = rest[index].as_str();
        if argument.starts_with('-') {
            if !options.contains(&argument) || seen_options.contains(&argument) {
                return Err(usage_error());
            }
            seen_options.push(argument);
        }
        match argument {
            "--force" => force = true,
            "--with-projections" => with_projections = true,
            "--json" => json = true,
            "--name" => {
                name = Some(value_after(rest, &mut index, "--name")?);
            }
            "--to" => {
                let raw = value_after(rest, &mut index, "--to")?;
                for target in raw.split(',').map(str::trim) {
                    if target.is_empty() || to.iter().any(|existing| existing == target) {
                        return Err(usage_error());
                    }
                    to.push(target.to_owned());
                }
            }
            "--from" => {
                to.push(value_after(rest, &mut index, "--from")?);
            }
            other => positionals.push(other.to_owned()),
        }
        index += 1;
    }
    if !(minimum..=maximum).contains(&positionals.len())
        || positionals.iter().any(|value| value.is_empty())
        || (subcommand == "publish" && (name.is_none() || to.is_empty()))
        || (matches!(subcommand, "project" | "unproject") && to.len() != 1)
    {
        return Err(usage_error());
    }
    match subcommand {
        "inventory" => inventory(json),
        "check" => check_all(positionals.first().map(String::as_str), json),
        "refresh" => refresh(positionals.first().map(String::as_str), force),
        "publish" => {
            let source = positionals.first().ok_or_else(usage_error)?;
            let name = name.ok_or_else(|| Error::new("CLI_ARGUMENT", "publish 需要 --name。"))?;
            publish(PathBuf::from(source), &name, &to)
        }
        "project" => {
            let name = positionals.first().ok_or_else(usage_error)?;
            let target = to
                .first()
                .ok_or_else(|| Error::new("CLI_ARGUMENT", "project 需要 --to。"))?;
            let registry = ProjectionRegistry::from_environment()?;
            let projected = registry.project(name, target)?;
            println!("已投影：{projected}");
            Ok(())
        }
        "unproject" => {
            let name = positionals.first().ok_or_else(usage_error)?;
            let target = to
                .first()
                .ok_or_else(|| Error::new("CLI_ARGUMENT", "unproject 需要 --from。"))?;
            let registry = ProjectionRegistry::from_environment()?;
            registry.unproject(name, target, force)?;
            println!("已撤除投影：{target}/{name}");
            Ok(())
        }
        "unpublish" => {
            let name = positionals.first().ok_or_else(usage_error)?;
            let registry = ProjectionRegistry::from_environment()?;
            let torn = registry.unpublish(name, with_projections)?;
            println!("已发布源 {name} 移除；撤除投影 {} 项。", torn.len());
            Ok(())
        }
        "install" => {
            let (source, root, name) = install_args(&positionals)?;
            let service = SkillsService::from_environment()?;
            let installed = service.install(Path::new(&source), &root, &name)?;
            println!("已安装：{installed}");
            Ok(())
        }
        "uninstall" => {
            let (root, name) = two(&positionals)?;
            let service = SkillsService::from_environment()?;
            let trash = service.uninstall(&root, &name)?;
            println!("已卸载到保管区：{trash}");
            Ok(())
        }
        "copy" => {
            let (source_root, name, target_root) = three(&positionals)?;
            let service = SkillsService::from_environment()?;
            let copied = service.copy_to(&source_root, &name, &target_root)?;
            println!("已复制：{copied}");
            Ok(())
        }
        "trash" => trash(json),
        "restore" => {
            let id = positionals.first().ok_or_else(usage_error)?;
            let service = SkillsService::from_environment()?;
            let restored = service.restore(id)?;
            println!("已恢复：{restored}");
            Ok(())
        }
        "purge" => {
            let id = positionals.first().ok_or_else(usage_error)?;
            let service = SkillsService::from_environment()?;
            service.purge(id)?;
            println!("已彻底删除：{id}");
            Ok(())
        }
        other => Err(Error {
            code: "CLI_COMMAND",
            message: Box::leak(format!("未知 skills 子命令：{other}。").into_boxed_str()),
        }),
    }
}

fn usage_error() -> Error {
    Error::new("CLI_ARGUMENT", "参数不足或无效；请查看 atm help。")
}

fn value_after(rest: &[String], index: &mut usize, flag: &str) -> Result<String> {
    *index += 1;
    rest.get(*index)
        .filter(|value| !value.trim().is_empty() && !value.starts_with('-'))
        .cloned()
        .ok_or_else(|| {
            Error::new(
                "CLI_ARGUMENT",
                Box::leak(format!("{flag} 缺少值。").into_boxed_str()),
            )
        })
}

fn two(positionals: &[String]) -> Result<(String, String)> {
    match positionals {
        [first, second] => Ok((first.clone(), second.clone())),
        _ => Err(usage_error()),
    }
}

fn three(positionals: &[String]) -> Result<(String, String, String)> {
    match positionals {
        [first, second, third] => Ok((first.clone(), second.clone(), third.clone())),
        _ => Err(usage_error()),
    }
}

fn install_args(positionals: &[String]) -> Result<(String, String, String)> {
    match positionals {
        [source, root, name] => Ok((source.clone(), root.clone(), name.clone())),
        [source, root] => {
            let name = std::path::Path::new(&source)
                .file_name()
                .map(|value| value.to_string_lossy().into_owned())
                .ok_or_else(usage_error)?;
            Ok((source.clone(), root.clone(), name))
        }
        _ => Err(usage_error()),
    }
}

fn service() -> Result<SkillsService> {
    SkillsService::from_environment()
}

fn registry() -> Result<ProjectionRegistry> {
    ProjectionRegistry::from_environment()
}

fn publish(source: PathBuf, name: &str, targets: &[String]) -> Result<()> {
    let projected = registry()?.publish(&source, name, targets)?;
    for item in projected {
        println!("已投影：{item}");
    }
    Ok(())
}

fn refresh(name: Option<&str>, force: bool) -> Result<()> {
    let items = registry()?.refresh(name, force)?;
    report_checks(&items);
    finish_checks(&items)
}

fn check_all(name: Option<&str>, json: bool) -> Result<()> {
    let items = registry()?.check(name)?;
    if json {
        println!(
            "{}",
            serde_json::to_string_pretty(&items).unwrap_or_default()
        );
        return finish_checks(&items);
    }
    report_checks(&items);
    finish_checks(&items)?;
    println!("全部投影正常。");
    Ok(())
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

fn finish_checks(items: &[CheckItem]) -> Result<()> {
    if items.iter().all(|item| item.status == "ok") {
        Ok(())
    } else {
        Err(Error::new(
            "PROJECTION_BROKEN",
            "存在断链或被修改的投影；可用 refresh 修复（被修改副本需 --force 覆盖）。",
        ))
    }
}

fn inventory(json: bool) -> Result<()> {
    let snapshot = service()?.inventory()?;
    if json {
        println!(
            "{}",
            serde_json::to_string_pretty(&snapshot).unwrap_or_default()
        );
        return Ok(());
    }
    for root in &snapshot.roots {
        if !root.exists {
            println!("{:<12} 根不存在  {}", root.id, root.path);
            continue;
        }
        println!("{:<12} {} 项  {}", root.id, root.entries.len(), root.path);
        for entry in &root.entries {
            let kind = match entry.kind {
                "omh_managed" => "OMH 管理",
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
    Ok(())
}

fn trash(json: bool) -> Result<()> {
    let snapshot = service()?.inventory()?;
    if json {
        println!(
            "{}",
            serde_json::to_string_pretty(&snapshot.trash).unwrap_or_default()
        );
        return Ok(());
    }
    if snapshot.trash.is_empty() {
        println!("保管区为空。");
        return Ok(());
    }
    for item in &snapshot.trash {
        println!("{}  原 {}", item.id, item.origin_path);
    }
    Ok(())
}
