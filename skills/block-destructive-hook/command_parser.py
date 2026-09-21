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


# Bash's ANSI-C quoting ($'...') decodes backslash escapes into literal bytes
# before the word is used as a command or argument. Recognizing this table
# structurally (rather than pattern-matching specific payloads) keeps escaped
# targets like $'/' or $'\x2f' from bypassing the token-level checks below.
_ANSI_C_ESCAPES = {
    "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f",
    "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\",
    "'": "'", '"': '"', "?": "?",
}


def _decode_ansi_c(body: str) -> str:
    """Decode the escapes bash recognizes inside a $'...' word."""
    out: list[str] = []

    def safe_chr(value: int) -> str:
        try:
            return chr(value)
        except (OverflowError, ValueError):
            # Invalid Unicode escapes must not crash the safety parser and
            # accidentally turn a destructive command into a fail-open result.
            return "\ufffd"

    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\" or i + 1 >= len(body):
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt in _ANSI_C_ESCAPES:
            out.append(_ANSI_C_ESCAPES[nxt])
            i += 2
        elif nxt == "x":
            m = re.match(r"[0-9A-Fa-f]{1,2}", body[i + 2 :])
            if m:
                out.append(safe_chr(int(m.group(), 16)))
                i += 2 + len(m.group())
            else:
                out.append(ch)
                i += 1
        elif nxt in "01234567":
            m = re.match(r"[0-7]{1,3}", body[i + 1 :])
            out.append(safe_chr(int(m.group(), 8) & 0xFF))
            i += 1 + len(m.group())
        elif nxt in "uU":
            width = 4 if nxt == "u" else 8
            m = re.match(r"[0-9A-Fa-f]{1,%d}" % width, body[i + 2 :])
            if m:
                out.append(safe_chr(int(m.group(), 16)))
                i += 2 + len(m.group())
            else:
                out.append(ch)
                i += 1
        elif nxt == "c" and i + 2 < len(body):
            out.append(safe_chr(ord(body[i + 2].upper()) ^ 0x40))
            i += 3
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _split_top_level(body: str, sep: str) -> list[str]:
    """Split on sep, ignoring occurrences nested inside braces."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in body:
        if ch == "{":
            depth += 1
            buf.append(ch)
        elif ch == "}":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


_MAX_BRACE_ITEMS = 5000


def _expand_brace_range(body: str) -> list[str] | None:
    m = re.fullmatch(r"(-?\d+)\.\.(-?\d+)(?:\.\.(-?\d+))?", body)
    if m:
        start_s, end_s, step_s = m.groups()
        start, end = int(start_s), int(end_s)
        step = abs(int(step_s)) if step_s else 1
        step = step or 1
        step = step if start <= end else -step
        width = 0
        if (start_s.startswith("0") and len(start_s) > 1) or (end_s.startswith("0") and len(end_s) > 1):
            width = max(len(start_s.lstrip("-")), len(end_s.lstrip("-")))
        values = range(start, end + (1 if step > 0 else -1), step)
        if len(values) > _MAX_BRACE_ITEMS:
            return None
        if width:
            return [f"{v:0{width}d}" if v >= 0 else f"-{abs(v):0{max(width - 1, 1)}d}" for v in values]
        return [str(v) for v in values]
    m = re.fullmatch(r"([A-Za-z])\.\.([A-Za-z])(?:\.\.(-?\d+))?", body)
    if m:
        start_c, end_c, step_s = m.groups()
        start, end = ord(start_c), ord(end_c)
        step = abs(int(step_s)) if step_s else 1
        step = step or 1
        step = step if start <= end else -step
        values = range(start, end + (1 if step > 0 else -1), step)
        return [chr(v) for v in values]
    return None


class _BraceExpansionLimitExceeded(Exception):
    pass


def expand_braces(word: str) -> list[str]:
    """Expand bash brace expressions such as {a,b,c} and {1..5} in a word.

    Only unquoted words reach this (callers skip quoted tokens), matching
    bash's own rule that brace expansion never applies inside quotes.
    """
    try:
        return _expand_braces(word, [0])
    except _BraceExpansionLimitExceeded:
        # Chained/nested groups (e.g. "{a,b}" repeated 20 times) expand
        # combinatorially; bail out rather than let one adversarial token
        # hang the classifier, and fall back to the literal, unexpanded word.
        return [word]


def _expand_braces(word: str, counter: list[int]) -> list[str]:
    start = word.find("{")
    if start == -1:
        return [word]
    depth = 0
    end = -1
    i = start
    while i < len(word):
        if word[i] == "{":
            depth += 1
        elif word[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
        i += 1
    if end == -1:
        return [word]
    prefix, body, suffix = word[:start], word[start + 1 : end], word[end + 1 :]
    parts = _split_top_level(body, ",")
    if len(parts) > 1:
        items = parts
    else:
        items = _expand_brace_range(body)
        if items is None:
            # No top-level comma or valid range: this pair is not a brace
            # expansion and stays literal, matching bash's own rule.
            return [word]
    results: list[str] = []
    for item in items:
        for candidate in _expand_braces(prefix + item + suffix, counter):
            counter[0] += 1
            if counter[0] > _MAX_BRACE_ITEMS:
                raise _BraceExpansionLimitExceeded()
            results.append(candidate)
    return results


# Utility wrappers that execute a trailing command still accept their own
# flags first. Some flags take a value that may be fused (-n19), given with
# "=" (--adjustment=19), or passed as a separate argument (-n 19); only the
# last form should consume an extra token, or the wrapper's real payload
# (e.g. the "rm" in "nice -n19 rm -rf /") is swallowed as a flag value.
WRAPPER_VALUE_OPTIONS: dict[str, set[str]] = {
    "nice": {"-n", "--adjustment"},
    "timeout": {"-k", "--kill-after", "-s", "--signal"},
    "nohup": set(),
    "exec": {"-a"},
    "xargs": {"-a", "--arg-file", "-d", "--delimiter", "-E", "-I", "--replace",
              "-L", "--max-lines", "-n", "--max-args", "-P", "--max-procs",
              "-s", "--max-chars"},
}

# SQL clients accept the statement/command either as a separate argument, a
# "--opt=value" long form, or fused directly onto a short flag (-cVALUE).
SQL_SHORT_VALUE_OPTIONS = {"-c", "-e", "-Q", "-q"}
SQL_LONG_VALUE_OPTIONS = {"--command", "--execute"}
SQL_EXACT_VALUE_OPTIONS = SQL_SHORT_VALUE_OPTIONS | SQL_LONG_VALUE_OPTIONS | {"-cmd"}


def sql_client_statements(tokens: list[Token], index: int) -> list[str]:
    """Return every candidate SQL statement passed to a SQL client invocation."""
    args = tokens[index + 1 :]
    statements: list[str] = [t.value for t in args]
    for position, token in enumerate(args):
        value = token.value
        if value in SQL_EXACT_VALUE_OPTIONS and position + 1 < len(args):
            statements.append(" ".join(item.value for item in args[position + 1 :]))
            continue
        for option in SQL_LONG_VALUE_OPTIONS:
            if value.startswith(option + "="):
                statements.append(value[len(option) + 1 :])
        for option in SQL_SHORT_VALUE_OPTIONS:
            if value.startswith(option) and value != option:
                statements.append(value[len(option) :])
    return statements


_SHELL_WORDS = {"sh", "bash", "zsh", "dash", "ksh", "shell"}
_SCRIPT_SOURCE_WORDS = _SHELL_WORDS | {"source"}


def _read_shell_word(text: str, pos: int) -> tuple[str | None, int]:
    """Read one shell word (quoted or bare) starting at pos."""
    n = len(text)
    if pos >= n:
        return None, pos
    if text.startswith("$'", pos):
        j = pos + 2
        while j < n and text[j] != "'":
            j += 2 if text[j] == "\\" and j + 1 < n else 1
        return _decode_ansi_c(text[pos + 2 : j]), min(j + 1, n)
    if text[pos] in "'\"":
        q = text[pos]
        j = pos + 1
        while j < n and text[j] != q:
            j += 2 if text[j] == "\\" and j + 1 < n else 1
        return text[pos + 1 : j], min(j + 1, n)
    j = pos
    while j < n and text[j] not in " \t\r\n;|&":
        j += 1
    return (text[pos:j] if j > pos else None), j


def here_document_payloads(text: str) -> list[str]:
    """Return payloads fed to a shell via ``<<<`` here-strings or ``<<`` heredocs.

    Both redirections feed text to the *preceding* command's stdin; when that
    command is a shell invoked without ``-c``, it reads and executes that
    text as a script, exactly like ``printf ... | sh``. The scan tracks quote
    state itself (rather than using a regex over the raw text) so a `<<<`
    that only appears inside quoted documentation, e.g. ``echo "sh <<< x"``,
    is never mistaken for a real redirection.
    """
    payloads: list[str] = []
    i = 0
    n = len(text)
    quote: str | None = None
    ansi_quote = False
    word_start = 0
    last_word = ""

    def flush_word(end: int) -> None:
        nonlocal last_word, word_start
        if end > word_start:
            last_word = text[word_start:end]
        word_start = end

    while i < n:
        ch = text[i]
        if quote == "'":
            if ansi_quote and ch == "\\":
                i += 2
                continue
            if ch == "'":
                quote = None
                ansi_quote = False
            i += 1
            continue
        if quote == '"':
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                quote = None
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if ch in "'\"":
            ansi_quote = ch == "'" and i > 0 and text[i - 1] == "$"
            quote = ch
            i += 1
            continue
        if ch in " \t\r\n;|&()":
            flush_word(i)
            word_start = i + 1
            i += 1
            continue
        if text.startswith("<<<", i):
            flush_word(i)
            boundary = max(text.rfind(c, 0, i) for c in ";\n|&")
            commands = tokenize(text[boundary + 1 : i])
            word = command_name(commands[-1])[0] if commands else None
            j = i + 3
            while j < n and text[j] in " \t":
                j += 1
            payload_word, j = _read_shell_word(text, j)
            if word in _SHELL_WORDS and payload_word is not None:
                payloads.append(payload_word)
            i = word_start = j
            continue
        if text.startswith("<<", i):
            flush_word(i)
            word = posixpath.basename(last_word)
            j = i + 2
            if j < n and text[j] == "-":
                j += 1
            while j < n and text[j] in " \t":
                j += 1
            quote_char = ""
            if j < n and text[j] in "'\"":
                quote_char = text[j]
                j += 1
            delim_start = j
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            delim = text[delim_start:j]
            if quote_char and j < n and text[j] == quote_char:
                j += 1
            while j < n and text[j] != "\n":
                j += 1
            j += 1
            body_start = j
            if delim:
                m = re.compile(r"^[ \t]*" + re.escape(delim) + r"[ \t]*$", re.M).search(text, body_start)
                if m:
                    if word in _SHELL_WORDS:
                        payloads.append(text[body_start : m.start()])
                    j = m.end()
            i = word_start = j
            continue
        i += 1
    return payloads


def split_heredocs(text: str) -> tuple[str, list[str], list[str]]:
    """Mask heredoc bodies and return executable shell/expansion payloads.

    Plain heredoc text is data, not a command (``cat <<EOF`` must not classify
    a line containing ``rm -rf``). An unquoted delimiter still permits shell
    substitutions, while a shell consumer executes its body as a script.
    """
    masked = list(text)
    shell_payloads: list[str] = []
    expansion_payloads: list[str] = []
    i = 0
    quote: str | None = None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if not text.startswith("<<", i) or text.startswith("<<<", i):
            i += 1
            continue

        op = i
        j = i + 2
        strip_tabs = j < len(text) and text[j] == "-"
        if strip_tabs:
            j += 1
        while j < len(text) and text[j] in " \t":
            j += 1
        quoted = j < len(text) and text[j] in "'\""
        q = text[j] if quoted else ""
        if quoted:
            j += 1
        start = j
        while j < len(text) and (text[j] not in " \t\r\n;|&<>" and (not q or text[j] != q)):
            j += 1
        delim = text[start:j]
        if q and j < len(text) and text[j] == q:
            j += 1
        line_end = text.find("\n", j)
        if not delim or line_end < 0:
            i = j
            continue
        body_start = line_end + 1
        pattern = r"^" + (r"\t*" if strip_tabs else "") + re.escape(delim) + r"[ \t]*$"
        match = re.compile(pattern, re.M).search(text, body_start)
        if not match:
            i = j
            continue
        body = text[body_start : match.start()]

        # Resolve the command segment immediately preceding the redirection.
        boundary = max(text.rfind(c, 0, op) for c in ";\n|&")
        prefix_commands = tokenize(text[boundary + 1 : op])
        consumer = command_name(prefix_commands[-1])[0] if prefix_commands else None
        if consumer in _SHELL_WORDS:
            shell_payloads.append(body)
        elif not quoted:
            expansion_payloads.append(body)

        # Preserve newlines so command boundaries remain intact, but hide data
        # and the terminator from the ordinary command tokenizer.
        for k in range(body_start, match.end()):
            if masked[k] != "\n":
                masked[k] = " "
        i = match.end()
    return "".join(masked), shell_payloads, expansion_payloads


def _word_scan(text: str, on_char) -> None:
    """Shared quote-aware scan used by the redirection/substitution
    detectors below: tracks quote state (including $'...' escapes) and the
    most recently completed top-level word, and calls ``on_char`` at every
    unquoted, top-level character *before* applying default word-boundary
    handling, so a caller's own multi-character syntax (``<(``, a lone
    ``|``) gets first refusal instead of being silently consumed by the
    generic boundary handling below.
    """
    i = 0
    n = len(text)
    quote: str | None = None
    ansi_quote = False
    word_start = 0
    last_word = ""

    def flush_word(end: int) -> None:
        nonlocal last_word, word_start
        if end > word_start:
            last_word = text[word_start:end]
        word_start = end

    while i < n:
        ch = text[i]
        if quote == "'":
            if ansi_quote and ch == "\\":
                i += 2
                continue
            if ch == "'":
                quote = None
                ansi_quote = False
            i += 1
            continue
        if quote == '"':
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                quote = None
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if ch in "'\"":
            ansi_quote = ch == "'" and i > 0 and text[i - 1] == "$"
            quote = ch
            i += 1
            continue
        step = on_char(text, i, last_word, flush_word)
        if step is not None:
            i = word_start = step
            continue
        if ch in " \t\r\n;|&()":
            flush_word(i)
            word_start = i + 1
            i += 1
            continue
        i += 1


def shell_process_substitution_targets(text: str) -> bool:
    """True if a shell/interpreter is given a ``<(...)`` process substitution
    as an argument. Bash runs such a substitution to produce a real file
    (typically /dev/fd/N); when the consuming command reads its argument as
    script source -- exactly what ``sh``/``bash``/... do with a positional
    filename, or what ``source`` does with any filename -- that generated
    content is executed just as if it had been piped in directly.
    """
    found = False

    def on_word(text: str, i: int, last_word: str, flush_word) -> int | None:
        nonlocal found
        if text.startswith("<(", i):
            flush_word(i)
            boundary = max(text.rfind(c, 0, i) for c in ";\n|&")
            commands = tokenize(text[boundary + 1 : i])
            consumer = command_name(commands[-1])[0] if commands else None
            if consumer in _SCRIPT_SOURCE_WORDS:
                found = True
            return i + 2
        return None

    _word_scan(text, on_word)
    return found


def pipe_shell_targets(text: str) -> list[str]:
    """Return the raw text of each command segment immediately following a
    real pipe (a single unquoted ``|``, not ``||``). A pipe feeds the
    previous command's output to this segment's stdin; when this segment
    resolves (through wrappers) to a shell reading no script/-c argument,
    that stdin is executed as code.
    """
    segments: list[str] = []

    def on_word(text: str, i: int, last_word: str, flush_word) -> int | None:
        if text[i] == "|" and (i + 1 >= len(text) or text[i + 1] != "|") and (i == 0 or text[i - 1] != "|"):
            flush_word(i)
            j = i + 1
            while j < len(text) and text[j] in " \t":
                j += 1
            k = j
            while k < len(text) and text[k] not in ";\n|&":
                k += 1
            segments.append(text[j:k])
            return j
        return None

    _word_scan(text, on_word)
    return segments


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
        elif ch == "$" and i + 1 < len(text) and text[i + 1] == "'":
            j = i + 2
            while j < len(text) and text[j] != "'":
                if text[j] == "\\" and j + 1 < len(text):
                    j += 2
                else:
                    j += 1
            buf.append(_decode_ansi_c(text[i + 2 : j]))
            had_quote = True
            i = j
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
    expanded: list[list[Token]] = []
    for command in commands:
        if not command:
            continue
        new_command: list[Token] = []
        for token in command:
            if token.quoted:
                new_command.append(token)
            else:
                new_command.extend(Token(piece) for piece in expand_braces(token.value))
        expanded.append(new_command)
    return expanded


def shell_substitutions(text: str) -> list[str]:
    """Return commands executed by shell substitution constructs.

    This intentionally understands only the quoting needed to distinguish shell
    syntax from literal documentation.  In particular, substitutions in single
    quotes (and escaped substitutions) are data, while substitutions in double
    quotes still execute. Process substitutions ``<(...)`` and ``>(...)`` are
    included because Bash evaluates their bodies before the surrounding command.
    """
    found: list[str] = []
    i = 0
    quote: str | None = None
    ansi_quote = False
    while i < len(text):
        ch = text[i]
        if quote == "'":
            if ansi_quote and ch == "\\":
                i += 2
                continue
            if ch == "'":
                quote = None
                ansi_quote = False
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if quote == '"':
            if ch == '"':
                quote = None
                i += 1
                continue
            if text.startswith(("$(", "<(", ">("), i):
                body, end = _parenthesized_substitution(text, i + 2)
                if body is not None:
                    found.append(body)
                    i = end
                    continue
            elif ch == "`":
                body, end = _backtick_substitution(text, i + 1)
                if body is not None:
                    found.append(body)
                    i = end
                    continue
            i += 1
            continue
        if ch in "'\"":
            ansi_quote = ch == "'" and i > 0 and text[i - 1] == "$"
            quote = ch
            i += 1
        elif ch == "\\":
            i += 2
        elif text.startswith(("$(", "<(", ">("), i):
            body, end = _parenthesized_substitution(text, i + 2)
            if body is not None:
                found.append(body)
                i = end
            else:
                i += 2
        elif ch == "`":
            body, end = _backtick_substitution(text, i + 1)
            if body is not None:
                found.append(body)
                i = end
            else:
                i += 1
        else:
            i += 1
    return found


def _backtick_substitution(text: str, start: int) -> tuple[str | None, int]:
    i = start
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == "`":
            return text[start:i], i + 1
        else:
            i += 1
    return None, start


def _parenthesized_substitution(text: str, start: int) -> tuple[str | None, int]:
    depth = 1
    i = start
    quote: str | None = None
    while i < len(text):
        ch = text[i]
        if quote == "'":
            if ch == "'":
                quote = None
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if quote == '"':
            if ch == '"':
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
        elif text.startswith(("$(", "<(", ">("), i):
            # Nested substitutions of any of the three forms open a new
            # level; only counting "$(" here would let a nested <( or >(
            # supply an extra ")" that closes this substitution too early,
            # truncating (and hiding) the rest of its body.
            depth += 1
            i += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return None, start


_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

_PREFIX_VALUE_OPTIONS: dict[str, set[str]] = {
    "sudo": {"-u", "--user", "-g", "--group", "-h", "--host", "-p",
             "--prompt", "-C", "--close-from", "-r", "--role", "-t", "--type"},
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "command": set(),
    "builtin": set(),
}


def _skip_utility_options(tokens: list[Token], index: int, value_options: set[str]) -> int:
    """Skip one utility's options without consuming its payload command."""
    while index < len(tokens):
        value = tokens[index].value
        if value == "--":
            return index + 1
        if not value.startswith("-") or value == "-":
            return index
        if value.startswith("--"):
            name, attached = value.split("=", 1)[0], "=" in value
        else:
            name, attached = value[:2], len(value) > 2
        index += 1
        if name in value_options and not attached:
            index += 1
    return index


