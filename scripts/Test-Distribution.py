#!/usr/bin/env python3
"""Exercise an extracted native distribution offline with no Python on its PATH.

The test runner uses Python; the tested CLI gets an empty PATH and a fake home.
No real accounts, installations, configuration, venvs or network are used.
"""
import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def verify_runtime_payload(cache: Path, manifest: dict, identity: str, env: dict, root: Path):
    """Validate the copied runtime and Rust snapshot without preparing any venv."""
    catalog = json.loads((cache / "canonical-catalog.json").read_text(encoding="utf-8"))
    assert catalog["sourceIdentity"] == identity
    assert catalog["schemaVersion"] == 1
    assert catalog["product"] == "atm-harness-catalog"
    for skill in catalog["skills"]:
        assert (cache / skill["path"] / "SKILL.md").is_file()
    for overlay in catalog["attributionOverlays"]:
        assert json.loads((cache / overlay["path"]).read_text(encoding="utf-8")) == overlay["data"]
    for group in manifest["runtimeGroups"]:
        lock = group.get("requirementsLock")
        if lock:
            assert (cache / lock).is_file()
            assert "--hash=sha256:" in (cache / lock).read_text(encoding="utf-8")
    ids = {skill["id"] for skill in catalog["skills"]}
    assert set(manifest["runtimeBindings"]) <= ids | {"hook:watcher"}
    for entry in manifest["files"]:
        if entry["path"].endswith(".py"):
            ast.parse((cache / entry["path"]).read_text(encoding="utf-8"), filename=entry["path"])
    watcher = cache / "runtimes/watcher/scripts/watcher"
    assert watcher.is_file() and not (cache / "scripts").exists()
    before = {path.relative_to(root) for path in root.rglob("*")}
    for name in ("maintenance:doc-alignment", "watcher:doc-alignment", "doc-watcher:doc-alignment"):
        # The runner provides Python solely to exercise a Python payload. The
        # distributor itself retains empty PATH and never creates a venv.
        result = subprocess.run(
            [sys.executable, "-S", "-B", str(watcher), "skill", "observe", "--repo-root", str(cache), "--dry-run"],
            input=json.dumps({"hook_event_name": "UserPromptSubmit", "skill_name": name}),
            cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30, check=True,
        )
        assert json.loads(result.stdout)["skill_attribution"]["primary"]["name"] == "watcher:doc-alignment"
    assert {path.relative_to(root) for path in root.rglob("*")} == before, "read-only payload check wrote files"
    print(f"DISTRIBUTION_PAYLOAD=PASS: {len(catalog['skills'])} catalog entries, runtime locks/scripts, historical identity, no venv/hooks", flush=True)


