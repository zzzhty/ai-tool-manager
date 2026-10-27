#!/usr/bin/env python3
"""Package native binaries and the manifest allowlist; Python is build tooling only."""
import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def verify(cli: Path, payload: Path) -> dict:
    result = subprocess.run(
        [str(cli), "harness", "verify-source", "--source", str(payload)],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    return json.loads(result.stdout)


def payload_path(root: Path, raw: str) -> Path:
    relative = Path(raw)
    if (not raw or relative.is_absolute() or ".." in relative.parts
            or "\\" in raw or ":" in raw or any(ord(char) < 32 for char in raw)):
        raise SystemExit(f"invalid payload path: {raw!r}")
    return root / relative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    suffix = ".exe" if sys.platform == "win32" else ""
    binaries = [repo / "target/release" / (name + suffix) for name in ("atm", "atm-desktop")]
    for binary in binaries:
        if not binary.is_file():
            parser.error(f"build the native release binary first: {binary}")
    source = repo / "harness"
    expected = verify(binaries[0], source)
    manifest = json.loads((source / "content-lock.json").read_text(encoding="utf-8"))
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    for binary in binaries:
        shutil.copy2(binary, destination / binary.name)
    payload = destination / "harness"
    payload.mkdir()
    # Rust validates every path and digest before this build-only copier runs.
    for directory in manifest.get("directories", []):
        payload_path(payload, directory).mkdir(parents=True, exist_ok=True)
    for item in manifest["files"]:
        target = payload_path(payload, item["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(payload_path(source, item["path"]), target)
    for metadata in ("content-manifest.json", "content-lock.json"):
        shutil.copy2(source / metadata, payload / metadata)
    if verify(destination / binaries[0].name, payload) != expected:
        raise SystemExit("payload changed while packaging; rebuild from a stable checkout")
    shutil.copy2(repo / "LICENSE", destination / "LICENSE")
    (destination / "README.txt").write_text(
        "AI Tooling Manager (atm)\n\n"
        "Keep atm, atm-desktop and harness/ together when extracting or upgrading.\n"
        "CLI: ./atm help (Windows: .\\atm.exe help). Desktop: atm-desktop.\n"
        "Static skills distribution and recorded status do not require Python.\n"
        "Run: atm harness bootstrap; after upgrading: atm harness sync.\n"
        "Then: atm update skills --harness <ID> to reapply recorded distributions.\n"
        "Python payload runtimes require explicit preparation with an absolute interpreter.\n"
        "Skill-watcher hooks are retired; only receipt-based removal of old entries remains.\n"
        "ATM_HOME selects manager state. Legacy Python state requires explicit atm harness adopt.\n"
        "This portable build is unsigned. Native desktop runtime requirements apply.\n"
        f"Platform: {sys.platform} {platform.machine()}\n", encoding="utf-8")
    archive = shutil.make_archive(str(destination), "zip" if sys.platform == "win32" else "gztar",
                                  destination.parent, destination.name)
    print(f"DISTRIBUTION_PACKAGE={archive}")


if __name__ == "__main__":
    main()