def command_name(tokens: list[Token]) -> tuple[str | None, int]:
    """Return executable name and index after command-prefix wrappers.

    Prefixes are matched on basename and their options are consumed according
    to whether those options take values. This covers absolute paths and avoids
    both swallowing a payload and mistaking an option value for an executable.
    """
    i = 0
    while i < len(tokens):
        word = tokens[i].value
        base = posixpath.basename(word)
        if _ASSIGNMENT_RE.match(word):
            i += 1
            continue
        if base in _PREFIX_VALUE_OPTIONS:
            i = _skip_utility_options(tokens, i + 1, _PREFIX_VALUE_OPTIONS[base])
            if base == "env":
                while i < len(tokens) and _ASSIGNMENT_RE.match(tokens[i].value):
                    i += 1
            continue
        if base in WRAPPER_VALUE_OPTIONS:
            i = _skip_utility_options(tokens, i + 1, WRAPPER_VALUE_OPTIONS[base])
            if base == "timeout":
                while i < len(tokens) and re.fullmatch(
                    r"[0-9]+(?:\.[0-9]+)?(?:ms|s|m|h|d)?", tokens[i].value
                ):
                    i += 1
            if base == "xargs" and i >= len(tokens):
                return "echo", i
            continue
        return base, i
    return None, i


