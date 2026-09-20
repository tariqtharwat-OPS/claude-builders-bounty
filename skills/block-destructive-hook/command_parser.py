#!/usr/bin/env python3
"""Small shell-command tokenizer and destructive-intent classifier.

This is intentionally not a shell parser or executor. It only recognizes command
words, separators, options, and quoted arguments well enough for the hook's
contract; quoted documentation/echo text is never treated as a command.
"""
from __future__ import annotations

import os
import posixpath
import re
import sys
from dataclasses import dataclass


@dataclass
class Token:
    value: str
    quoted: bool = False


def tokenize(text: str) -> list[list[Token]]:
    """Tokenize simple shell command lists, preserving command boundaries."""
    commands: list[list[Token]] = [[]]
    buf: list[str] = []
    had_quote = False
    quote: str | None = None
    escaped = False
    i = 0

    def flush() -> None:
        nonlocal buf, had_quote
        if buf or had_quote:
            commands[-1].append(Token("".join(buf), had_quote))
            buf, had_quote = [], False

    while i < len(text):
        ch = text[i]
        if escaped:
            buf.append(ch)
            escaped = False
        elif quote:
            if ch == quote:
                quote = None
                had_quote = True
            else:
                buf.append(ch)
        elif ch in "'\"":
            quote = ch
            had_quote = True
        elif ch == "\\":
            escaped = True
        elif ch == "#" and (not buf and (not commands[-1] or True)):
            # At a token boundary, # starts a shell comment. A # in a word is data.
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        elif ch in " \t\r":
            flush()
        elif ch == "\n" or ch == ";":
            flush()
            if commands[-1]:
                commands.append([])
        elif ch in "|&":
            flush()
            if i + 1 < len(text) and text[i + 1] == ch:
                i += 1
            if commands[-1]:
                commands.append([])
        else:
            buf.append(ch)
        i += 1
    if escaped:
        buf.append("\\")
    flush()
    return [command for command in commands if command]


def command_name(tokens: list[Token]) -> tuple[str | None, int]:
    """Return executable name and index after harmless command wrappers."""
    i = 0
    while i < len(tokens):
        word = tokens[i].value
        if word in {"sudo", "command", "builtin"}:
            i += 1
            continue
        if word == "env":
            i += 1
            while i < len(tokens) and ("=" in tokens[i].value and not tokens[i].value.startswith("=")):
                i += 1
            continue
        if word.startswith("VAR=") and "=" in word:
            i += 1
            continue
        return posixpath.basename(word), i
    return None, i


def shell_rm_dangerous(tokens: list[Token], index: int) -> bool:
    args = tokens[index + 1 :]
    options_done = False
    targets: list[str] = []
    for token in args:
        word = token.value
        if not options_done and word == "--":
            options_done = True
        elif not options_done and word.startswith("-") and word != "-":
            continue
        else:
            options_done = True
            targets.append(word)
    for target in targets:
        expanded = target
        if expanded == "~" or expanded.startswith("~/"):
            expanded = os.path.expanduser(expanded)
        if expanded == "$HOME" or expanded.startswith("$HOME/"):
            expanded = os.path.expanduser("~") + expanded[5:]
        normalized = posixpath.normpath(expanded)
        if normalized in {"/", ".", ".."} or normalized.startswith("../"):
            return True
        if expanded == "./build" or expanded.startswith("./build/"):
            return True
        if expanded in {"*", "./*", ".?*"} or expanded.startswith("/*"):
            return True
        if normalized.startswith(("/var", "/etc", "/usr", "/bin", "/sbin", "/home", "/Users", "/System", "/Library")):
            return True
    return False


def sql_without_comments(value: str) -> str:
    value = re.sub(r"/\*.*?\*/", " ", value, flags=re.S)
    value = re.sub(r"--[^\r\n]*", " ", value)
    return value


def sql_delete_without_where(value: str) -> bool:
    cleaned = sql_without_comments(value)
    for statement in re.split(r";", cleaned):
        if re.match(r"^\s*delete\s+from\s+[^\s;]+(?:\s|$)", statement, re.I) and not re.search(r"\bwhere\b", statement, re.I):
            return True
    return False


def sql_schema_destructive(value: str) -> bool:
    cleaned = sql_without_comments(value)
    return bool(re.search(r"\b(?:drop\s+(?:table|database)|truncate(?:\s+table)?)\b", cleaned, re.I))


def git_force_push(tokens: list[Token], index: int) -> bool:
    args = tokens[index + 1 :]
    subcommand = None
    i = 0
    while i < len(args):
        word = args[i].value
        if word in {"-C", "--git-dir", "--work-tree"}:
            i += 2
            continue
        if word.startswith(("--git-dir=", "--work-tree=")):
            i += 1
            continue
        if not word.startswith("-"):
            subcommand = word
            break
        i += 1
    if subcommand != "push":
        return False
    return any(t.value in {"-f", "--force", "--force-with-lease"} or t.value.startswith("--force-with-lease=") for t in args[i + 1 :])


def is_destructive(command: str) -> bool:
    for tokens in tokenize(command):
        name, index = command_name(tokens)
        if not name:
            continue
        if name == "rm" and shell_rm_dangerous(tokens, index):
            return True
        if name == "git" and (git_force_push(tokens, index) or any(t.value == "--hard" for t in tokens[index + 1 :]) and any(t.value == "reset" for t in tokens[index + 1 :])):
            return True
        if name in {"halt", "shutdown"}:
            return True
        # Direct SQL entered as a command, and SQL passed to common clients.
        if name.lower() in {"delete", "drop", "truncate"}:
            statement = " ".join(t.value for t in tokens[index:])
            if name.lower() == "delete" and sql_delete_without_where(statement):
                return True
            if name.lower() in {"drop", "truncate"}:
                return True
        if name in {"psql", "mysql", "sqlite3", "sqlcmd"}:
            for token in tokens[index + 1 :]:
                if sql_delete_without_where(token.value) or sql_schema_destructive(token.value):
                    return True
        if name == "dd" and any(t.value.startswith(("if=/dev/zero", "if=/dev/random")) for t in tokens[index + 1 :]):
            return True
        if name == "mkfs" or name.startswith("mkfs."):
            return True
        if name == "init" and any(t.value == "0" for t in tokens[index + 1 :]):
            return True
        if name == "python" and any(t.value in {"-c", "-e"} for t in tokens[index + 1 :]):
            if any(re.search(r"(?:os\.system|subprocess)", t.value) for t in tokens[index + 1 :]):
                return True
    # Pipelines such as curl | sh are still structurally visible as commands.
    names = [command_name(tokens)[0] for tokens in tokenize(command)]
    if any(n in {"curl", "wget"} for n in names) and any(n in {"sh", "bash", "zsh"} for n in names):
        return True
    return False


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    return 0 if is_destructive(command) else 1


if __name__ == "__main__":
    raise SystemExit(main())
