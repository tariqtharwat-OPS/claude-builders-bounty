# Block Destructive Commands — Claude Code Hook

A `PreToolUse` hook that denies dangerous Bash commands before Claude Code runs them.
It only returns a permission decision for a blocked command. Safe commands return no
hook decision, so Claude Code's normal permission flow remains in control.

## Claude Code registration

Copy the script to a stable absolute path and make it executable:

```bash
mkdir -p ~/.claude/hooks
cp block-destructive.sh ~/.claude/hooks/block-destructive.sh
chmod 700 ~/.claude/hooks/block-destructive.sh
```

Add this to `~/.claude/settings.json` (merge it with existing settings; do not
replace unrelated configuration):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/Users/YOU/.claude/hooks/block-destructive.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Use the real absolute path for `command`. The `matcher` limits this hook to the
Bash tool. Claude Code sends a JSON request on stdin, including `tool_name`,
`tool_input.command`, and `cwd`. A blocked request returns the official
`hookSpecificOutput` `PreToolUse` response with `permissionDecision: "deny"`.
For safe/non-Bash requests this hook emits no decision (neutral exit), rather
than explicitly returning `allow` and bypassing Claude Code permissions.

## Blocked patterns

- Filesystem destruction: root, glob-root, parent/current/home directories, and
  `./build` targets used with recursive/force `rm` options
- `DROP TABLE`, `DROP DATABASE`, `TRUNCATE`, and `DELETE FROM` without `WHERE`
- `git push --force`, `git push -f`, and `git reset --hard`
- Disk formatting/wiping and `shutdown`, `halt`, or `init 0`
- Common `curl|sh`, `curl|bash`, `wget|bash`, and Python command-execution forms

A word such as `halt` in `printf halt` is not treated as a shutdown command.
Blocked attempts are logged to `~/.claude/hooks/blocked.log`; the `project` value
comes from the request's JSON `cwd`.

## Testing

Run the protocol-level tests from this directory:

```bash
bash tests/test_block_destructive.sh
```

The test invokes the script with the same JSON-over-stdin protocol Claude Code
uses and checks denial, neutral safe-command behavior, adversarial path forms,
benign halt text, and JSON `cwd` logging.
