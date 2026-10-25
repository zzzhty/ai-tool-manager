#!/usr/bin/env bash
# Synthetic tests only; no Home Codex CLI or provider-account queries.
set -euo pipefail
# This entry point is synthetic even if the caller enabled separate live tests.
export LKM_SKILLS_LIVE=0 LKM_OMH_LIVE=0
unset ATM_TEST_OMH_CHECKOUT
lkm_repo="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$lkm_repo"
lkm_cache="$lkm_repo/.validation-cache"
mkdir -p "$lkm_cache"
touch "$lkm_cache/npm-user.conf" "$lkm_cache/npm-global.conf"
if [[ -z "$(printenv CARGO_HOME)" ]]; then export CARGO_HOME="$lkm_cache/cargo"; fi
export npm_config_userconfig="$lkm_cache/npm-user.conf"
export npm_config_globalconfig="$lkm_cache/npm-global.conf"
export npm_config_cache="$lkm_cache/npm"
cargo fmt --all --check
cargo clippy --locked --offline -p atm-core -p atm-cli -p atm --no-default-features --all-targets -- -D warnings
cargo test --locked --offline -p atm-core -p atm-cli -p atm --no-default-features --all-targets
npm run check
npm test
npm run build
git diff --check
python3 - <<'PY'
import json, re, subprocess
from pathlib import Path
files = sorted(set(subprocess.check_output(["git","-c","core.quotepath=false","ls-files","--cached","--others","--exclude-standard"],text=True).splitlines()))
allowed = sorted(json.loads(Path("scripts/source-manifest.json").read_text()))
if files != allowed:
    raise SystemExit("Source manifest does not match the project file inventory")
pattern = re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----)")
for relative in files:
    text = Path(relative).read_bytes().decode("utf-8")
    if "\0" in text or text.startswith("%TSD-Header-###%") or pattern.search(text):
        raise SystemExit("Source audit failed for " + relative)
print("SOURCE_AUDIT=PASS: %s readable UTF-8 project source files; no detected credential patterns" % len(files))
PY
