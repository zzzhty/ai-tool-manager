use atm_core::distribution::runtime::{self, RuntimeSpec};
use std::{fs, path::Path};

fn spec() -> RuntimeSpec {
    RuntimeSpec {
        id: "workflow".into(),
        minimum_python: [3, 11],
        requirements_lock: None,
        imports: vec![],
    }
}

#[test]
fn missing_python_is_clear_and_does_not_create_managed_state() {
    let temp = tempfile::tempdir().unwrap();
    let manager = temp.path().join("manager");
    let error = runtime::prepare(
        &manager,
        temp.path(),
        &spec(),
        &temp.path().join("missing-python"),
        None,
        true,
    )
    .unwrap_err();
    assert_eq!(error.code, "HARNESS_PYTHON_REQUIRED");
    assert!(!manager.exists());
}

#[test]
fn lock_requires_exact_versions_hashes_and_confined_paths() {
    let temp = tempfile::tempdir().unwrap();
    let lock = temp.path().join("requirements.lock");
    let mut spec = RuntimeSpec {
        requirements_lock: Some("requirements.lock".into()),
        ..spec()
    };
    fs::write(
        &lock,
        format!("PyYAML==6.0.3 --hash=sha256:{}\n", "a".repeat(64)),
    )
    .unwrap();
    assert_eq!(
        runtime::validate_spec_lock(&spec, temp.path()).unwrap()["PyYAML"],
        "6.0.3"
    );
    for bad in [
        "PyYAML>=6\n",
        "--index-url https://example.test\n",
        "-r ../../requirements.txt\n",
        "PyYAML==6.0.3\n",
        "thing @ https://example.test/a.whl\n",
    ] {
        fs::write(&lock, bad).unwrap();
        assert!(runtime::validate_spec_lock(&spec, temp.path()).is_err());
    }
    spec.requirements_lock = Some("../requirements.lock".into());
    assert!(runtime::validate_spec_lock(&spec, temp.path()).is_err());
    spec.requirements_lock = Some(r"C:\requirements.lock".into());
    assert!(runtime::validate_spec_lock(&spec, temp.path()).is_err());
}

#[test]
fn controlled_pip_argv_preserves_space_unicode_and_offline_policy() {
    let lock = Path::new("C:/用户/Python env/requirements.lock");
    let wheels = Path::new("C:/用户/cache wheels");
    let args = runtime::pip_arguments(lock, wheels, true);
    assert!(args.iter().any(|a| a == "--require-hashes"));
    assert!(args.iter().any(|a| a == "--no-index"));
    assert_eq!(args.last().unwrap(), lock.as_os_str());
    let index = args.iter().position(|a| a == "--find-links").unwrap();
    assert_eq!(args[index + 1], wheels.as_os_str());
    assert_eq!(
        runtime::venv_python(Path::new("C:/用户/Python env"), true),
        Path::new("C:/用户/Python env/Scripts/python.exe")
    );
}

// These Unix fixtures create executables while other tests spawn children.
// A concurrent fork can briefly retain a writable fixture FD until exec, making
// Linux return ETXTBSY. Serialize fixture lifetimes, not production processes.
#[cfg(unix)]
static EXECUTABLE_FIXTURES: std::sync::Mutex<()> = std::sync::Mutex::new(());

#[cfg(unix)]
fn fake_python(temp: &Path, fail: bool) -> std::path::PathBuf {
    use std::os::unix::fs::PermissionsExt;
    let path = temp.join(if fail {
        "failed Python 中文"
    } else {
        "Python 中文"
    });
    let script=r##"#!/bin/sh
if [ "$3" = "-m" ] && [ "$4" = "venv" ]; then
  FAIL_BUILD
  /bin/mkdir -p "$5/bin"
  /bin/cp "$0" "$5/bin/python"
  /bin/chmod 755 "$5/bin/python"
  /usr/bin/printf 'home = /fake/base\n' > "$5/pyvenv.cfg"
  exit 0
fi
if [ "$2" = "-m" ] && [ "$3" = "pip" ]; then
  prefix=$(/usr/bin/dirname "$(/usr/bin/dirname "$0")")
  for value in "$@"; do
    if [ "$previous" = "--find-links" ]; then
      if [ ! -f "$value/fake-1.0.whl" ]; then exit 1; fi
    fi
    previous=$value
  done
  /usr/bin/printf installed > "$prefix/fake-installed"
  exit 0
fi
case "$0" in */bin/python) prefix=$(/usr/bin/dirname "$(/usr/bin/dirname "$0")");; *) prefix=/fake/base;; esac
if [ -f "$prefix/fake-installed" ]; then deps='{"FakeDep":"1.0"}'; else deps='{}'; fi
/usr/bin/printf '{"version":[3,11],"prefix":"%s","basePrefix":"/fake/base","distributions":%s,"modules":{}}\n' "$prefix" "$deps"
"##.replace("FAIL_BUILD",if fail {"exit 1"} else {":"});
    fs::write(&path, script).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

#[test]
#[cfg(unix)]
fn creates_at_final_path_reuses_verified_env_and_keeps_old_on_failure() {
    let _fixture_lock = EXECUTABLE_FIXTURES.lock().unwrap();
    let temp = tempfile::Builder::new()
        .prefix("TEST_ONLY runtime 空间 ")
        .tempdir()
        .unwrap();
    let interpreter = fake_python(temp.path(), false);
    let manager = temp.path().join("manager");
    let first = runtime::prepare(&manager, temp.path(), &spec(), &interpreter, None, true).unwrap();
    assert!(first.root.join(".atm-runtime.json").is_file());
    assert_eq!(
        runtime::prepare(&manager, temp.path(), &spec(), &interpreter, None, true).unwrap(),
        first
    );
    let failed = fake_python(temp.path(), true);
    assert!(runtime::prepare(&manager, temp.path(), &spec(), &failed, None, true).is_err());
    assert!(first.python.is_file());
    assert!(first.root.join(".atm-runtime.json").is_file());
    assert_eq!(
        fs::read_dir(manager.join("runtimes/workflow"))
            .unwrap()
            .count(),
        3
    ); // complete, incomplete, lock
    assert_eq!(
        runtime::prepare(&manager, temp.path(), &spec(), &failed, None, true)
            .unwrap_err()
            .code,
        "HARNESS_RUNTIME_INCOMPLETE"
    );
}

