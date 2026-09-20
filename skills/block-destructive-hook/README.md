# Block Destructive Commands — Claude Code Hook

A `PreToolUse` hook that denies dangerous Bash commands before Claude Code runs them.
It only returns a permission decision for a blocked command. Safe commands return no
hook decision, so Claude Code's normal permission flow remains in control.

## Claude Code registration

From this directory, run the installer once:

```bash
./install.sh
```

It copies the hook and its tokenizer to `~/.claude/hooks/`, then merges one
`Bash` `PreToolUse` entry into `~/.claude/settings.json` without replacing
unrelated settings. The installed hook uses its adjacent tokenizer, so the
absolute path remains valid from every project.

Manual registration is also supported: copy both `block-destructive.sh` and
`command_parser.py` to a stable absolute directory, make them executable, and
add this to `~/.claude/settings.json` (merge it; do not replace unrelated
configuration):

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

The classifier tokenizes command boundaries, shell quoting, wrappers, and options;
it does not search arbitrary text for dangerous substrings. It blocks:

- Filesystem destruction: root, normalized parent traversal, glob-root,
  parent/current/home directories, sensitive system subtrees, and `./build`
- `DROP TABLE`, `DROP DATABASE`, `TRUNCATE`, and `DELETE FROM` without `WHERE`,
  including multiline SQL and SQL comments
- `git push --force`, `git push -f`, `git push --force-with-lease` (including
  `git -C repo push ...`), and `git reset --hard`
- `shutdown` and `halt` as command words, plus the existing download-to-shell
  and disk-wipe patterns

Ordinary `rm -rf build` remains neutral. Quoted documentation such as
`echo 'rm -rf /'` and `printf 'git push --force'` remains neutral. Blocked
attempts are logged to `~/.claude/hooks/blocked.log`; the `project` value comes
from the request's JSON `cwd`.

## Testing

Run the protocol-level tests from this directory:

```bash
bash tests/test_block_destructive.sh
```

The test invokes the script with the same JSON-over-stdin protocol Claude Code
uses and checks denial, neutral safe-command behavior, quoted echo/documentation,
`git -C` force pushes, force-with-lease, normalized paths, multiline/commented
SQL, benign halt text, and JSON `cwd` logging. The installer is intentionally
small and only merges its own hook entry.
