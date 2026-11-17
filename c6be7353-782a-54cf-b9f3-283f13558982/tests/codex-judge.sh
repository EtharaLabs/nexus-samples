#!/bin/sh
# Installed as /usr/local/bin/codex in the verifier image. Reward Kit (root) runs the judge
# through it; it hands the judge's CODEX_HOME to uid 1000 and runs the real Codex there, so
# the judge reads the work under evaluation but cannot write /logs/verifier, /tests, /build
# or /workspace, and the reward stays with root. Ownership changes only on the paths Reward
# Kit itself creates, never through a symbolic link. A sandbox that does not let root switch
# users runs the judge as root instead, as Reward Kit does without this wrapper.
set -u
real=/usr/local/lib/codex/codex
if [ "$(id -u)" -ne 0 ]; then
  exec "$real" "$@"
fi
drop=yes
home=/tmp
if [ -n "${CODEX_HOME:-}" ] && [ -d "$CODEX_HOME" ] && [ ! -L "$CODEX_HOME" ]; then
  for path in "$CODEX_HOME" "$CODEX_HOME/auth.json" "$CODEX_HOME/config.toml" \
    "$CODEX_HOME/rewardkit-attempts"; do
    if [ -e "$path" ] && [ ! -L "$path" ]; then
      chown -h 1000:1000 "$path" 2>/dev/null || drop=no
    fi
  done
  home=$CODEX_HOME
fi
if [ "$drop" = yes ] && setpriv --reuid=1000 --regid=1000 --clear-groups true 2>/dev/null; then
  HOME=$home exec setpriv --reuid=1000 --regid=1000 --clear-groups --no-new-privs "$real" "$@"
fi
exec "$real" "$@"
