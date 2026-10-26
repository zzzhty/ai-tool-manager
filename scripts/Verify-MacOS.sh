#!/usr/bin/env bash
# Existing toolchains/caches only; memory-only keys, no app signing or installation.
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { echo 'MACOS_VALIDATION=NOT_RUN: requires macOS'; exit 1; }
atm_repo="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$atm_repo"
export ATM_SKILLS_LIVE=0 ATM_ENGINE_LIVE=0 PYTHONNOUSERSITE=1
unset ATM_TEST_ENGINE_CHECKOUT PYTHONPATH PYTHONHOME
unset ATM_HOME CLAUDE_CONFIG_DIR COPILOT_HOME CODEX_HOME
unset GEMINI_CLI_HOME OPENCLAW_STATE_DIR PI_CODING_AGENT_DIR
unset APPLE_CERTIFICATE APPLE_CERTIFICATE_PASSWORD APPLE_ID APPLE_PASSWORD APPLE_TEAM_ID
unset APPLE_API_KEY APPLE_API_ISSUER APPLE_API_KEY_PATH APPLE_SIGNING_IDENTITY
# Explicit compile-time platform configuration keeps WebKit storage ephemeral.
# Cargo builds the executable only: no bundler, signing command or distribution.
export TAURI_CONFIG="$(python3 - <<'PY'
import json
from pathlib import Path
config=json.loads(Path('apps/desktop/src-tauri/tauri.macos.conf.json').read_text())
config['bundle']['active']=False
print(json.dumps(config))
PY
)"
bash scripts/Verify-Local.sh
cargo clippy --locked --offline --workspace --all-targets --features smoke-tests -- -D warnings
cargo test --locked --offline --workspace --all-targets --features smoke-tests
cargo build --locked --offline --release -p atm --features smoke-tests
python3 scripts/Test-MacOSGui.py
