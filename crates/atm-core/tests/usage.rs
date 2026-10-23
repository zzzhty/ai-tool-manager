// Hand-written TEST_ONLY protocol data only; transports never contact any endpoint.
use atm_core::usage::{
    self,
    codex::{self, Rpc, RpcFailure, RpcResult},
    glm::{self, PlanKind, Request, Response, Transport},
    AuthKind, Cache, Provider, Region, Status, MAX_RESPONSE_BYTES,
};
use atm_core::Result;
use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use std::collections::VecDeque;
use zeroize::Zeroizing;
fn now() -> DateTime<Utc> {
    DateTime::from_timestamp(1791849600, 0).unwrap()
}
fn account(email: &str) -> Value {
    json!({"account":{"type":"chatgpt","email":email,"planType":"pro"}})
}
fn rates() -> Value {
    json!({"accountId":"TEST_ONLY_ACCOUNT_A","ordinaryUsageAllowed":true,"rateLimits":{"primary":{"usedPercent":25,"windowDurationMins":300,"resetsAt":1791856800},"secondary":null}})
}
fn glm_data() -> Value {
    json!({"success":true,"code":200,"data":{"level":"pro","limits":[{"type":"TOKENS_LIMIT","unit":3,"number":1,"percentage":40,"nextResetTime":1791856800000i64},{"type":"CREDIT_LIMIT","unit":6,"number":7,"percentage":20,"nextResetTime":1791853200000i64},{"type":"TIME_LIMIT","percentage":10}]}})
}
struct MockHttp {
    response: Option<Response>,
    calls: usize,
    expected: Region,
}
impl Transport for MockHttp {
    fn get(&mut self, r: &Request) -> Result<Response> {
        self.calls += 1;
        assert_eq!(r.authorization().to_str().unwrap(), "TEST_ONLY_KEY");
        assert!(r.authorization().is_sensitive());
        assert_eq!(
            r.endpoint(),
            if self.expected == Region::China {
                glm::CHINA_ENDPOINT
            } else {
                glm::INTERNATIONAL_ENDPOINT
            }
        );
        Ok(self.response.take().unwrap())
    }
}
fn http(status: u16, body: Value, region: Region) -> MockHttp {
    MockHttp {
        response: Some(Response {
            status,
            json_content: true,
            body: Zeroizing::new(serde_json::to_vec(&body).unwrap()),
        }),
        calls: 0,
        expected: region,
    }
}
struct MockRpc {
    steps: VecDeque<(&'static str, RpcResult<Value>)>,
    calls: Vec<String>,
    changed_after: bool,
    changed: bool,
}
impl MockRpc {
    fn new(steps: Vec<(&'static str, RpcResult<Value>)>) -> Self {
        Self {
            steps: steps.into(),
            calls: vec![],
            changed_after: false,
            changed: false,
        }
    }
}
impl Rpc for MockRpc {
    fn request(&mut self, method: &'static str, params: Value) -> RpcResult<Value> {
        self.calls.push(method.into());
        if method == "account/read" {
            assert_eq!(params, json!({"refreshToken":false}));
        }
        if method == "account/rateLimits/read" && self.changed_after {
            self.changed = true;
        }
        let (expected, result) = self.steps.pop_front().unwrap();
        assert_eq!(method, expected);
        result
    }
    fn notify(&mut self, method: &'static str) -> RpcResult<()> {
        assert_eq!(method, "initialized");
        self.calls.push(method.into());
        Ok(())
    }
    fn reset_account_changed(&mut self) {
        self.changed = false;
    }
    fn account_changed(&self) -> bool {
        self.changed
    }
}
fn rpc(before: Value, limits: RpcResult<Value>, after: Value) -> MockRpc {
    MockRpc::new(vec![
        ("initialize", Ok(json!({"userAgent":"TEST_ONLY_CLI/1.0"}))),
        ("account/read", Ok(before)),
        ("account/rateLimits/read", limits),
        ("account/read", Ok(after)),
    ])
}
#[test]
fn codex_multibucket_preferred_and_legacy_single_bucket_works() {
    let legacy = codex::parse(&rates(), &json!("pro"), now());
    assert_eq!(legacy.windows.len(), 1);
    assert_eq!(legacy.windows[0].remaining_percent, Some(75.));
    let multiple = json!({"ordinaryUsageAllowed":true,"rateLimits":{"primary":{"usedPercent":99}},"rateLimitsByLimitId":{
 "codex":{"primary":{"usedPercent":10,"windowDurationMins":15,"resetsAt":1791860000},"secondary":{"usedPercent":20,"windowDurationMins":10080,"resetsAt":1791850000},"credits":{"hasCredits":true,"balance":"123.5"}},
 "TEST_ONLY_extra":{"primary":{"usedPercent":30,"windowDurationMins":60,"resetsAt":1791860000}}}});
    let parsed = codex::parse(&multiple, &json!("plus"), now());
    assert_eq!(parsed.windows.len(), 3);
    assert!(parsed
        .windows
        .iter()
        .any(|w| w.remaining_percent == Some(90.)));
    assert!(!parsed.windows.iter().any(|w| w.used_percent == Some(99.)));
    assert_eq!(parsed.credits.unwrap().balance, Some(123.5));
    assert!(!serde_json::to_string(&parsed.windows)
        .unwrap()
        .contains("TEST_ONLY_extra"));
}
#[test]
fn codex_supported_subscription_plans_are_preserved_without_unknown_warning() {
    // PlanType oracle: openai/codex b043762f9e3eb65dd5164ff5880f139bc6d084c7.
    for name in [
        "free",
        "go",
        "plus",
        "pro",
        "prolite",
        "promax",
        "team",
        "self_serve_business_prolite",
        "self_serve_business_usage_based",
        "business",
        "ent26",
        "enterprise_cbp_automation",
        "enterprise_cbp_usage_based",
        "enterprise",
        "edu",
        "edu_plus",
        "edu_pro",
    ] {
        let snapshot = codex::parse(&rates(), &json!(name), now());
        assert_eq!(snapshot.plan_name.as_deref(), Some(name), "{name}");
        assert!(!snapshot.warnings.iter().any(|w| w == "plan_unknown"));
    }
    let unknown = codex::parse(&rates(), &json!("unknown"), now());
    assert!(unknown.plan_name.is_none());
    assert!(unknown.warnings.iter().any(|w| w == "plan_unknown"));
}
#[test]
fn codex_missing_null_illegal_percentages_and_seconds_are_not_zero_or_fixed_quota() {
    for value in [
        Value::Null,
        json!(-1),
        json!(101),
        json!("12"),
        json!(false),
    ] {
        let p = codex::parse(
            &json!({"ordinaryUsageAllowed":true,"rateLimits":{"primary":{"usedPercent":value,"resetsAt":1791856800000i64}}}),
            &Value::Null,
            now(),
        );
        assert_eq!(p.status, Status::Unknown);
        assert_eq!(p.windows[0].remaining_percent, None);
        assert_eq!(p.windows[0].window_duration_mins, None);
        assert_eq!(p.windows[0].resets_at, None);
    }
    assert_eq!(
        codex::parse(
            &json!({"rateLimits":null,"rateLimitsByLimitId":null}),
            &json!("TEST_ONLY_UNKNOWN_PLAN"),
            now()
        )
        .windows
        .len(),
        0
    );
    assert_eq!(
        codex::parse(
            &json!({"ordinaryUsageAllowed":true,"rateLimitsByLimitId":{},"rateLimits":{"primary":{"usedPercent":0}}}),
            &Value::Null,
            now()
        )
        .status,
        Status::Unknown
    );
    let p = codex::parse(&rates(), &json!("TEST_ONLY_UNKNOWN_PLAN"), now());
    assert!(p.plan_name.is_none());
    assert!(p.windows[0].resets_at.is_some());
}
#[test]
fn codex_unavailable_usage_permission_hides_windows_and_replaces_cached_quota() {
    // Backend-owned permission contract: openai/codex b043762f9e3eb65dd5164ff5880f139bc6d084c7.
    for permission in [
        Some(json!(false)),
        Some(Value::Null),
        None,
        Some(json!("true")),
        Some(json!(1)),
    ] {
        let mut cache = Cache::default();
        cache.update(
            "TEST_ONLY_BINDING",
            codex::parse(&rates(), &json!("pro"), now()),
        );
        let mut payload = rates();
        if let Some(value) = permission.clone() {
            payload["ordinaryUsageAllowed"] = value;
        } else {
            payload
                .as_object_mut()
                .unwrap()
                .remove("ordinaryUsageAllowed");
        }
        let a = account("TEST_ONLY_PERMISSION@example.invalid");
        let mut transport = rpc(a.clone(), Ok(payload), a);
        let denied = codex::query(&mut transport, "TEST_ONLY_PROFILE", true, now())
            .unwrap()
            .snapshot;
        assert_eq!(denied.status, Status::Unknown);
        assert!(denied.windows.is_empty());
        assert_eq!(denied.plan_name.as_deref(), Some("pro"));
        let warning = if permission == Some(json!(false)) {
            "ordinary_usage_not_allowed"
        } else {
            "ordinary_usage_permission_unknown"
        };
        assert!(denied.warnings.iter().any(|w| w == warning));
        let stored = cache.update("TEST_ONLY_BINDING", denied);
        assert!(stored.windows.is_empty());
        let failed = usage::Snapshot::empty(
            Provider::Codex,
            Region::Global,
            AuthKind::ChatgptOauth,
            Status::Unavailable,
        );
        let next = cache.update(
            "TEST_ONLY_BINDING",
            failed.failed(Status::Unavailable, "cli_request_failed", now()),
        );
        assert!(next.windows.is_empty());
        assert_ne!(next.status, Status::Stale);
    }
}
#[test]
fn codex_handshake_subscription_only_and_no_login_inference_reset_or_refresh() {
    let a = account("TEST_ONLY_A@example.invalid");
    let mut r = rpc(a.clone(), Ok(rates()), a);
    let got = codex::query(&mut r, "TEST_ONLY_PROFILE", true, now()).unwrap();
    assert_eq!(got.snapshot.status, Status::Ok);
    assert!(got.binding.is_some());
    assert_eq!(
        r.calls,
        [
            "initialize",
            "initialized",
            "account/read",
            "account/rateLimits/read",
            "account/read"
        ]
    );
    let mut r = MockRpc::new(vec![]);
    assert!(codex::query(&mut r, "TEST_ONLY_PROFILE", false, now()).is_err());
    assert!(r.calls.is_empty());
    let mut r = MockRpc::new(vec![
        ("initialize", Ok(json!({}))),
        ("account/read", Ok(json!({"account":{"type":"apiKey"}}))),
    ]);
    let got = codex::query(&mut r, "TEST_ONLY_PROFILE", true, now()).unwrap();
    assert_eq!(got.snapshot.status, Status::UnsupportedAuth);
    assert_eq!(got.snapshot.auth_kind, AuthKind::ApiKey);
    assert!(got.snapshot.windows.is_empty());
    assert_eq!(r.calls.len(), 3);
}
#[test]
fn codex_account_change_notification_and_missing_identity_hide_all_quota() {
    let a = account("TEST_ONLY_A@example.invalid");
    let b = account("TEST_ONLY_B@example.invalid");
    let mut r = rpc(a.clone(), Ok(rates()), b);
    let got = codex::query(&mut r, "TEST_ONLY_PROFILE", true, now()).unwrap();
    assert!(got.binding.is_none());
    assert!(got.snapshot.windows.is_empty());
    assert_eq!(got.snapshot.status, Status::Unknown);
    let mut r = rpc(a.clone(), Ok(rates()), a);
    r.changed_after = true;
    assert!(codex::query(&mut r, "TEST_ONLY_PROFILE", true, now())
        .unwrap()
        .snapshot
        .windows
        .is_empty());
    let unknown = json!({"account":{"type":"chatgpt","email":null,"planType":"pro"}});
    let mut limits = rates();
    limits.as_object_mut().unwrap().remove("accountId");
    let mut r = rpc(unknown.clone(), Ok(limits), unknown);
    let result = codex::query(&mut r, "TEST_ONLY_PROFILE", true, now()).unwrap();
    assert!(result.binding.is_none());
    assert!(result.snapshot.windows.is_empty());
}
#[test]
fn codex_nullable_email_uses_rate_account_id_without_exposing_it_in_snapshot() {
    for email in [Value::Null, json!("")] {
        let account = json!({"account":{"type":"chatgpt","email":email,"planType":"pro"}});
        let mut limits = rates();
        limits["accountId"] = json!("TEST_ONLY_EMAILLESS_ACCOUNT");
        let mut transport = rpc(account.clone(), Ok(limits), account);
        let result = codex::query(&mut transport, "TEST_ONLY_PROFILE", true, now()).unwrap();
        assert_eq!(result.snapshot.status, Status::Ok);
        assert!(result.binding.is_some());
        assert_eq!(result.snapshot.windows[0].remaining_percent, Some(75.));
        assert!(!serde_json::to_string(&result.snapshot)
            .unwrap()
            .contains("TEST_ONLY_EMAILLESS_ACCOUNT"));
        assert_eq!(
            transport.calls,
            [
                "initialize",
                "initialized",
                "account/read",
                "account/rateLimits/read",
                "account/read"
            ]
        );
    }
}
#[test]
fn codex_rate_account_ids_scope_shared_email_workspaces_and_reject_invalid_ids() {
    let account = account("TEST_ONLY_SHARED@example.invalid");
    let mut bindings = vec![];
    for id in ["TEST_ONLY_WORKSPACE_A", "TEST_ONLY_WORKSPACE_B"] {
        let mut limits = rates();
        limits["accountId"] = json!(id);
        let mut transport = rpc(account.clone(), Ok(limits), account.clone());
        let result = codex::query(&mut transport, "TEST_ONLY_PROFILE", true, now()).unwrap();
        assert_eq!(result.snapshot.status, Status::Ok);
        bindings.push(result.binding.unwrap());
    }
    assert_ne!(bindings[0], bindings[1]);
    let mut cache = Cache::default();
    cache.update(&bindings[0], codex::parse(&rates(), &json!("pro"), now()));
    let failure = usage::Snapshot::empty(
        Provider::Codex,
        Region::Global,
        AuthKind::ChatgptOauth,
        Status::Unavailable,
    );
    assert!(cache.update(&bindings[1], failure).windows.is_empty());
    for id in [
        json!(""),
        json!("  "),
        json!("TEST_ONLY\nINVALID"),
        json!("x".repeat(321)),
        json!(123),
        json!({"unexpected":true}),
    ] {
        let mut limits = rates();
        limits["accountId"] = id;
        let mut transport = rpc(account.clone(), Ok(limits), account.clone());
        let result = codex::query(&mut transport, "TEST_ONLY_PROFILE", true, now()).unwrap();
        assert!(result.binding.is_none());
        assert!(result.snapshot.windows.is_empty());
        assert_eq!(result.snapshot.status, Status::ProtocolError);
    }
}
#[test]
fn codex_protocol_capabilities_and_auth_errors_are_static() {
    for (code, status) in [
        (-32601, Status::UnsupportedVersion),
        (401, Status::AuthenticationFailed),
        (403, Status::AuthenticationFailed),
        (429, Status::RateLimited),
        (500, Status::Unavailable),
    ] {
        let e = codex::rpc_error(&json!({"code":code,"message":"TEST_ONLY_SECRET_ECHO"}));
        assert_eq!(e.status, status);
        assert!(!e.warning.contains("TEST_ONLY"));
    }
    assert_eq!(
        codex::rpc_error(&json!({"data":{"reason":"token_expired"}})).status,
        Status::Expired
    );
    let a = account("TEST_ONLY_A@example.invalid");
    let mut r = rpc(
        a.clone(),
        Err(RpcFailure::new(
            Status::Unavailable,
            "TEST_ONLY_NETWORK_FAILURE",
        )),
        a,
    );
    assert!(codex::query(&mut r, "TEST_ONLY_PROFILE", true, now())
        .unwrap()
        .binding
        .is_none());
}

#[test]
fn email_only_codex_account_can_query_but_cannot_reuse_another_workspace_cache() {
    let a = json!({"account":{"type":"chatgpt","email":"TEST_ONLY_A@example.invalid","planType":"plus"}});
    let mut limits = rates();
    limits.as_object_mut().unwrap().remove("accountId");
    let mut r = rpc(a.clone(), Ok(limits), a);
    let result = codex::query(&mut r, "TEST_ONLY_PROFILE", true, now()).unwrap();
    assert_eq!(result.snapshot.status, Status::Ok);
    assert!(result.binding.is_none());
    assert!(result
        .snapshot
        .warnings
        .iter()
        .any(|w| w == "account_cache_disabled"));
}
#[test]
fn glm_regions_raw_authorization_and_no_auto_fallback() {
    for region in [Region::China, Region::International] {
        let mut transport = http(200, glm_data(), region);
        let p = glm::query(
            &mut transport,
            region,
            PlanKind::Personal,
            "TEST_ONLY_KEY",
            true,
            now(),
        )
        .unwrap();
        assert_eq!(p.status, Status::Ok);
        assert_eq!(p.source, "official_plugin_compat");
        assert_eq!(transport.calls, 1);
        assert_eq!(p.windows[0].remaining_percent, Some(60.));
        assert_eq!(p.windows[0].window_duration_mins, Some(300));
        assert_eq!(p.windows[1].window_duration_mins, Some(10080));
        assert!(p.windows[1].resets_at < p.windows[0].resets_at);
        assert_eq!(p.windows[2].kind, "tool_quota");
        assert_eq!(p.windows[2].window_duration_mins, None);
    }
}
#[test]
fn glm_five_hour_token_window_accepts_provider_tuple_without_guessing_other_cycles() {
    // Official usage plugin 0446d0b labels TOKENS_LIMIT as the five-hour window.
    for (unit, number, duration) in [(3, 5, Some(300)), (3, 2, None), (99, 5, None)] {
        let data = json!({"data":{"level":"pro","limits":[{"type":"TOKENS_LIMIT","unit":unit,"number":number,"percentage":40}]}});
        let snapshot = glm::parse(&data, Region::China, now());
        assert_eq!(snapshot.windows[0].window_duration_mins, duration);
        assert_eq!(snapshot.windows[0].remaining_percent, Some(60.));
        assert_eq!(
            snapshot.warnings.iter().any(|w| w == "cycle_unknown"),
            duration.is_none()
        );
    }
}
#[test]
fn glm_unknown_cycle_plan_missing_percent_and_ms_are_explicit() {
    let data = json!({"data":{"limits":[{"type":"TOKENS_LIMIT","unit":99,"number":1,"nextResetTime":1791856800},{"type":"CREDIT_LIMIT","unit":6,"number":1,"percentage":null},{"type":"TIME_LIMIT","percentage":102}]}});
    let p = glm::parse(&data, Region::China, now());
    assert_eq!(p.status, Status::Unknown);
    assert!(p.plan_name.is_none());
    assert!(p.windows.iter().all(|w| w.remaining_percent.is_none()));
    assert_eq!(p.windows[0].window_duration_mins, None);
    assert_eq!(p.windows[0].resets_at, None);
    assert_eq!(p.windows[1].window_duration_mins, Some(10080));
}
#[test]
fn glm_team_api_and_unconfirmed_queries_never_call_transport() {
    for (kind, status) in [
        (PlanKind::Team, Status::UnsupportedPlanType),
        (PlanKind::ApiBalance, Status::UnsupportedAuth),
    ] {
        let mut t = http(200, glm_data(), Region::China);
        let s = glm::query(&mut t, Region::China, kind, "", true, now()).unwrap();
        assert_eq!(s.status, status);
        assert_eq!(t.calls, 0);
    }
    let mut t = http(200, glm_data(), Region::China);
    assert!(glm::query(
        &mut t,
        Region::China,
        PlanKind::Personal,
        "TEST_ONLY_KEY",
        false,
        now()
    )
    .is_err());
    assert_eq!(t.calls, 0);
}
#[test]
fn glm_http_business_errors_redirects_and_oversized_html_fail_closed() {
    for (code, status) in [
        (401, Status::AuthenticationFailed),
        (403, Status::AuthenticationFailed),
        (429, Status::RateLimited),
        (503, Status::Unavailable),
        (302, Status::ProtocolError),
    ] {
        let mut t = http(code, json!({"error":"TEST_ONLY_SECRET"}), Region::China);
        let s = glm::query(
            &mut t,
            Region::China,
            PlanKind::Personal,
            "TEST_ONLY_KEY",
            true,
            now(),
        )
        .unwrap();
        assert_eq!(s.status, status);
        assert!(s.windows.is_empty());
        assert_eq!(t.calls, 1);
        assert!(!serde_json::to_string(&s)
            .unwrap()
            .contains("TEST_ONLY_SECRET"));
    }
    for data in [
        json!({"code":1234,"data":{"limits":[]}}),
        json!({"success":false,"message":"TEST_ONLY_SECRET_ECHO"}),
        json!({"data":null}),
    ] {
        let mut t = http(200, data, Region::China);
        assert_eq!(
            glm::query(
                &mut t,
                Region::China,
                PlanKind::Personal,
                "TEST_ONLY_KEY",
                true,
                now()
            )
            .unwrap()
            .status,
            Status::ProtocolError
        );
    }
    let mut t = MockHttp {
        response: Some(Response {
            status: 200,
            json_content: false,
            body: Zeroizing::new(vec![b'x'; MAX_RESPONSE_BYTES + 1]),
        }),
        calls: 0,
        expected: Region::China,
    };
    assert_eq!(
        glm::query(
            &mut t,
            Region::China,
            PlanKind::Personal,
            "TEST_ONLY_KEY",
            true,
            now()
        )
        .unwrap()
        .status,
        Status::ProtocolError
    );
}
#[test]
fn exact_official_https_allowlist_crlf_and_protocol_depth_size() {
    for url in [
        "http://api.z.ai/api/monitor/usage/quota/limit",
        "https://api.z.ai.evil.invalid/api/monitor/usage/quota/limit",
        "https://api.z.ai@evil.invalid/api/monitor/usage/quota/limit",
        "https://api.z.ai/api/monitor/usage/quota/limit?redirect=TEST_ONLY",
        "https://evil.invalid/?api.z.ai",
        "https://127.0.0.1/api/monitor/usage/quota/limit",
        "https://api.z.ai:444/api/monitor/usage/quota/limit",
    ] {
        assert!(glm::validate_endpoint(url).is_err());
    }
    assert!(glm::validate_endpoint(glm::CHINA_ENDPOINT).is_ok());
    assert!(Request::new(Region::China, "TEST_ONLY_KEY\r\nx: y").is_err());
    assert!(Request::new(Region::Global, "TEST_ONLY_KEY").is_err());
    assert!(usage::bounded_json(&vec![b'x'; MAX_RESPONSE_BYTES + 1]).is_err());
    let nested = format!("{}0{}", "[".repeat(33), "]".repeat(33));
    assert!(usage::bounded_json(nested.as_bytes()).is_err());
    assert!(usage::bounded_json(br#"{"data":1,"data":2}"#).is_err());
    assert!(usage::bounded_json(b"<html>TEST_ONLY</html>").is_err());
}
#[test]
fn cached_snapshots_scope_credentials_region_account_and_auth_failure() {
    let mut cache = Cache::default();
    let good = glm::parse(&glm_data(), Region::China, now());
    cache.update("TEST_ONLY_KEY_A_REV1", good.clone());
    let fail = good
        .clone()
        .failed(Status::Unavailable, "network_failure", now());
    let stale = cache.update("TEST_ONLY_KEY_A_REV1", fail.clone());
    assert_eq!(stale.status, Status::Stale);
    assert_eq!(stale.observed_at, good.observed_at);
    assert!(stale.windows.iter().all(|w| w.status == Status::Stale));
    assert!(cache
        .update("TEST_ONLY_KEY_B_REV1", fail.clone())
        .windows
        .is_empty());
    assert!(cache
        .update("TEST_ONLY_KEY_A_REV2", fail.clone())
        .windows
        .is_empty());
    let mut other = fail.clone();
    other.region = Region::International;
    assert!(cache
        .update("TEST_ONLY_KEY_A_REV1", other)
        .windows
        .is_empty());
    let unauthorized = good.failed(Status::AuthenticationFailed, "authentication_failed", now());
    assert!(cache
        .update("TEST_ONLY_KEY_A_REV1", unauthorized)
        .windows
        .is_empty());
    assert!(cache
        .update("TEST_ONLY_KEY_A_REV1", fail)
        .windows
        .is_empty());
}
#[test]
fn unknown_never_becomes_zero_and_api_is_separate_from_subscription() {
    let s = usage::Snapshot::empty(
        Provider::Codex,
        Region::Global,
        AuthKind::ApiKey,
        Status::Unknown,
    );
    assert!(s.windows.is_empty());
    assert!(s.observed_at.is_none());
    assert!(s.credits.is_none());
}
