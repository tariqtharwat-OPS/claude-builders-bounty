#!/usr/bin/env python3
"""Generate a conservative, diff-grounded pull-request review.

The patch is the source of truth for changed paths and line counts. PR metadata is
optional context and is never allowed to manufacture findings or certainty.
"""
from __future__ import annotations

import argparse
import ast
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class InputError(ValueError):
    """An input cannot be reviewed safely."""


def _require_metadata_object(value) -> dict:
    if not isinstance(value, dict):
        raise InputError("metadata must be a JSON object")
    return value


def load_metadata(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"metadata could not be read: {exc}") from exc
    return _require_metadata_object(value)


def fetch_pr(url: str) -> tuple[dict, str]:
    parsed = urlparse(url)
    match = re.fullmatch(r"/([^/]+)/([^/]+)/pull/(\d+)/?", parsed.path)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or not match:
        raise InputError("expected https://github.com/owner/repo/pull/number")
    owner, repo, number = match.groups()
    target = f"{owner}/{repo}"
    try:
        metadata = _require_metadata_object(json.loads(subprocess.check_output(
            ["gh", "pr", "view", number, "--repo", target,
             "--json", "title,body,files,additions,deletions,changedFiles"],
            text=True, stderr=subprocess.PIPE)))
        diff = subprocess.check_output(["gh", "pr", "diff", number, "--repo", target],
                                       text=True, stderr=subprocess.PIPE)
        if not isinstance(diff, str):
            raise InputError("GitHub CLI returned a non-text diff")
        return metadata, diff
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError,
            UnicodeError):
        api = f"https://api.github.com/repos/{target}/pulls/{number}"
        try:
            def get_json(endpoint):
                request = Request(endpoint, headers={"Accept": "application/vnd.github+json"})
                with urlopen(request, timeout=20) as response:
                    return json.load(response)
            raw = _require_metadata_object(get_json(api))
            files = get_json(api + "/files?per_page=100")
            if not isinstance(files, list):
                raise InputError("GitHub API returned invalid file metadata")
            metadata = {"title": raw.get("title", ""), "body": raw.get("body", ""),
                        "files": files, "additions": raw.get("additions"),
                        "deletions": raw.get("deletions"),
                        "changedFiles": raw.get("changed_files")}
            diff_url = raw.get("diff_url") if isinstance(raw, dict) else None
            if not isinstance(diff_url, str) or not diff_url:
                raise InputError("GitHub API returned an invalid diff_url")
            request = Request(diff_url, headers={"Accept": "application/vnd.github.v3.diff"})
            with urlopen(request, timeout=20) as response:
                return metadata, response.read().decode("utf-8")
        except (HTTPError, URLError, KeyError, ValueError, TypeError,
                AttributeError, UnicodeError, json.JSONDecodeError) as exc:
            raise InputError(f"unable to fetch PR: {exc}") from exc


