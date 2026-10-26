//! Pure Codex hook config planning. Receipt evidence, not a name prefix, grants ownership.
use super::{runtime::PreparedRuntime, Artifact};
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

pub const EVENTS: [&str; 4] = ["SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"];
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HookOwnership {
    pub schema_version: u32,
    pub owner: String,
    pub target: PathBuf,
    pub groups: BTreeMap<String, Value>,
    pub runtime: PreparedRuntime,
    pub bundle_root: PathBuf,
    pub hooks_preexisted: bool,
    pub preserved_empty_events: Vec<String>,
}
#[derive(Debug, Clone)]
pub struct HookPlan {
    pub artifact: Option<Artifact>,
    pub ownership: Option<HookOwnership>,
}
fn invalid() -> Error {
    Error::new(
        "HARNESS_HOOK_CONFIG",
        "hooks.json 或 hook ownership 无效；未更改配置。",
    )
}
fn conflict() -> Error {
    Error::new(
        "HARNESS_HOOK_CONFLICT",
        "Watcher hook 已被用户修改或存在无收据的同名条目；未覆盖或删除。",
    )
}

/// Codex accepts a command string, so quote every argument for its platform.
/// Windows shell-expansion metacharacters are rejected instead of ambiguously
/// interpreting them. Unicode, spaces, apostrophes and backslashes are supported.
pub fn command_line(args: &[String], windows: bool) -> Result<String> {
    if args.is_empty() || args.iter().any(|arg| arg.chars().any(char::is_control)) {
        return Err(invalid());
    }
    if !windows {
        return Ok(args
            .iter()
            .map(|arg| format!("'{}'", arg.replace('\'', "'\\''")))
            .collect::<Vec<_>>()
            .join(" "));
    }
    let mut quoted = Vec::new();
    for arg in args {
        if arg
            .chars()
            .any(|c| matches!(c, '%' | '!' | '^' | '&' | '|' | '<' | '>' | '"'))
        {
            return Err(invalid());
        }
        let mut result = String::from("\"");
        let mut slashes = 0;
        for c in arg.chars() {
            if c == '\\' {
                slashes += 1;
            } else {
                result.push_str(&"\\".repeat(slashes));
                slashes = 0;
                result.push(c);
            }
        }
        result.push_str(&"\\".repeat(slashes * 2));
        result.push('"');
        quoted.push(result);
    }
    Ok(quoted.join(" "))
}
fn watcher_like(group: &Value) -> bool {
    group
        .get("hooks")
        .and_then(Value::as_array)
        .is_some_and(|handlers| {
            handlers.iter().any(|handler| {
                let status = handler
                    .get("statusMessage")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                let command = handler.get("command").and_then(Value::as_str).unwrap_or("");
                status.starts_with("Watcher skill:")
                    || status.starts_with("Skill Watcher:")
                    || command.contains("codex_hook_adapter.py")
            })
        })
}
fn validate(value: &Value) -> Result<()> {
    if !value.is_object() {
        return Err(invalid());
    }
    if let Some(hooks) = value.get("hooks") {
        let hooks = hooks.as_object().ok_or_else(invalid)?;
        for groups in hooks.values() {
            for group in groups.as_array().ok_or_else(invalid)? {
                if !group.is_object() || group.get("hooks").is_some_and(|value| !value.is_array()) {
                    return Err(invalid());
                }
            }
        }
    }
    Ok(())
}

