#!/bin/bash
# Tests for destructive command blocker

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLOCKER="$SCRIPT_DIR/../block-destructive.sh"

pass_count=0
fail_count=0

test_block() {
  local cmd="$1"
  local description="$2"
  
  # Run the blocker with the dangerous command (non-interactive mode)
  output=$(echo "" | bash "$BLOCKER" "$cmd" 2>&1 || true)
  
  if echo "$output" | grep -q "BLOCKED\|SECURITY WARNING\|destructive"; then
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
  
  if ! echo "$output" | grep -q "BLOCKED\|SECURITY WARNING"; then
    echo "✓ $description"
    ((pass_count++))
  else
    echo "✗ $description (unexpectedly blocked: $output)"
    ((fail_count++))
  fi
}

echo "Testing destructive command blocker..."
echo ""

# Test 1: Block rm -rf /
test_block "rm -rf /" "Blocks rm -rf /"

# Test 2: Block rm -rf *
test_block "rm -rf *" "Blocks rm -rf *"

# Test 3: Block dd disk wipe
test_block "dd if=/dev/zero of=/dev/sda" "Blocks dd disk wipe"

# Test 4: Block mkfs format
test_block "mkfs.ext4 /dev/sda1" "Blocks mkfs format"

# Test 5: Block sudo rm -rf
test_block "sudo rm -rf /var/log" "Blocks sudo rm -rf"

# Test 6: Allow safe commands
test_allow "ls -la" "Allows ls -la"

# Test 7: Allow git commands
test_allow "git status" "Allows git status"

# Test 8: Allow npm install
test_allow "npm install" "Allows npm install"

echo ""
echo "Results: $pass_count passed, $fail_count failed"

if [ $fail_count -eq 0 ]; then
  echo "All tests passed ✓"
  exit 0
else
  echo "Some tests failed ✗"
  exit 1
fi
