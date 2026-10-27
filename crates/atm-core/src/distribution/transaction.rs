//! Durable multi-file journal. Recovery never overwrites post-crash user edits.
//! Directory/type changes use complete sibling stages and retained before-images;
//! the live target is never filled recursively. Cross-file visibility is not atomic.
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions},
    io::{self, Write},
    path::{Component, Path, PathBuf},
};

const MAX_BYTES: usize = 64 * 1024 * 1024;
const MAX_NODES: usize = 100_000;
// Each directory adds several JSON containers; stay below serde_json's bounded recursion limit.
const MAX_DEPTH: usize = 32;
const JOURNAL_SCHEMA: u32 = 2;
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", content = "value", rename_all = "camelCase")]
pub enum Node {
    File(Vec<u8>),
    Symlink(PathBuf),
    Directory(BTreeMap<String, Node>),
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Change {
    pub path: PathBuf,
    pub before: Option<Node>,
    pub after: Option<Node>,
}
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Journal {
    schema_version: u32,
    product: String,
    transaction_id: String,
    changes: Vec<Change>,
    committed: bool,
}

pub fn conflict() -> Error {
    Error::new(
        "HARNESS_CONFLICT",
        "受管文件已修改、同名目标已有其他所有者，或路径不安全；已保留现状。",
    )
}
fn bounded() -> Error {
    Error::new(
        "HARNESS_TRANSACTION_SIZE",
        "分发事务超出大小、深度或条目上限；尚未开始目标写入。",
    )
}
fn special(meta: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        meta.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        meta.file_type().is_symlink()
    }
}
pub fn safe_path(path: &Path) -> Result<()> {
    if !path.is_absolute()
        || path
            .components()
            .any(|p| matches!(p, Component::ParentDir | Component::CurDir))
        || path.to_string_lossy().chars().any(char::is_control)
    {
        return Err(conflict());
    }
    let mut current = PathBuf::new();
    let parts: Vec<_> = path.components().collect();
    for part in parts.iter().take(parts.len().saturating_sub(1)) {
        current.push(part.as_os_str());
        match fs::symlink_metadata(&current) {
            Ok(meta) if !meta.is_dir() || special(&meta) => return Err(conflict()),
            Ok(_) => (),
            Err(error) if error.kind() == io::ErrorKind::NotFound => (),
            Err(error) => return Err(error.into()),
        }
    }
    Ok(())
}
fn name_valid(name: &str) -> bool {
    !name.is_empty()
        && !name.contains(['/', '\\', ':'])
        && !name.chars().any(char::is_control)
        && name != "."
        && name != ".."
        && Path::new(name)
            .components()
            .all(|c| matches!(c, Component::Normal(_)))
}
#[derive(Default)]
struct Budget {
    bytes: usize,
    nodes: usize,
}
impl Budget {
    fn node(&mut self, depth: usize) -> Result<()> {
        self.nodes = self.nodes.checked_add(1).ok_or_else(bounded)?;
        if self.nodes > MAX_NODES || depth > MAX_DEPTH {
            return Err(bounded());
        }
        Ok(())
    }
    fn bytes(&mut self, amount: usize) -> Result<()> {
        self.bytes = self.bytes.checked_add(amount).ok_or_else(bounded)?;
        if self.bytes > MAX_BYTES {
            return Err(bounded());
        }
        Ok(())
    }
}
fn snapshot_at(path: &Path, budget: &mut Budget, depth: usize) -> Result<Option<Node>> {
    safe_path(path)?;
    let metadata = match fs::symlink_metadata(path) {
        Ok(value) => value,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    budget.node(depth)?;
    if special(&metadata) {
        return Ok(Some(Node::Symlink(fs::read_link(path)?)));
    }
    if metadata.is_file() {
        if metadata.len() > MAX_BYTES as u64 {
            return Err(bounded());
        }
        let bytes = fs::read(path)?;
        budget.bytes(bytes.len())?;
        return Ok(Some(Node::File(bytes)));
    }
    if metadata.is_dir() {
        let mut entries = BTreeMap::new();
        let mut names = BTreeSet::new();
        for entry in fs::read_dir(path)? {
            let entry = entry?;
            let name = entry.file_name().into_string().map_err(|_| conflict())?;
            if !name_valid(&name) || !names.insert(name.to_lowercase()) {
                return Err(conflict());
            }
            let value = snapshot_at(&entry.path(), budget, depth + 1)?.ok_or_else(conflict)?;
            entries.insert(name, value);
        }
        return Ok(Some(Node::Directory(entries)));
    }
    Err(conflict())
}
pub fn snapshot(path: &Path) -> Result<Option<Node>> {
    snapshot_at(path, &mut Budget::default(), 0)
}
pub fn file_bytes(path: &Path) -> Result<Option<Vec<u8>>> {
    match snapshot(path)? {
        None => Ok(None),
        Some(Node::File(bytes)) => Ok(Some(bytes)),
        _ => Err(conflict()),
    }
}
pub struct Lock {
    _file: File,
}
impl Lock {
    pub fn acquire(home: &Path) -> Result<Self> {
        let path = home.join("state/manager.lock");
        safe_path(&path)?;
        match fs::symlink_metadata(&path) {
            Ok(meta) if !meta.is_file() || special(&meta) => return Err(conflict()),
            Ok(_) => (),
            Err(error) if error.kind() == io::ErrorKind::NotFound => (),
            Err(error) => return Err(error.into()),
        }
        fs::create_dir_all(path.parent().ok_or_else(conflict)?)?;
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.custom_flags(libc::O_NOFOLLOW);
        }
        let file = options.open(path)?;
        file.try_lock().map_err(|_| {
            Error::new(
                "HARNESS_BUSY",
                "分发锁被其他进程占用或无法获取；未启动操作。",
            )
        })?;
        Ok(Self { _file: file })
    }
}
fn sync_directory(path: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        File::open(path)?.sync_all()?;
    }
    #[cfg(not(unix))]
    {
        let _ = path;
    }
    Ok(())
}
#[cfg(windows)]
fn native_path(path: &Path) -> Result<PathBuf> {
    // std::fs supplies the extended DOS/UNC prefix required by Win32 for long
    // paths. Resolve only the existing parent: the leaf can itself be a link
    // being moved, and resolving that leaf would mutate its destination.
    let parent = path.parent().ok_or_else(conflict)?;
    let leaf = path.file_name().ok_or_else(conflict)?;
    Ok(fs::canonicalize(parent)?.join(leaf))
}

