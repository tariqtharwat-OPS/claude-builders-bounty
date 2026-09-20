#!/bin/bash
# Claude Code Hook: Block Destructive Commands
# 
# This hook intercepts dangerous shell commands before execution in Claude Code.
# Install by adding to your Claude Code configuration or wrapping exec calls.

set -euo pipefail

# List of destructive command patterns to block
DESTRUCTIVE_PATTERNS=(
  "^rm\s+-rf\s+/$"                    # rm -rf /
  "^rm\s+-rf\s+\*"                    # rm -rf *
  "^dd\s+if=/dev/zero"                # dd if=/dev/zero (disk wipe)
  "^mkfs\."                            # mkfs.ext4, mkfs.xfs, etc (format disk)
  "^sudo\s+rm\s+-rf"                  # sudo rm -rf
  "^:\(\)\{\s*:\|:\s*&\s*\}\s*;:"     # Fork bomb
  "^chmod\s+-R\s+777\s+/"             # chmod -R 777 /
  "^chown\s+-R\s+root:root\s+/"       # chown entire system
  "^shutdown\s+-h\s+now"              # Immediate shutdown
  "^halt"                              # System halt
  "^init\s+0"                          # Runlevel 0 (shutdown)
  "^wget.*\|\s*bash"                  # Download and execute
  "^curl.*\|\s*sh"                    # Download and execute
  "^python.*-c\s+import\s+os.*system" # Python system command injection
)

# Function to check if a command is destructive
is_destructive() {
  local cmd="$1"
  
  for pattern in "${DESTRUCTIVE_PATTERNS[@]}"; do
    if echo "$cmd" | grep -qE "$pattern"; then
      return 0  # Match found - destructive
    fi
  done
  
  return 1  # No match - safe
}

# Function to log blocked attempts
log_blocked() {
  local cmd="$1"
  local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  echo "[$timestamp] BLOCKED: $cmd" >> ~/.claude-code-blocked.log
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
    echo "⚠️  SECURITY WARNING: Destructive command detected!"
    echo "   Command: $cmd"
    echo ""
    echo "This command could cause irreversible damage to your system."
    echo ""
    read -p "Are you absolutely sure? Type 'YES' to proceed: " confirmation
    
    if [ "$confirmation" != "YES" ]; then
      echo "❌ Command blocked for safety."
      log_blocked "$cmd"
      return 1
    else
      echo "⚠️  Proceeding with caution..."
      log_blocked "$cmd"
    fi
  fi
  
  return 0
}

# Example usage in Claude Code context:
# Add this to your Claude Code pre-execution hook:
#
# ```json
# {
#   "hooks": {
#     "preExec": "bash /path/to/block-destructive.sh \"$COMMAND\""
#   }
# }
# ```

# If called with arguments, validate the first argument as a command
if [ $# -gt 0 ]; then
  validate_command "$1"
  exit $?
fi

# Otherwise, show usage
echo "Usage: block-destructive.sh <command>"
echo ""
echo "This script blocks dangerous shell commands in Claude Code."
echo "Add it as a pre-execution hook to protect your system."