def shell_rm_dangerous(tokens: list[Token], index: int) -> bool:
    args = tokens[index + 1 :]
    options_done = False
    recursive = force = False
    targets: list[str] = []
    for token in args:
        word = token.value
        if not options_done and word == "--":
            options_done = True
        elif not options_done and word.startswith("-") and word != "-":
            if word.startswith("--"):
                recursive |= word == "--recursive"
                force |= word == "--force"
            else:
                flags = word[1:]
                recursive |= "r" in flags or "R" in flags
                force |= "f" in flags
            continue
        else:
            options_done = True
            targets.append(word)

    # The acceptance contract says to block the rm -rf pattern, regardless of
    # target. This also closes glob/expansion bypasses which cannot be resolved
    # safely without executing the user's shell.
    if recursive and force and targets:
        return True

    # Preserve protection for especially dangerous rm targets even when one of
    # -r/-f is omitted.
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


def sql_code(value: str) -> str:
    """Mask SQL comments and quoted literals while preserving code layout."""
    out = list(value)
    i = 0
    state: str | None = None
    while i < len(value):
        if state == "line-comment":
            if value[i] in "\r\n":
                state = None
            else:
                out[i] = " "
            i += 1
            continue
        if state == "block-comment":
            out[i] = " "
            if value.startswith("*/", i):
                out[i : i + 2] = [" ", " "]
                state = None
                i += 2
            else:
                i += 1
            continue
        if state in {"'", '"', "`"}:
            quote = state
            out[i] = " "
            if value[i] == quote:
                if i + 1 < len(value) and value[i + 1] == quote:
                    out[i + 1] = " "
                    i += 2
                    continue
                state = None
            elif value[i] == "\\" and i + 1 < len(value):
                out[i + 1] = " "
                i += 2
                continue
            i += 1
            continue
        if value.startswith("--", i):
            out[i : i + 2] = [" ", " "]
            state = "line-comment"
            i += 2
        elif value.startswith("/*", i):
            out[i : i + 2] = [" ", " "]
            state = "block-comment"
            i += 2
        elif value[i] in "'\"`":
            out[i] = " "
            state = value[i]
            i += 1
        else:
            i += 1
    return "".join(out)


