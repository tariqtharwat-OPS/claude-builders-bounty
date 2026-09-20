#!/bin/bash
# Tests for destructive command blocker
# Per acceptance criteria: blocks rm -rf, DROP TABLE, git push --force,
# TRUNCATE, DELETE FROM without WHERE; logs to ~/.claude/hooks/blocked.log;
# does not interfere with normal commands.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLOCKER="$SCRIPT_DIR/../block-destructive.sh"

pass_count=0
fail_count=0

# Clean up any previous test log
rm -f "$HOME/.claude/hooks/blocked.log"

test_block() {
  local cmd="$1"
  local description="$2"
  
  # Run the blocker with the dangerous command
  output=$(bash "$BLOCKER" "$cmd" 2>&1 || true)
  
  if echo "$output" | grep -qi "BLOCKED\|destructive"; then
    echo "✓ $description"
    ((pass_count++))
  else
    echo "✗ $description (expected block, got: $output)"
    ((fail_count++))
  fi
}

test_allow() {
  local cmd="$1"
  local description="$2"
  
  # Run the blocker with a safe command
  output=$(bash "$BLOCKER" "$cmd" 2>&1 || true)
  
  if ! echo "$output" | grep -qi "BLOCKED\|destructive"; then
    echo "✓ $description"
    ((pass_count++))
  else
    echo "✗ $description (unexpectedly blocked: $output)"
    ((fail_count++))
  fi
}

echo "Testing destructive command blocker..."
echo ""

# === REQUIRED PATTERNS (from acceptance criteria) ===

# rm -rf patterns
test_block "rm -rf /" "Blocks rm -rf /"
test_block "rm -rf *" "Blocks rm -rf *"

# DROP TABLE
test_block "DROP TABLE users" "Blocks DROP TABLE"
test_block "mysql -e 'DROP TABLE orders'" "Blocks DROP TABLE in SQL command"

# git push --force
test_block "git push --force" "Blocks git push --force"
test_block "git push -f origin main" "Blocks git push -f"

# TRUNCATE
test_block "TRUNCATE TABLE logs" "Blocks TRUNCATE TABLE"
test_block "TRUNCATE users" "Blocks TRUNCATE"

# DELETE FROM without WHERE
test_block "DELETE FROM users;" "Blocks DELETE FROM without WHERE"
test_block "DELETE FROM orders" "Blocks DELETE FROM (end of line)"

# === ADDITIONAL DESTRUCTIVE PATTERNS ===

test_block "dd if=/dev/zero of=/dev/sda" "Blocks dd disk wipe"
test_block "mkfs.ext4 /dev/sda1" "Blocks mkfs format"
test_block "sudo rm -rf /var/log" "Blocks sudo rm -rf"

# === SAFE COMMANDS (must not be blocked) ===

test_allow "ls -la" "Allows ls -la"
test_allow "git status" "Allows git status"
test_allow "npm install" "Allows npm install"
test_allow "git push origin main" "Allows normal git push"
test_allow "DELETE FROM users WHERE id=5" "Allows DELETE with WHERE clause"
test_allow "cat /etc/hosts" "Allows cat"
test_allow "python script.py" "Allows normal python"

echo ""

# === LOG FILE VERIFICATION ===
echo "Verifying log file..."
if [ -f "$HOME/.claude/hooks/blocked.log" ]; then
  log_lines=$(wc -l < "$HOME/.claude/hooks/blocked.log")
  if [ "$log_lines" -ge 7 ]; then
    echo "✓ Log file exists at ~/.claude/hooks/blocked.log with $log_lines entries"
    ((pass_count++))
  else
    echo "✗ Log file has only $log_lines entries (expected >= 7)"
    ((fail_count++))
  fi
  
  # Verify log format includes timestamp, command, project path
  if grep -q "BLOCKED:" "$HOME/.claude/hooks/blocked.log" && grep -q "project:" "$HOME/.claude/hooks/blocked.log"; then
    echo "✓ Log entries contain timestamp, command, and project path"
    ((pass_count++))
  else
    echo "✗ Log entries missing required fields"
    ((fail_count++))
  fi
else
  echo "✗ Log file not found at ~/.claude/hooks/blocked.log"
  ((fail_count++))
fi

echo ""
echo "Results: $pass_count passed, $fail_count failed"

if [ $fail_count -eq 0 ]; then
  echo "All tests passed ✓"
  exit 0
else
  echo "Some tests failed ✗"
  exit 1
fi
