//! Explicit one-owner handoff. Prepared destination caches/venvs are inactive;
//! the existing journal owns the source marker, client changes and both receipts.
use super::*;

const RESERVATION: &str = "state/relocation.json";
const RETIRED: &str = "state/relocated.json";

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Reservation {
    schema_version: u32,
    source_home: PathBuf,
    destination_home: PathBuf,
    selected_identity: String,
    previous: State,
    completed: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RelocationPlan {
    pub source_home: PathBuf,
    pub destination_home: PathBuf,
    pub targets: Vec<String>,
    pub runtime_groups: Vec<String>,
    pub files: Vec<PathBuf>,
    #[serde(skip)]
    reservation: Reservation,
    #[serde(skip)]
    reservation_before: Option<Node>,
    #[serde(skip)]
    source_before: Node,
    #[serde(skip)]
    bundle: source::Bundle,
    #[serde(skip)]
    projection: Plan,
}

fn incomplete() -> Error {
    Error::new("HARNESS_RELOCATION_PENDING", "目标 manager 正在准备迁移；请继续显式 migrate 或在目标 home 执行 recover，不能启动第二个 owner。")
}
fn moved() -> Error {
    Error::new("HARNESS_HOME_RELOCATED", "该 manager 已交接或正在交接；查看 state/relocated.json，并在目标 home 执行 status 或 recover。")
}
fn reservation(home: &Path) -> Result<Option<Reservation>> {
    transaction::file_bytes(&home.join(RESERVATION))?
        .map(|bytes| {
            let record: Reservation = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
            if record.schema_version != 1
                || record.destination_home != home
                || physical_overlap(&record.source_home, &record.destination_home)
                || record.previous.schema_version != 1
                || record.previous.product != "atm-harness"
                || record.previous.source_identity.len() != 64
            {
                return Err(invalid());
            }
            transaction::safe_path(&record.source_home.join(RETIRED))?;
            // This is historical evidence. Its former client paths may have
            // legitimately changed after handoff; do not validate those paths
            // against today's filesystem as if they were the active receipt.
            Ok(record)
        })
        .transpose()
}

impl Service {
    pub(super) fn relocation_guard(&self) -> Result<()> {
        // An already-open shell may still export the former ATM_HOME after its
        // tree has been archived. The canonical owner's retained handoff record
        // prevents that stale setting from recreating the old manager directory.
        let canonical = self.user.join(".atm");
        if self.home != canonical {
            if let Some(record) = reservation(&canonical)? {
                if record.completed && record.source_home == self.home {
                    return Err(moved());
                }
            }
        }
        if transaction::snapshot(&self.home.join(RETIRED))?.is_some() {
            return Err(moved());
        }
        if let Some(record) = reservation(&self.home)? {
            if !record.completed || transaction::pending(&self.home) {
                return Err(incomplete());
            }
        }
        Ok(())
    }
    fn destination(&self, home: PathBuf) -> Result<Self> {
        let mut destination = Self::new(home, self.user.clone())?;
        destination.inherit_environment = self.inherit_environment;
        destination.target_roots = self.target_roots.clone();
        Ok(destination)
    }

    /// Read-only preview: no cache, runtime, lock, marker or target writes.
    pub fn plan_relocation(
        &self,
        destination: &Path,
        source_root: &Path,
    ) -> Result<RelocationPlan> {
        self.relocation_guard()?;
        if transaction::pending(&self.home) || transaction::pending(destination) {
            return Err(incomplete());
        }
        transaction::safe_path(&destination.join(RESERVATION))?;
        let physical_destination = physical_path(destination)?;
        if physical_overlap(&physical_path(&self.home)?, &physical_destination) {
            return Err(invalid());
        }
        // Service preserves the caller's manager path in cache references. Use
        // physical paths for overlap checks, but retain that same spelling in
        // the reservation and projection. Windows may expand an 8.3 temp path
        // during canonicalization; reopening the requested --home must still
        // match its reservation and produce an unchanged refresh plan.
        let destination = destination.to_path_buf();
        let original = self.state()?;
        // Retired hook removal is a separate explicit ownership operation.
        if original.hooks.is_some() || original.receipts.is_empty() {
            return Err(invalid());
        }
        let source_bytes = transaction::file_bytes(&self.state_path())?.ok_or_else(invalid)?;
        if encode(&decode_state(&source_bytes)?)? != encode(&original)? {
            return Err(transaction::conflict());
        }
        let source_before = Node::File(source_bytes);
        let bundle = source::load(source_root)?;
        self.bundle(&original)?;
        let previous_reservation = reservation(&destination)?;
        let reservation_before = transaction::snapshot(&destination.join(RESERVATION))?;
        if let Some(previous) = previous_reservation {
            if previous.completed
                || previous.source_home != self.home
                || previous.selected_identity != bundle.identity
                || encode(&previous.previous)? != encode(&original)?
                || transaction::snapshot(&destination.join("state/distribution.json"))?.is_some()
            {
                return Err(transaction::conflict());
            }
        } else if fs::symlink_metadata(&destination).is_ok() {
            // A fresh destination must really be absent; never adopt a user's tree.
            return Err(transaction::conflict());
        }
        let mut targets = Vec::new();
        for receipt in original.receipts.values() {
            let (_, skills) = self.root(&receipt.target)?;
            if skills.parent() != Some(receipt.root.as_path())
                || !receipt.root.is_dir()
                || physical_overlap(&receipt.root, &physical_destination)
            {
                return Err(transaction::conflict());
            }
            targets.push(receipt.target.clone());
        }
        targets.sort();
        let groups: BTreeSet<_> = bundle.manifest["runtimeGroups"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|g| g["id"].as_str())
            .collect();
        // Never silently move/rebind an external or undeclared environment.
        if original
            .runtimes
            .iter()
            .any(|(id, runtime)| runtime.external || !groups.contains(id.as_str()))
        {
            return Err(Error::new(
                "HARNESS_RUNTIME_SPEC",
                "迁移需要明确处理外部或已移除的 runtime；旧引用保持不变。",
            ));
        }
        let record = Reservation {
            schema_version: 1,
            source_home: self.home.clone(),
            destination_home: destination.clone(),
            selected_identity: bundle.identity.clone(),
            previous: original.clone(),
            completed: false,
        };
        let runtime_groups = original.runtimes.keys().cloned().collect();
        let mut desired = original;
        desired.source_identity = bundle.identity.clone();
        desired.release_version = bundle.release.clone();
        desired.runtimes.clear();
        let dest = self.destination(destination.clone())?;
        let projection =
            dest.plan_from_state("refresh", &targets, None, desired, Some(bundle.clone()))?;
        let mut files = projection.files.clone();
        files.extend([
            self.home.join(RETIRED),
            self.state_path(),
            destination.join(RESERVATION),
        ]);
        Ok(RelocationPlan {
            source_home: self.home.clone(),
            destination_home: destination,
            targets,
            runtime_groups,
            files,
            reservation: record,
            reservation_before,
            source_before,
            bundle,
            projection,
        })
    }

    /// Build final-path runtimes and journal the one-owner handoff. Neither old
    /// environments nor old caches/logs are deleted or renamed by this operation.
    pub fn relocate(
        &self,
        plan: RelocationPlan,
        python: Option<&Path>,
        offline: bool,
    ) -> Result<Value> {
        if plan.source_home != self.home
            || plan.destination_home != plan.reservation.destination_home
            || plan.projection.home != plan.destination_home
            || plan.runtime_groups
                != plan
                    .reservation
                    .previous
                    .runtimes
                    .keys()
                    .cloned()
                    .collect::<Vec<_>>()
        {
            return Err(invalid());
        }
        if !plan.runtime_groups.is_empty()
            && python.is_none_or(|p| !p.is_absolute() || !p.is_file())
        {
            return Err(Error::new(
                "HARNESS_PYTHON_REQUIRED",
                "迁移已准备的 runtime 需要明确的绝对 Python 路径；不会移动旧 venv。",
            ));
        }
        self.relocation_guard()?;
        let _source_lock = Lock::acquire(&self.home)?;
        if transaction::pending(&self.home)
            || transaction::pending(&plan.destination_home)
            || transaction::snapshot(&self.state_path())? != Some(plan.source_before.clone())
            || transaction::snapshot(&plan.destination_home.join(RESERVATION))?
                != plan.reservation_before
        {
            return Err(transaction::conflict());
        }
        let dest = self.destination(plan.destination_home.clone())?;
        if plan.reservation_before.is_none() {
            // Exclusive creation closes the absent-destination preview/apply race.
            fs::create_dir(&dest.home).map_err(|_| transaction::conflict())?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                fs::set_permissions(&dest.home, fs::Permissions::from_mode(0o700))?;
            }
        }
        let _destination_lock = Lock::acquire(&dest.home)?;
        if plan.reservation_before.is_none() {
            transaction::atomic_write(&dest.home.join(RESERVATION), &encode(&plan.reservation)?)?;
        }
        dest.cache_bundle(&plan.bundle)?;
        // Copy optional offline wheels without altering the old cache. Pip still
        // validates every selected dependency against the content's existing lock.
        let old_wheels = self.home.join("cache/wheels");
        if let Some(Node::Directory(wheels)) = transaction::snapshot(&old_wheels)? {
            for (name, node) in wheels {
                let Node::File(bytes) = node else {
                    return Err(transaction::conflict());
                };
                let path = dest.home.join("cache/wheels").join(name);
                match transaction::snapshot(&path)? {
                    None => transaction::apply(
                        &dest.home,
                        vec![Change {
                            path,
                            before: None,
                            after: Some(Node::File(bytes)),
                        }],
                    )?,
                    Some(Node::File(existing)) if existing == bytes => (),
                    _ => return Err(transaction::conflict()),
                }
            }
        }
        let mut runtimes = BTreeMap::new();
        for id in &plan.runtime_groups {
            let spec: runtime::RuntimeSpec = serde_json::from_value(
                plan.bundle.manifest["runtimeGroups"]
                    .as_array()
                    .and_then(|g| g.iter().find(|g| g["id"] == *id))
                    .cloned()
                    .ok_or_else(invalid)?,
            )
            .map_err(|_| invalid())?;
            let prepared = runtime::prepare(
                &dest.home,
                &dest.cache(&plan.bundle.identity),
                &spec,
                python.ok_or_else(invalid)?,
                None,
                offline,
            )?;
            runtimes.insert(id.clone(), prepared);
        }
        let changes = self.relocation_changes(&plan, runtimes)?;
        for guard in &plan.projection.guards {
            if transaction::snapshot(&guard.path)? != guard.before {
                return Err(transaction::conflict());
            }
        }
        transaction::apply(&dest.home, changes)?;
        Ok(
            json!({"migrated":true,"sourceHome":self.home,"destinationHome":dest.home,
            "recoveryRecord":dest.home.join(RESERVATION),"oldDataRetained":true,"status":dest.status()?}),
        )
    }

    fn relocation_changes(
        &self,
        plan: &RelocationPlan,
        runtimes: BTreeMap<String, runtime::PreparedRuntime>,
    ) -> Result<Vec<Change>> {
        let mut changes = vec![Change {
            path: self.home.join(RETIRED),
            before: None,
            after: Some(Node::File(encode(
                &json!({"schemaVersion":1,"destinationHome":plan.destination_home}),
            )?)),
        }];
        let mut projection = plan.projection.changes.clone();
        let mut receipt = projection.pop().ok_or_else(invalid)?;
        let Some(Node::File(bytes)) = &receipt.after else {
            return Err(invalid());
        };
        let mut state = decode_state(bytes)?;
        state.runtimes = runtimes;
        receipt.after = Some(Node::File(encode(&state)?));
        changes.extend(projection);
        changes.push(Change {
            path: self.state_path(),
            before: Some(plan.source_before.clone()),
            after: None,
        });
        changes.push(receipt);
        let mut complete = plan.reservation.clone();
        complete.completed = true;
        changes.push(Change {
            path: plan.destination_home.join(RESERVATION),
            before: Some(Node::File(encode(&plan.reservation)?)),
            after: Some(Node::File(encode(&complete)?)),
        });
        Ok(changes)
    }

    pub(super) fn recover_relocation(&self) -> Result<Option<Value>> {
        let Some(record) = reservation(&self.home)? else {
            return Ok(None);
        };
        if record.completed && !transaction::pending(&self.home) {
            return Ok(Some(self.status()?));
        }
        if !record.source_home.is_dir() {
            return Err(transaction::conflict());
        }
        let _source_lock = Lock::acquire(&record.source_home)?;
        let _destination_lock = Lock::acquire(&self.home)?;
        transaction::recover(&self.home)?;
        let complete = reservation(&self.home)?.ok_or_else(invalid)?.completed;
        if !complete
            && (transaction::snapshot(&record.source_home.join(RETIRED))?.is_some()
                || transaction::file_bytes(&record.source_home.join("state/distribution.json"))?
                    .map(|bytes| decode_state(&bytes).and_then(|state| encode(&state)))
                    .transpose()?
                    != Some(encode(&record.previous)?))
        {
            return Err(transaction::conflict());
        }
        Ok(Some(if complete {
            self.status()?
        } else {
            json!({"recovered":true,"activeHome":record.source_home,"destinationPrepared":true,
                "message":"原 owner 已恢复；保留的目标缓存/venv 可供显式 migrate 重试。"})
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn interrupted_handoff_restores_one_owner_at_every_boundary_and_preserves_user_edits() {
        for checkpoint in 0..=5 {
            let temp = tempfile::tempdir().unwrap();
            let old = temp.path().join("old");
            let new = temp.path().join("new");
            let client = temp.path().join("client.txt");
            let service = Service::new(old.clone(), temp.path().join("user")).unwrap();
            let destination = service.destination(new.clone()).unwrap();
            let state = State {
                schema_version: 1,
                product: "atm-harness".into(),
                source_identity: "a".repeat(64),
                release_version: "1".into(),
                receipts: BTreeMap::new(),
                runtimes: BTreeMap::new(),
                hooks: None,
                adopted_legacy: None,
            };
            let record = Reservation {
                schema_version: 1,
                source_home: old.clone(),
                destination_home: new.clone(),
                selected_identity: state.source_identity.clone(),
                previous: state.clone(),
                completed: false,
            };
            transaction::atomic_write(
                &old.join("state/distribution.json"),
                &encode(&state).unwrap(),
            )
            .unwrap();
            transaction::atomic_write(&new.join(RESERVATION), &encode(&record).unwrap()).unwrap();
            fs::write(&client, b"old source reference").unwrap();
            let projection = Plan {
                operation: "refresh".into(),
                targets: vec![],
                files: vec![client.clone()],
                home: new.clone(),
                guards: vec![],
                changes: vec![
                    Change {
                        path: client.clone(),
                        before: Some(Node::File(b"old source reference".to_vec())),
                        after: Some(Node::File(b"new source reference".to_vec())),
                    },
                    Change {
                        path: new.join("state/distribution.json"),
                        before: None,
                        after: Some(Node::File(encode(&state).unwrap())),
                    },
                ],
            };
            let plan = RelocationPlan {
                source_home: old.clone(),
                destination_home: new.clone(),
                targets: vec![],
                runtime_groups: vec![],
                files: vec![],
                reservation: record,
                reservation_before: None,
                source_before: Node::File(encode(&state).unwrap()),
                projection,
                bundle: source::Bundle {
                    identity: state.source_identity.clone(),
                    release: "1".into(),
                    files: BTreeMap::new(),
                    catalog: json!({}),
                    manifest: json!({}),
                },
            };
            let changes = service.relocation_changes(&plan, BTreeMap::new()).unwrap();
            assert_eq!(changes.len(), 5);
            transaction::interrupt_after(&new, changes, checkpoint).unwrap();
            assert!(
                destination.status().is_err(),
                "incomplete destination must not act as owner"
            );
            if checkpoint > 0 {
                assert!(
                    service.status().is_err(),
                    "retired source must refuse operations"
                );
            }
            if checkpoint == 2 {
                fs::write(&client, b"post-crash user edit").unwrap();
                assert!(destination.recover().is_err());
                assert_eq!(fs::read(&client).unwrap(), b"post-crash user edit");
                assert!(transaction::pending(&new));
                assert!(new.join(RESERVATION).is_file());
                // Restore only the test-owned edit before exercising explicit recovery.
                fs::write(&client, b"new source reference").unwrap();
            }
            destination.recover().unwrap();
            assert_eq!(fs::read(&client).unwrap(), b"old source reference");
            assert!(old.join("state/distribution.json").exists());
            assert!(!old.join(RETIRED).exists());
            assert!(!new.join("state/distribution.json").exists());
            assert!(!transaction::pending(&new));
            assert!(service.status().is_ok());
            assert_eq!(
                destination.status().unwrap_err().code,
                "HARNESS_RELOCATION_PENDING"
            );
        }
    }
}
