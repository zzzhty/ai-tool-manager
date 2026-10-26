//! Build-time view of the harness registry. No installed engine or Python needed.
use crate::{Error, Result};
use std::path::{Path, PathBuf};

struct RootCandidate {
    source: &'static str,
    env: &'static str,
    append: &'static str,
}

pub struct ToolDescriptor {
    pub id: &'static str,
    pub label: &'static str,
    pub aliases: &'static [&'static str],
    skills: &'static str,
    candidates: &'static [RootCandidate],
}

include!(concat!(env!("OUT_DIR"), "/tools.rs"));

pub fn find(id: &str) -> Result<&'static ToolDescriptor> {
    TOOLS
        .iter()
        .find(|tool| tool.id == id || tool.aliases.contains(&id))
        .ok_or(Error::new("SKILLS_NAME", "未知的技能根标识。"))
}

fn path_error() -> Error {
    Error::new(
        "SKILLS_ROOT",
        "工具根目录环境变量必须是绝对路径，且 profile 必须有效。",
    )
}

fn absolute(raw: &str, home: &Path) -> Result<PathBuf> {
    let path = if raw == "~" {
        home.to_path_buf()
    } else if raw.starts_with("~/") || raw.starts_with("~\\") {
        home.join(&raw[2..])
    } else {
        PathBuf::from(raw)
    };
    if path.is_absolute() {
        Ok(path)
    } else {
        Err(path_error())
    }
}

impl ToolDescriptor {
    pub fn resolve(&self, home: &Path, inherit_environment: bool) -> Result<PathBuf> {
        self.resolve_with(home, |name| {
            if inherit_environment {
                std::env::var(name).ok()
            } else {
                None
            }
        })
    }

    pub fn resolve_with(
        &self,
        home: &Path,
        env: impl Fn(&str) -> Option<String>,
    ) -> Result<PathBuf> {
        if !home.is_absolute() {
            return Err(path_error());
        }
        let value = |name: &str| env(name).unwrap_or_default().trim().to_owned();
        for candidate in self.candidates {
            let base = match candidate.source {
                "environment" => {
                    let raw = value(candidate.env);
                    if raw.is_empty() {
                        continue;
                    }
                    absolute(&raw, home)?
                }
                "openclaw-state" => {
                    let raw_home = value("OPENCLAW_HOME");
                    let base = if raw_home.is_empty()
                        || matches!(raw_home.as_str(), "null" | "undefined")
                    {
                        home.to_path_buf()
                    } else {
                        absolute(&raw_home, home)?
                    };
                    let profile = value("OPENCLAW_PROFILE");
                    if !profile.is_empty()
                        && (profile.len() > 64
                            || !profile.as_bytes()[0].is_ascii_alphanumeric()
                            || !profile
                                .bytes()
                                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-'))
                    {
                        return Err(path_error());
                    }
                    let state = value("OPENCLAW_STATE_DIR");
                    let root = if !state.is_empty() {
                        absolute(&state, &base)?
                    } else if profile.is_empty() || profile.eq_ignore_ascii_case("default") {
                        base.join(candidate.append)
                    } else {
                        base.join(format!("{}-{profile}", candidate.append))
                    };
                    return Ok(root.join(self.skills));
                }
                "user-home" => home.to_path_buf(),
                _ => return Err(path_error()),
            };
            return Ok(base.join(candidate.append).join(self.skills));
        }
        Err(path_error())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn registry_paths_keep_distinct_tools_and_aliases_without_python() {
        let home = std::env::temp_dir().join("TEST_ONLY_catalog");
        let override_root = home.join("custom-copilot");
        let env = |name: &str| {
            (name == "COPILOT_HOME").then(|| override_root.to_string_lossy().into_owned())
        };
        assert_eq!(
            find("copilot").unwrap().resolve_with(&home, env).unwrap(),
            override_root.join("skills")
        );
        assert_eq!(
            find("vscode").unwrap().resolve_with(&home, env).unwrap(),
            home.join(".copilot/skills")
        );
        assert_eq!(
            find("omp").unwrap().resolve(&home, false).unwrap(),
            home.join(".omp/agent/skills")
        );
        assert_eq!(
            find("openclaw")
                .unwrap()
                .resolve_with(&home, |name| (name == "OPENCLAW_PROFILE")
                    .then(|| "work".into()))
                .unwrap(),
            home.join(".openclaw-work/skills")
        );
        assert!(find("copilot")
            .unwrap()
            .resolve_with(&home, |_| Some("relative".into()))
            .is_err());
    }
}
