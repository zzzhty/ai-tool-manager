use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::fmt;
use uuid::Uuid;
use zeroize::Zeroizing;

#[derive(Clone, Serialize, Deserialize)]
#[serde(transparent)]
pub(crate) struct Secret(pub(crate) Zeroizing<String>);
impl fmt::Debug for Secret {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("Secret([REDACTED])")
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "PascalCase")]
pub(crate) struct KeyEntry {
    pub id: Uuid,
    pub name: String,
    pub secret: Secret,
    pub updated_utc: DateTime<Utc>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "PascalCase")]
pub struct TargetMapping {
    pub id: Uuid,
    pub label: String,
    pub file_path: String,
    pub pointer: String,
    pub key_id: Uuid,
    #[serde(default)]
    pub bearer_prefix: bool,
    #[serde(default)]
    pub replace_variables: bool,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "PascalCase")]
pub(crate) struct VaultDocument {
    pub version: u32,
    pub keys: Vec<KeyEntry>,
    pub targets: Vec<TargetMapping>,
}
impl Default for VaultDocument {
    fn default() -> Self {
        Self {
            version: 1,
            keys: Vec::new(),
            targets: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct KeyView {
    pub id: Uuid,
    pub name: String,
    pub mask: &'static str,
    pub updated_utc: DateTime<Utc>,
}
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SnapshotView {
    pub keys: Vec<KeyView>,
    pub targets: Vec<TargetMapping>,
}