def load_diff(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InputError(f"diff could not be read: {exc}") from exc


def _is_docs(path: str) -> bool:
    lower = path.lower()
    return (lower.endswith((".md", ".mdx", ".rst", ".adoc", ".txt")) or
            "/docs/" in f"/{lower}" or lower.startswith("docs/"))


def _is_test(path: str) -> bool:
    lower = path.lower()
    return (lower.startswith(("test/", "tests/", "spec/", "specs/")) or
            "/test/" in lower or "/tests/" in lower or
            bool(re.search(r"(^|[_./])test[s]?([_.]|$)", lower)))


def _is_generated_or_vendor(path: str) -> bool:
    lower = path.lower()
    return ("/vendor/" in f"/{lower}" or lower.startswith(("vendor/", "generated/")) or
            "/generated/" in f"/{lower}" or lower.endswith((".min.js", ".min.css")))


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")


def _is_safe_patch_path(path: str) -> bool:
    """Accept only canonical, relative, repository-local POSIX paths."""
    if (not isinstance(path, str) or not path or path.startswith("/") or
            "\\" in path or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        return False
    normalized = posixpath.normpath(path)
    if normalized in (".", "..") or normalized != path:
        return False
    return ".." not in path.split("/")


_QUOTED_GIT_PATH = r'"(?:\\.|[^"\\])*"'


def _decode_git_path(token: str) -> str | None:
    """Decode Git's C-quoted UTF-8 path representation."""
    if not token.startswith('"'):
        return token
    try:
        decoded = ast.literal_eval(token)
        if not isinstance(decoded, str):
            return None
        return decoded.encode("latin-1").decode("utf-8")
    except (SyntaxError, ValueError, UnicodeError):
        return None


def _diff_paths(header: str) -> tuple[str, str] | None:
    """Extract the two paths from a conventional git diff header.

    Git leaves ordinary spaces unquoted, so the separator is the final `` b/``.
    More exotic quoted names are rejected rather than decoded incorrectly.
    """
    quoted = re.fullmatch(
        rf"diff --git ({_QUOTED_GIT_PATH}) ({_QUOTED_GIT_PATH})", header)
    if quoted:
        old_token = _decode_git_path(quoted.group(1))
        new_token = _decode_git_path(quoted.group(2))
        if not old_token or not new_token:
            return None
        if not old_token.startswith("a/") or not new_token.startswith("b/"):
            return None
        return old_token[2:], new_token[2:]
    match = re.fullmatch(r"diff --git a/(.+) b/(.+)", header)
    return (match.group(1), match.group(2)) if match else None


_GIT_BINARY_ALPHABET = set(
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`|~"
)


def _validate_git_binary_payload(lines: list[str]) -> str | None:
    """Validate the framed, size-delimited payload emitted by ``git diff --binary``."""
    if not lines:
        return "GIT binary patch has no payload"
    index = 0
    sections = 0
    while index < len(lines):
        match = re.fullmatch(r"(?:literal|delta) (\d+)", lines[index])
        if not match:
            return "GIT binary patch has an invalid literal/delta header"
        expected = int(match.group(1))
        index += 1
        decoded = 0
        payload_lines = 0
        while index < len(lines) and lines[index] != "":
            encoded = lines[index]
            if not encoded or encoded[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
                return "GIT binary patch has an invalid payload length"
            length = (ord(encoded[0]) - ord("A") + 1
                      if encoded[0].isupper() else ord(encoded[0]) - ord("a") + 27)
            if length > 52 or len(encoded) != 1 + ((length + 3) // 4) * 5:
                return "GIT binary patch has a truncated or malformed payload line"
            if any(char not in _GIT_BINARY_ALPHABET for char in encoded[1:]):
                return "GIT binary patch has invalid base85 payload characters"
            decoded += length
            payload_lines += 1
            index += 1
        if decoded != expected or (expected and not payload_lines):
            return "GIT binary patch payload length does not match its declared size"
        sections += 1
        if index < len(lines):
            index += 1
            if index == len(lines):
                return "GIT binary patch ends between payload sections"
    return None if sections else "GIT binary patch has no payload sections"


def _path_from_header(value: str, prefix: str) -> str | None:
    """Return a conventional ---/+++ path, or None for an invalid header."""
    if value == "/dev/null":
        return value
    quoted = re.fullmatch(rf"({_QUOTED_GIT_PATH})(?:\t.*)?", value)
    if quoted:
        value = _decode_git_path(quoted.group(1)) or ""
    else:
        value = value.split("\t", 1)[0]
    if not value.startswith(prefix):
        return None
    path = value[len(prefix):]
    return path if path and _is_safe_patch_path(path) else None


def analyze_diff(diff_text: str) -> dict:
    """Parse a complete unified patch and inspect only attributable additions.

    A hunk is accepted only when its observed context/add/delete lines exactly
    match both counts in its header. This rejects truncated or hand-edited
    patches instead of reviewing a misleading prefix.
    """
    result = {"files_changed": [], "text_files": [], "binary_files": [],
              "file_status": {}, "total_additions": 0, "total_deletions": 0,
              "security_flags": [], "security_notes": [], "has_tests": False,
              "has_test_evidence": False, "has_docs": False,
              "generated_files": [], "malformed": False, "parse_warnings": [],
              "reviewable": False, "input_state": "unclassified",
              "trivial_reason": "", "total_changed_lines": 0}
    current = None
    current_state = None
    hunk = None
    seen_destinations = set()
    secret_patterns = [
        (r"(?i)\b(password|passwd|secret|api[_-]?key|private[_-]?key)\s*[:=]\s*['\"][^'\"]+['\"]", "Hardcoded credential"),
        (r"(?i)\b(token|access_token)\s*[:=]\s*['\"][A-Za-z0-9_./+=-]{12,}['\"]", "Hardcoded access token"),
        (r"(?i)\beval\s*\(", "Dynamic code execution"),
        (r"(?i)\bsubprocess\.(call|run|Popen)\s*\(.*\bshell\s*=\s*True", "Shell injection risk"),
        (r"(?i)\bos\.system\s*\(", "Command injection risk"),
    ]

    def warn(message: str) -> None:
        result["malformed"] = True
        result["parse_warnings"].append(message)

    def finish_hunk() -> None:
        nonlocal hunk
        if hunk is not None:
            if (hunk["old_seen"] != hunk["old_expected"] or
                    hunk["new_seen"] != hunk["new_expected"]):
                warn(f"hunk counts do not match in {current or 'unknown file'}")
            hunk = None

    def finish_file() -> None:
        nonlocal current, current_state
        finish_hunk()
        if current_state is not None:
            if current_state["binary"]:
                if (current_state["old_header"] or current_state["new_header"] or
                        current_state["saw_hunk"]):
                    warn(f"binary patch for {current or 'unknown file'} also contains text structure")
                if current_state["git_binary"]:
                    error = _validate_git_binary_payload(current_state["binary_payload"])
                    if error:
                        warn(f"{error} in {current or 'unknown file'}")
                if current_state["safe"] and current not in result["binary_files"]:
                    result["binary_files"].append(current)
            else:
                if not current_state["old_header"] or not current_state["new_header"]:
                    warn(f"text patch for {current or 'unknown file'} lacks ---/+++ headers")
                if (current_state["old_path"] == "/dev/null" and
                        current_state["new_path"] == "/dev/null"):
                    warn(f"text patch for {current or 'unknown file'} has no file side")
                if not current_state["saw_hunk"]:
                    warn(f"text patch for {current or 'unknown file'} has no hunk")
                if current_state["safe"] and current not in result["text_files"]:
                    result["text_files"].append(current)
        current = None
        current_state = None

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            finish_file()
            paths = _diff_paths(raw)
            current = paths[1] if paths else None
            safe = bool(paths and _is_safe_patch_path(paths[0]) and
                        _is_safe_patch_path(paths[1]))
            current_state = {"old_header": False, "new_header": False,
                             "old_path": None, "new_path": None,
                             "saw_hunk": False, "binary": False,
                             "safe": safe,
                             "old_diff": paths[0] if paths else None,
                             "new_diff": paths[1] if paths else None,
                             "git_binary": False, "binary_payload": []}
            if not paths:
                warn("an unreadable diff header was found")
            elif not safe:
                warn("an unsafe or non-canonical path was found in a diff header")
            elif current in seen_destinations:
                warn(f"repeated or ambiguous file section for {current}")
            else:
                seen_destinations.add(current)
                result["files_changed"].append(current)
                result["file_status"][current] = "modified"
                if _is_test(current):
                    result["has_tests"] = True
                if _is_docs(current):
                    result["has_docs"] = True
                if (_is_generated_or_vendor(current) and
                        current not in result["generated_files"]):
                    result["generated_files"].append(current)
            continue

        if current_state is None:
            if raw.strip():
                warn("content appeared outside a file patch")
            continue

        if raw.startswith("--- ") and hunk is None:
            if current_state["binary"] or current_state["new_header"]:
                warn(f"unexpected --- header transition in {current or 'unknown file'}")
            path = _path_from_header(raw[4:], "a/")
            if path is None:
                warn(f"invalid --- header in {current}")
            else:
                if current_state["old_header"]:
                    warn(f"duplicate --- header in {current}")
                expected = current_state["old_diff"]
                if path not in (expected, "/dev/null"):
                    warn(f"--- header path does not match diff header in {current}")
                current_state["old_path"] = path
                current_state["old_header"] = True
                if path == "/dev/null" and current_state["safe"]:
                    result["file_status"][current] = "added"
            continue
        if raw.startswith("+++ ") and hunk is None:
            if current_state["binary"] or not current_state["old_header"]:
                warn(f"unexpected +++ header transition in {current or 'unknown file'}")
            path = _path_from_header(raw[4:], "b/")
            if path is None:
                warn(f"invalid +++ header in {current}")
            else:
                if current_state["new_header"]:
                    warn(f"duplicate +++ header in {current}")
                expected = current_state["new_diff"]
                if path not in (expected, "/dev/null"):
                    warn(f"+++ header path does not match diff header in {current}")
                current_state["new_path"] = path
                current_state["new_header"] = True
                if path == "/dev/null" and current_state["safe"]:
                    result["file_status"][current] = "deleted"
            continue
        if raw.startswith(("Binary files ", "GIT binary patch")):
            finish_hunk()
            if current_state["binary"]:
                warn(f"duplicate binary marker in {current or 'unknown file'}")
            if (current_state["old_header"] or current_state["new_header"] or
                    current_state["saw_hunk"]):
                warn(f"binary marker conflicts with text structure in {current or 'unknown file'}")
            if raw.startswith("Binary files "):
                marker = re.fullmatch(r"Binary files a/(.+) and b/(.+) differ", raw)
                if (not marker or not current_state["safe"] or
                        marker.group(1) != current_state["old_diff"] or
                        marker.group(2) != current_state["new_diff"]):
                    warn(f"binary marker paths do not match the diff header in {current or 'unknown file'}")
            else:
                current_state["git_binary"] = True
            current_state["binary"] = True
            result["parse_warnings"].append(f"binary content in {current} was not line-inspected")
            continue
        if raw.startswith("@@"):
            if current_state["binary"]:
                warn(f"binary marker followed by textual hunk in {current}")
                continue
            if not current_state["old_header"] or not current_state["new_header"]:
                warn(f"hunk appeared before a complete header pair in {current or 'unknown file'}")
            finish_hunk()
            match = _HUNK_RE.match(raw)
            if not match:
                warn(f"malformed hunk in {current}")
                continue
            hunk = {"old_expected": int(match.group(2) or "1"),
                    "new_expected": int(match.group(4) or "1"),
                    "old_seen": 0, "new_seen": 0}
            current_state["saw_hunk"] = True
            continue
        if hunk is None:
            if current_state["binary"]:
                if current_state["git_binary"]:
                    current_state["binary_payload"].append(raw)
                # Binary content is uninspectable, but its framing is validated.
                continue
            if raw.startswith(("index ", "old mode ", "new mode ",
                               "new file mode ", "deleted file mode ",
                               "similarity index ", "dissimilarity index ")):
                continue
            transition = next((prefix for prefix in
                               ("rename from ", "rename to ", "copy from ", "copy to ")
                               if raw.startswith(prefix)), None)
            if transition:
                transition_path = raw[len(transition):]
                if not _is_safe_patch_path(transition_path):
                    warn(f"unsafe path in {transition.strip()} metadata")
                continue
            if raw.strip():
                warn(f"unexpected content outside hunk in {current}")
            continue
        if raw.startswith("\\ No newline"):
            continue
        if not raw or raw[0] not in " +-":
            warn(f"unprefixed content in {current}")
            continue
        if raw[0] == " ":
            hunk["old_seen"] += 1
            hunk["new_seen"] += 1
            continue
        if raw[0] == "-":
            hunk["old_seen"] += 1
            if raw[1:].strip():
                result["total_deletions"] += 1
            continue
        # The only remaining valid hunk marker is '+'.
        result["total_additions"] += 1
        hunk["new_seen"] += 1
        if not current or not current_state["safe"]:
            warn("addition has no safe file path")
            continue
        added = raw[1:].strip()
        if _is_test(current):
            result["has_tests"] = True
            if re.search(r"(?:\bassert(?:[A-Z]\w*)?\b|\bdef\s+test_\w+|\b(?:it|test|describe)\s*\(|\b(?:pytest|unittest)\b|\bfunc\s+Test[A-Z]|#\[test\]|\.to(?:Equal|Be|Contain)\s*\()", added):
                result["has_test_evidence"] = True
        if _is_docs(current):
            result["has_docs"] = True
        if _is_generated_or_vendor(current) and current not in result["generated_files"]:
            result["generated_files"].append(current)
        if _is_docs(current):
            if any(re.search(pattern, added) for pattern, _ in secret_patterns):
                result["security_notes"].append(f"example-like security text in documentation: {current}")
            continue
        for pattern, label in secret_patterns:
            if re.search(pattern, added):
                if "hardcoded credential" in added.lower() and "password =" in added.lower():
                    result["security_notes"].append(f"possible example text in {current}; not treated as a finding")
                    continue
                result["security_flags"].append({"file": current, "label": label,
                                                  "line": added[:160]})
    finish_file()
    return result

def finalize_analysis(analysis: dict, diff_text: str) -> dict:
    changed = analysis["total_additions"] + analysis["total_deletions"]
    analysis["total_changed_lines"] = changed
    if analysis["malformed"]:
        analysis["input_state"] = "rejected"
        analysis["trivial_reason"] = "the diff is malformed or structurally ambiguous"
    elif not diff_text.strip():
        analysis["input_state"] = "insufficient"
        analysis["trivial_reason"] = "the diff is empty"
    elif not analysis["files_changed"]:
        analysis["input_state"] = "insufficient"
        analysis["trivial_reason"] = "the diff contains no changed files"
    elif analysis["binary_files"] and not analysis["text_files"]:
        analysis["input_state"] = "limited"
        analysis["trivial_reason"] = "all changed files are binary or otherwise uninspectable"
    elif changed == 0:
        analysis["input_state"] = "insufficient"
        analysis["trivial_reason"] = "the diff contains no substantive text lines"
    elif changed <= 1 or (analysis["total_additions"] == 1 and analysis["total_deletions"] == 1):
        analysis["input_state"] = "insufficient"
        analysis["trivial_reason"] = "the diff contains only a trivial one-line change"
    else:
        analysis["reviewable"] = True
        analysis["input_state"] = "limited" if analysis["binary_files"] else "valid"
    return analysis


def _metadata_context(metadata: dict, analysis: dict) -> tuple[str, list[str]]:
    uncertainty = []
    actual = len(analysis["files_changed"])
    claimed = metadata.get("changedFiles")
    if not isinstance(claimed, int) or claimed < 0:
        uncertainty.append("PR metadata has no valid changed-file count")
    elif claimed != actual:
        uncertainty.append(f"metadata claims {claimed} files; the patch contains {actual}")
    for key in ("additions", "deletions"):
        value = metadata.get(key)
        actual_value = analysis["total_additions" if key == "additions" else "total_deletions"]
        if not isinstance(value, int) or value < 0:
            uncertainty.append(f"PR metadata has no valid {key} count")
        elif value != actual_value:
            uncertainty.append(f"metadata claims {value} {key}; the patch contains {actual_value}")
    return ("; ".join(uncertainty), uncertainty)


def confidence_level(analysis: dict, uncertainties: list[str]) -> str:
    """Apply semantic gates; High is possible only with complete evidence."""
    # Keep this gate on the evidence field itself, not only on the derived
    # input_state.  Callers/tests may pass an analysis assembled or mutated
    # independently of finalize_analysis; binary content is never inspected
    # and therefore can never support High confidence.
    if analysis.get("binary_files") or analysis.get("input_state") != "valid" or uncertainties:
        return "Low"
    if (analysis["security_flags"] or analysis["generated_files"] or
            not analysis["has_tests"] or not analysis["has_test_evidence"]):
        return "Low" if analysis["security_flags"] or analysis["generated_files"] else "Medium"
    if (analysis["total_additions"] + analysis["total_deletions"] >= 20 and
            len(analysis["files_changed"]) >= 2):
        return "High"
    return "Medium"


def generate_report(metadata: dict, diff_analysis: dict, evidence: dict | None = None) -> str:
    title = metadata.get("title") if isinstance(metadata.get("title"), str) else "Unknown PR"
    additions = diff_analysis["total_additions"]
    deletions = diff_analysis["total_deletions"]
    changed = len(diff_analysis["files_changed"])
    metadata_uncertainty, uncertainties = _metadata_context(metadata, diff_analysis)
    if not diff_analysis["reviewable"]:
        reason = diff_analysis["trivial_reason"] or "insufficient diff evidence"
        if diff_analysis.get("input_state") == "rejected":
            status = "Rejected review — unsafe or ambiguous input"
        elif diff_analysis.get("input_state") == "limited":
            status = "Limited review — content is uninspectable"
        else:
            status = "No review — insufficient input"
        lines = ["## PR Review Report", "", "### 📋 Summary", f"- **PR:** {title}",
                 f"- **Review status:** ⏸️ {status} ({reason}).",
                 "- **Overall assessment:** No review performed; the patch is not sufficient for a grounded review.",
                 "- **Confidence:** Not applicable (insufficient or unsafe input)", "",
                 "### ✅ Code Quality", "- No review performed.", "", "### 🔒 Security",
                 "- No security analysis performed.", "", "### 🧪 Tests", "- No review performed.", "",
                 "### 📖 Documentation", "- No review performed.", "", "### 💡 Suggestions",
                 "1. Provide a complete, substantive unified diff and valid PR metadata.", ""]
        if diff_analysis["binary_files"]:
            lines.insert(6, "- **Uninspectable files:** " + ", ".join(
                f"`{path}`" for path in diff_analysis["binary_files"]))
        if diff_analysis.get("input_state") == "rejected" and diff_analysis["parse_warnings"]:
            lines.insert(6, "- **Validation failure:** " + "; ".join(diff_analysis["parse_warnings"][:3]))
        return "\n".join(lines)

    issues = len(diff_analysis["security_flags"])
    limited = (diff_analysis.get("input_state") == "limited" or
               bool(diff_analysis.get("binary_files")) or bool(uncertainties))
    if limited:
        assessment = "⚠️ Limited review — manual inspection required"
    elif issues > 2:
        assessment = "🚫 Needs significant revision"
    elif issues or not diff_analysis["has_tests"]:
        assessment = "⚠️ Needs revision before merge"
    else:
        assessment = "✅ Looks good with minor suggestions"
    confidence = confidence_level(diff_analysis, uncertainties)
    lines = ["## PR Review Report", "", "### 📋 Summary", f"- **PR:** {title}",
             f"- **Diff evidence:** {changed} file(s), +{additions}/-{deletions} lines (from the patch).",
             f"- **Overall assessment:** {assessment}", f"- **Confidence:** {confidence}", ""]
    if limited:
        limitations = []
        if diff_analysis["binary_files"]:
            limitations.append("uninspectable binary files: " + ", ".join(
                f"`{path}`" for path in diff_analysis["binary_files"]))
        if metadata_uncertainty:
            limitations.append(metadata_uncertainty)
        lines.append("- **Review status:** Limited — " + "; ".join(limitations) + ".")
    if metadata_uncertainty:
        lines.append(f"- **Uncertainty:** {metadata_uncertainty}.")
    lines += ["", "### ✅ Code Quality"]
    lines.append(f"- Patch contains {changed} changed file(s) and {additions + deletions} substantive changed line(s).")
    if changed > 10 or additions > 300:
        lines.append("- ⚠️ Large change surface; review in focused chunks and verify generated/vendor files.")
    else:
        lines.append("- Scope is summarized from the exact patch, not the metadata count.")
    if diff_analysis["generated_files"]:
        lines.append("- ⚠️ Generated/vendor-heavy paths were present: " + ", ".join(f"`{p}`" for p in diff_analysis["generated_files"]))
    lines += ["", "### 🔒 Security"]
    if diff_analysis["security_flags"]:
        lines.extend(f"- ❌ **{f['label']}** in `{f['file']}`: `{f['line']}`" for f in diff_analysis["security_flags"])
    else:
        qualifier = "inspected textual additions" if diff_analysis["binary_files"] else "added non-documentation lines"
        lines.append(f"- ✅ No high-confidence risky patterns found in {qualifier}.")
    if diff_analysis["binary_files"]:
        lines.append("- ⚠️ Binary content was not inspected; no security conclusion is made for those files.")
    for note in diff_analysis["security_notes"]:
        lines.append(f"- ℹ️ {note} (not counted as a code finding).")
    lines += ["", "### 🧪 Tests", "- ✅ Test files are included in the patch." if diff_analysis["has_tests"] else "- ⚠️ No test files detected in the patch.",
              "", "### 📖 Documentation", "- ✅ Documentation paths are included in the patch." if diff_analysis["has_docs"] else "- ℹ️ No documentation paths are included; assess whether public behavior changed.",
              "", "### 💡 Suggestions"]
    suggestions = []
    if not diff_analysis["has_tests"]: suggestions.append("Add tests for changed behavior and failure paths.")
    if issues: suggestions.append("Resolve the security finding(s) above and verify with focused tests.")
    if diff_analysis["binary_files"]: suggestions.append("Inspect every binary file with an appropriate binary-aware tool before merge.")
    if changed > 10 or additions > 300: suggestions.append("Split or independently verify the largest change surfaces.")
    if not suggestions: suggestions.append("Confirm the patch behavior with project checks before merge.")
    lines.extend(f"{i}. {item}" for i, item in enumerate(suggestions, 1))
    if evidence:
        lines += ["", "### 🔎 Evidence binding"]
        for key in ("CANDIDATE_SHA", "WORKTREE", "CLEAN", "EVIDENCE_FOR_SHA", "AUDIT_FOR_SHA"):
            if key in evidence and evidence[key] is not None:
                lines.append(f"- **{key}:** `{evidence[key]}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a grounded PR review report")
    parser.add_argument("--metadata")
    parser.add_argument("--diff")
    parser.add_argument("--pr")
    parser.add_argument("--output", "-o")
    parser.add_argument("--candidate-sha")
    parser.add_argument("--worktree")
    parser.add_argument("--clean")
    parser.add_argument("--evidence-for-sha")
    parser.add_argument("--audit-for-sha")
    args = parser.parse_args()
    if bool(args.pr) == bool(args.metadata or args.diff):
        parser.error("provide --pr, or both --metadata and --diff")
    try:
        if args.pr:
            metadata, diff_text = fetch_pr(args.pr)
        else:
            if not args.metadata or not args.diff:
                parser.error("--metadata and --diff are required together")
            metadata, diff_text = load_metadata(args.metadata), load_diff(args.diff)
        analysis = finalize_analysis(analyze_diff(diff_text), diff_text)
        evidence = {"CANDIDATE_SHA": args.candidate_sha, "WORKTREE": args.worktree,
                    "CLEAN": args.clean, "EVIDENCE_FOR_SHA": args.evidence_for_sha,
                    "AUDIT_FOR_SHA": args.audit_for_sha}
        report = generate_report(metadata, analysis, evidence if any(evidence.values()) else None)
        if args.output:
            Path(args.output).write_text(report, encoding="utf-8")
            print(f"Written {args.output}")
        else:
            print(report)
        return 2 if analysis.get("input_state") == "rejected" else 0
    except InputError as exc:
        print(f"PR review unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
