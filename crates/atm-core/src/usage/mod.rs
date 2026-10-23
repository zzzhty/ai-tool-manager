//! Manual-only provider queries. No login, inference, reset or background polling.
pub mod codex;
pub mod glm;
pub mod process;
use crate::{Error, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

pub const MAX_RESPONSE_BYTES: usize = 256 * 1024;
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Provider {
    Codex,
    Glm,
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Region {
    Global,
    China,
    International,
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AuthKind {
    ChatgptOauth,
    CodingPlanKey,
    ApiKey,
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Ok,
    Unknown,
    UnsupportedAuth,
    UnsupportedPlanType,
    UnsupportedVersion,
    Expired,
    AuthenticationFailed,
    RateLimited,
    Stale,
    Unavailable,
    ProtocolError,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Window {
    pub id: String,
    pub label: String,
    pub kind: String,
    pub used_percent: Option<f64>,
    pub remaining_percent: Option<f64>,
    pub window_duration_mins: Option<u64>,
    pub resets_at: Option<DateTime<Utc>>,
    pub status: Status,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Credits {
    pub has_credits: Option<bool>,
    pub unlimited: Option<bool>,
    pub balance: Option<f64>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Snapshot {
    pub provider: Provider,
    pub region: Region,
    pub auth_kind: AuthKind,
    pub source: String,
    pub observed_at: Option<DateTime<Utc>>,
    pub checked_at: Option<DateTime<Utc>>,
    pub status: Status,
    pub plan_name: Option<String>,
    pub windows: Vec<Window>,
    pub credits: Option<Credits>,
    pub warnings: Vec<String>,
}
impl Snapshot {
    pub fn empty(provider: Provider, region: Region, auth_kind: AuthKind, status: Status) -> Self {
        Self {
            provider,
            region,
            auth_kind,
            status,
            source: match provider {
                Provider::Codex => "official_app_server",
                Provider::Glm => "official_plugin_compat",
            }
            .into(),
            observed_at: None,
            checked_at: None,
            plan_name: None,
            windows: vec![],
            credits: None,
            warnings: vec![],
        }
    }
    pub fn failed(mut self, status: Status, warning: &'static str, now: DateTime<Utc>) -> Self {
        self.status = status;
        self.checked_at = Some(now);
        self.observed_at = None;
        self.windows.clear();
        self.plan_name = None;
        self.credits = None;
        self.warnings = vec![warning.into()];
        self
    }
}
pub fn percentage(v: &Value) -> Option<f64> {
    v.as_f64()
        .filter(|n| n.is_finite() && (0.0..=100.0).contains(n))
}
pub fn timestamp(v: &Value, millis: bool) -> Option<DateTime<Utc>> {
    let n = v.as_i64()?;
    // Explicit units and a plausible 2000–2100 range reject accidental seconds/milliseconds mixing.
    let d = if millis {
        DateTime::from_timestamp_millis(n)
    } else {
        DateTime::from_timestamp(n, 0)
    }?;
    (946684800..=4102444800)
        .contains(&d.timestamp())
        .then_some(d)
}
pub fn bounded_json(bytes: &[u8]) -> Result<Value> {
    if bytes.len() > MAX_RESPONSE_BYTES {
        return Err(Error::new("USAGE_SIZE", "额度响应超过安全上限。"));
    }
    let mut depth = 0usize;
    let mut quoted = false;
    let mut escaped = false;
    for b in bytes {
        if quoted {
            if escaped {
                escaped = false;
            } else if *b == b'\\' {
                escaped = true;
            } else if *b == b'"' {
                quoted = false;
            }
        } else if *b == b'"' {
            quoted = true;
        } else if matches!(*b, b'[' | b'{') {
            depth += 1;
            if depth > 32 {
                return Err(Error::new("USAGE_DEPTH", "额度响应嵌套过深。"));
            }
        } else if matches!(*b, b']' | b'}') {
            depth = depth.saturating_sub(1);
        }
    }
    serde_json::from_slice::<Value>(bytes)
        .map_err(|_| Error::new("USAGE_FORMAT", "额度响应格式无效。"))?;
    crate::jsonc::parse_value(bytes)
        .map_err(|_| Error::new("USAGE_FORMAT", "额度响应包含重复字段或无效结构。"))
}
pub fn plan(v: &Value) -> Option<String> {
    let p = v.as_str()?.to_ascii_lowercase();
    matches!(
        p.as_str(),
        "free"
            | "go"
            | "plus"
            | "pro"
            | "prolite"
            | "promax"
            | "team"
            | "self_serve_business_prolite"
            | "self_serve_business_usage_based"
            | "business"
            | "ent26"
            | "enterprise_cbp_automation"
            | "enterprise_cbp_usage_based"
            | "enterprise"
            | "edu"
            | "edu_plus"
            | "edu_pro"
            | "lite"
            | "max"
    )
    .then_some(p)
}
pub fn has_known_usage(s: &Snapshot) -> bool {
    s.windows.iter().any(|w| w.used_percent.is_some())
}
pub fn finalize(mut s: Snapshot, now: DateTime<Utc>) -> Snapshot {
    s.checked_at = Some(now);
    s.observed_at = Some(now);
    s.status = if has_known_usage(&s) {
        Status::Ok
    } else {
        Status::Unknown
    };
    s
}
/// Only memory snapshots, scoped to provider/region plus credential revision or proven CLI account.
#[derive(Default)]
pub struct Cache {
    entries: BTreeMap<String, Snapshot>,
}
impl Cache {
    pub fn update(&mut self, binding: &str, next: Snapshot) -> Snapshot {
        let scoped = format!(
            "{:?}:{:?}:{:?}:{binding}",
            next.provider, next.region, next.auth_kind
        );
        if matches!(next.status, Status::Unavailable | Status::RateLimited) {
            if let Some(old) = self.entries.get(&scoped) {
                if has_known_usage(old) {
                    let mut stale = old.clone();
                    stale.status = Status::Stale;
                    stale.checked_at = next.checked_at;
                    stale.warnings = next.warnings;
                    stale.warnings.push("cached_snapshot_not_live".into());
                    for window in &mut stale.windows {
                        window.status = Status::Stale;
                    }
                    return stale;
                }
            }
        }
        if matches!(next.status, Status::Ok | Status::Unknown) && next.observed_at.is_some() {
            self.entries.insert(scoped, next.clone());
        } else {
            self.entries.remove(&scoped);
        }
        next
    }
    pub fn clear(&mut self) {
        self.entries.clear();
    }
}
