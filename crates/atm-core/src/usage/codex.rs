use super::*;
use serde_json::json;

#[derive(Clone, Copy, Debug)]
pub struct RpcFailure {
    pub status: Status,
    pub warning: &'static str,
}
impl RpcFailure {
    pub fn new(status: Status, warning: &'static str) -> Self {
        Self { status, warning }
    }
}
pub type RpcResult<T> = std::result::Result<T, RpcFailure>;
pub trait Rpc {
    fn request(&mut self, method: &'static str, params: Value) -> RpcResult<Value>;
    fn notify(&mut self, method: &'static str) -> RpcResult<()>;
    fn reset_account_changed(&mut self) {}
    fn account_changed(&self) -> bool {
        false
    }
}
pub struct BoundSnapshot {
    pub binding: Option<String>,
    pub snapshot: Snapshot,
}
fn account_marker(account: &Value) -> Option<(String, bool)> {
    let account = account.get("account")?;
    if account.get("type")?.as_str()? != "chatgpt" {
        return None;
    }
    let mut fields = ["", ""];
    for (index, name) in ["email", "planType"].into_iter().enumerate() {
        match account.get(name) {
            None | Some(Value::Null) => {}
            Some(Value::String(value))
                if value.len() <= 320 && !value.chars().any(char::is_control) =>
            {
                fields[index] = value;
            }
            _ => return None,
        }
    }
    Some((
        crate::windows::hash(format!("{}\0{}", fields[0], fields[1]).as_bytes()),
        !fields[0].trim().is_empty(),
    ))
}
pub fn query(
    rpc: &mut dyn Rpc,
    profile: &str,
    confirmed: bool,
    now: DateTime<Utc>,
) -> Result<BoundSnapshot> {
    if !confirmed {
        return Err(Error::new(
            "CONFIRM_REQUIRED",
            "须确认 CLI 可能联网并使用所选 CLI 帐号；CLI 可能自行刷新 OAuth。",
        ));
    }
    let base = Snapshot::empty(
        Provider::Codex,
        Region::Global,
        AuthKind::ChatgptOauth,
        Status::Unknown,
    );
    let failure = |e: RpcFailure| BoundSnapshot {
        binding: None,
        snapshot: base.clone().failed(e.status, e.warning, now),
    };
    let init = match rpc.request("initialize", json!({"clientInfo":{"name":"local_key_manager","version":env!("CARGO_PKG_VERSION")},"capabilities":{}})) {
        Ok(v) => v, Err(e) => return Ok(failure(e)),
    };
    if !init.is_object() {
        return Ok(failure(RpcFailure::new(
            Status::ProtocolError,
            "initialize_invalid",
        )));
    }
    if let Err(e) = rpc.notify("initialized") {
        return Ok(failure(e));
    }
    let before = match rpc.request("account/read", json!({"refreshToken":false})) {
        Ok(v) => v,
        Err(e) => return Ok(failure(e)),
    };
    let auth = before.pointer("/account/type").and_then(Value::as_str);
    if auth == Some("apiKey") {
        let mut api = base.clone();
        api.auth_kind = AuthKind::ApiKey;
        return Ok(BoundSnapshot {
            binding: None,
            snapshot: api.failed(Status::UnsupportedAuth, "api_balance_not_supported", now),
        });
    }
    if auth != Some("chatgpt") {
        return Ok(failure(RpcFailure::new(
            if auth.is_none() {
                Status::AuthenticationFailed
            } else {
                Status::UnsupportedAuth
            },
            "chatgpt_subscription_required",
        )));
    }
    let Some((marker, has_email)) = account_marker(&before) else {
        return Ok(failure(RpcFailure::new(
            Status::Unknown,
            "account_identity_missing",
        )));
    };
    rpc.reset_account_changed();
    let limits = rpc.request("account/rateLimits/read", Value::Null);
    // Confirm binding after reading; never attach another account's result or cache.
    let after = match rpc.request("account/read", json!({"refreshToken":false})) {
        Ok(v) => v,
        Err(e) => return Ok(failure(e)),
    };
    if rpc.account_changed()
        || account_marker(&after).map(|value| value.0).as_ref() != Some(&marker)
    {
        return Ok(failure(RpcFailure::new(Status::Unknown, "account_changed")));
    }
    // The backend-associated accountId scopes workspaces independently of shared/null emails.
    let cache_binding = match &limits {
        Ok(value) => match value.get("accountId") {
            None | Some(Value::Null) if has_email => None,
            None | Some(Value::Null) => {
                return Ok(failure(RpcFailure::new(
                    Status::Unknown,
                    "account_identity_missing",
                )));
            }
            Some(Value::String(id))
                if !id.trim().is_empty()
                    && id.len() <= 320
                    && !id.chars().any(char::is_control) =>
            {
                Some(crate::windows::hash(format!("{profile}\0{id}").as_bytes()))
            }
            _ => {
                return Ok(failure(RpcFailure::new(
                    Status::ProtocolError,
                    "account_identity_missing",
                )));
            }
        },
        Err(_) => None,
    };
    let mut snapshot = match limits {
        Ok(v) => parse(
            &v,
            after.pointer("/account/planType").unwrap_or(&Value::Null),
            now,
        ),
        Err(e) => base.failed(e.status, e.warning, now),
    };
    if init.get("userAgent").and_then(Value::as_str).is_none() {
        snapshot.warnings.push("cli_version_unknown".into());
    }
    if cache_binding.is_none() {
        snapshot.warnings.push("account_cache_disabled".into());
    }
    Ok(BoundSnapshot {
        binding: cache_binding,
        snapshot,
    })
}
pub fn rpc_error(v: &Value) -> RpcFailure {
    let code = v.get("code").and_then(Value::as_i64);
    let reason = v.pointer("/data/reason").and_then(Value::as_str);
    if matches!(reason, Some("token_expired" | "auth_expired")) {
        return RpcFailure::new(Status::Expired, "credentials_expired");
    }
    match code {
        Some(-32601) => RpcFailure::new(Status::UnsupportedVersion, "method_not_found"),
        Some(401 | 403) => RpcFailure::new(Status::AuthenticationFailed, "authentication_failed"),
        Some(429) => RpcFailure::new(Status::RateLimited, "server_rate_limited"),
        _ => RpcFailure::new(Status::Unavailable, "cli_request_failed"),
    }
}
pub fn parse(rates: &Value, account_plan: &Value, now: DateTime<Utc>) -> Snapshot {
    let mut s = Snapshot::empty(
        Provider::Codex,
        Region::Global,
        AuthKind::ChatgptOauth,
        Status::Unknown,
    );
    s.plan_name = plan(account_plan);
    let map = rates.get("rateLimitsByLimitId").and_then(Value::as_object);
    let buckets: Vec<(&str, &Value)> = match map {
        Some(map) => map.iter().map(|(id, v)| (id.as_str(), v)).collect(),
        None => rates
            .get("rateLimits")
            .filter(|v| v.is_object())
            .map(|v| vec![("codex", v)])
            .unwrap_or_default(),
    };
    if buckets.len() > 64 {
        return s.failed(Status::ProtocolError, "too_many_buckets", now);
    }
    for (i, (bucket_id, bucket)) in buckets.iter().enumerate() {
        if !bucket.is_object() {
            s.warnings.push("invalid_bucket".into());
            continue;
        }
        if s.plan_name.is_none() {
            s.plan_name = bucket.get("planType").and_then(plan);
        }
        if *bucket_id == "codex" {
            if let Some(c) = bucket.get("credits").filter(|v| v.is_object()) {
                let balance = c
                    .get("balance")
                    .and_then(|v| {
                        v.as_f64()
                            .or_else(|| v.as_str().and_then(|s| s.parse::<f64>().ok()))
                    })
                    .filter(|n| n.is_finite() && *n >= 0.0 && *n < 1e12);
                s.credits = Some(Credits {
                    has_credits: c.get("hasCredits").and_then(Value::as_bool),
                    unlimited: c.get("unlimited").and_then(Value::as_bool),
                    balance,
                });
            }
        }
        for cycle in ["primary", "secondary"] {
            let Some(w) = bucket.get(cycle).filter(|v| v.is_object()) else {
                continue;
            };
            let used = w.get("usedPercent").and_then(percentage);
            let duration = w
                .get("windowDurationMins")
                .and_then(Value::as_u64)
                .filter(|n| *n > 0 && *n <= 5256000);
            let reset = w.get("resetsAt").and_then(|v| timestamp(v, false));
            let bucket_hash = crate::windows::hash(bucket_id.as_bytes());
            s.windows.push(Window {
                id: format!("{}-{cycle}", &bucket_hash[..16]),
                label: format!(
                    "{} · {}",
                    if *bucket_id == "codex" {
                        "Codex".into()
                    } else {
                        format!("其他额度桶 {}", i + 1)
                    },
                    cycle
                ),
                kind: "subscription_quota".into(),
                used_percent: used,
                remaining_percent: used.map(|n| 100.0 - n),
                window_duration_mins: duration,
                resets_at: reset,
                status: if used.is_some() {
                    Status::Ok
                } else {
                    Status::Unknown
                },
            });
            if used.is_none() {
                s.warnings.push("usage_unknown".into());
            }
            if duration.is_none() {
                s.warnings.push("cycle_unknown".into());
            }
            if reset.is_none() {
                s.warnings.push("reset_unknown".into());
            }
        }
    }
    if s.plan_name.is_none() {
        s.warnings.push("plan_unknown".into());
    }
    // Ordinary usage permission belongs to the backend; meters cannot prove recovery.
    let permission = rates.get("ordinaryUsageAllowed").and_then(Value::as_bool);
    if permission != Some(true) {
        s.windows.clear();
        s.warnings.push(
            if permission == Some(false) {
                "ordinary_usage_not_allowed"
            } else {
                "ordinary_usage_permission_unknown"
            }
            .into(),
        );
    }
    s.warnings.sort();
    s.warnings.dedup();
    finalize(s, now)
}