def sql_delete_without_where(value: str) -> bool:
    cleaned = sql_code(value)
    for statement in cleaned.split(";"):
        if re.match(r"^\s*delete\s+from\s+[^\s;]+(?:\s|$)", statement, re.I) and not re.search(r"\bwhere\b", statement, re.I):
            return True
    return False


def sql_schema_destructive(value: str) -> bool:
    return bool(re.search(r"\b(?:drop\s+(?:table|database)|truncate(?:\s+table)?)\b", sql_code(value), re.I))


def git_force_push(tokens: list[Token], index: int) -> bool:
    args = tokens[index + 1 :]
    subcommand = None
    i = 0
    while i < len(args):
        word = args[i].value
        if word in {"-C", "-c", "--config-env", "--git-dir", "--work-tree",
                    "--namespace", "--super-prefix"}:
            i += 2
            continue
        if word.startswith(("--config-env=", "--git-dir=", "--work-tree=",
                            "--namespace=", "--super-prefix=")):
            i += 1
            continue
        if not word.startswith("-"):
            subcommand = word
            break
        i += 1
    if subcommand != "push":
        return False
    return any(t.value in {"-f", "--force", "--force-with-lease"} or t.value.startswith("--force-with-lease=") for t in args[i + 1 :])


_SHORT_OPTION_ASSIGNMENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=(\-[rRfF]+)\b")


