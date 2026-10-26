use crate::{
    usage::{
        self,
        codex::{self, Rpc},
        glm::{self, PlanKind, Transport},
        process::StdioRpc,
        AuthKind, Cache, Provider, Region, Snapshot, Status,
    },
    Error, Result,
};
use chrono::Utc;
use std::path::{Path, PathBuf};
use uuid::Uuid;

#[derive(Default)]
pub struct UsageService {
    cache: Cache,
    connection: Option<(PathBuf, PathBuf, Uuid)>,
}
impl UsageService {
    pub fn configure_codex(&mut self, cli: &Path, profile: &Path, confirmed: bool) -> Result<()> {
        if !confirmed {
            return Err(Error::new(
                "CONFIRM_REQUIRED",
                "请确认所选 CLI 与帐号目录。",
            ));
        }
        let cli = usage::process::executable(cli)?;
        if !profile.is_absolute()
            || !profile.is_dir()
            || profile.to_string_lossy().chars().any(char::is_control)
        {
            return Err(Error::new(
                "CLI_PROFILE",
                "请选择已经由用户登录配置的 CLI 帐号目录；不会新建或读取登录文件。",
            ));
        }
        // Store only explicit path selection in memory. No credential file or connection is opened here.
        self.connection = Some((cli, profile.to_owned(), Uuid::new_v4()));
        self.cache.clear();
        Ok(())
    }
    pub fn disconnect_codex(&mut self) {
        self.connection = None;
        self.cache.clear();
    }
    pub fn query_codex(&mut self, confirmed: bool) -> Result<Snapshot> {
        if !confirmed {
            return Err(Error::new(
                "CONFIRM_REQUIRED",
                "请确认 CLI 可能联网并使用其已登录帐号。",
            ));
        }
        let (cli, profile, connection) = self.connection.clone().ok_or(Error::new(
            "CLI_NOT_CONNECTED",
            "请先选择 Codex CLI 和帐号目录。",
        ))?;
        let mut rpc = match StdioRpc::launch(&cli, &profile, true) {
            Ok(r) => r,
            Err(_) => {
                return Ok(Snapshot::empty(
                    Provider::Codex,
                    Region::Global,
                    AuthKind::ChatgptOauth,
                    Status::Unknown,
                )
                .failed(Status::Unavailable, "cli_start_failed", Utc::now()))
            }
        };
        self.query_codex_with(
            &mut rpc,
            &profile.to_string_lossy(),
            &connection.to_string(),
            true,
        )
    }
    pub fn query_codex_with(
        &mut self,
        rpc: &mut dyn Rpc,
        profile: &str,
        connection: &str,
        confirmed: bool,
    ) -> Result<Snapshot> {
        let result = codex::query(rpc, profile, confirmed, Utc::now())?;
        match result.binding {
            Some(binding) => Ok(self
                .cache
                .update(&format!("{connection}:{binding}"), result.snapshot)),
            // Cannot prove the active account: never reuse an earlier account's quotas.
            None => {
                self.cache.clear();
                Ok(result.snapshot)
            }
        }
    }
    pub fn query_glm(
        &mut self,
        transport: &mut dyn Transport,
        region: Region,
        kind: PlanKind,
        credential_revision: &str,
        key: &str,
        confirmed: bool,
    ) -> Result<Snapshot> {
        let result = glm::query(transport, region, kind, key, confirmed, Utc::now())?;
        Ok(self.cache.update(credential_revision, result))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn new_service_does_not_connect_or_query_and_confirmation_precedes_paths() {
        let mut service = UsageService::default();
        assert_eq!(
            service.query_codex(false).unwrap_err().code,
            "CONFIRM_REQUIRED"
        );
        assert_eq!(
            service.query_codex(true).unwrap_err().code,
            "CLI_NOT_CONNECTED"
        );
        assert_eq!(
            service
                .configure_codex(
                    Path::new("TEST_ONLY_CLI"),
                    Path::new("TEST_ONLY_PROFILE"),
                    false
                )
                .unwrap_err()
                .code,
            "CONFIRM_REQUIRED"
        );
    }
    #[test]
    fn windows_shims_are_rejected_without_shell_execution() {
        let mut service = UsageService::default();
        let profile = tempfile::tempdir().unwrap();
        let shim = profile.path().join("TEST_ONLY_CLI.cmd");
        std::fs::write(&shim, b"TEST_ONLY never executable").unwrap();
        assert_eq!(
            service
                .configure_codex(&shim, profile.path(), true)
                .unwrap_err()
                .code,
            "CLI_SHIM"
        );
        assert!(service.connection.is_none());
    }
}
