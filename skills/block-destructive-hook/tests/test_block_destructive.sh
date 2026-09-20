#!/bin/bash
# Exercise the actual Claude Code PreToolUse JSON protocol.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLOCKER="$SCRIPT_DIR/../block-destructive.sh"
TEST_HOME="$(mktemp -d)"
trap 'rm -rf "$TEST_HOME"' EXIT
export HOME="$TEST_HOME"

run_hook() {
  local command="$1"
  local cwd="${2:-/tmp/test-project}"
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' "$command" "$cwd" | bash "$BLOCKER"
}

assert_decision() {
  local command="$1" expected="$2" description="$3"
  local output
  output=$(run_hook "$command")
  if [ "$expected" = deny ] && printf '%s' "$output" | grep -q '"permissionDecision":"deny"'; then
    printf 'ok - %s\n' "$description"
  elif [ "$expected" = neutral ] && [ -z "$output" ]; then
    printf 'ok - %s\n' "$description"
  else
    printf 'not ok - %s: %s\n' "$description" "$output"
    return 1
  fi
}

# Destructive commands receive deny; safe Bash receives no decision so Claude
# Code's ordinary permission handling remains authoritative.
assert_decision 'rm -rf /' deny 'denies rm -rf /'
assert_decision "echo 'rm -rf /'" neutral 'does not match destructive text inside echo quotes'
assert_decision "printf '%s' \"git push --force\"" neutral 'does not match documentation text inside printf'
assert_decision 'git -C repo push -f origin main' deny 'denies force push after git -C'
assert_decision 'git -C repo push --force origin main' deny 'denies long force push after git -C'
assert_decision 'git push --force-with-lease origin main' deny 'denies force-with-lease push'
assert_decision 'rm -rf /tmp/..' deny 'denies normalized parent traversal to root'
assert_decision $'DELETE FROM users\n-- WHERE id=5' deny 'denies multiline DELETE with SQL comment'
assert_decision $'psql -c \"DELETE FROM users /* harmless-looking comment */\n-- WHERE id=5\"' deny 'denies DELETE hidden in multiline SQL comments'
assert_decision $'psql -c \"DELETE FROM users\nWHERE id=5\"' neutral 'allows multiline DELETE with WHERE'
assert_decision 'rm -r -f -- /' deny 'denies split flags and -- root'
assert_decision 'rm -rf ~' deny 'denies home directory'
assert_decision 'rm -rf .' deny 'denies current directory'
assert_decision 'rm -rf ./build' deny 'denies build tree'
assert_decision 'rm -rf "~/"' deny 'denies quoted home directory'
assert_decision 'rm -rf ./*' deny 'denies current-directory glob'
assert_decision 'rm --recursive --force -- /' deny 'denies long flags and -- root'
assert_decision 'sudo rm -rf /var/log' deny 'denies sudo system subtree'
assert_decision 'rm -rf /var/*' deny 'denies absolute subtree glob'
assert_decision 'rm /' deny 'denies root without flags'
assert_decision 'DROP TABLE users' deny 'denies DROP TABLE'
assert_decision 'TRUNCATE TABLE logs' deny 'denies TRUNCATE'
assert_decision 'DELETE FROM users;' deny 'denies DELETE without WHERE'
assert_decision 'git push --force origin main' deny 'denies force push'
assert_decision 'shutdown -h now' deny 'denies shutdown'
assert_decision 'sudo halt' deny 'denies halt command'
assert_decision 'printf halt' neutral 'does not block halt as an argument'
assert_decision 'echo halted' neutral 'does not block halt word prefixes'
assert_decision 'cat <(rm -rf /)' deny 'denies destructive Bash process substitution'
assert_decision 'cat >(sh -c "rm -rf /")' deny 'denies destructive output process substitution'
assert_decision "exec sh -c 'rm -rf /'" deny 'denies exec shell wrapper'
assert_decision "timeout 5 sh -c 'rm -rf /'" deny 'denies timeout shell wrapper'
assert_decision "find . -exec rm -rf / \\;" deny 'denies find exec payload'
assert_decision "printf 'rm -rf /' | sh" deny 'denies shell pipeline payload'
assert_decision 'psql -c DELETE FROM users' deny 'denies unquoted SQL client payload'
assert_decision 'ls -la' neutral 'leaves safe command undecided'
assert_decision 'rm -rf build' neutral 'allows ordinary named directory'
assert_decision 'DELETE FROM users WHERE id=5' neutral 'allows DELETE with WHERE'

# cwd must come from the JSON request, not the process cwd or an environment
# fallback.
requested_cwd='/json/project/with spaces'
run_hook 'rm -rf /' "$requested_cwd" >/dev/null
log_file="$HOME/.claude/hooks/blocked.log"
if grep -Fq "project: $requested_cwd" "$log_file" && ! grep -Fq "project: $(pwd)" "$log_file"; then
  printf 'ok - blocked log records JSON cwd\n'
else
  printf 'not ok - blocked log did not record JSON cwd\n'
  cat "$log_file"
  exit 1
fi

# Invalid and non-Bash protocol events are neutral.
if [ -z "$(printf '%s' '{"tool_name":"Read"}' | bash "$BLOCKER")" ]; then
  printf 'ok - non-Bash event is neutral\n'
else
  printf 'not ok - non-Bash event received a decision\n'
  exit 1
fi

printf 'Protocol tests passed\n'