def expand_simple_option_assignments(command: str) -> str:
    """Resolve literal rm flags stored in a shell variable."""
    assignments = {name: flags for name, flags in _SHORT_OPTION_ASSIGNMENT.findall(command)}
    for name, flags in assignments.items():
        command = re.sub(rf"\${re.escape(name)}\b|\$\{{{re.escape(name)}\}}", flags, command)
    return command


def piped_or_heredoc_sql_is_destructive(command: str) -> bool:
    """Inspect SQL text fed to sqlite3 through stdin rather than argv."""
    if not re.search(r"(?:\|\s*|\b)sqlite3\b[^\n]*(?:<<|$)", command):
        return False
    delete = re.search(r"\bdelete\s+from\s+[^\s;]+(?:\s|$)", command, re.I)
    if delete and not re.search(r"\bwhere\b", command[delete.start() :], re.I):
        return True
    return bool(re.search(r"\b(?:drop\s+(?:table|database)|truncate(?:\s+table)?)\b", command, re.I))


# is_destructive recurses into every substitution, wrapper payload, and -c
# string it finds. A real command never nests more than a few levels deep;
# an adversarial one can nest thousands, which previously blew Python's
# recursion limit and crashed -- and a crash exits non-zero, indistinguishable
# from "allowed", i.e. silently fails open on exactly the input designed to
# defeat analysis. Past this depth we fail closed instead.
_MAX_RECURSION_DEPTH = 50


