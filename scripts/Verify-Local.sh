#!/usr/bin/env bash
# Synthetic tests only; no Home Codex CLI or provider-account queries.
set -euo pipefail
# This entry point is synthetic even if the caller enabled separate live tests.
export ATM_SKILLS_LIVE=0 ATM_ENGINE_LIVE=0
unset ATM_TEST_ENGINE_CHECKOUT
atm_repo="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$atm_repo"
atm_cache="$atm_repo/.validation-cache"
mkdir -p "$atm_cache"
touch "$atm_cache/npm-user.conf" "$atm_cache/npm-global.conf"
if [[ -z "$(printenv CARGO_HOME)" ]]; then export CARGO_HOME="$atm_cache/cargo"; fi
export npm_config_userconfig="$atm_cache/npm-user.conf"
export npm_config_globalconfig="$atm_cache/npm-global.conf"
export npm_config_cache="$atm_cache/npm"
cargo fmt --all --check
cargo clippy --locked --offline -p atm-core -p atm-cli -p atm --no-default-features --all-targets -- -D warnings
cargo test --locked --offline -p atm-core -p atm-cli -p atm --no-default-features --all-targets
npm run check
npm test
npm run build
# Embedded harness engine suite. Byte-compilation always runs; unit tests need
# PyYAML/jsonschema importable by the runner. Without them the suite is an
# honest SKIPPED (never a fabricated pass); CI sets ATM_ENGINE_PYTHON_STRICT=1
# to require them.
python3 -m compileall -q harness/scripts harness/tests harness/plugins/watcher harness/plugins/workflow
if python3 -c "import yaml, jsonschema" 2>/dev/null; then
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s harness/tests -p "test_*.py"
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s harness/plugins/watcher/tests -p "test_*.py"
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s harness/plugins/workflow/tests -p "test_*.py"
  (cd harness && python3 scripts/check_plugin_generations.py >/dev/null)
elif [[ "${ATM_ENGINE_PYTHON_STRICT:-0}" == "1" ]]; then
  echo "PYTHON_SUITE=FAIL: tooling dependencies missing (yaml/jsonschema) in strict mode" >&2
  exit 1
else
  echo "PYTHON_SUITE=SKIPPED (tooling deps unavailable; run pip install -r harness/requirements.txt)"
fi
git diff --check
python3 - <<'PY'
import json, re, subprocess
from pathlib import PurePosixPath
from pathlib import Path
files = sorted(set(subprocess.check_output(["git","-c","core.quotepath=false","ls-files","--cached","--others","--exclude-standard"],text=True).splitlines()))
manifest = json.loads(Path("scripts/source-manifest.json").read_text())
allowed = set(manifest["files"])
for entry in manifest.get("directories", []):
    prefix = entry["path"].rstrip("/") + "/"
    excluded = set(entry.get("exclude", []))
    matched = {f for f in files if f.startswith(prefix) and not (excluded & set(PurePosixPath(f).parts[1:]))}
    # A directory entry that matches nothing means an ignore rule silently ate the tree.
    if not matched:
        raise SystemExit("Source manifest directory %s has no tracked files; check ignore rules" % entry["path"])
    allowed |= matched
if files != sorted(allowed):
    raise SystemExit("Source manifest does not match the project file inventory")
pattern = re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----)")
for relative in files:
    text = Path(relative).read_bytes().decode("utf-8")
    if "\0" in text or text.startswith("%TSD-Header-###%") or pattern.search(text):
        raise SystemExit("Source audit failed for " + relative)
print("SOURCE_AUDIT=PASS: %s readable UTF-8 project source files; no detected credential patterns" % len(files))
PY
