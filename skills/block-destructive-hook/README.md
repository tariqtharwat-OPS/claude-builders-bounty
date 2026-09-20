# Block Destructive Commands — Claude Code Hook

Pre-tool-use hook that intercepts dangerous bash commands before they execute in Claude Code.

## Installation (2 commands)

```bash
mkdir -p ~/.claude/hooks && cp block-destructive.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/block-destructive.sh
```

## Blocked Patterns

| Category | Patterns |
|----------|----------|
| Filesystem | `rm -rf /`, `rm -rf *`, `rm -rf ..` |
| Database | `DROP TABLE`, `DROP DATABASE`, `TRUNCATE`, `DELETE FROM` without `WHERE` |
| Git | `git push --force`, `git push -f`, `git reset --hard` |
| System | `dd if=/dev/zero`, `mkfs.*`, `shutdown`, `halt`, `init 0` |
| Remote exec | `wget … \| bash`, `curl … \| sh`, `python -c "import os; system(…)"` |

## Hook Protocol

Claude Code `PreToolUse` invokes the script with a JSON request on stdin, for example
`{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}`. The hook emits
structured JSON with `hookSpecificOutput.permissionDecision` set to `deny` or
`allow`. The legacy `block-destructive.sh "command"` form remains available for
manual smoke tests.

## How It Works

1. Claude Code invokes the hook before executing any bash command
2. The hook checks the command against known destructive patterns
3. If matched: command is **blocked**, Claude receives a clear explanation, and the attempt is logged
4. If safe: command passes through normally

## Logging

Every blocked attempt is logged to `~/.claude/hooks/blocked.log` with:
- Timestamp
- Attempted command
- Project path

## Testing

```bash
bash tests/test_block_destructive.sh
```

## Why This Exists

Claude Code can execute arbitrary shell commands. A misunderstood instruction or hallucinated command could destroy data, drop databases, or force-push broken code. This hook adds a safety net that catches the most dangerous patterns before they cause irreversible damage.
