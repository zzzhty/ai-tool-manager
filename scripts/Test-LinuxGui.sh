#!/usr/bin/env bash
# Native WebKit GUI, bundled local IPC and synthetic provider data only.
set -euo pipefail
[[ "$(printenv CI)" == true ]]
lkm_root="$(mktemp -d "$RUNNER_TEMP/lkm-gui-XXXXXX")"
mkdir -p artifacts/linux-gui
trap 'lkm_exit=$?; cp "$lkm_root/app.log" artifacts/linux-gui/app.log 2>/dev/null || true; if [[ -f "$lkm_root/result.json" ]]; then cp "$lkm_root/result.json" artifacts/linux-gui/result.json; fi; if [[ $lkm_exit -ne 0 ]]; then cat "$lkm_root/app.log"; fi; exit "$lkm_exit"' EXIT
export HOME="$lkm_root/home"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_RUNTIME_DIR="$lkm_root/runtime"
export TMPDIR="$lkm_root/tmp"
export LKM_GUI_TEST_ROOT="$lkm_root"
export LKM_TESTED_SHA="$(git rev-parse HEAD)"
export GDK_BACKEND=x11
export LIBGL_ALWAYS_SOFTWARE=1
export WEBKIT_DISABLE_COMPOSITING_MODE=1
install -d -m 700 "$HOME" "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_RUNTIME_DIR" "$TMPDIR"
timeout 45s target/release/atm-desktop --demo > "$lkm_root/app.log" 2>&1
[[ -f "$lkm_root/result.json" ]]
python3 - "$lkm_root/result.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
assert r['passed'] and r['renderedVault'] and r['renderedQuotaUi'] and r['renderedOmhUi'] and r['renderedSkillsUi'] and r['unknownVisible'] and r['demoQueryRendered'] and r['resized']
print('LINUX_NATIVE_GUI_SMOKE=PASS: native WebKit rendering, resize and synthetic quota, omh snapshot and skills inventory IPC')
PY
mkdir -p artifacts/linux-gui
cp "$lkm_root/result.json" artifacts/linux-gui/result.json

