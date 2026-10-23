#!/usr/bin/env bash
# CI private-bus fixture only. No Home service or credential files.
set -euo pipefail
[[ "$(printenv CI)" == true && "$(printenv LKM_ISOLATED_KEYRING_TEST)" == 1 ]]
[[ "$(printenv LKM_TEST_ROOT)" == "$(printenv RUNNER_TEMP)"/lkm-keyring-* ]]
if [[ -z "$(printenv CARGO_HOME)" ]]; then export CARGO_HOME="$HOME/.cargo"; fi
if [[ -z "$(printenv RUSTUP_HOME)" ]]; then export RUSTUP_HOME="$HOME/.rustup"; fi
export HOME="$LKM_TEST_ROOT/home"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_RUNTIME_DIR="$LKM_TEST_ROOT/runtime"
export TMPDIR="$LKM_TEST_ROOT/tmp"
install -d -m 700 "$HOME" "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_RUNTIME_DIR" "$TMPDIR"
lkm_keyring_pid=""
cleanup() { if [[ -n "$lkm_keyring_pid" ]]; then kill "$lkm_keyring_pid" 2>/dev/null || true; wait "$lkm_keyring_pid" 2>/dev/null || true; fi; }
trap cleanup EXIT
start_keyring() {
  printf '%s' TEST_ONLY_KEYRING_PASSWORD | gnome-keyring-daemon --foreground --components=secrets --unlock > "$LKM_TEST_ROOT/daemon.log" 2>&1 &
  lkm_keyring_pid=$!
  for lkm_attempt in $(seq 1 40); do
    if [[ "$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.NameHasOwner org.freedesktop.secrets)" == "(true,)" ]]; then return; fi
    sleep 0.25
  done
  echo "Private Secret Service did not start" >&2; return 1
}
start_keyring
LKM_KEYRING_PHASE=create cargo test --locked -p atm-core --test secret_service_ci -- --ignored --exact isolated_secret_service_lifecycle --nocapture
cleanup
lkm_keyring_pid=""
start_keyring
LKM_KEYRING_PHASE=reopen cargo test --locked -p atm-core --test secret_service_ci -- --ignored --exact isolated_secret_service_lifecycle --nocapture
echo "SECRET_SERVICE_LIFECYCLE=PASS: real private service create/read/lock/restart/unlock/encrypted-vault-and-backup"
