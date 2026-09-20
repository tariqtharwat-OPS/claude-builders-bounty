#!/bin/bash
# Claude Code PreToolUse hook: block destructive Bash commands.
# Protocol input is JSON on stdin; the legacy command-argument mode is retained
# for local smoke tests.

set -euo pipefail

LOG_FILE="$HOME/.claude/hooks/blocked.log"
mkdir -p "$(dirname "$LOG_FILE")"

DESTRUCTIVE_PATTERNS=(
  'DROP[[:space:]]+TABLE'
  'DROP[[:space:]]+DATABASE'
  'TRUNCATE[[:space:]]+'
  'DELETE[[:space:]]+FROM[[:space:]]+[[:alnum:]_."`]+[[:space:]]*(;|$)'
  'git[[:space:]]+push([^;|&]*[[:space:]])(-f|--force)([[:space:]]|$)'
  'git[[:space:]]+reset[[:space:]]+--hard'
  'dd[[:space:]]+if=/dev/(zero|random)'
  'mkfs\.'
  'init[[:space:]]+0'
  'wget.*\|[[:space:]]*bash'
  'curl.*\|[[:space:]]*(sh|bash)'
  'python.*-[ce][[:space:]]+.*(os\.system|subprocess)'
)

# Return success when a command contains a destructive operation.  This is
# deliberately conservative for filesystem targets, but does not treat every
# occurrence of the word "halt" as a shutdown command (for example, echo halt).
is_destructive() {
  local cmd="$1"
  local normalized rm_candidate
  normalized=$(printf '%s' "$cmd" | tr '\n\r\t' '   ')
  # Quotes do not change an rm target; removing them lets the safety check
  # catch forms such as rm -rf "~/" without interpreting shell input.
  rm_candidate=$(printf '%s' "$normalized" | tr -d "'\"")

  # rm options may be separate, combined, long, or followed by --.  Block
  # filesystem roots, glob roots, parent/current/home directories, and the
  # common build-tree form; ordinary named paths remain usable.
  if printf '%s' "$rm_candidate" | grep -qiE '(^|[^[:alnum:]_])rm([[:space:]]+(-[[:alnum:]]+|--[[:alnum:]-]+|--)){1,}[[:space:]]+(/|/\*|\*|\.\.?/?|\.\/\*|~(/.*)?|\$HOME(/.*)?|\./build(/.*)?)([[:space:];|&]|$)'; then
    return 0
  fi

  # Never permit removal of sensitive absolute system paths, including without flags.
  if printf '%s' "$rm_candidate" | grep -qiE '(^|[^[:alnum:]_])rm([[:space:]]+(-[[:alnum:]]+|--[[:alnum:]-]+|--))*[[:space:]]+(/|/\*|/(var|etc|usr|bin|sbin|home|Users|System|Library)(/.*)?)([[:space:];|&]|$)'; then
    return 0
  fi

  # Shutdown commands must be command words, not harmless prose/arguments.
  if printf '%s' "$normalized" | grep -qiE '(^|[;|&])[[:space:]]*(sudo[[:space:]]+)?(halt|shutdown)([[:space:]]|$)'; then
    return 0
  fi

  for pattern in "${DESTRUCTIVE_PATTERNS[@]}"; do
    if printf '%s' "$normalized" | grep -qiE "$pattern"; then
      return 0
    fi
  done

  # Cover SQL schema qualification and DELETE statements with quoted table
  # names without blocking DELETE ... WHERE ... statements.
  if printf '%s' "$normalized" | grep -qiE '(^|[^[:alnum:]_])delete[[:space:]]+from[[:space:]]+[^[:space:];|&]+[[:space:]]*(;|$)'; then
    return 0
  fi
  return 1
}

log_blocked() {
  local cmd="$1"
  local project_path="${2:-${CLAUDE_PROJECT_PATH:-$(pwd)}}"
  local timestamp
  timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  printf '[%s] BLOCKED: %s | project: %s\n' "$timestamp" "$cmd" "$project_path" >> "$LOG_FILE"
}

validate_command() {
  local cmd="$1"
  [ -z "$cmd" ] && return 0
  if is_destructive "$cmd"; then
    printf '%s\n' 'DESTRUCTIVE COMMAND BLOCKED' "Command: $cmd"
    log_blocked "$cmd"
    return 1
  fi
  return 0
}

# Claude Code's official PreToolUse contract: deny only when this hook has a
# decision.  Safe/non-Bash input intentionally produces no permissionDecision,
# preserving Claude Code's normal permission flow rather than granting access.
if [ "$#" -eq 0 ]; then
  PROTOCOL_INPUT=$(cat)
  parsed=$(printf '%s' "$PROTOCOL_INPUT" | python3 -c '
import base64, json, sys
try:
    data = json.load(sys.stdin)
    if data.get("tool_name") == "Bash":
        tool_input = data.get("tool_input") or {}
        command = tool_input.get("command", "")
        cwd = data.get("cwd") or ""
        print(base64.b64encode(command.encode()).decode() + "\t" + base64.b64encode(cwd.encode()).decode())
except (ValueError, TypeError, AttributeError):
    pass
')
  if [ -z "$parsed" ]; then
    exit 0
  fi
  command_b64=${parsed%%$'\t'*}
  cwd_b64=${parsed#*$'\t'}
  command=$(printf '%s' "$command_b64" | base64 --decode 2>/dev/null || printf '%s' "$command_b64" | base64 -D)
  cwd=$(printf '%s' "$cwd_b64" | base64 --decode 2>/dev/null || printf '%s' "$cwd_b64" | base64 -D)
  if [ -n "$command" ] && is_destructive "$command"; then
    log_blocked "$command" "${cwd:-${CLAUDE_PROJECT_PATH:-$(pwd)}}"
    printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Destructive command blocked by safety hook."}}'
  fi
  exit 0
fi

if [ "$#" -gt 0 ]; then
  validate_command "$1"
  exit $?
fi