#[test]
#[cfg(unix)]
fn external_env_is_validated_without_managed_state_or_marker_writes() {
    let _fixture_lock = EXECUTABLE_FIXTURES.lock().unwrap();
    let temp = tempfile::tempdir().unwrap();
    let interpreter = fake_python(temp.path(), false);
    let external = temp.path().join("user venv");
    fs::create_dir_all(external.join("bin")).unwrap();
    fs::copy(&interpreter, external.join("bin/python")).unwrap();
    fs::write(external.join("pyvenv.cfg"), "external config\n").unwrap();
    let manager = temp.path().join("manager");
    let prepared = runtime::prepare(
        &manager,
        temp.path(),
        &spec(),
        Path::new("unused"),
        Some(&external),
        true,
    )
    .unwrap();
    assert!(prepared.external);
    assert!(!manager.exists());
    assert!(!external.join(".atm-runtime.json").exists());
    assert_eq!(
        fs::read_to_string(external.join("pyvenv.cfg")).unwrap(),
        "external config\n"
    );
    assert_eq!(fs::read_dir(external).unwrap().count(), 2);
}

#[test]
#[cfg(unix)]
fn offline_cached_dependencies_and_missing_wheel_diagnosis_use_controlled_pip() {
    let _fixture_lock = EXECUTABLE_FIXTURES.lock().unwrap();
    let temp = tempfile::tempdir().unwrap();
    let interpreter = fake_python(temp.path(), false);
    let dependency = RuntimeSpec {
        requirements_lock: Some("requirements.lock".into()),
        ..spec()
    };
    fs::write(
        temp.path().join("requirements.lock"),
        format!("FakeDep==1.0 --hash=sha256:{}\n", "a".repeat(64)),
    )
    .unwrap();
    let ready = temp.path().join("ready");
    fs::create_dir_all(ready.join("cache/wheels")).unwrap();
    fs::write(ready.join("cache/wheels/fake-1.0.whl"), "fake pip fixture").unwrap();
    assert!(runtime::prepare(&ready, temp.path(), &dependency, &interpreter, None, true).is_ok());
    let missing = temp.path().join("missing");
    fs::create_dir_all(missing.join("cache/wheels")).unwrap();
    assert_eq!(
        runtime::prepare(&missing, temp.path(), &dependency, &interpreter, None, true)
            .unwrap_err()
            .code,
        "HARNESS_RUNTIME_OFFLINE_MISSING"
    );
}

#[test]
#[cfg(unix)]
fn exclusive_lock_and_linked_runtime_root_fail_closed() {
    let _fixture_lock = EXECUTABLE_FIXTURES.lock().unwrap();
    use std::os::unix::fs::symlink;
    let temp = tempfile::tempdir().unwrap();
    let interpreter = fake_python(temp.path(), false);
    let manager = temp.path().join("manager");
    let group = manager.join("runtimes/workflow");
    fs::create_dir_all(&group).unwrap();
    let lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(group.join(".prepare.lock"))
        .unwrap();
    lock.lock().unwrap();
    assert_eq!(
        runtime::prepare(&manager, temp.path(), &spec(), &interpreter, None, true)
            .unwrap_err()
            .code,
        "HARNESS_RUNTIME_BUSY"
    );
    drop(lock);
    let unsafe_manager = temp.path().join("unsafe");
    fs::create_dir(&unsafe_manager).unwrap();
    symlink(&group, unsafe_manager.join("runtimes")).unwrap();
    assert_eq!(
        runtime::prepare(
            &unsafe_manager,
            temp.path(),
            &spec(),
            &interpreter,
            None,
            true
        )
        .unwrap_err()
        .code,
        "HARNESS_RUNTIME_SPEC"
    );
}

#[test]
#[cfg(unix)]
fn prepared_reference_is_bound_to_group_manager_and_current_requirements() {
    let _fixture_lock = EXECUTABLE_FIXTURES.lock().unwrap();
    let temp = tempfile::tempdir().unwrap();
    let interpreter = fake_python(temp.path(), false);
    let manager = temp.path().join("manager");
    let prepared =
        runtime::prepare(&manager, temp.path(), &spec(), &interpreter, None, true).unwrap();
    runtime::verify(&manager, temp.path(), &spec(), &prepared).unwrap();
    assert!(runtime::verify(
        &temp.path().join("other manager"),
        temp.path(),
        &spec(),
        &prepared
    )
    .is_err());
    let other_group = RuntimeSpec {
        id: "watcher".into(),
        ..spec()
    };
    assert!(runtime::verify(&manager, temp.path(), &other_group, &prepared).is_err());
    let new_lock = RuntimeSpec {
        requirements_lock: Some("new.lock".into()),
        ..spec()
    };
    fs::write(
        temp.path().join("new.lock"),
        format!("FakeDep==2.0 --hash=sha256:{}\n", "b".repeat(64)),
    )
    .unwrap();
    assert!(runtime::verify(&manager, temp.path(), &new_lock, &prepared).is_err());
    assert!(prepared.python.is_file());
    assert!(prepared.root.join(".atm-runtime.json").is_file());
}