def main():
    # Native command JSON and CI logs use UTF-8 even with a Windows legacy locale.
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--cli-only", action="store_true", help="label an explicit synthetic CLI-only archive; no desktop release claim")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="atm distribution Unicode 测试 ") as temporary:
        # macOS's default /var temporary path is a system symlink. Keep the
        # tested payload and manager paths physical without relaxing ownership.
        root = Path(temporary).resolve()
        extracted = root / "extracted"
        shutil.unpack_archive(args.archive.resolve(), extracted)
        package, = extracted.iterdir()
        cli = package / ("atm.exe" if os.name == "nt" else "atm")
        desktop = package / ("atm-desktop.exe" if os.name == "nt" else "atm-desktop")
        if not args.cli_only:
            assert desktop.is_file(), "desktop binary missing from release archive"
        user = root / "user"
        user.mkdir()
        home = user / "manager with spaces"
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
        env.update(PATH="", HOME=str(user), USERPROFILE=str(user), ATM_HOME=str(home),
                   APPDATA=str(user / "appdata"), LOCALAPPDATA=str(user / "localappdata"),
                   XDG_DATA_HOME=str(user / ".local/share"), XDG_CONFIG_HOME=str(user / ".config"))

        def run(*arguments, success=True, program=cli):
            print("DISTRIBUTION_STEP=" + program.name + " " + " ".join(arguments), flush=True)
            result = subprocess.run([str(program), *arguments], cwd=root, env=env,
                stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", timeout=120)
            if (result.returncode == 0) != success:
                raise RuntimeError(f"{arguments}: exit {result.returncode}\n"
                                   f"{result.stdout[-10000:]}\n{result.stderr[-10000:]}")
            return result

        run("help")
        run("harness", "status", "--json")
        assert not home.exists(), "read-only status created a manager home"
        invalid = run("harness", "bootstrap", "--home", "relative-manager-home", success=False)
        assert "CLI_ARGUMENT" in invalid.stderr and not home.exists()
        source = package / "harness"
        assert not (source / "scripts").exists(), "installer scripts leaked into payload"
        assert not (source / "tests").exists()
        source_info = json.loads(run("harness", "verify-source").stdout)
        manifest = json.loads((source / "distribution-manifest.json").read_text(encoding="utf-8"))
        actual = {path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()}
        assert actual == {entry["path"] for entry in manifest["files"]} | {"distribution-manifest.json"}
        if not args.cli_only:
            resources = json.loads(run("--verify-distribution", program=desktop).stdout)
            assert resources["releaseBuild"] and not resources["guiInitialized"] and not resources["storageInitialized"]
            assert resources["sourceIdentity"] == source_info["identity"]
            assert Path(resources["sourceRoot"]) == source.resolve()
            assert "/index.html" in resources["frontendAssets"]
            assert not home.exists(), "desktop resource probe initialized storage"
            print("DISTRIBUTION_RESOURCES=" + json.dumps(resources, ensure_ascii=False, sort_keys=True), flush=True)
            print("DISTRIBUTION_DESKTOP=PASS: embedded HTML/JS/CSS and adjacent verified payload; no GUI/storage initialized", flush=True)
        env["ATM_HOME"] = str(user / "unused-manager")
        run("harness", "bootstrap", "--home", str(home))
        assert not Path(env["ATM_HOME"]).exists()
        env["ATM_HOME"] = str(home)
        status = json.loads(run("harness", "status", "--json").stdout)
        cache = Path(status["manager"]["repository"])
        assert status["runtimes"] == {} and not status["hooksEnabled"]
        verify_runtime_payload(cache, manifest, source_info["identity"], env, root)
        assert not (home / "venv").exists() and not (home / "runtimes").exists()
        run("harness", "plan", "install", "--harness", "zcode")
        assert not (user / ".zcode").exists(), "plan changed the target"
        # The full local cache must support every static operation offline.
        hidden = package / "hidden-harness"
        source.rename(hidden)
        try:
            if not args.cli_only:
                assert "HARNESS_SOURCE_MISSING" in run("harness", "verify-source", success=False).stderr
                assert "HARNESS_SOURCE_MISSING" in run("--verify-distribution", program=desktop, success=False).stderr
            run("install", "skills", "--harness", "zcode")
            run("update", "skills", "--harness", "zcode")
            run("check", "skills", "--harness", "zcode")
            codex = user / ".codex"
            codex.mkdir()
            codex_config = codex / "config.toml"
            codex_config.write_text('theme = "TEST_ONLY user setting"\n', encoding="utf-8")
            run("install", "skills", "--harness", "codex")
            run("update", "skills", "--harness", "codex")
            run("check", "skills", "--harness", "codex")
            run("uninstall", "skills", "--harness", "codex")
            assert 'theme = "TEST_ONLY user setting"' in codex_config.read_text(encoding="utf-8")
            config = user / ".zcode/user-config.json"
            config.write_text('{"testOnly":"preserve"}\n', encoding="utf-8")
            instructions = user / ".zcode/AGENTS.md"
            original = instructions.read_bytes()
            instructions.write_bytes(original + b"\nTEST_ONLY user modification\n")
            run("update", "skills", "--harness", "zcode", success=False)
            run("uninstall", "skills", "--harness", "zcode", success=False)
            assert instructions.read_bytes().endswith(b"TEST_ONLY user modification\n")
            instructions.write_bytes(original)
            status = json.loads(run("harness", "status", "--json").stdout)
            assert status["product"] == "atm-harness"
            run("uninstall", "skills", "--harness", "zcode")
            assert config.read_text(encoding="utf-8") == '{"testOnly":"preserve"}\n'
            assert not instructions.exists()
        finally:
            hidden.rename(source)
        run("harness", "sync")
        scope = "synthetic CLI-only archive" if args.cli_only else "complete extracted release (CLI lifecycle + desktop resources + runtime payload)"
        print(f"DISTRIBUTION_SMOKE=PASS: {scope}, empty PATH, offline cache, Unicode/spaces, "
              "plan/apply, native Codex projection, status, user-edit conflict and configuration preservation")


if __name__ == "__main__":
    main()
