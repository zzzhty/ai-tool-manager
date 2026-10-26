#!/usr/bin/env python3
"""Build a portable ATM directory from already-built native release binaries."""
import argparse
import platform
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "harness/scripts"))
    from embedded_identity import content_identity
    from plugin_package_identity import require_repository_identity
    require_repository_identity(repo / "harness")
    suffix = ".exe" if sys.platform == "win32" else ""
    binaries = [repo / "target/release" / (name + suffix) for name in ("atm", "atm-desktop")]
    for binary in binaries:
        if not binary.is_file():
            parser.error(f"build the native release binary first: {binary}")
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    for binary in binaries:
        shutil.copy2(binary, destination / binary.name)
    shutil.copytree(repo / "harness", destination / "harness",
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo", ".venv"))
    if content_identity(repo / "harness") != content_identity(destination / "harness"):
        raise SystemExit("source changed while packaging; rebuild from a stable checkout")
    shutil.copy2(repo / "LICENSE", destination / "LICENSE")
    (destination / "README.txt").write_text(
        "AI Tooling Manager (atm)\n\n"
        "Keep atm, atm-desktop and harness/ together when extracting or upgrading.\n"
        "CLI: ./atm help (Windows: .\\atm.exe help). Desktop: atm-desktop.\n"
        "Harness requires Python 3.11+ with venv/pip; first bootstrap installs requirements.\n"
        "Run: atm harness bootstrap; after upgrading: atm harness sync.\n"
        "Then: atm update skills --harness <ID> to reapply recorded distributions.\n"
        "ATM_HOME selects manager state; sync preserves receipts and user configuration.\n"
        "This portable build is unsigned. Native desktop runtime requirements apply.\n"
        f"Platform: {sys.platform} {platform.machine()}\n", encoding="utf-8")
    archive = shutil.make_archive(str(destination), "zip" if sys.platform == "win32" else "gztar",
                                  destination.parent, destination.name)
    print(f"DISTRIBUTION_PACKAGE={archive}")


if __name__ == "__main__":
    main()
