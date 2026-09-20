#!/bin/bash
# Claude Code Hook: Block Destructive Commands
# 
# Pre-tool-use hook that intercepts dangerous bash commands before execution.
# Follows Claude Code hooks format: ~/.claude/hooks/
#
# Install:
#   1. mkdir -p ~/.claude/hooks
#   2. cp block-destructive.sh ~/.claude/hooks/
#   3. chmod +x ~/.claude/hooks/block-destructive.sh

set -euo pipefail

# Claude Code sends PreToolUse hooks a JSON object on stdin.  Keep the
# argument form as a small, convenient local smoke-test interface.
PROTOCOL_INPUT=""
if [ "$#" -eq 0 ]; then
  PROTOCOL_INPUT=$(cat)
fi

# Log file per spec: ~/.claude/hooks/blocked.log
LOG_FILE="$HOME/.claude/hooks/blocked.log"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# List of destructive command patterns to block (per acceptance criteria)
DESTRUCTIVE_PATTERNS=(
  # File system destruction
  "rm\s+-rf\s+/"                    # rm -rf /
  "rm\s+-rf\s+\*"                   # rm -rf *
  "rm\s+-rf\s+\.\."                 # rm -rf ..
  "rm\s+(--recursive|--force|-r|-f|-[rf]{2})\s+(--recursive|--force|-r|-f|-[rf]{2})\s+(\/|\*|\.\.)" # split rm flags
  
  # Database destruction
  "DROP\s+TABLE"                    # DROP TABLE
  "DROP\s+DATABASE"                 # DROP DATABASE
  "TRUNCATE\s+"                     # TRUNCATE
  "DELETE\s+FROM\s+\w+\s*;"         # DELETE FROM without WHERE
  "DELETE\s+FROM\s+\w+\s*$"         # DELETE FROM without WHERE (end of line)
  
  # Git destruction
  "git\s+push\s+--force"            # git push --force
  "git\s+push\s+-f"                 # git push -f
  "git\s+reset\s+--hard"            # git reset --hard (on main/master)
  
  # System destruction
  "dd\s+if=/dev/zero"               # dd disk wipe
  "dd\s+if=/dev/random"             # dd disk wipe
  "mkfs\."                          # mkfs format
  "shutdown\s+-h\s+now"             # Immediate shutdown
  "halt"                            # System halt
  "init\s+0"                        # Runlevel 0 (shutdown)
  
  # Remote code execution
  "wget.*\|\s*bash"                 # Download and execute
  "curl.*\|\s*sh"                   # Download and execute
  "curl.*\|\s*bash"                 # Download and execute
  "python.*-c\s+import\s+os.*system" # Python system command injection
)

# Function to check if a command is destructive
is_destructive() {
  local cmd="$1"
  
  for pattern in "${DESTRUCTIVE_PATTERNS[@]}"; do
    if echo "$cmd" | grep -qiE "$pattern"; then
      return 0  # Match found - destructive
    fi
  done
  
  return 1  # No match - safe
}

# Function to log blocked attempts per spec
log_blocked() {
  local cmd="$1"
  local project_path="${CLAUDE_PROJECT_PATH:-$(pwd)}"
  local timestamp
  timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  echo "[$timestamp] BLOCKED: $cmd | project: $project_path" >> "$LOG_FILE"
}

# Main function: validate command before execution
validate_command() {
  local cmd="$1"
  
  # Skip empty commands
  if [ -z "$cmd" ]; then
    return 0
  fi
  
  # Check if destructive
  if is_destructive "$cmd"; then
    # Clear message to Claude explaining why blocked
    echo "⚠️  DESTRUCTIVE COMMAND BLOCKED"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Command: $cmd"
    echo ""
    echo "This command was blocked because it matches known destructive patterns:"
    echo "  • rm -rf / or similar filesystem destruction"
    echo "  • DROP TABLE / TRUNCATE / DELETE FROM without WHERE"
    echo "  • git push --force or git reset --hard"
    echo "  • dd, mkfs, or system shutdown commands"
    echo "  • Remote code execution via curl/wget | bash"
    echo ""
    echo "If this is intentional, run the command directly in your terminal."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Log the blocked attempt
    log_blocked "$cmd"
    
    # Return non-zero to block execution
    return 1
  fi
  
  # Command is safe - allow execution
  return 0
}

# Protocol mode: emit only Claude Code's structured hook response on stdout.
if [ -n "$PROTOCOL_INPUT" ]; then
  command=$(printf '%s' "$PROTOCOL_INPUT" | python3 -c '
import json, sys
try:
    data=json.load(sys.stdin)
    if data.get("tool_name") == "Bash":
        print(data.get("tool_input", {}).get("command", ""))
    else:
        print("")
except (ValueError, TypeError, AttributeError):
    print("")
')
  if [ -n "$command" ] && is_destructive "$command"; then
    log_blocked "$command"
    python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Destructive command blocked by safety hook."}}))'
  else
    python3 -c 'import json; print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}))'
  fi
  exit 0
fi

# If called with arguments, validate the first argument as a command
if [ $# -gt 0 ]; then
  if validate_command "$1"; then
    exit 0  # Safe - allow
  else
    exit 1  # Blocked
  fi
fi

# Otherwise, show usage
echo "Usage: block-destructive.sh <command>"
echo ""
echo "Claude Code hook that blocks destructive bash commands."
echo ""
echo "Installation (2 commands):"
echo "  mkdir -p ~/.claude/hooks && cp block-destructive.sh ~/.claude/hooks/"
echo "  chmod +x ~/.claude/hooks/block-destructive.sh"
echo ""
echo "Blocked patterns: rm -rf, DROP TABLE, git push --force, TRUNCATE,"
echo "DELETE FROM without WHERE, dd, mkfs, shutdown, curl|bash, etc."
echo ""
echo "Blocked attempts are logged to: $LOG_FILE"
