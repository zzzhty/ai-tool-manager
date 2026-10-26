# Managed user PATH

Status: Accepted

## Registration

`scripts/manager_environment.py` owns PATH registration for installation, repair,
and update. Only the current user's environment is modified.

| Environment | Registration target |
| --- | --- |
| bash | `~/.bashrc` |
| zsh | `$ZDOTDIR/.zshrc`, or `~/.zshrc` when `ZDOTDIR` is unset |
| fish | `$XDG_CONFIG_HOME/fish/conf.d/oh-my-harness.fish`, or the same path under `~/.config` |
| Windows | `HKCU\Environment\Path` |

Other shells require manual PATH setup. Login profiles and system-wide
configuration are not registration targets.

## Shell format

Each managed block starts with `# oh-my-harness PATH`, followed by a readable
deduplication check and assignment. Bash/zsh use `case` and `export`; fish uses
`if not contains` and `set -gx PATH`. The manager path is quoted for the shell.
Repeated sourcing does not duplicate the entry, and an empty PATH does not gain
an implicit current-directory entry.

## Ownership

`state/environment.json` records the user, manager bin path, and owned shell
configuration paths or Windows entry. Registration is idempotent. Relocation
uses the recorded bin path, and a shell-config root change cleans only owned
blocks recorded for the same user. Another account's receipt never supplies
write targets.

A shell block is replaceable or removable only when its complete comment and
command match the recorded installation. Every configuration is checked before
any write. Duplicate, incomplete, or edited blocks stop the operation. Unrelated
text, file permissions, and dotfile symlinks are preserved. Uninstall removes
only owned blocks or registry entries added by the installation.

`--no-path` skips registration for that invocation. Existing parent shells keep
their current environment; registered PATH settings apply to new terminals.
