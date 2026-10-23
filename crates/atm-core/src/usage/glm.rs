use super::*;
use reqwest::{
    blocking::Client,
    header::{HeaderValue, AUTHORIZATION, CONTENT_TYPE},
    redirect::Policy,
    Url,
};
use std::{io::Read, time::Duration};
use zeroize::Zeroizing;

pub const CHINA_ENDPOINT: &str = "https://open.bigmodel.cn/api/monitor/usage/quota/limit";
pub const INTERNATIONAL_ENDPOINT: &str = "https://api.z.ai/api/monitor/usage/quota/limit";
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PlanKind {
    Personal,
    Team,
    ApiBalance,
}
pub struct Request {
    region: Region,
    authorization: HeaderValue,
}
impl Request {
    pub fn new(region: Region, key: &str) -> Result<Self> {
        if !matches!(region, Region::China | Region::International) {
            return Err(Error::new(
                "USAGE_REGION",
                "请选择智谱中国或 Z.ai 国际地区。",
            ));
        }
        if key.is_empty()
            || key.len() > 8192
            || !key.is_ascii()
            || key.trim() != key
            || key.bytes().any(|b| b < 33 || b == 127)
        {
            return Err(Error::new(
                "USAGE_CREDENTIAL",
                "查询凭据包含不支持的字符或为空。",
            ));
        }
        let mut authorization = HeaderValue::from_str(key)
            .map_err(|_| Error::new("USAGE_CREDENTIAL", "查询凭据无效。"))?;
        authorization.set_sensitive(true);
        Ok(Self {
            region,
            authorization,
        })
    }
    pub fn endpoint(&self) -> &'static str {
        if self.region == Region::China {
            CHINA_ENDPOINT
        } else {
            INTERNATIONAL_ENDPOINT
        }
    }
    /// Kept opaque in production; useful to assert the exact raw Authorization contract.
    pub fn authorization(&self) -> &HeaderValue {
        &self.authorization
    }
}
pub fn validate_endpoint(endpoint: &str) -> Result<()> {
    let url =
        Url::parse(endpoint).map_err(|_| Error::new("USAGE_ENDPOINT", "额度服务地址不受支持。"))?;
    if url.scheme() != "https"
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || ![CHINA_ENDPOINT, INTERNATIONAL_ENDPOINT].contains(&endpoint)
    {
        return Err(Error::new(
            "USAGE_ENDPOINT",
            "只允许固定官方 HTTPS 额度地址。",
        ));
    }
    Ok(())
}
pub struct Response {
    pub status: u16,
    pub json_content: bool,
    pub body: Zeroizing<Vec<u8>>,
}
pub trait Transport {
    fn get(&mut self, request: &Request) -> Result<Response>;
}
pub struct OfficialHttps;
impl Transport for OfficialHttps {
    fn get(&mut self, request: &Request) -> Result<Response> {
        validate_endpoint(request.endpoint())?;
        // Fixed domains, no redirects, proxies, retries or model requests.
        let client = Client::builder()
            .https_only(true)
            .no_proxy()
            .redirect(Policy::none())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(12))
            .build()
            .map_err(|_| Error::new("USAGE_NETWORK", "无法建立安全额度连接。"))?;
        let response = client
            .get(request.endpoint())
            .header(AUTHORIZATION, request.authorization.clone())
            .header("Accept", "application/json")
            .send()
            .map_err(|_| Error::new("USAGE_NETWORK", "额度服务暂不可用；不会自动重试。"))?;
        let status = response.status().as_u16();
        let json_content = response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|h| h.to_str().ok())
            .is_some_and(|s| {
                s.split(';')
                    .next()
                    .is_some_and(|m| m.trim().eq_ignore_ascii_case("application/json"))
            });
        if response
            .content_length()
            .is_some_and(|n| n > MAX_RESPONSE_BYTES as u64)
        {
            return Err(Error::new("USAGE_SIZE", "额度响应超过安全上限。"));
        }
        let mut body = Zeroizing::new(Vec::new());
        response
            .take(MAX_RESPONSE_BYTES as u64 + 1)
            .read_to_end(&mut body)
            .map_err(|_| Error::new("USAGE_NETWORK", "读取额度响应失败。"))?;
        if body.len() > MAX_RESPONSE_BYTES {
            return Err(Error::new("USAGE_SIZE", "额度响应超过安全上限。"));
        }
        Ok(Response {
            status,
            json_content,
            body,
        })
    }
}
pub fn query(
    transport: &mut dyn Transport,
    region: Region,
    kind: PlanKind,
    key: &str,
    confirmed: bool,
    now: DateTime<Utc>,
) -> Result<Snapshot> {
    if !confirmed {
        return Err(Error::new(
            "CONFIRM_REQUIRED",
            "须主动确认使用所选密钥连接官方额度服务。",
        ));
    }
    let auth = if kind == PlanKind::ApiBalance {
        AuthKind::ApiKey
    } else {
        AuthKind::CodingPlanKey
    };
    let base = Snapshot::empty(Provider::Glm, region, auth, Status::Unknown);
    if kind == PlanKind::Team {
        return Ok(base.failed(Status::UnsupportedPlanType, "personal_plugin_only", now));
    }
    if kind == PlanKind::ApiBalance {
        return Ok(base.failed(Status::UnsupportedAuth, "api_balance_not_supported", now));
    }
    let request = Request::new(region, key)?;
    let response = match transport.get(&request) {
        Ok(r) => r,
        Err(e) => {
            return Ok(base.failed(
                if matches!(e.code, "USAGE_SIZE" | "USAGE_DEPTH" | "USAGE_FORMAT") {
                    Status::ProtocolError
                } else {
                    Status::Unavailable
                },
                "request_failed",
                now,
            ))
        }
    };
    let status = match response.status {
        200 => None,
        401 | 403 => Some((Status::AuthenticationFailed, "authentication_failed")),
        429 => Some((Status::RateLimited, "server_rate_limited")),
        300..=399 => Some((Status::ProtocolError, "redirect_blocked")),
        500..=599 => Some((Status::Unavailable, "server_unavailable")),
        _ => Some((Status::ProtocolError, "unexpected_http_status")),
    };
    if let Some((status, warning)) = status {
        return Ok(base.failed(status, warning, now));
    }
    if !response.json_content {
        return Ok(base.failed(Status::ProtocolError, "non_json_response", now));
    }
    let value = match bounded_json(&response.body) {
        Ok(v) => v,
        Err(_) => return Ok(base.failed(Status::ProtocolError, "invalid_response", now)),
    };
    let mut result = parse(&value, region, now);
    // Remote fields never carry credential text through to UI or logs.
    if serde_json::to_string(&result).is_ok_and(|s| s.contains(key)) {
        result = base.failed(Status::ProtocolError, "unsafe_response", now);
    }
    Ok(result)
}
pub fn parse(root: &Value, region: Region, now: DateTime<Utc>) -> Snapshot {
    let mut s = Snapshot::empty(
        Provider::Glm,
        region,
        AuthKind::CodingPlanKey,
        Status::Unknown,
    );
    if root
        .get("success")
        .is_some_and(|v| v.as_bool() != Some(true))
        || root
            .get("code")
            .is_some_and(|v| !matches!(v.as_i64(), Some(0 | 200)))
    {
        return s.failed(Status::ProtocolError, "provider_business_error", now);
    }
    let Some(data) = root.get("data").and_then(Value::as_object) else {
        return s.failed(Status::ProtocolError, "data_missing", now);
    };
    if data
        .get("planType")
        .and_then(Value::as_str)
        .is_some_and(|p| p.eq_ignore_ascii_case("team"))
    {
        return s.failed(Status::UnsupportedPlanType, "personal_plugin_only", now);
    }
    s.plan_name = data.get("level").and_then(plan);
    if s.plan_name.is_none() {
        s.warnings.push("plan_unknown".into());
    }
    let Some(limits) = data.get("limits").and_then(Value::as_array) else {
        return s.failed(Status::Unknown, "limits_missing", now);
    };
    if limits.len() > 64 {
        return s.failed(Status::ProtocolError, "too_many_windows", now);
    }
    for (i, limit) in limits.iter().enumerate() {
        let kind = match limit.get("type").and_then(Value::as_str) {
            Some("TOKENS_LIMIT") => "model_quota",
            Some("CREDIT_LIMIT") => "model_credit_quota",
            Some("TIME_LIMIT") => "tool_quota",
            _ => "unknown_quota",
        };
        let duration = match (
            kind,
            limit.get("unit").and_then(Value::as_u64),
            limit.get("number").and_then(Value::as_u64),
        ) {
            ("model_quota", Some(3), Some(5)) => Some(300),
            ("model_quota" | "model_credit_quota", Some(3), Some(1)) => Some(300),
            ("model_quota" | "model_credit_quota", Some(6), Some(1 | 7)) => Some(10080),
            _ => None,
        };
        if duration.is_some() {
            s.warnings.push("glm_cycle_compat_interpretation".into());
        } else {
            s.warnings.push("cycle_unknown".into());
        }
        let used = limit.get("percentage").and_then(percentage);
        let reset = limit.get("nextResetTime").and_then(|v| timestamp(v, true));
        s.windows.push(Window {
            id: format!("glm-{i}"),
            label: match kind {
                "model_quota" => "模型额度",
                "model_credit_quota" => "模型积分额度",
                "tool_quota" => "工具额度",
                _ => "未知额度",
            }
            .into(),
            kind: kind.into(),
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
    }
    s.warnings.sort();
    s.warnings.dedup();
    finalize(s, now)
}