/// Rename without replacing a newly appeared destination. Unsupported native
/// operations fail closed; there is no check-then-overwrite fallback.
pub(super) fn rename_exclusive(from: &Path, to: &Path) -> Result<()> {
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    {
        use std::{ffi::CString, os::unix::ffi::OsStrExt};
        let from = CString::new(from.as_os_str().as_bytes()).map_err(|_| conflict())?;
        let to = CString::new(to.as_os_str().as_bytes()).map_err(|_| conflict())?;
        #[cfg(target_os = "linux")]
        let status = unsafe {
            libc::renameat2(
                libc::AT_FDCWD,
                from.as_ptr(),
                libc::AT_FDCWD,
                to.as_ptr(),
                libc::RENAME_NOREPLACE,
            )
        };
        #[cfg(target_os = "macos")]
        let status = unsafe { libc::renamex_np(from.as_ptr(), to.as_ptr(), libc::RENAME_EXCL) };
        if status != 0 {
            return Err(io::Error::last_os_error().into());
        }
        Ok(())
    }
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        #[link(name = "kernel32")]
        extern "system" {
            fn MoveFileExW(from: *const u16, to: *const u16, flags: u32) -> i32;
        }
        let from: Vec<u16> = native_path(from)?
            .as_os_str()
            .encode_wide()
            .chain(Some(0))
            .collect();
        let to: Vec<u16> = native_path(to)?
            .as_os_str()
            .encode_wide()
            .chain(Some(0))
            .collect();
        if unsafe { MoveFileExW(from.as_ptr(), to.as_ptr(), 0) } == 0 {
            return Err(io::Error::last_os_error().into());
        }
        Ok(())
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos", windows)))]
    {
        let _ = (from, to);
        Err(Error::new(
            "HARNESS_PLATFORM",
            "此平台缺少安全的排他重命名实现。",
        ))
    }
}