def is_destructive(command: str, _depth: int = 0) -> bool:
    if _depth > _MAX_RECURSION_DEPTH:
        return True

    command = expand_simple_option_assignments(command)
    structural_command, heredoc_shell_payloads, heredoc_expansion_payloads = split_heredocs(command)

    if piped_or_heredoc_sql_is_destructive(command):
        return True

    # Command substitutions execute even when embedded in an otherwise benign
    # command. Quoted heredocs suppress expansion; unquoted heredocs do not.
    substitution_sources = [structural_command, *heredoc_expansion_payloads]
    if any(
        is_destructive(substitution, _depth + 1)
        for source in substitution_sources
        for substitution in shell_substitutions(source)
    ):
        return True

    # A shell fed a script via a heredoc/here-string executes it like a pipe.
    if any(is_destructive(payload, _depth + 1) for payload in heredoc_shell_payloads):
        return True
    if any(is_destructive(payload, _depth + 1) for payload in here_document_payloads(structural_command)):
        return True

    for tokens in tokenize(structural_command):
        name, index = command_name(tokens)
        if not name:
            continue
        # Common utility wrappers execute the remaining arguments as a command;
        # recursively classify that payload instead of treating the wrapper as
        # the terminal command name.
        for position, token in enumerate(tokens):
            wrapper = posixpath.basename(token.value)
            if wrapper in WRAPPER_VALUE_OPTIONS:
                value_opts = WRAPPER_VALUE_OPTIONS[wrapper]
                payload = tokens[position + 1 :]
                idx = 0
                while idx < len(payload) and payload[idx].value.startswith("-") and payload[idx].value != "-":
                    opt = payload[idx].value
                    if opt == "--":
                        idx += 1
                        break
                    if opt.startswith("--"):
                        optname, fused = opt.split("=", 1)[0], "=" in opt
                    else:
                        optname, fused = opt[:2], len(opt) > 2
                    idx += 1
                    if optname in value_opts and not fused:
                        idx += 1
                payload = payload[idx:]
                if wrapper == "timeout":
                    while payload and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:ms|s|m|h|d)?", payload[0].value):
                        payload = payload[1:]
                if payload and is_destructive(" ".join(item.value for item in payload), _depth + 1):
                    return True
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
            for statement in sql_client_statements(tokens, index):
                if sql_delete_without_where(statement) or sql_schema_destructive(statement):
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
        # A shell's -c string and eval's arguments are executable shell code,
        # unlike the same text passed to echo/printf as documentation. Scan for
        # shells after wrappers such as exec, timeout, nohup, nice, and xargs.
        for position, token in enumerate(tokens[index:], start=index):
            if posixpath.basename(token.value) in _SHELL_WORDS and position + 1 < len(tokens):
                shell_args = tokens[position + 1 :]
                for shell_position, shell_token in enumerate(shell_args):
                    option = shell_token.value
                    if option.startswith(("-c=", "--command=")):
                        payload = option.split("=", 1)[1]
                    elif (
                        option == "--command" or
                        (option.startswith("-") and not option.startswith("--") and "c" in option[1:])
                    ) and shell_position + 1 < len(shell_args):
                        # Shell flags are routinely clustered (-lc, -euxc); the
                        # command string is the following argv element.
                        payload = shell_args[shell_position + 1].value
                    else:
                        continue
                    if payload and is_destructive(payload, _depth + 1):
                        return True
                    break
        if name == "eval":
            payload = " ".join(token.value for token in tokens[index + 1 :])
            if payload and is_destructive(payload, _depth + 1):
                return True
        # find executes the command after -exec/-execdir; inspect its payload.
        if name == "find":
            for position, token in enumerate(tokens[index + 1 :], start=index + 1):
                if token.value in {"-exec", "-execdir"}:
                    payload = []
                    for item in tokens[position + 1 :]:
                        if item.value in {";", "+"}:
                            break
                        payload.append(item.value)
                    if payload and is_destructive(" ".join(payload), _depth + 1):
                        return True
    # Pipelines into a shell execute their stdin as code; fail closed. A shell
    # reading a <(...) process substitution as its script argument is exactly
    # as dangerous as being piped that same output directly.
    for segment in pipe_shell_targets(structural_command):
        seg_tokens = tokenize(segment)
        if seg_tokens and command_name(seg_tokens[0])[0] in _SHELL_WORDS:
            return True
    if shell_process_substitution_targets(structural_command):
        return True
    # Download-then-execute remains covered even without a direct pipe (e.g.
    # "curl -o f url; bash f").
    names = [command_name(tokens)[0] for tokens in tokenize(structural_command)]
    if any(n in {"curl", "wget"} for n in names) and any(n in _SHELL_WORDS for n in names):
        return True
    return False


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    return 0 if is_destructive(command) else 1


if __name__ == "__main__":
    raise SystemExit(main())
