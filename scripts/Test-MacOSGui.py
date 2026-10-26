#!/usr/bin/env python3
"""Supervise only a freshly built TEST_ONLY native demo; no signing or installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import tempfile
import time

if platform.system() != "Darwin":
    raise SystemExit("MACOS_GUI=NOT_RUN: requires macOS and a graphical session")
repo = Path(__file__).resolve().parents[1]
target = Path(os.environ.get("CARGO_TARGET_DIR", repo / "target")).resolve()
parser = argparse.ArgumentParser()
parser.add_argument("--binary", type=Path, default=target / "release/atm-desktop")
args = parser.parse_args()
binary = args.binary.resolve()
assert binary.name == "atm-desktop" and target in binary.parents
assert binary.is_file() and os.access(binary, os.X_OK)
evidence = repo / "artifacts/macos-gui"
evidence.mkdir(parents=True, exist_ok=True)
original = b'{\r\n // Synthetic demonstration only\r\n "apiKey": "FAKE_DEMO_OLD",\r\n "authorization": "Bearer ${env:DEMO_KEY}",\r\n}\r\n'
replacement = original.replace(b"FAKE_DEMO_OLD", b"FAKE_DEMO_NEW", 1)
with tempfile.TemporaryDirectory(prefix="TEST_ONLY-atm-gui-", dir="/private/tmp") as directory:
    root = Path(directory)
    executable = root / "atm-desktop"
    shutil.copyfile(binary, executable)
    executable.chmod(0o700)
    binary_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    assert binary_sha == hashlib.sha256(binary.read_bytes()).hexdigest()
    architectures = subprocess.check_output(["/usr/bin/lipo", "-archs", str(executable)], text=True).strip()
    assert platform.machine() in architectures.split()
    env = {key: os.environ[key] for key in ["PATH", "LANG", "LC_ALL", "__CF_USER_TEXT_ENCODING"] if key in os.environ}
    env.update({
        "HOME": str(root / "home"), "TMPDIR": str(root / "tmp"),
        "XDG_DATA_HOME": str(root / "data"), "XDG_CONFIG_HOME": str(root / "config"),
        "ATM_HOME": str(root / "harness"), "CI": "true", "ATM_GUI_TEST_ROOT": str(root),
        "ATM_TESTED_SHA": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "ATM_SKILLS_LIVE": "0", "ATM_ENGINE_LIVE": "0", "PYTHONNOUSERSITE": "1",
    })
    for name in ["home", "tmp", "data", "config", "harness"]:
        (root / name).mkdir(mode=0o700)
    with (evidence / "app.log").open("w") as output:
        process = subprocess.Popen([str(executable), "--demo"], env=env, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        observed = []
        deadline = time.monotonic() + 60
        try:
            launch = subprocess.check_output(["/bin/ps", "-p", str(process.pid), "-o", "command="], text=True).strip()
            assert str(executable) in launch and "--demo" in launch
            actual_env = subprocess.check_output(["/bin/ps", "eww", "-p", str(process.pid), "-o", "command="], text=True)
            for key in ["HOME", "TMPDIR", "ATM_GUI_TEST_ROOT", "ATM_SKILLS_LIVE", "ATM_ENGINE_LIVE"]:
                assert key + "=" + env[key] in actual_env
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise TimeoutError("native smoke did not produce terminal evidence within 60 seconds")
                for config in (root / "tmp").glob("atm-demo-*/synthetic.jsonc"):
                    content = config.read_bytes()
                    assert content in (original, replacement), "unexpected synthetic configuration bytes"
                    phase = "original" if content == original else "applied"
                    if not observed or observed[-1] != phase:
                        observed.append(phase)
                time.sleep(0.05)
            code = process.wait()
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    result_path = root / "result.json"
    if result_path.is_file():
        shutil.copyfile(result_path, evidence / "result.json")
    if code != 0 or not result_path.is_file():
        raise SystemExit("MACOS_GUI=FAIL: managed demo exit=" + str(code) + "; inspect synthetic app.log")
    result = json.loads(result_path.read_text())
    required = ["passed", "renderedVault", "renderedQuotaUi", "renderedHarnessUi", "renderedSkillsUi",
                "unknownVisible", "demoQueryRendered", "resized", "confirmedWrite", "confirmationRefused",
                "cancellationRefused", "duplicateRefused", "rollbackApplied", "capabilityDenied",
                "demoMutationRefused", "incognito"]
    assert all(result.get(key) is True for key in required)
    assert result["platform"] == "macos" and result["testedSha"] == env["ATM_TESTED_SHA"]
    assert result["pid"] == process.pid
    assert Path(result["home"]) == Path(env["HOME"])
    assert Path(result["temporaryDirectory"]) == Path(env["TMPDIR"])
    fixture = Path(result["demoDirectory"])
    assert fixture.parent == root / "tmp"
    assert observed == ["original", "applied", "original"], observed
    assert (fixture / "synthetic.jsonc").read_bytes() == original
    backups = list((fixture / "backups").glob("*.atmbackup"))
    assert len(backups) == 2
    for backup in backups:
        assert backup.stat().st_mode & 0o777 == 0o600
        assert b"FAKE_DEMO_" not in backup.read_bytes()
    assert not list(fixture.glob(".atm-*.tmp"))
    assert not list((root / "home").rglob("vault.lock"))
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        group_cleaned = True
    else:
        group_cleaned = False
    assert group_cleaned
    result.update({"launchMode": "native-binary", "machOArchitectures": architectures,
                   "binarySha256": binary_sha, "sourceTreeDirty": bool(subprocess.check_output(
                       ["git", "status", "--porcelain"], cwd=repo, text=True)),
                   "keychainScope": "memory-only synthetic protector; native Keychain not accessed",
                   "observedDiskPhases": observed, "isolationVerified": True,
                   "processCleaned": process.poll() is not None, "processGroupCleaned": group_cleaned,
                   "distributionPerformed": False})
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print("MACOS_NATIVE_GUI_SMOKE=PASS: isolated native IPC write/rollback, ACL, incognito and cleanup")