/// Plan an explicitly requested enable/disable. This never runs a payload or
/// writes a config. Caller journals artifact and ownership in one transaction.
pub fn plan(
    target: &Path,
    current: Option<&[u8]>,
    previous: Option<&HookOwnership>,
    enable: bool,
    runtime: Option<&PreparedRuntime>,
    bundle_root: &Path,
) -> Result<HookPlan> {
    if !target.is_absolute() || !bundle_root.is_absolute() {
        return Err(invalid());
    }
    let before: Value = match current {
        Some(bytes) => serde_json::from_slice(bytes).map_err(|_| invalid())?,
        None => json!({}),
    };
    validate(&before)?;
    let hooks_preexisted =
        previous.map_or(before.get("hooks").is_some(), |old| old.hooks_preexisted);
    let preserved_empty_events = previous
        .map(|old| old.preserved_empty_events.clone())
        .unwrap_or_else(|| {
            before
                .get("hooks")
                .and_then(Value::as_object)
                .map(|events| {
                    events
                        .iter()
                        .filter_map(|(event, groups)| {
                            groups
                                .as_array()
                                .is_some_and(Vec::is_empty)
                                .then_some(event.clone())
                        })
                        .collect()
                })
                .unwrap_or_default()
        });
    let mut after = before.clone();
    if let Some(previous) = previous {
        if previous.schema_version != 1
            || previous.owner != "atm-harness:watcher"
            || previous.target != target
            || !previous.bundle_root.is_absolute()
            || previous.groups.len() != EVENTS.len()
            || EVENTS
                .iter()
                .any(|event| !previous.groups.contains_key(*event))
        {
            return Err(invalid());
        }
        for (event, expected) in &previous.groups {
            let groups = after
                .get_mut("hooks")
                .and_then(|v| v.get_mut(event))
                .and_then(Value::as_array_mut)
                .ok_or_else(conflict)?;
            let matches: Vec<_> = groups
                .iter()
                .enumerate()
                .filter_map(|(i, g)| (g == expected).then_some(i))
                .collect();
            if matches.len() != 1 {
                return Err(conflict());
            }
            groups.remove(matches[0]);
        }
    }
    if after
        .get("hooks")
        .and_then(Value::as_object)
        .is_some_and(|events| {
            events.values().any(|groups| {
                groups
                    .as_array()
                    .is_some_and(|groups| groups.iter().any(watcher_like))
            })
        })
    {
        return Err(conflict());
    }
    let ownership = if enable {
        let runtime = runtime.ok_or_else(invalid)?;
        if runtime.id != "watcher" || !runtime.python.is_absolute() {
            return Err(invalid());
        }
        let script = bundle_root.join("runtimes/watcher/scripts/watcher");
        let args = vec![
            runtime.python.to_string_lossy().into_owned(),
            "-B".into(),
            script.to_string_lossy().into_owned(),
            "skill".into(),
            "observe".into(),
            "--repo-root".into(),
            bundle_root.to_string_lossy().into_owned(),
        ];
        let command = command_line(&args, cfg!(windows))?;
        let mut owned = BTreeMap::new();
        let root = after.as_object_mut().ok_or_else(invalid)?;
        let hooks = root
            .entry("hooks")
            .or_insert_with(|| json!({}))
            .as_object_mut()
            .ok_or_else(invalid)?;
        for event in EVENTS {
            let group = json!({"hooks":[{"type":"command","async":false,"command":command,"timeoutSec":10,"statusMessage":format!("Watcher skill: observe {event}")}]});
            hooks
                .entry(event)
                .or_insert_with(|| json!([]))
                .as_array_mut()
                .ok_or_else(invalid)?
                .push(group.clone());
            owned.insert(event.to_owned(), group);
        }
        Some(HookOwnership {
            schema_version: 1,
            owner: "atm-harness:watcher".into(),
            target: target.to_path_buf(),
            groups: owned,
            runtime: runtime.clone(),
            bundle_root: bundle_root.to_path_buf(),
            hooks_preexisted,
            preserved_empty_events: preserved_empty_events.clone(),
        })
    } else {
        None
    };
    if let Some(hooks) = after.get_mut("hooks").and_then(Value::as_object_mut) {
        if previous.is_some() {
            hooks.retain(|event, groups| {
                !EVENTS.contains(&event.as_str())
                    || preserved_empty_events.contains(event)
                    || !groups.as_array().is_some_and(Vec::is_empty)
            });
        }
        if hooks.is_empty() && !hooks_preexisted {
            after.as_object_mut().ok_or_else(invalid)?.remove("hooks");
        }
    }
    let artifact = if before == after {
        None
    } else {
        let mut bytes = serde_json::to_vec_pretty(&after).map_err(|_| invalid())?;
        bytes.push(b'\n');
        Some(Artifact {
            path: target.to_path_buf(),
            bytes,
        })
    };
    Ok(HookPlan {
        artifact,
        ownership,
    })
}
