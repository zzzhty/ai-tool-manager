#!/usr/bin/env python3
"""Exercise the shipped CLI from an extracted archive in a disposable user home.

No real accounts/configuration are used. Bootstrap downloads Python dependencies.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="atm distribution ") as temporary:
        root = Path(temporary)
        extracted = root / "extracted"
        shutil.unpack_archive(args.archive.resolve(), extracted)
        package, = extracted.iterdir()
        cli = package / ("atm.exe" if os.name == "nt" else "atm")
        user = root / "user"
        user.mkdir()
        home = user / "manager with spaces"
        # Deliberately retain only runtime/network certificate variables, not tool homes.
        keep = {"PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
                "TEMP", "TMP", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
                "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy"}
        env = {key: value for key, value in os.environ.items() if key in keep}
        env.update(HOME=str(user), USERPROFILE=str(user), ATM_HOME=str(home),
                   APPDATA=str(user / "appdata"), LOCALAPPDATA=str(user / "localappdata"),
                   XDG_DATA_HOME=str(user / ".local/share"), XDG_CONFIG_HOME=str(user / ".config"),
                   PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
        # Exercise automatic Python discovery, not ATM_BOOTSTRAP_PYTHON.
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")

        def run(*arguments, success=True):
            result = subprocess.run([str(cli), *arguments], cwd=root, env=env,
                                    input="", text=True, capture_output=True, timeout=240)
            if (result.returncode == 0) != success:
                raise RuntimeError(f"{arguments}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
            return result

        run("help")
        run("list", "skills", "--json")
        source = package / "harness"
        hidden = package / "hidden-harness"
        source.rename(hidden)
        try:
            result = run("harness", "sync", success=False)
            assert "HARNESS_SOURCE_MISSING" in result.stderr
        finally:
            hidden.rename(source)
        # Explicit --home must override ATM_HOME; no state may appear at the latter.
        env["ATM_HOME"] = str(user / "unused-manager")
        run("harness", "bootstrap", "--home", str(home))
        assert not Path(env["ATM_HOME"]).exists()
        env["ATM_HOME"] = str(home)
        run("harness", "--", "install", "zcode", "--yes")
        run("check", "skills", "--harness", "zcode")
        local = user / "synthetic-source"
        local.mkdir()
        (local / "SKILL.md").write_text("---\nname: test-only\ndescription: Synthetic distribution test\n---\n# Test\n")
        run("publish", "skills", str(local), "--name", "test-only", "--to", "codex")
        config = user / ".zcode/user-config.json"
        config.write_text('{"testOnly":"preserve"}\n')
        instructions = user / ".zcode/AGENTS.md"
        before = {path: path.read_bytes() for path in (home / "state").rglob("*.json")
                  if path.name != "manager.json"}
        data = user / ("Library/Application Support/atm" if sys.platform == "darwin" else
                       "localappdata/atm" if os.name == "nt" else ".local/share/atm")
        registry = data / "skills-sources/registry.json"
        before[registry] = registry.read_bytes()
        before[config] = config.read_bytes()
        before[instructions] = instructions.read_bytes()
        # An engine-only upgrade must sync despite an unchanged plugin generation.
        change = source / "scripts/release_probe.txt"
        change.write_text("TEST_ONLY engine upgrade\n")
        run("harness", "sync")
        assert (home / "repo/scripts/release_probe.txt").read_bytes() == change.read_bytes()
        for path, data in before.items():
            assert path.read_bytes() == data, f"sync changed preserved state: {path}"
        run("check", "skills", "test-only", "--json")
        run("update", "skills", "--harness", "zcode")
        run("check", "skills", "--harness", "zcode")
        (home / "repo/scripts/release_probe.txt").write_text("TEST_ONLY drift\n")
        run("harness", "sync")
        assert (home / "repo/scripts/release_probe.txt").read_bytes() == change.read_bytes()
        assert config.read_bytes() == before[config]
        status = json.loads(run("harness", "status", "--json").stdout)
        assert status
        print("DISTRIBUTION_SMOKE=PASS: extracted release, automatic Python, bootstrap, install, "
              "engine-only upgrade, drift repair, receipts/configuration and local projection retained")


if __name__ == "__main__":
    main()
