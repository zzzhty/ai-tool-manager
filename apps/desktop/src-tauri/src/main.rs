#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use atm_core::application::{
    configuration::{
        CandidateView, ConfigurationSession, ConfigurationSnapshot as DesktopSnapshot, TargetView,
    },
    usage_service::UsageService,
};
use atm_core::{
    batch::{BackupView, FileResult, PreviewView},
    harness::{self, HarnessStatusSnapshot},
    skills::{SkillsInventoryView, SkillsService},
    storage,
    usage::{
        self,
        glm::{self, PlanKind},
        Region, Snapshot as UsageSnapshot,
    },
    Error, TargetMapping,
};
use serde::{Deserialize, Serialize};
#[cfg(all(any(target_os = "linux", target_os = "macos"), feature = "smoke-tests"))]
use std::path::PathBuf;
use std::{
    path::Path,
    sync::{Arc, Mutex},
};
#[cfg(all(any(target_os = "linux", target_os = "macos"), feature = "smoke-tests"))]
use tauri::Manager;
use tauri::{State, WebviewWindow};
use tauri_plugin_dialog::DialogExt;
use uuid::Uuid;
use zeroize::Zeroizing;

struct Service {
    configuration: ConfigurationSession,
    usage: Arc<Mutex<UsageService>>,
    demo: bool,
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
#[tauri::command]
fn snapshot(window: WebviewWindow, state: AppState<'_>) -> Result<DesktopSnapshot, Error> {
    authorized(&window)?;
    lock(&state)?.configuration.get()?.snapshot()
}
#[tauri::command]
fn save_key(
    window: WebviewWindow,
    state: AppState<'_>,
    id: Option<Uuid>,
    name: String,
    secret: String,
) -> Result<Uuid, Error> {
    let secret = Zeroizing::new(secret);
    authorized(&window)?;
    lock(&state)?
        .configuration
        .get()?
        .save_key(id, name, secret)
}
#[tauri::command]
fn delete_key(window: WebviewWindow, state: AppState<'_>, id: Uuid) -> Result<(), Error> {
    authorized(&window)?;
    lock(&state)?.configuration.get()?.delete_key(id)
}
#[tauri::command]
fn save_target(
    window: WebviewWindow,
    state: AppState<'_>,
    target: TargetView,
) -> Result<Uuid, Error> {
    authorized(&window)?;
    lock(&state)?.configuration.get()?.save_target(target)
}
#[tauri::command]
fn delete_target(window: WebviewWindow, state: AppState<'_>, id: Uuid) -> Result<(), Error> {
    authorized(&window)?;
    lock(&state)?.configuration.get()?.delete_target(id)
}
#[tauri::command]
fn preview(
    window: WebviewWindow,
    state: AppState<'_>,
    selected: Vec<Uuid>,
) -> Result<PreviewView, Error> {
    authorized(&window)?;
    lock(&state)?.configuration.get()?.preview(selected)
}
#[tauri::command]
fn apply_preview(
    window: WebviewWindow,
    state: AppState<'_>,
    id: Uuid,
    confirmed: bool,
) -> Result<Vec<FileResult>, Error> {
    authorized(&window)?;
    lock(&state)?
        .configuration
        .get()?
        .apply_preview(id, confirmed)
}
#[tauri::command]
fn cancel_preview(window: WebviewWindow, state: AppState<'_>) -> Result<(), Error> {
    authorized(&window)?;
    lock(&state)?.configuration.invalidate();
    Ok(())
}
#[tauri::command]
fn list_backups(window: WebviewWindow, state: AppState<'_>) -> Result<Vec<BackupView>, Error> {
    authorized(&window)?;
    lock(&state)?.configuration.get()?.list_backups()
}
#[tauri::command]
fn preview_rollback(
    window: WebviewWindow,
    state: AppState<'_>,
    backup_path: String,
) -> Result<PreviewView, Error> {
    authorized(&window)?;
    lock(&state)?
        .configuration
        .get()?
        .preview_rollback(backup_path)
}
#[tauri::command]
fn infer_template(
    window: WebviewWindow,
    state: AppState<'_>,
    file_path: String,
) -> Result<CandidateView, Error> {
    authorized(&window)?;
    lock(&state)?.configuration.get()?.infer_template(file_path)
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
    lock(&state)?
        .configuration
        .get()?
        .save_template(candidate_id, name, selected_pointers, schema)
}
#[tauri::command]
fn delete_template(window: WebviewWindow, state: AppState<'_>, id: Uuid) -> Result<(), Error> {
    authorized(&window)?;
    lock(&state)?.configuration.get()?.delete_template(id)
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
        (
            service.demo,
            service.configuration.directory()?.to_path_buf(),
        )
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
        let mut service = lock(&state)?;
        let (key, revision) = if plan_kind == PlanKind::Personal && !service.demo {
            let id = key_id.ok_or(Error::new("KEY_MISSING", "请选择命名密钥。"))?;
            service.configuration.get()?.usage_credential(id)?
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
            roots: atm_core::tool_catalog::TOOLS
                .iter()
                .map(|tool| {
                    let demo_home = std::env::temp_dir().join("TEST_ONLY/home");
                    let root = tool.resolve(&demo_home, false)?;
                    let entries = match tool.id {
                        "claude-code" => vec![
                            demo_entry("demo-skill", "directory"),
                            demo_entry("managed", "engine_managed"),
                        ],
                        "codex" => vec![demo_entry("review-agent", "directory")],
                        _ => vec![],
                    };
                    Ok(SkillRootView {
                        id: tool.id,
                        label: tool.label,
                        path: format!(
                            "TEST_ONLY/home/{}",
                            root.strip_prefix(&demo_home)
                                .expect("synthetic root")
                                .display()
                        ),
                        exists: !entries.is_empty(),
                        entries,
                    })
                })
                .collect::<Result<Vec<_>, Error>>()?,
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
        let directory = lock(&state)?.configuration.directory()?.to_path_buf();
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
        let mut service = lock(&state)?;
        let configuration = service.configuration.get()?;
        let directory = configuration.directory();
        if !directory.starts_with(root.join("tmp"))
            || std::fs::read(directory.join("synthetic.jsonc"))?.as_slice() != DEMO_CONFIG
            || configuration.list_backups()?.len() != 2
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

/// Read-only portable-package probe. It deliberately runs before GUI, storage,
/// keyring or application-service initialization and never enables a hook.
fn verify_distribution() -> Result<serde_json::Value, Error> {
    let context = context();
    let assets: std::collections::BTreeSet<_> = context
        .assets()
        .iter()
        .map(|(path, _)| path.into_owned())
        .collect();
    let invalid = || Error::new("DISTRIBUTION_RESOURCES", "桌面程序内嵌资源不完整。");
    let index = context
        .assets()
        .get(&"/index.html".into())
        .ok_or_else(invalid)?;
    let html = std::str::from_utf8(&index).map_err(|_| invalid())?;
    let mut referenced = Vec::new();
    for attribute in ["src=\"", "href=\""] {
        for part in html.split(attribute).skip(1) {
            let path = part.split('"').next().ok_or_else(invalid)?;
            if !path.starts_with("/assets/")
                || !assets.contains(path)
                || context
                    .assets()
                    .get(&path.into())
                    .is_none_or(|bytes| bytes.is_empty())
            {
                return Err(invalid());
            }
            referenced.push(path.to_owned());
        }
    }
    if !referenced.iter().any(|path| path.ends_with(".js"))
        || !referenced.iter().any(|path| path.ends_with(".css"))
    {
        return Err(invalid());
    }
    let source = atm_core::distribution::source::locate()?;
    let bundle = atm_core::distribution::source::load(&source)?;
    Ok(serde_json::json!({
        "product": "atm-desktop", "releaseBuild": !cfg!(debug_assertions),
        "frontendAssets": assets,
        "referencedAssets": referenced, "sourceRoot": source,
        "sourceIdentity": bundle.identity, "payloadFiles": bundle.files.len(),
        "guiInitialized": false, "storageInitialized": false
    }))
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
        Ok(std::env::temp_dir().join(format!("atm-demo-{}", Uuid::new_v4())))
    } else {
        storage::data_directory()
    };
    let protector = if demo {
        storage::demo_protector()?
    } else {
        storage::system()
    };
    let mut configuration = ConfigurationSession::new(directory, protector, demo);
    if demo {
        let service = configuration.get()?;
        let file = service.directory().join("synthetic.jsonc");
        std::fs::write(&file, DEMO_CONFIG)?;
        let key = service.save_key(
            None,
            "演示密钥（假数据）".into(),
            Zeroizing::new("FAKE_DEMO_NEW".into()),
        )?;
        for (pointer, bearer) in [("/apiKey", false), ("/authorization", true)] {
            service.save_target(TargetView {
                template_id: None,
                target: TargetMapping {
                    id: Uuid::nil(),
                    label: format!("演示 {pointer}"),
                    file_path: file.to_string_lossy().into_owned(),
                    pointer: pointer.into(),
                    key_id: key,
                    bearer_prefix: bearer,
                    replace_variables: false,
                },
            })?;
        }
    }
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Mutex::new(Service {
            configuration,
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
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args
        .first()
        .is_some_and(|arg| arg == "--verify-distribution")
    {
        if args.len() != 1 {
            eprintln!("CLI_ARGUMENT: --verify-distribution 不接受附加参数。");
            std::process::exit(2);
        }
        match verify_distribution() {
            Ok(result) => println!("{result}"),
            Err(error) => {
                eprintln!("{error}");
                std::process::exit(1);
            }
        }
        return;
    }
    if let Err(error) = run() {
        // Release builds have no console: surface only the safe static error.
        let _ = tauri::Builder::default()
            .plugin(tauri_plugin_dialog::init())
            .setup(move |app| {
                app.dialog()
                    .message(error.message)
                    .title("AI Tooling Manager无法启动")
                    .blocking_show();
                app.handle().exit(1);
                Ok(())
            })
            .run(context());
    }
}