pub fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    safe_path(path)?;
    let parent = path.parent().ok_or_else(conflict)?;
    fs::create_dir_all(parent)?;
    let original = snapshot(path)?;
    let exists = match &original {
        Some(Node::File(_)) => true,
        None => false,
        _ => return Err(conflict()),
    };
    let temporary = parent.join(format!(".atm-write-{}", uuid::Uuid::new_v4()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        if snapshot(path)? != original {
            return Err(conflict());
        }
        #[cfg(windows)]
        {
            if exists {
                crate::windows::replace(&native_path(&temporary)?, &native_path(path)?)?;
            } else {
                rename_exclusive(&temporary, path)?;
            }
        }
        #[cfg(not(windows))]
        {
            if exists {
                fs::rename(&temporary, path)?;
            } else {
                rename_exclusive(&temporary, path)?;
            }
        }
        sync_directory(parent)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn validate_node(node: &Node, budget: &mut Budget, depth: usize) -> Result<()> {
    budget.node(depth)?;
    match node {
        Node::File(bytes) => budget.bytes(bytes.len())?,
        Node::Symlink(target) => {
            if target.as_os_str().is_empty()
                || target.to_string_lossy().chars().any(char::is_control)
            {
                return Err(conflict());
            }
        }
        Node::Directory(entries) => {
            let mut names = BTreeSet::new();
            for (name, child) in entries {
                if !name_valid(name) || !names.insert(name.to_lowercase()) {
                    return Err(conflict());
                }
                validate_node(child, budget, depth + 1)?;
            }
        }
    }
    Ok(())
}
fn overlap(a: &Path, b: &Path) -> bool {
    // Also reject case aliases on Unix so a plan has the same ownership contract
    // when validated or resumed on a case-insensitive supported filesystem.
    let a = a.to_string_lossy().replace('\\', "/").to_lowercase();
    let b = b.to_string_lossy().replace('\\', "/").to_lowercase();
    a == b || a.starts_with(&(b.clone() + "/")) || b.starts_with(&(a + "/"))
}
fn journal_path(home: &Path) -> PathBuf {
    home.join("state/rust-journal.json")
}
fn needs_swap(change: &Change) -> bool {
    if change.before == change.after {
        return false;
    }
    matches!(change.before, Some(Node::Directory(_) | Node::Symlink(_)))
        || matches!(change.after, Some(Node::Directory(_) | Node::Symlink(_)))
        || (change.before.is_some()
            && change.after.is_some()
            && !matches!(
                (&change.before, &change.after),
                (Some(Node::File(_)), Some(Node::File(_)))
            ))
}
fn custody(journal: &Journal, index: usize) -> Result<PathBuf> {
    Ok(journal.changes[index]
        .path
        .parent()
        .ok_or_else(conflict)?
        .join(format!(
            ".atm-transaction-{}-{index}",
            journal.transaction_id
        )))
}
fn owner_bytes(journal: &Journal, index: usize) -> Result<Vec<u8>> {
    serde_json::to_vec(&(&journal.transaction_id, index, &journal.changes[index].path))
        .map_err(|_| conflict())
}
fn validate_journal(home: &Path, journal: &Journal) -> Result<()> {
    if journal.schema_version != JOURNAL_SCHEMA
        || journal.product != "atm-harness"
        || uuid::Uuid::parse_str(&journal.transaction_id)
            .map(|id| id.to_string() != journal.transaction_id)
            .unwrap_or(true)
        || journal.changes.len() > MAX_NODES
    {
        return Err(conflict());
    }
    let mut budget = Budget::default();
    let reserved = [journal_path(home), home.join("state/manager.lock")];
    for (index, change) in journal.changes.iter().enumerate() {
        safe_path(&change.path)?;
        if change.path.file_name().is_none()
            || reserved.iter().any(|p| overlap(p, &change.path))
            || journal.changes[..index]
                .iter()
                .any(|old| overlap(&old.path, &change.path))
        {
            return Err(conflict());
        }
        for node in [&change.before, &change.after].into_iter().flatten() {
            validate_node(node, &mut budget, 0)?;
        }
        if needs_swap(change) {
            let root = custody(journal, index)?;
            safe_path(&root)?;
            if journal
                .changes
                .iter()
                .any(|other| overlap(&root, &other.path))
            {
                return Err(conflict());
            }
        }
    }
    Ok(())
}
struct LimitedBytes(Vec<u8>);
impl Write for LimitedBytes {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > MAX_BYTES.saturating_sub(self.0.len()) {
            return Err(io::Error::other("journal exceeds limit"));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
fn encode_journal(journal: &Journal) -> Result<Vec<u8>> {
    let mut bytes = LimitedBytes(Vec::new());
    serde_json::to_writer(&mut bytes, journal).map_err(|_| bounded())?;
    Ok(bytes.0)
}

/// Writes only a private stage, never a live destination. Partial files can be
/// recognized as prefixes of the intended payload after interruption.
fn stage_node(path: &Path, node: &Node) -> Result<()> {
    safe_path(path)?;
    match node {
        Node::File(bytes) => {
            let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
            file.write_all(bytes)?;
            file.sync_all()?;
        }
        Node::Directory(entries) => {
            fs::create_dir(path)?;
            for (name, child) in entries {
                stage_node(&path.join(name), child)?;
            }
            sync_directory(path)?;
        }
        Node::Symlink(target) => {
            #[cfg(unix)]
            {
                std::os::unix::fs::symlink(target, path)?;
            }
            #[cfg(windows)]
            {
                let destination = if target.is_absolute() {
                    target.clone()
                } else {
                    path.parent().ok_or_else(conflict)?.join(target)
                };
                if destination.is_dir() {
                    std::os::windows::fs::symlink_dir(target, path)?;
                } else {
                    std::os::windows::fs::symlink_file(target, path)?;
                }
            }
        }
    }
    Ok(())
}
fn partial_matches(actual: &Node, expected: &Node, allow_prefix: bool) -> bool {
    match (actual, expected) {
        (Node::File(a), Node::File(e)) => {
            if allow_prefix {
                e.starts_with(a)
            } else {
                a == e
            }
        }
        (Node::Symlink(a), Node::Symlink(e)) => a == e,
        (Node::Directory(a), Node::Directory(e)) => a.iter().all(|(name, child)| {
            e.get(name)
                .is_some_and(|expected| partial_matches(child, expected, allow_prefix))
        }),
        _ => false,
    }
}
fn known_subset(actual: &Option<Node>, expected: &Option<Node>, allow_prefix: bool) -> bool {
    match (actual, expected) {
        (None, _) => true,
        (Some(a), Some(e)) => partial_matches(a, e, allow_prefix),
        _ => false,
    }
}
#[derive(Debug)]
struct Custody {
    root: PathBuf,
    present: bool,
    old: Option<Node>,
    new: Option<Node>,
}
fn inspect_custody(journal: &Journal, index: usize) -> Result<Custody> {
    let root = custody(journal, index)?;
    let actual = snapshot(&root)?;
    let Some(Node::Directory(entries)) = actual else {
        if actual.is_some() {
            return Err(conflict());
        }
        return Ok(Custody {
            root,
            present: false,
            old: None,
            new: None,
        });
    };
    if entries
        .keys()
        .any(|key| !["owner.json", "old", "new"].contains(&key.as_str()))
    {
        return Err(conflict());
    }
    let owner = owner_bytes(journal, index)?;
    match entries.get("owner.json") {
        Some(Node::File(bytes)) if bytes == &owner => (),
        Some(Node::File(bytes)) if owner.starts_with(bytes) && entries.len() == 1 => (),
        None if entries.is_empty() => (),
        _ => return Err(conflict()),
    }
    Ok(Custody {
        root,
        present: true,
        old: entries.get("old").cloned(),
        new: entries.get("new").cloned(),
    })
}
fn rename_checked(from: &Path, to: &Path, expected: &Node) -> Result<()> {
    if snapshot(from)? != Some(expected.clone()) || snapshot(to)?.is_some() {
        return Err(conflict());
    }
    rename_exclusive(from, to)?;
    sync_directory(from.parent().ok_or_else(conflict)?)?;
    if to.parent() != from.parent() {
        sync_directory(to.parent().ok_or_else(conflict)?)?;
    }
    Ok(())
}
fn forward_swap(journal: &Journal, index: usize) -> Result<()> {
    let change = &journal.changes[index];
    let root = custody(journal, index)?;
    if snapshot(&change.path)? != change.before || snapshot(&root)?.is_some() {
        return Err(conflict());
    }
    fs::create_dir_all(root.parent().ok_or_else(conflict)?)?;
    fs::create_dir(&root)?;
    stage_node(
        &root.join("owner.json"),
        &Node::File(owner_bytes(journal, index)?),
    )?;
    if let Some(after) = &change.after {
        stage_node(&root.join("new"), after)?;
    }
    sync_directory(&root)?;
    if snapshot(&root.join("new"))? != change.after {
        return Err(conflict());
    }
    if let Some(before) = &change.before {
        rename_checked(&change.path, &root.join("old"), before)?;
    }
    if let Some(after) = &change.after {
        rename_checked(&root.join("new"), &change.path, after)?;
    }
    Ok(())
}
fn preflight_swap_rollback(journal: &Journal, index: usize) -> Result<()> {
    let change = &journal.changes[index];
    let target = snapshot(&change.path)?;
    let custody = inspect_custody(journal, index)?;
    if !known_subset(&custody.new, &change.after, true) {
        return Err(conflict());
    }
    if target == change.before && custody.old.is_none() {
        return Ok(());
    }
    if !custody.present || custody.old != change.before {
        return Err(conflict());
    }
    if target.is_none() {
        return Ok(());
    }
    if target == change.after && custody.new.is_none() {
        return Ok(());
    }
    Err(conflict())
}
fn rollback_swap(journal: &Journal, index: usize) -> Result<()> {
    preflight_swap_rollback(journal, index)?;
    let change = &journal.changes[index];
    let mut actual = snapshot(&change.path)?;
    if actual == change.before {
        return Ok(());
    }
    let root = custody(journal, index)?;
    if let Some(after) = &actual {
        rename_checked(&change.path, &root.join("new"), after)?;
        actual = None;
    }
    if actual.is_none() {
        if let Some(before) = &change.before {
            rename_checked(&root.join("old"), &change.path, before)?;
        }
    }
    Ok(())
}
fn remove_exact(path: &Path, expected: &Node) -> Result<()> {
    if snapshot(path)? != Some(expected.clone()) {
        return Err(conflict());
    }
    match expected {
        Node::Directory(entries) => {
            for (name, child) in entries {
                remove_exact(&path.join(name), child)?;
            }
            fs::remove_dir(path)?;
        }
        Node::File(_) => fs::remove_file(path)?,
        Node::Symlink(_) => {
            #[cfg(windows)]
            {
                use std::os::windows::fs::MetadataExt;
                if fs::symlink_metadata(path)?.file_attributes() & 0x10 != 0 {
                    fs::remove_dir(path)?;
                } else {
                    fs::remove_file(path)?;
                }
            }
            #[cfg(not(windows))]
            {
                fs::remove_file(path)?;
            }
        }
    }
    Ok(())
}
fn cleanup_swap(journal: &Journal, index: usize) -> Result<()> {
    let change = &journal.changes[index];
    let custody = inspect_custody(journal, index)?;
    if !custody.present {
        return Ok(());
    }
    if journal.committed {
        if !known_subset(&custody.old, &change.before, false) || custody.new.is_some() {
            return Err(conflict());
        }
    } else if custody.old.is_some() || !known_subset(&custody.new, &change.after, true) {
        return Err(conflict());
    }
    // Removing known leaves is restartable: a crash leaves a known subset.
    if let Some(old) = custody.old {
        remove_exact(&custody.root.join("old"), &old)?;
    }
    if let Some(new) = custody.new {
        remove_exact(&custody.root.join("new"), &new)?;
    }
    if let Some(owner) = snapshot(&custody.root.join("owner.json"))? {
        remove_exact(&custody.root.join("owner.json"), &owner)?;
    }
    fs::remove_dir(&custody.root)?;
    sync_directory(custody.root.parent().ok_or_else(conflict)?)
}
fn replace_simple(change: &Change, forward: bool) -> Result<()> {
    let (before, after) = if forward {
        (&change.before, &change.after)
    } else {
        (&change.after, &change.before)
    };
    let actual = snapshot(&change.path)?;
    if &actual == after {
        return Ok(());
    }
    if &actual != before {
        return Err(conflict());
    }
    match after {
        Some(Node::File(bytes)) => atomic_write(&change.path, bytes)?,
        Some(Node::Symlink(target)) => stage_node(&change.path, &Node::Symlink(target.clone()))?,
        None => {
            if let Some(before) = before {
                remove_exact(&change.path, before)?;
                sync_directory(change.path.parent().ok_or_else(conflict)?)?;
            }
        }
        Some(Node::Directory(_)) => return Err(conflict()),
    }
    Ok(())
}
pub fn pending(home: &Path) -> bool {
    !matches!(fs::symlink_metadata(journal_path(home)), Err(e) if e.kind() == io::ErrorKind::NotFound)
}
pub fn recover(home: &Path) -> Result<()> {
    let path = journal_path(home);
    let Some(bytes) = file_bytes(&path)? else {
        return Ok(());
    };
    let journal: Journal = serde_json::from_slice(&bytes).map_err(|_| conflict())?;
    validate_journal(home, &journal)?;
    if !journal.committed {
        // Validate the entire rollback first, including every custody before-image.
        for (index, change) in journal.changes.iter().enumerate() {
            if needs_swap(change) {
                preflight_swap_rollback(&journal, index)?;
            } else {
                let actual = snapshot(&change.path)?;
                if actual != change.before && actual != change.after {
                    return Err(conflict());
                }
            }
        }
        for (index, change) in journal.changes.iter().enumerate().rev() {
            if needs_swap(change) {
                rollback_swap(&journal, index)?;
            } else if snapshot(&change.path)? == change.after {
                replace_simple(change, false)?;
            }
        }
    }
    for (index, change) in journal.changes.iter().enumerate() {
        if needs_swap(change) {
            cleanup_swap(&journal, index)?;
        }
    }
    if file_bytes(&path)? != Some(bytes) {
        return Err(conflict());
    }
    fs::remove_file(&path)?;
    sync_directory(path.parent().ok_or_else(conflict)?)
}
fn preflight_journal(home: &Path, journal: &Journal) -> Result<Vec<u8>> {
    if pending(home) {
        return Err(Error::new(
            "HARNESS_RECOVERY_REQUIRED",
            "发现未完成的分发 journal；请先执行 atm harness recover。",
        ));
    }
    validate_journal(home, journal)?;
    // Bound serialized bytes before the first journal or target write.
    let encoded = encode_journal(journal)?;
    for (index, change) in journal.changes.iter().enumerate() {
        if snapshot(&change.path)? != change.before {
            return Err(conflict());
        }
        if needs_swap(change) && snapshot(&custody(journal, index)?)?.is_some() {
            return Err(conflict());
        }
    }
    Ok(encoded)
}

/// Validate an intended journal, including bounded serialization and exact
/// current snapshots, without creating a lock, stage, journal or target file.
pub fn validate_plan(home: &Path, changes: &[Change]) -> Result<()> {
    let journal = Journal {
        schema_version: JOURNAL_SCHEMA,
        product: "atm-harness".into(),
        transaction_id: uuid::Uuid::new_v4().to_string(),
        changes: changes.to_vec(),
        committed: false,
    };
    preflight_journal(home, &journal)?;
    Ok(())
}

pub fn apply(home: &Path, changes: Vec<Change>) -> Result<()> {
    let mut journal = Journal {
        schema_version: JOURNAL_SCHEMA,
        product: "atm-harness".into(),
        transaction_id: uuid::Uuid::new_v4().to_string(),
        changes,
        committed: false,
    };
    let encoded = preflight_journal(home, &journal)?;
    let path = journal_path(home);
    atomic_write(&path, &encoded)?;
    for (index, change) in journal.changes.iter().enumerate() {
        let result = if needs_swap(change) {
            forward_swap(&journal, index)
        } else {
            replace_simple(change, true)
        };
        if let Err(error) = result {
            if recover(home).is_err() {
                return Err(Error::new(
                    "HARNESS_RECOVERY_REQUIRED",
                    "操作失败且恢复仍需处理；journal 和未确认所有权的文件已保留。",
                ));
            }
            return Err(error);
        }
    }
    journal.committed = true;
    atomic_write(&path, &encode_journal(&journal)?)?;
    // A committed journal only owns cleanup; subsequent recovery must not undo
    // already committed receipts, including if the user edits a target now.
    recover(home)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn journal(changes: Vec<Change>) -> Journal {
        Journal {
            schema_version: JOURNAL_SCHEMA,
            product: "atm-harness".into(),
            transaction_id: uuid::Uuid::new_v4().to_string(),
            changes,
            committed: false,
        }
    }
    fn save(home: &Path, journal: &Journal) {
        atomic_write(&journal_path(home), &encode_journal(journal).unwrap()).unwrap();
    }
    fn directory() -> Node {
        Node::Directory(BTreeMap::from([
            ("SKILL.md".into(), Node::File(b"new skill".to_vec())),
            (
                "nested".into(),
                Node::Directory(BTreeMap::from([(
                    "helper.py".into(),
                    Node::File(b"helper".to_vec()),
                )])),
            ),
        ]))
    }
    fn stage_for(journal: &Journal) -> PathBuf {
        let root = custody(journal, 0).unwrap();
        fs::create_dir(&root).unwrap();
        stage_node(
            &root.join("owner.json"),
            &Node::File(owner_bytes(journal, 0).unwrap()),
        )
        .unwrap();
        root
    }
    #[test]
    #[cfg(windows)]
    fn native_file_and_directory_operations_support_long_unicode_paths() {
        use std::os::windows::ffi::OsStrExt;
        let temp = tempfile::tempdir().unwrap();
        let mut parent = temp.path().to_path_buf();
        for index in 0..5 {
            parent.push(format!("{index}-{}", "payload-path-".repeat(4)));
        }
        fs::create_dir_all(&parent).unwrap();
        let path = parent.join("技能 file.txt");
        assert!(path.as_os_str().encode_wide().count() > 260);
        atomic_write(&path, b"first").unwrap();
        atomic_write(&path, b"replacement").unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"replacement");
        let collision = parent.join("existing.txt");
        fs::write(&collision, b"user").unwrap();
        assert!(rename_exclusive(&path, &collision).is_err());
        assert_eq!(fs::read(&collision).unwrap(), b"user");
        assert_eq!(fs::read(&path).unwrap(), b"replacement");
        let directory = parent.join("技能 directory");
        fs::create_dir(&directory).unwrap();
        fs::write(directory.join("content"), b"payload").unwrap();
        let moved = parent.join("moved directory");
        rename_exclusive(&directory, &moved).unwrap();
        assert_eq!(fs::read(moved.join("content")).unwrap(), b"payload");
    }

    #[test]
    fn missing_root_retirement_recovers_each_boundary_and_refuses_reappearance() {
        for checkpoint in 0..=3 {
            let temp = tempfile::tempdir().unwrap();
            let home = temp.path();
            let root = home.join("missing-client");
            let old = home.join("state/manager.json");
            let archive = home.join("state/legacy-handoff/test/manager.json");
            let receipt = home.join("state/distribution.json");
            let old_node = Some(Node::File(b"old owner".to_vec()));
            atomic_write(&old, b"old owner").unwrap();
            let j = journal(vec![
                Change {
                    path: archive.clone(),
                    before: None,
                    after: old_node.clone(),
                },
                Change {
                    path: old.clone(),
                    before: old_node.clone(),
                    after: None,
                },
                Change {
                    path: receipt.clone(),
                    before: None,
                    after: Some(Node::File(b"new owner".to_vec())),
                },
                Change {
                    path: root.clone(),
                    before: None,
                    after: None,
                },
            ]);
            preflight_journal(home, &j).unwrap();
            save(home, &j);
            for change in j.changes.iter().take(checkpoint) {
                replace_simple(change, true).unwrap();
            }
            recover(home).unwrap();
            assert_eq!(snapshot(&old).unwrap(), old_node);
            assert!(!archive.exists());
            assert!(!receipt.exists());
            assert!(!root.exists());
            assert!(!pending(home));

            // A root returning after plan construction blocks apply before writes.
            fs::create_dir(&root).unwrap();
            fs::write(root.join("user.txt"), b"user data").unwrap();
            assert!(apply(home, j.changes.clone()).is_err());
            assert!(!pending(home));
            assert_eq!(snapshot(&old).unwrap(), old_node);

            // An interrupted transaction retains evidence if a user root has
            // appeared; recovery must not claim or remove that new resource.
            save(home, &j);
            assert!(recover(home).is_err());
            assert!(pending(home));
            assert_eq!(fs::read(root.join("user.txt")).unwrap(), b"user data");
            assert_eq!(snapshot(&old).unwrap(), old_node);
        }
    }

    #[test]
    fn lock_conflicts_and_file_recovery() {
        let temp = tempfile::tempdir().unwrap();
        let home = temp.path();
        let lock = Lock::acquire(home).unwrap();
        assert!(Lock::acquire(home).is_err());
        drop(lock);
        let path = home.join("target");
        fs::write(&path, b"old").unwrap();
        let change = Change {
            path: path.clone(),
            before: Some(Node::File(b"old".to_vec())),
            after: Some(Node::File(b"new".to_vec())),
        };
        let j = journal(vec![change.clone()]);
        save(home, &j);
        fs::write(&path, b"new").unwrap();
        recover(home).unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"old");
        apply(home, vec![change.clone()]).unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"new");
        assert!(apply(home, vec![change]).is_err());
    }
    #[test]
    fn recovery_preserves_post_crash_user_edits_and_preflights_all_changes() {
        let temp = tempfile::tempdir().unwrap();
        let first = temp.path().join("first");
        let second = temp.path().join("second");
        fs::write(&first, b"new").unwrap();
        fs::write(&second, b"user").unwrap();
        let changes = [first.clone(), second.clone()]
            .into_iter()
            .map(|path| Change {
                path,
                before: Some(Node::File(b"old".to_vec())),
                after: Some(Node::File(b"new".to_vec())),
            })
            .collect();
        save(temp.path(), &journal(changes));
        assert!(recover(temp.path()).is_err());
        assert_eq!(fs::read(first).unwrap(), b"new");
        assert_eq!(fs::read(second).unwrap(), b"user");
        assert!(pending(temp.path()));
    }
    #[test]
    #[cfg(unix)]
    fn link_to_tree_recovers_at_each_durable_boundary() {
        use std::os::unix::fs::symlink;
        for checkpoint in 0..=4 {
            let temp = tempfile::tempdir().unwrap();
            let path = temp.path().join("skill");
            let old = temp.path().join("old-source");
            fs::create_dir(&old).unwrap();
            symlink(&old, &path).unwrap();
            let before = Some(Node::Symlink(old.clone()));
            let after = Some(directory());
            let j = journal(vec![Change {
                path: path.clone(),
                before: before.clone(),
                after: after.clone(),
            }]);
            save(temp.path(), &j);
            let root = stage_for(&j);
            if checkpoint == 0 {
                fs::remove_file(root.join("owner.json")).unwrap();
            }
            if checkpoint == 1 {
                fs::create_dir(root.join("new")).unwrap();
                fs::write(root.join("new/SKILL.md"), b"new").unwrap();
            }
            if checkpoint >= 2 {
                stage_node(&root.join("new"), after.as_ref().unwrap()).unwrap();
            }
            if checkpoint >= 3 {
                fs::rename(&path, root.join("old")).unwrap();
            }
            if checkpoint >= 4 {
                fs::rename(root.join("new"), &path).unwrap();
            }
            recover(temp.path()).unwrap();
            assert_eq!(snapshot(&path).unwrap(), before);
            assert!(!root.exists());
            assert!(!pending(temp.path()));
            assert!(old.is_dir());
        }
    }
    #[test]
    fn directory_delete_and_creation_rollback_keep_exact_content() {
        for deleting in [false, true] {
            let temp = tempfile::tempdir().unwrap();
            let path = temp.path().join("skill");
            let (before, after) = if deleting {
                (Some(directory()), None)
            } else {
                (None, Some(directory()))
            };
            if let Some(node) = &before {
                stage_node(&path, node).unwrap();
            }
            let j = journal(vec![Change {
                path: path.clone(),
                before: before.clone(),
                after,
            }]);
            save(temp.path(), &j);
            forward_swap(&j, 0).unwrap();
            recover(temp.path()).unwrap();
            assert_eq!(snapshot(&path).unwrap(), before);
        }
    }
    #[test]
    fn committed_cleanup_is_restartable_and_does_not_undo_user_edits() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("skill");
        stage_node(&path, &directory()).unwrap();
        let mut j = journal(vec![Change {
            path: path.clone(),
            before: Some(directory()),
            after: Some(Node::File(b"replacement".to_vec())),
        }]);
        save(temp.path(), &j);
        forward_swap(&j, 0).unwrap();
        j.committed = true;
        save(temp.path(), &j);
        let root = custody(&j, 0).unwrap();
        fs::remove_file(root.join("old/SKILL.md")).unwrap();
        fs::write(&path, b"user edit after commit").unwrap();
        recover(temp.path()).unwrap();
        assert_eq!(fs::read(path).unwrap(), b"user edit after commit");
        assert!(!root.exists());
    }
    #[test]
    fn changed_private_stage_is_preserved_and_never_overwritten() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("skill");
        let j = journal(vec![Change {
            path: path.clone(),
            before: None,
            after: Some(directory()),
        }]);
        save(temp.path(), &j);
        let root = stage_for(&j);
        stage_node(&root.join("new"), &directory()).unwrap();
        fs::write(root.join("new/SKILL.md"), b"user stage edit").unwrap();
        assert!(recover(temp.path()).is_err());
        assert!(!path.exists());
        assert_eq!(
            fs::read(root.join("new/SKILL.md")).unwrap(),
            b"user stage edit"
        );
        assert!(pending(temp.path()));
    }
    #[test]
    fn unsafe_or_overlapping_journal_paths_fail_before_any_target_change() {
        let temp = tempfile::tempdir().unwrap();
        let target = temp.path().join("target");
        fs::write(&target, b"owned").unwrap();
        for name in ["../escape", "/absolute", r"a\b", "C:escape"] {
            let change = Change {
                path: target.clone(),
                before: Some(Node::File(b"owned".to_vec())),
                after: Some(Node::Directory(BTreeMap::from([(
                    name.into(),
                    Node::File(b"x".to_vec()),
                )]))),
            };
            assert!(apply(temp.path(), vec![change]).is_err());
            assert_eq!(fs::read(&target).unwrap(), b"owned");
            assert!(!pending(temp.path()));
        }
        let self_edit = Change {
            path: journal_path(temp.path()),
            before: None,
            after: Some(Node::File(vec![])),
        };
        assert!(apply(temp.path(), vec![self_edit]).is_err());
        let parent = Change {
            path: target.clone(),
            before: Some(Node::File(b"owned".to_vec())),
            after: None,
        };
        let child = Change {
            path: target.join("child"),
            before: None,
            after: None,
        };
        assert!(apply(temp.path(), vec![parent, child]).is_err());
    }
    #[test]
    #[cfg(unix)]
    fn dangling_journal_link_is_pending_and_cannot_be_overwritten() {
        let temp = tempfile::tempdir().unwrap();
        fs::create_dir(temp.path().join("state")).unwrap();
        std::os::unix::fs::symlink(temp.path().join("absent"), journal_path(temp.path())).unwrap();
        assert!(pending(temp.path()));
        assert!(apply(temp.path(), vec![]).is_err());
        assert!(recover(temp.path()).is_err());
        assert!(fs::symlink_metadata(journal_path(temp.path()))
            .unwrap()
            .file_type()
            .is_symlink());
    }
    #[test]
    fn exclusive_rename_never_overwrites_a_same_name_destination() {
        let temp = tempfile::tempdir().unwrap();
        let from = temp.path().join("owned");
        let to = temp.path().join("foreign");
        fs::write(&from, b"owned").unwrap();
        fs::write(&to, b"user").unwrap();
        assert!(rename_exclusive(&from, &to).is_err());
        assert_eq!(fs::read(&from).unwrap(), b"owned");
        assert_eq!(fs::read(&to).unwrap(), b"user");
    }
    #[test]
    fn bounded_writer_rejects_json_expansion_before_journal_write() {
        let mut bytes = LimitedBytes(vec![0; MAX_BYTES - 1]);
        assert!(bytes.write_all(&[1, 2]).is_err());
        assert_eq!(bytes.0.len(), MAX_BYTES - 1);
    }
}
