#!/usr/bin/env bash
# Native WebKit GUI, bundled local IPC and synthetic provider data only.
set -euo pipefail
[[ "$(printenv CI)" == true ]]
atm_root="$(mktemp -d "$RUNNER_TEMP/atm-gui-XXXXXX")"
mkdir -p artifacts/linux-gui
trap 'atm_exit=$?; cp "$atm_root/app.log" artifacts/linux-gui/app.log 2>/dev/null || true; if [[ -f "$atm_root/result.json" ]]; then cp "$atm_root/result.json" artifacts/linux-gui/result.json; fi; if [[ $atm_exit -ne 0 ]]; then cat "$atm_root/app.log"; fi; exit "$atm_exit"' EXIT
export HOME="$atm_root/home"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_RUNTIME_DIR="$atm_root/runtime"
export TMPDIR="$atm_root/tmp"
export ATM_GUI_TEST_ROOT="$atm_root"
export ATM_TESTED_SHA="$(git rev-parse HEAD)"
export GDK_BACKEND=x11
export LIBGL_ALWAYS_SOFTWARE=1
export WEBKIT_DISABLE_COMPOSITING_MODE=1
install -d -m 700 "$HOME" "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_RUNTIME_DIR" "$TMPDIR"
timeout 45s target/release/atm-desktop --demo > "$atm_root/app.log" 2>&1
[[ -f "$atm_root/result.json" ]]
python3 - "$atm_root/result.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
assert r['passed'] and r['renderedVault'] and r['renderedQuotaUi'] and r['renderedHarnessUi'] and r['renderedSkillsUi'] and r['unknownVisible'] and r['demoQueryRendered'] and r['resized']
print('LINUX_NATIVE_GUI_SMOKE=PASS: native WebKit rendering, resize and synthetic quota, harness snapshot and skills inventory IPC')
PY
mkdir -p artifacts/linux-gui
cp "$atm_root/result.json" artifacts/linux-gui/result.json

