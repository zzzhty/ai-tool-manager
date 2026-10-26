#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use atm::{template_store, usage_service::UsageService};
use atm_core::{
    batch::{BackupView, BatchUpdater, FileResult, Preview, PreviewView},
    harness::{self, HarnessStatusSnapshot},
    jsonc,
    skills::{SkillsInventoryView, SkillsService},
    storage,
    templates::{self, ApplicationIdentity, TemplateCandidate},
    usage::{
        self,
        glm::{self, PlanKind},
        Region, Snapshot as UsageSnapshot,
    },
    windows, Error, KeyView, TargetMapping, Vault,
};
use serde::{Deserialize, Serialize};
#[cfg(all(any(target_os = "linux", target_os = "macos"), feature = "smoke-tests"))]
use std::path::PathBuf;
use std::{
    collections::BTreeSet,
    path::Path,
    sync::{Arc, Mutex},
};
#[cfg(all(any(target_os = "linux", target_os = "macos"), feature = "smoke-tests"))]
use tauri::Manager;
use tauri::{State, WebviewWindow};
use tauri_plugin_dialog::DialogExt;
use template_store::{Assignment, TemplateStore};
use uuid::Uuid;
use zeroize::Zeroizing;

struct Service {
    vault: Vault,
    updater: BatchUpdater,
    preview: Option<Preview>,
    templates: TemplateStore,
    candidate: Option<TemplateCandidate>,
    usage: Arc<Mutex<UsageService>>,
    demo: bool,
}
impl Service {
    fn invalidate(&mut self) {
        if let Some(mut plan) = self.preview.take() {
            plan.cancel();
        }
    }
}
type AppState<'a> = State<'a, Mutex<Service>>;
fn authorized(window: &WebviewWindow) -> Result<(), Error> {
    let url = window
        .url()
        .map_err(|_| Error::new("UI_SCOPE", "无法确认本地界面来源。"))?;
    let local = (url.scheme() == "tauri" && url.host_str() == Some("localhost"))
        || (matches!(url.scheme(), "http" | "https") && url.host_str() == Some("tauri.localhost"));
    if window.label() != "main" || !local {
        return Err(Error::new("UI_SCOPE", "仅允许已打包的本地主窗口。"));
    }
    Ok(())
}
fn lock<'a>(state: &'a AppState<'_>) -> Result<std::sync::MutexGuard<'a, Service>, Error> {
    state
        .lock()
        .map_err(|_| Error::new("STATE_BUSY", "管理器状态不可用，请重新启动。"))
}
#[derive(Clone, Serialize, Deserialize)]
struct TargetView {
    #[serde(flatten)]
    target: TargetMapping,
    #[serde(rename = "TemplateId", default)]
    template_id: Option<Uuid>,
}
#[derive(Serialize)]
struct TemplateField {
    pointer: String,
    label: String,
    kind: &'static str,
}
#[derive(Serialize)]
struct TemplateView {
    id: Uuid,
    name: String,
    fields: Vec<TemplateField>,
}
#[derive(Serialize)]
struct DesktopSnapshot {
    keys: Vec<KeyView>,
    targets: Vec<TargetView>,
    templates: Vec<TemplateView>,
    #[serde(rename = "storageKind")]
    storage_kind: &'static str,
    demo: bool,
}
#[derive(Serialize)]
struct CandidateView {
    id: Uuid,
    name: String,
    fields: Vec<TemplateField>,
    schema: serde_json::Value,
    warnings: Vec<String>,
}
fn fields(template: &templates::Template) -> Vec<TemplateField> {
    template
        .bindings
        .iter()
        .map(|binding| TemplateField {
            pointer: binding.pointer.clone(),
            label: binding.name.clone(),
            kind: "string",
        })
        .collect()
}
#[tauri::command]
fn snapshot(window: WebviewWindow, state: AppState<'_>) -> Result<DesktopSnapshot, Error> {
    authorized(&window)?;
    let service = lock(&state)?;
    let snap = service.vault.snapshot();
    Ok(DesktopSnapshot {
        storage_kind: storage::kind(),
        demo: service.demo,
        keys: snap.keys,
        targets: snap
            .targets
            .into_iter()
            .map(|target| TargetView {
                template_id: service
                    .templates
                    .assignments
                    .get(&target.id)
                    .and_then(|a| a.template_id),
                target,
            })
            .collect(),
        templates: service
            .templates
            .templates
            .values()
            .map(|t| TemplateView {
                id: t.id,
                name: t.name.clone(),
                fields: fields(t),
            })
            .collect(),
    })
}
#[tauri::command]
fn save_key(
    window: WebviewWindow,
    state: AppState<'_>,
    id: Option<Uuid>,
    name: String,
    secret: String,
) -> Result<Uuid, Error> {
    // Wrap the caller-owned plaintext before any fallible operation.
    let secret = Zeroizing::new(secret);
    authorized(&window)?;
    let mut service = lock(&state)?;
    service.invalidate();
    service.vault.save_key(id, name, secret)
}
#[tauri::command]
fn delete_key(window: WebviewWindow, state: AppState<'_>, id: Uuid) -> Result<(), Error> {
    authorized(&window)?;
    let mut service = lock(&state)?;
    service.invalidate();
    service.vault.delete_key(id)
}
#[tauri::command]
fn save_target(
    window: WebviewWindow,
    state: AppState<'_>,
    mut target: TargetView,
) -> Result<Uuid, Error> {
    authorized(&window)?;
    let mut service = lock(&state)?;
    service.invalidate();
    if target.target.id.is_nil() {
        target.target.id = Uuid::new_v4();
    }
    target.target.file_path = windows::canonical(&target.target.file_path)?;
    target.target.pointer = jsonc::normalize(&target.target.pointer)?;
    if let Some(id) = target.template_id {
        let t = service
            .templates
            .templates
            .get(&id)
            .ok_or(Error::new("TEMPLATE_MISSING", "请选择已保存模板。"))?;
        templates::validate_template(t)?;
        if !t.write_allowlist.contains(&target.target.pointer) {
            return Err(Error::new(
                "TEMPLATE_ALLOWLIST",
                "所选字段不在模板写入白名单内。",
            ));
        }
    }
    // Metadata is durable before exposing the mapping. An interrupted pair either
    // retains an explicit user-selected binding or fails closed on mapping drift.
    let old = service.templates.clone();
    let mut next = old.clone();
    next.assignments.insert(
        target.target.id,
        Assignment {
            template_id: target.template_id,
            mapping: target.target.clone(),
        },
    );
    next.save(service.vault.directory())?;
    service.templates = next;
    match service.vault.save_target(target.target) {
        Ok(id) => Ok(id),
        Err(error) => {
            if old.save(service.vault.directory()).is_ok() {
                service.templates = old;
            }
            Err(error)
        }
    }
}
#[tauri::command]
fn delete_target(window: WebviewWindow, state: AppState<'_>, id: Uuid) -> Result<(), Error> {
    authorized(&window)?;
    let mut service = lock(&state)?;
    service.invalidate();
    service.vault.delete_target(id)?;
    let mut next = service.templates.clone();
    next.assignments.remove(&id);
    next.save(service.vault.directory())?;
    service.templates = next;
    Ok(())
}
#[tauri::command]
fn preview(
    window: WebviewWindow,
    state: AppState<'_>,
    selected: Vec<Uuid>,
) -> Result<PreviewView, Error> {
    authorized(&window)?;
    let mut service = lock(&state)?;
    service.invalidate();
    let snapshot = service.vault.snapshot();
    let mut per_file: Vec<(String, BTreeSet<Uuid>)> = Vec::new();
    let mut drift: Vec<(String, Error)> = Vec::new();
    // Every configured schema on a selected file remains active even when only
    // a different mapping on that file is selected. No schema bypass by checkbox.
    for target in &snapshot.targets {
        match service.templates.for_mapping(target) {
            Ok(Some(template)) => {
                if let Some((_, ids)) = per_file
                    .iter_mut()
                    .find(|(path, _)| windows::same_path(path, &target.file_path))
                {
                    ids.insert(template.id);
                } else {
                    per_file.push((target.file_path.clone(), BTreeSet::from([template.id])));
                }
            }
            Err(error) => drift.push((target.file_path.clone(), error)),
            Ok(None) => {}
        }
    }
    // Orphaned template bindings keep guarding their file; only an explicit
    // mapping/template removal may discard this file's prior guard.
    for assignment in service.templates.assignments.values() {
        if let Some(id) = assignment.template_id {
            if let Some((_, ids)) = per_file
                .iter_mut()
                .find(|(path, _)| windows::same_path(path, &assignment.mapping.file_path))
            {
                ids.insert(id);
            } else {
                per_file.push((assignment.mapping.file_path.clone(), BTreeSet::from([id])));
            }
        }
    }
    let plan = service.updater.preview_with_validator(
        &service.vault,
        &selected,
        |path, original, requests| {
            if let Some((_, error)) = drift
                .iter()
                .find(|(known, _)| windows::same_path(known, path))
            {
                return Err(*error);
            }
            let Some((_, ids)) = per_file
                .iter()
                .find(|(known, _)| windows::same_path(known, path))
            else {
                return jsonc::edit(original, requests);
            };
            if ids.len() != 1 {
                return Err(Error::new(
                    "TEMPLATE_AMBIGUOUS",
                    "同一文件绑定多个不同模板，请统一后重试。",
                ));
            }
            let id = ids
                .first()
                .ok_or(Error::new("TEMPLATE_MISSING", "模板不可用。"))?;
            let template = service
                .templates
                .templates
                .get(id)
                .ok_or(Error::new("TEMPLATE_MISSING", "模板不可用。"))?;
            templates::prepare_patch(template, original, requests)
        },
    );
    let view = plan.view();
    service.preview = Some(plan);
    Ok(view)
}
#[tauri::command]
fn apply_preview(
    window: WebviewWindow,
    state: AppState<'_>,
    id: Uuid,
    confirmed: bool,
) -> Result<Vec<FileResult>, Error> {
    authorized(&window)?;
    let mut service = lock(&state)?;
    if !confirmed {
        return Err(Error::new(
            "CONFIRM_REQUIRED",
            "须确认遮罩预览后才允许应用。",
        ));
    }
    if !service.preview.as_ref().is_some_and(|plan| plan.id == id) {
        return Err(Error::new("PREVIEW_EXPIRED", "预览已失效，请重新预览。"));
    }
    let mut plan = service
        .preview
        .take()
        .ok_or(Error::new("PREVIEW_EXPIRED", "预览已失效，请重新预览。"))?;
    service.updater.apply(&mut plan, id, true)
}
#[tauri::command]
fn cancel_preview(window: WebviewWindow, state: AppState<'_>) -> Result<(), Error> {
    authorized(&window)?;
    lock(&state)?.invalidate();
    Ok(())
}
#[tauri::command]
fn list_backups(window: WebviewWindow, state: AppState<'_>) -> Result<Vec<BackupView>, Error> {
    authorized(&window)?;
    lock(&state)?.updater.backups()
}
#[tauri::command]
fn preview_rollback(
    window: WebviewWindow,
    state: AppState<'_>,
    backup_path: String,
) -> Result<PreviewView, Error> {
    authorized(&window)?;
    let mut service = lock(&state)?;
    service.invalidate();
    let plan = service.updater.preview_rollback(&backup_path)?;
    let view = plan.view();
    service.preview = Some(plan);
    Ok(view)
}
#[tauri::command]
fn infer_template(
    window: WebviewWindow,
    state: AppState<'_>,
    file_path: String,
) -> Result<CandidateView, Error> {
    authorized(&window)?;
    let mut service = lock(&state)?;
    service.candidate = None;
    let original = windows::read_snapshot(&file_path)?;
    let filename = Path::new(&original.path)
        .file_name()
        .and_then(|v| v.to_str())
        .unwrap_or("config.json")
        .to_owned();
    let candidate = templates::infer_candidate(
        &original.bytes,
        ApplicationIdentity {
            id: "user-selected".into(),
            display_name: "用户选择的配置".into(),
            config_file_names: vec![filename],
        },
        "我的配置模板".into(),
    )?;
    let view = CandidateView {
        id: candidate.template.id,
        name: candidate.template.name.clone(),
        fields: fields(&candidate.template),
        schema: candidate.template.schema.clone(),
        warnings: candidate.warnings.clone(),
    };
    service.candidate = Some(candidate);
    Ok(view)
}
#[tauri::command]
fn save_template(
    window: WebviewWindow,
    state: AppState<'_>,
    candidate_id: Uuid,
    name: String,
    selected_pointers: Vec<String>,
    schema: Option<String>,
) -> Result<Uuid, Error> {
    authorized(&window)?;
    let mut service = lock(&state)?;
    if selected_pointers.is_empty() || selected_pointers.len() > 1024 {
        return Err(Error::new(
            "TEMPLATE_ALLOWLIST",
            "请选择 1–1024 个精确字段。",
        ));
    }
    let candidate = service
        .candidate
        .as_ref()
        .ok_or(Error::new("CANDIDATE_EXPIRED", "候选已失效，请重新提取。"))?;
    if candidate.template.id != candidate_id {
        return Err(Error::new("CANDIDATE_EXPIRED", "候选已失效，请重新提取。"));
    }
    let mut candidate = candidate.clone();
    for pointer in &selected_pointers {
        if !candidate
            .template
            .bindings
            .iter()
            .any(|b| b.pointer == *pointer)
        {
            return Err(Error::new(
                "TEMPLATE_ALLOWLIST",
                "只能选择候选中的现有字符串字段。",
            ));
        }
    }
    candidate.template.name = name;
    candidate.template.write_allowlist = selected_pointers;
    candidate
        .template
        .bindings
        .retain(|b| candidate.template.write_allowlist.contains(&b.pointer));
    if let Some(schema) = schema {
        if schema.len() > 128 * 1024 {
            return Err(Error::new("SCHEMA_LIMIT", "Schema 太大。"));
        }
        let edited = jsonc::parse_value(schema.as_bytes()).map_err(|_| {
            Error::new(
                "SCHEMA_INVALID",
                "Schema 必须为无重复字段的有效 JSON 对象。",
            )
        })?;
        if edited != candidate.template.schema {
            candidate.template.source.kind = templates::SchemaSourceKind::UserAuthored;
            candidate.template.source.version = "user-reviewed-v1".into();
        }
        candidate.template.schema = edited;
    }
    let template = templates::confirm_candidate(candidate, true)?;
    let id = template.id;
    let mut next = service.templates.clone();
    next.templates.insert(id, template);
    next.save(service.vault.directory())?;
    service.templates = next;
    service.candidate = None;
    service.invalidate();
    Ok(id)
}
#[tauri::command]
fn delete_template(window: WebviewWindow, state: AppState<'_>, id: Uuid) -> Result<(), Error> {
    authorized(&window)?;
    let mut service = lock(&state)?;
    let active_ids: BTreeSet<_> = service
        .vault
        .snapshot()
        .targets
        .into_iter()
        .map(|t| t.id)
        .collect();
    if service
        .templates
        .assignments
        .iter()
        .any(|(target_id, a)| active_ids.contains(target_id) && a.template_id == Some(id))
    {
        return Err(Error::new(
            "TEMPLATE_IN_USE",
            "请先取消使用此模板的映射绑定。",
        ));
    }
    let mut next = service.templates.clone();
    next.assignments.retain(|_, a| a.template_id != Some(id));
    if next.templates.remove(&id).is_none() {
        return Err(Error::new("TEMPLATE_MISSING", "模板不存在。"));
    }
    next.save(service.vault.directory())?;
    service.templates = next;
    service.invalidate();
    Ok(())
}
#[tauri::command]
async fn initialize_storage(
    window: WebviewWindow,
    state: AppState<'_>,
    confirmed: bool,
) -> Result<(), Error> {
    authorized(&window)?;
    if !confirmed {
        return Err(Error::new(
            "CONFIRM_REQUIRED",
            "须确认在系统安全存储中创建或连接应用主密钥。",
        ));
    }
    let (demo, directory) = {
        let service = lock(&state)?;
        (service.demo, service.vault.directory().to_path_buf())
    };
    if demo {
        return Ok(());
    }
    tauri::async_runtime::spawn_blocking(move || storage::initialize(&directory, true))
        .await
        .map_err(|_| Error::new("STATE_BUSY", "安全存储连接未能完成。"))?
}
#[tauri::command]
fn configure_codex_cli(
    window: WebviewWindow,
    state: AppState<'_>,
    cli_path: String,
    profile_path: String,
    confirmed: bool,
) -> Result<(), Error> {
    authorized(&window)?;
    let service = lock(&state)?;
    let mut usage = service
        .usage
        .lock()
        .map_err(|_| Error::new("STATE_BUSY", "额度服务状态不可用。"))?;
    usage.configure_codex(Path::new(&cli_path), Path::new(&profile_path), confirmed)
}
#[tauri::command]
fn disconnect_codex_cli(window: WebviewWindow, state: AppState<'_>) -> Result<(), Error> {
    authorized(&window)?;
    let service = lock(&state)?;
    service
        .usage
        .lock()
        .map_err(|_| Error::new("STATE_BUSY", "额度服务状态不可用。"))?
        .disconnect_codex();
    Ok(())
}
#[tauri::command]
async fn query_codex_usage(
    window: WebviewWindow,
    state: AppState<'_>,
    confirmed: bool,
) -> Result<UsageSnapshot, Error> {
    authorized(&window)?;
    if !confirmed {
        return Err(Error::new(
            "CONFIRM_REQUIRED",
            "须确认 CLI 联网与帐号使用。",
        ));
    }
    let (manager, demo) = {
        let service = lock(&state)?;
        (service.usage.clone(), service.demo)
    };
    if demo {
        let mut result = usage::codex::parse(
            &serde_json::json!({"rateLimits":{"primary":{"usedPercent":25,"windowDurationMins":300}}}),
            &serde_json::json!("plus"),
            chrono::Utc::now(),
        );
        result.source = "synthetic_demo".into();
        return Ok(result);
    }
    tauri::async_runtime::spawn_blocking(move || {
        manager
            .lock()
            .map_err(|_| Error::new("STATE_BUSY", "额度服务状态不可用。"))?
            .query_codex(true)
    })
    .await
    .map_err(|_| Error::new("STATE_BUSY", "CLI 查询未能完成。"))?
}
#[tauri::command]
async fn query_glm_usage(
    window: WebviewWindow,
    state: AppState<'_>,
    region: Region,
    plan_kind: PlanKind,
    key_id: Option<Uuid>,
    confirmed: bool,
) -> Result<UsageSnapshot, Error> {
    authorized(&window)?;
    if !confirmed {
        return Err(Error::new(
            "CONFIRM_REQUIRED",
            "须确认使用所选密钥连接官方额度服务。",
        ));
    }
    if !matches!(region, Region::China | Region::International) {
        return Err(Error::new("USAGE_REGION", "请选择 GLM 地区。"));
    }
    let (manager, demo, key, revision) = {
        let service = lock(&state)?;
        let (key, revision) = if plan_kind == PlanKind::Personal && !service.demo {
            let id = key_id.ok_or(Error::new("KEY_MISSING", "请选择命名密钥。"))?;
            let key = service.vault.usage_credential(id)?;
            let view = service
                .vault
                .snapshot()
                .keys
                .into_iter()
                .find(|k| k.id == id)
                .ok_or(Error::new("KEY_MISSING", "密钥已不存在。"))?;
            (key, format!("{}:{}", id, view.updated_utc))
        } else {
            (Zeroizing::new(String::new()), "no-credential".into())
        };
        (service.usage.clone(), service.demo, key, revision)
    };
    if demo {
        let mut result = usage::glm::parse(
            &serde_json::json!({"data":{"level":"pro","limits":[{"type":"TOKENS_LIMIT","unit":3,"number":1,"percentage":40}]}}),
            region,
            chrono::Utc::now(),
        );
        result.source = "synthetic_demo".into();
        return Ok(result);
    }
    tauri::async_runtime::spawn_blocking(move || {
        manager
            .lock()
            .map_err(|_| Error::new("STATE_BUSY", "额度服务状态不可用。"))?
            .query_glm(
                &mut glm::OfficialHttps,
                region,
                plan_kind,
                &revision,
                &key,
                true,
            )
    })
    .await
    .map_err(|_| Error::new("STATE_BUSY", "GLM 查询未能完成。"))?
}
#[tauri::command]
async fn harness_status(
    window: WebviewWindow,
    state: AppState<'_>,
) -> Result<HarnessStatusSnapshot, Error> {
    authorized(&window)?;
    let demo = lock(&state)?.demo;
    if demo {
        // Same recorded shape with TEST_ONLY values; no process is launched in demo mode.
        let snapshot = harness::parse(
            &serde_json::json!({
                "product": "atm-harness",
                "observation": "recorded-state-only",
                "stateKind": "recorded",
                "operation": null,
                "worktreeClean": null,
                "desiredHarnesses": ["codex", "claude-code"],
                "harnessReceipts": {
                    "codex": [{"harness": "codex", "status": "ready", "root": "TEST_ONLY/home/.codex", "releaseVersion": "0.0.0", "updatedAt": "2026-10-15T00:00:00Z"}],
                    "claude-code": [{"harness": "claude-code", "status": "ready", "root": "TEST_ONLY/home/.claude", "releaseVersion": "0.0.0", "updatedAt": "2026-10-15T00:00:00Z"}]
                },
                "manager": {"product": "atm-harness", "channel": "stable", "status": "ready", "releaseVersion": "0.0.0", "revision": "TEST_ONLY_REVISION", "repository": "TEST_ONLY"}
            }),
            "TEST_ONLY/.atm",
            "synthetic_demo",
        )?;
        return Ok(snapshot);
    }
    tauri::async_runtime::spawn_blocking(harness::query_from_environment)
        .await
        .map_err(|_| Error::new("STATE_BUSY", "atm-harness 状态查询未能完成。"))?
}
#[tauri::command]
async fn harness_diagnose(
    window: WebviewWindow,
    state: AppState<'_>,
    operation: String,
) -> Result<atm_core::harness_machine::Diagnostic, Error> {
    authorized(&window)?;
    if lock(&state)?.demo {
        return Err(demo_refusal());
    }
    tauri::async_runtime::spawn_blocking(move || atm_core::harness_machine::diagnose(&operation))
        .await
        .map_err(|_| Error::new("HARNESS_CLI_FAILED", "harness 诊断未完成。"))?
}
#[tauri::command]
async fn harness_capabilities(
    window: WebviewWindow,
    state: AppState<'_>,
) -> Result<atm_core::harness_machine::Capabilities, Error> {
    authorized(&window)?;
    if lock(&state)?.demo {
        return Err(demo_refusal());
    }
    tauri::async_runtime::spawn_blocking(atm_core::harness_machine::capabilities)
        .await
        .map_err(|_| Error::new("HARNESS_CLI_FAILED", "harness 能力查询未完成。"))?
}
#[tauri::command]
async fn harness_execute(
    window: WebviewWindow,
    state: AppState<'_>,
    operation: String,
    harnesses: Vec<String>,
    confirmed: bool,
) -> Result<(), Error> {
    authorized(&window)?;
    if lock(&state)?.demo {
        return Err(demo_refusal());
    }
    tauri::async_runtime::spawn_blocking(move || {
        atm_core::harness_machine::execute(&operation, &harnesses, confirmed)
    })
    .await
    .map_err(|_| {
        Error::new(
            "HARNESS_OPERATION_FAILED",
            "harness 操作未完成；请核对状态。",
        )
    })?
}
fn demo_refusal() -> Error {
    Error::new(
        "DEMO_READONLY",
        "演示模式不修改任何本机目录；请用真实模式管理技能。",
    )
}
#[tauri::command]
async fn skills_inventory(
    window: WebviewWindow,
    state: AppState<'_>,
) -> Result<SkillsInventoryView, Error> {
    authorized(&window)?;
    let demo = lock(&state)?.demo;
    if demo {
        use atm_core::skills::{SkillEntryView, SkillRootView, SkillTrashView};
        let demo_entry = |name: &str, kind: &'static str| SkillEntryView {
            name: name.to_owned(),
            kind,
            display_name: None,
            description: Some("TEST_ONLY 演示条目".into()),
            link_target: None,
        };
        return Ok(SkillsInventoryView {
            roots: vec![
                SkillRootView {
                    id: "claude-code",
                    label: "Claude Code",
                    path: "TEST_ONLY/home/.claude/skills".into(),
                    exists: true,
                    entries: vec![
                        SkillEntryView {
                            name: "demo-skill".into(),
                            kind: "directory",
                            display_name: Some("演示技能".into()),
                            description: Some("TEST_ONLY 演示条目".into()),
                            link_target: None,
                        },
                        SkillEntryView {
                            name: "managed".into(),
                            kind: "engine_managed",
                            display_name: None,
                            description: None,
                            link_target: Some("TEST_ONLY/home/.atm/repo/plugins/demo".into()),
                        },
                    ],
                },
                SkillRootView {
                    id: "codex",
                    label: "Codex",
                    path: "TEST_ONLY/home/.codex/skills".into(),
                    exists: true,
                    entries: vec![demo_entry("review-agent", "directory")],
                },
                SkillRootView {
                    id: "copilot",
                    label: "Copilot CLI / VS Code",
                    path: "TEST_ONLY/home/.copilot/skills".into(),
                    exists: false,
                    entries: vec![],
                },
                SkillRootView {
                    id: "zcode",
                    label: "Z Code",
                    path: "TEST_ONLY/home/.zcode/skills".into(),
                    exists: false,
                    entries: vec![],
                },
                SkillRootView {
                    id: "gemini-cli",
                    label: "Gemini CLI",
                    path: "TEST_ONLY/home/.gemini/skills".into(),
                    exists: false,
                    entries: vec![],
                },
                SkillRootView {
                    id: "opencode",
                    label: "OpenCode",
                    path: "TEST_ONLY/home/.config/opencode/skills".into(),
                    exists: false,
                    entries: vec![],
                },
                SkillRootView {
                    id: "openclaw",
                    label: "OpenClaw",
                    path: "TEST_ONLY/home/.openclaw/skills".into(),
                    exists: false,
                    entries: vec![],
                },
                SkillRootView {
                    id: "pi-agent",
                    label: "Pi Agent",
                    path: "TEST_ONLY/home/.pi/agent/skills".into(),
                    exists: false,
                    entries: vec![],
                },
            ],
            trash: vec![SkillTrashView {
                id: "zcode/old-demo".into(),
                root_id: "zcode".into(),
                name: "old-demo".into(),
                origin_path: "TEST_ONLY/.zcode/skills/old-demo".into(),
            }],
            manager_home: Some("TEST_ONLY/home/.atm".into()),
        });
    }
    tauri::async_runtime::spawn_blocking(|| {
        SkillsService::from_environment().and_then(|service| service.inventory())
    })
    .await
    .map_err(|_| Error::new("STATE_BUSY", "技能盘点未能完成。"))?
}
#[tauri::command]
async fn skills_install(
    window: WebviewWindow,
    state: AppState<'_>,
    source_path: String,
    root_id: String,
    name: String,
    confirmed: bool,
) -> Result<String, Error> {
    authorized(&window)?;
    if !confirmed {
        return Err(Error::new("CONFIRM_REQUIRED", "须先确认技能安装目标。"));
    }
    if lock(&state)?.demo {
        return Err(demo_refusal());
    }
    tauri::async_runtime::spawn_blocking(move || {
        SkillsService::from_environment()?.install(Path::new(&source_path), &root_id, &name)
    })
    .await
    .map_err(|_| Error::new("STATE_BUSY", "技能安装未能完成。"))?
}
#[tauri::command]
async fn skills_uninstall(
    window: WebviewWindow,
    state: AppState<'_>,
    root_id: String,
    name: String,
    confirmed: bool,
) -> Result<String, Error> {
    authorized(&window)?;
    if !confirmed {
        return Err(Error::new("CONFIRM_REQUIRED", "须先确认技能卸载。"));
    }
    if lock(&state)?.demo {
        return Err(demo_refusal());
    }
    tauri::async_runtime::spawn_blocking(move || {
        SkillsService::from_environment()?.uninstall(&root_id, &name)
    })
    .await
    .map_err(|_| Error::new("STATE_BUSY", "技能卸载未能完成。"))?
}
#[tauri::command]
async fn skills_restore(
    window: WebviewWindow,
    state: AppState<'_>,
    trash_id: String,
    confirmed: bool,
) -> Result<String, Error> {
    authorized(&window)?;
    if !confirmed {
        return Err(Error::new("CONFIRM_REQUIRED", "须先确认技能恢复。"));
    }
    if lock(&state)?.demo {
        return Err(demo_refusal());
    }
    tauri::async_runtime::spawn_blocking(move || {
        SkillsService::from_environment()?.restore(&trash_id)
    })
    .await
    .map_err(|_| Error::new("STATE_BUSY", "技能恢复未能完成。"))?
}
#[tauri::command]
async fn skills_purge(
    window: WebviewWindow,
    state: AppState<'_>,
    trash_id: String,
    confirmed: bool,
) -> Result<(), Error> {
    authorized(&window)?;
    if !confirmed {
        return Err(Error::new("CONFIRM_REQUIRED", "须先确认彻底删除。"));
    }
    if lock(&state)?.demo {
        return Err(demo_refusal());
    }
    tauri::async_runtime::spawn_blocking(move || {
        SkillsService::from_environment()?.purge(&trash_id)
    })
    .await
    .map_err(|_| Error::new("STATE_BUSY", "彻底删除未能完成。"))?
}
#[tauri::command]
async fn skills_copy(
    window: WebviewWindow,
    state: AppState<'_>,
    source_root: String,
    name: String,
    target_root: String,
    confirmed: bool,
) -> Result<String, Error> {
    authorized(&window)?;
    if !confirmed {
        return Err(Error::new("CONFIRM_REQUIRED", "须先确认跨根复制目标。"));
    }
    if lock(&state)?.demo {
        return Err(demo_refusal());
    }
    tauri::async_runtime::spawn_blocking(move || {
        SkillsService::from_environment()?.copy_to(&source_root, &name, &target_root)
    })
    .await
    .map_err(|_| Error::new("STATE_BUSY", "跨根复制未能完成。"))?
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct NativeSmokeEvidence {
    rendered_vault: bool,
    rendered_quota_ui: bool,
    rendered_harness_ui: bool,
    rendered_skills_ui: bool,
    unknown_visible: bool,
    demo_query_rendered: bool,
    resized: bool,
    confirmed_write: bool,
    confirmation_refused: bool,
    cancellation_refused: bool,
    duplicate_refused: bool,
    rollback_applied: bool,
    capability_denied: bool,
    demo_mutation_refused: bool,
}
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
enum NativeSmokePhase {
    Ready,
    AwaitingPermission,
    Preview,
    Applied,
    RolledBack,
    Quota,
    Harness,
    Skills,
    Finished,
    Failed,
}
#[tauri::command]
fn report_linux_smoke(
    window: WebviewWindow,
    state: AppState<'_>,
    evidence: NativeSmokeEvidence,
    phase: Option<NativeSmokePhase>,
) -> Result<bool, Error> {
    authorized(&window)?;
    if !lock(&state)?.demo {
        return Err(Error::new("SMOKE_SCOPE", "GUI 测试只允许假数据演示模式。"));
    }
    #[cfg(all(any(target_os = "linux", target_os = "macos"), feature = "smoke-tests"))]
    {
        if std::env::var("CI").as_deref() != Ok("true") {
            return Err(Error::new(
                "SMOKE_SCOPE",
                "原生测试必须运行在 CI 隔离演示环境。",
            ));
        }
        let root = PathBuf::from(
            std::env::var_os("ATM_GUI_TEST_ROOT")
                .ok_or(Error::new("SMOKE_SCOPE", "缺少隔离测试目录。"))?,
        );
        storage::ensure_directory(&root)?;
        let directory = lock(&state)?.vault.directory().to_path_buf();
        if !directory.starts_with(root.join("tmp")) {
            return Err(Error::new("SMOKE_SCOPE", "测试存储不在隔离目录。"));
        }
        let acl_denied = window
            .app_handle()
            .state::<std::sync::atomic::AtomicBool>()
            .load(std::sync::atomic::Ordering::SeqCst);
        if let Some(phase) = phase {
            // Only finite phase names/booleans, never JS errors or configuration.
            eprintln!("TEST_ONLY_NATIVE_SMOKE_PHASE={phase:?} aclDenied={acl_denied}");
            if matches!(phase, NativeSmokePhase::Failed) {
                std::fs::write(
                    root.join("result.json"),
                    serde_json::to_vec(&serde_json::json!({
                        "passed":false, "phase":"failed", "pid":std::process::id(),
                        "scope":"synthetic assertion or IPC failure; see finite phase markers",
                        "testedSha":std::env::var("ATM_TESTED_SHA").unwrap_or_default()
                    }))
                    .map_err(|_| Error::new("SMOKE_SCOPE", "无法记录失败结果。"))?,
                )?;
                window.app_handle().exit(1);
            }
            return Ok(acl_denied);
        }
        if !evidence.rendered_vault
            || !evidence.rendered_quota_ui
            || !evidence.rendered_harness_ui
            || !evidence.rendered_skills_ui
            || !evidence.unknown_visible
            || !evidence.demo_query_rendered
            || !evidence.resized
            || !evidence.confirmed_write
            || !evidence.confirmation_refused
            || !evidence.cancellation_refused
            || !evidence.duplicate_refused
            || !evidence.rollback_applied
            || !evidence.capability_denied
            || !acl_denied
            || !evidence.demo_mutation_refused
        {
            eprintln!("TEST_ONLY_NATIVE_SMOKE_REJECTED flags={evidence:?} aclDenied={acl_denied}");
            return Err(Error::new("SMOKE_SCOPE", "原生 GUI 测试条件不满足。"));
        }
        let service = lock(&state)?;
        let directory = service.vault.directory();
        if !directory.starts_with(root.join("tmp"))
            || std::fs::read(directory.join("synthetic.jsonc"))?.as_slice() != DEMO_CONFIG
            || service.updater.backups()?.len() != 2
        {
            return Err(Error::new("SMOKE_SCOPE", "假配置回滚或备份验证失败。"));
        }
        let result = serde_json::json!({
            "passed":true, "testedSha":std::env::var("ATM_TESTED_SHA").unwrap_or_default(),
            "renderedVault":evidence.rendered_vault, "renderedQuotaUi":evidence.rendered_quota_ui,
            "renderedHarnessUi":evidence.rendered_harness_ui, "renderedSkillsUi":evidence.rendered_skills_ui,
            "unknownVisible":evidence.unknown_visible, "demoQueryRendered":evidence.demo_query_rendered, "resized":evidence.resized,
            "confirmedWrite":evidence.confirmed_write, "confirmationRefused":evidence.confirmation_refused,
            "cancellationRefused":evidence.cancellation_refused, "duplicateRefused":evidence.duplicate_refused,
            "rollbackApplied":evidence.rollback_applied, "capabilityDenied":evidence.capability_denied,
            "demoMutationRefused":evidence.demo_mutation_refused,
            "pid":std::process::id(), "demoDirectory":directory,
            "incognito":window.app_handle().config().app.windows.iter().any(|config| config.label == "main" && config.incognito),
            "home":std::env::var("HOME").unwrap_or_default(), "temporaryDirectory":std::env::temp_dir(),
            "scope":"Native WebKit IPC: confirmed synthetic write, cancel/replay/ACL refusal and encrypted whole-file rollback",
            "platform":std::env::consts::OS, "architecture":std::env::consts::ARCH
        });
        std::fs::write(
            root.join("result.json"),
            serde_json::to_vec(&result)
                .map_err(|_| Error::new("SMOKE_SCOPE", "无法记录测试结果。"))?,
        )?;
        window.app_handle().exit(0);
        Ok(true)
    }
    #[cfg(not(all(any(target_os = "linux", target_os = "macos"), feature = "smoke-tests")))]
    {
        let _ = (evidence, phase);
        Err(Error::new("SMOKE_SCOPE", "此构建未启用本机 GUI 测试。"))
    }
}
#[cfg(all(any(target_os = "linux", target_os = "macos"), feature = "smoke-tests"))]
const NATIVE_SMOKE_SCRIPT: &str = include_str!("native_smoke.js");
const DEMO_CONFIG: &[u8] = b"{\r\n // Synthetic demonstration only\r\n \"apiKey\": \"FAKE_DEMO_OLD\",\r\n \"authorization\": \"Bearer ${env:DEMO_KEY}\",\r\n}\r\n";
fn context() -> tauri::Context<tauri::Wry> {
    // macOS embeds a single Info.plist symbol at this macro expansion site.
    tauri::generate_context!()
}
fn run() -> Result<(), Error> {
    let demo = std::env::args().skip(1).any(|arg| arg == "--demo");
    // Validate the synthetic test envelope before opening any vault or key store.
    #[cfg(all(any(target_os = "linux", target_os = "macos"), feature = "smoke-tests"))]
    if let Some(root) = std::env::var_os("ATM_GUI_TEST_ROOT") {
        let root = std::fs::canonicalize(root)?;
        if !demo || std::env::var("CI").as_deref() != Ok("true") {
            return Err(Error::new("SMOKE_SCOPE", "原生测试必须使用隔离演示模式。"));
        }
        for variable in ["HOME", "TMPDIR"] {
            let path = std::env::var_os(variable)
                .ok_or(Error::new("SMOKE_SCOPE", "缺少隔离测试环境。"))?;
            let path = std::fs::canonicalize(path)?;
            if !path.starts_with(&root) || path == root {
                return Err(Error::new("SMOKE_SCOPE", "测试环境不在隔离目录内。"));
            }
        }
    }
    let directory = if demo {
        std::env::temp_dir().join(format!("atm-demo-{}", Uuid::new_v4()))
    } else {
        storage::data_directory()?
    };
    let protector = if demo {
        storage::demo_protector()?
    } else {
        storage::system()
    };
    let mut vault = Vault::open_with_protector(&directory, protector.clone())?;
    if demo {
        let file = directory.join("synthetic.jsonc");
        std::fs::write(&file, DEMO_CONFIG)?;
        let key = vault.save_key(
            None,
            "演示密钥（假数据）".into(),
            Zeroizing::new("FAKE_DEMO_NEW".into()),
        )?;
        for (pointer, bearer) in [("/apiKey", false), ("/authorization", true)] {
            vault.save_target(TargetMapping {
                id: Uuid::nil(),
                label: format!("演示 {pointer}"),
                file_path: file.to_string_lossy().into_owned(),
                pointer: pointer.into(),
                key_id: key,
                bearer_prefix: bearer,
                replace_variables: false,
            })?;
        }
    }
    let templates = TemplateStore::load_with_protector(&directory, protector.clone())?;
    let updater = BatchUpdater::with_protector(vault.backup_directory(), protector);
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Mutex::new(Service {
            vault,
            updater,
            preview: None,
            templates,
            candidate: None,
            usage: Arc::new(Mutex::new(UsageService::default())),
            demo,
        }))
        .invoke_handler(tauri::generate_handler![
            snapshot,
            save_key,
            delete_key,
            save_target,
            delete_target,
            preview,
            apply_preview,
            cancel_preview,
            list_backups,
            preview_rollback,
            infer_template,
            save_template,
            delete_template,
            initialize_storage,
            configure_codex_cli,
            disconnect_codex_cli,
            query_codex_usage,
            query_glm_usage,
            harness_status,
            harness_capabilities,
            harness_diagnose,
            harness_execute,
            skills_inventory,
            skills_install,
            skills_uninstall,
            skills_restore,
            skills_purge,
            skills_copy,
            report_linux_smoke
        ]);
    #[cfg(all(any(target_os = "linux", target_os = "macos"), feature = "smoke-tests"))]
    let builder = builder
        .setup(|app| {
            if std::env::var("CI").as_deref() == Ok("true")
                && std::env::var_os("ATM_GUI_TEST_ROOT").is_some()
                && app.state::<Mutex<Service>>().lock().is_ok_and(|s| s.demo)
            {
                app.manage(std::sync::atomic::AtomicBool::new(false));
                let handle = app.handle().clone();
                // This bundled window has no capability: assert actual IPC ACL denial.
                let probe = tauri::WebviewWindowBuilder::new(
                    app,
                    "smoke-denied",
                    tauri::WebviewUrl::App("index.html".into()),
                )
                .visible(false)
                .incognito(true);
                // WebKitGTK reports the test receipt without navigating the custom protocol.
                #[cfg(target_os = "linux")]
                let probe = probe.on_document_title_changed(move |_, title| {
                    match title.as_str() {
                        "TEST_ONLY-acl-started" => {
                            eprintln!("TEST_ONLY_NATIVE_SMOKE_ACL_WINDOW=started");
                        }
                        "TEST_ONLY-acl-denied" => {
                            eprintln!("TEST_ONLY_NATIVE_SMOKE_ACL_WINDOW=denied-acknowledged");
                            handle
                                .state::<std::sync::atomic::AtomicBool>()
                                .store(true, std::sync::atomic::Ordering::SeqCst);
                        }
                        "TEST_ONLY-acl-unexpected" => {
                            eprintln!("TEST_ONLY_NATIVE_SMOKE_ACL_WINDOW=unexpected-response");
                        }
                        _ => {}
                    }
                });
                #[cfg(target_os = "macos")]
                let probe = probe.on_navigation(move |url| {
                    if url.path() == "/TEST_ONLY-acl-unexpected" {
                        eprintln!("TEST_ONLY_NATIVE_SMOKE_ACL_WINDOW=unexpected-response");
                        return false;
                    }
                    if url.path() == "/TEST_ONLY-acl-denied" {
                        eprintln!("TEST_ONLY_NATIVE_SMOKE_ACL_WINDOW=denied-acknowledged");
                        handle
                            .state::<std::sync::atomic::AtomicBool>()
                            .store(true, std::sync::atomic::Ordering::SeqCst);
                        return false;
                    }
                    true
                });
                probe.build()?;
            }
            Ok(())
        })
        .on_page_load(|webview, payload| {
            if std::env::var("CI").as_deref() == Ok("true")
                && webview
                    .app_handle()
                    .state::<Mutex<Service>>()
                    .lock()
                    .is_ok_and(|s| s.demo)
                && payload.event() == tauri::webview::PageLoadEvent::Finished
            {
                if webview.label() == "smoke-denied" {
                    eprintln!("TEST_ONLY_NATIVE_SMOKE_ACL_WINDOW=loaded");
                    #[cfg(target_os = "linux")]
                    let receipt = "document.title = bothDenied ? 'TEST_ONLY-acl-denied' : 'TEST_ONLY-acl-unexpected';";
                    #[cfg(target_os = "macos")]
                    let receipt = "window.location.href = new URL(bothDenied ? '/TEST_ONLY-acl-denied' : '/TEST_ONLY-acl-unexpected', window.location.href).href;";
                    let script = [
                        r#"
                  (async () => {
                    document.title = 'TEST_ONLY-acl-started';
                    const denied = async (command, args) => {
                      try { await window.__TAURI_INTERNALS__.invoke(command,args); return false; }
                      catch (error) { return /not allowed|forbidden|denied/i.test(String(error)); }
                    };
                    const bothDenied = await denied('snapshot',{}) && await denied('apply_preview',{
                      id:'00000000-0000-0000-0000-000000000000',confirmed:true
                    });
                "#,
                        receipt,
                        "})();",
                    ]
                    .concat();
                    let _ = webview.eval(&script);
                    return;
                }
                if webview.label() != "main" {
                    return;
                }
                let _ = webview
                    .window()
                    .set_size(tauri::LogicalSize::new(640.0, 480.0));
                let _ = webview.eval(NATIVE_SMOKE_SCRIPT);
            }
        });
    builder
        .run(context())
        .map_err(|_| Error::new("RUNTIME_FAILED", "本地窗口启动失败。"))
}
fn main() {
    if let Err(error) = run() {
        // Release builds have no console: surface only the safe static error.
        let _ = tauri::Builder::default()
            .plugin(tauri_plugin_dialog::init())
            .setup(move |app| {
                app.dialog()
                    .message(error.message)
                    .title("AI Tool Manager无法启动")
                    .blocking_show();
                app.handle().exit(1);
                Ok(())
            })
            .run(context());
    }
}
