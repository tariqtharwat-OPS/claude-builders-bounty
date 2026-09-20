#!/usr/bin/env python3
"""Generate a conservative, diff-grounded pull-request review.

The patch is the source of truth for changed paths and line counts. PR metadata is
optional context and is never allowed to manufacture findings or certainty.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class InputError(ValueError):
    """An input cannot be reviewed safely."""


def load_metadata(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"metadata could not be read: {exc}") from exc
    if not isinstance(value, dict):
        raise InputError("metadata must be a JSON object")
    return value


def fetch_pr(url: str) -> tuple[dict, str]:
    parsed = urlparse(url)
    match = re.fullmatch(r"/([^/]+)/([^/]+)/pull/(\d+)/?", parsed.path)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or not match:
        raise InputError("expected https://github.com/owner/repo/pull/number")
    owner, repo, number = match.groups()
    target = f"{owner}/{repo}"
    try:
        metadata = json.loads(subprocess.check_output(
            ["gh", "pr", "view", number, "--repo", target,
             "--json", "title,body,files,additions,deletions,changedFiles"],
            text=True, stderr=subprocess.PIPE))
        diff = subprocess.check_output(["gh", "pr", "diff", number, "--repo", target],
                                       text=True, stderr=subprocess.PIPE)
        return metadata, diff
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        api = f"https://api.github.com/repos/{target}/pulls/{number}"
        try:
            def get_json(endpoint):
                request = Request(endpoint, headers={"Accept": "application/vnd.github+json"})
                with urlopen(request, timeout=20) as response:
                    return json.load(response)
            raw = get_json(api)
            files = get_json(api + "/files?per_page=100")
            metadata = {"title": raw.get("title", ""), "body": raw.get("body", ""),
                        "files": files, "additions": raw.get("additions"),
                        "deletions": raw.get("deletions"),
                        "changedFiles": raw.get("changed_files")}
            request = Request(raw["diff_url"], headers={"Accept": "application/vnd.github.v3.diff"})
            with urlopen(request, timeout=20) as response:
                return metadata, response.read().decode("utf-8")
        except (HTTPError, URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise InputError(f"unable to fetch PR: {exc}") from exc


def load_diff(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
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


def analyze_diff(diff_text: str) -> dict:
    """Parse a unified patch and inspect only added, attributable lines."""
    result = {"files_changed": [], "file_status": {}, "total_additions": 0,
              "total_deletions": 0, "security_flags": [], "security_notes": [],
              "has_tests": False, "has_docs": False, "generated_files": [],
              "malformed": False, "parse_warnings": [], "reviewable": False,
              "trivial_reason": "", "total_changed_lines": 0}
    current = None
    in_hunk = False
    saw_header = False
    secret_patterns = [
        (r"(?i)\b(password|passwd|secret|api[_-]?key|private[_-]?key)\s*[:=]\s*['\"][^'\"]+['\"]", "Hardcoded credential"),
        (r"(?i)\b(token|access_token)\s*[:=]\s*['\"][A-Za-z0-9_./+=-]{12,}['\"]", "Hardcoded access token"),
        (r"(?i)\beval\s*\(", "Dynamic code execution"),
        (r"(?i)\bsubprocess\.(call|run|Popen)\s*\(.*\bshell\s*=\s*True", "Shell injection risk"),
        (r"(?i)\bos\.system\s*\(", "Command injection risk"),
    ]
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            match = re.match(r"diff --git a/(.+) b/(.+)$", raw)
            current = match.group(2) if match else None
            in_hunk = False
            saw_header = bool(match)
            if not match:
                result["malformed"] = True
                result["parse_warnings"].append("an unreadable diff header was found")
            elif current not in result["files_changed"]:
                result["files_changed"].append(current)
                result["file_status"][current] = "modified"
            continue
        if raw.startswith("--- ") and current and raw[4:] == "/dev/null":
            result["file_status"][current] = "added"
        elif raw.startswith("+++ ") and current and raw[4:] == "/dev/null":
            result["file_status"][current] = "deleted"
        if raw.startswith("@@"):
            in_hunk = bool(re.match(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", raw))
            if not in_hunk:
                result["malformed"] = True
                result["parse_warnings"].append(f"malformed hunk in {current or 'unknown file'}")
            continue
        if raw.startswith(("Binary files ", "GIT binary patch")):
            if current:
                result["parse_warnings"].append(f"binary content in {current} was not line-inspected")
            continue
        if not in_hunk or raw.startswith(("---", "+++")):
            continue
        if not raw or raw[0] not in " +-\\":
            result["malformed"] = True
            result["parse_warnings"].append(f"unprefixed content in {current or 'unknown file'}")
            continue
        if raw.startswith("\\ No newline"):
            continue
        if raw.startswith("-"):
            if raw[1:].strip():
                result["total_deletions"] += 1
            continue
        if not raw.startswith("+"):
            continue
        result["total_additions"] += 1
        if not current:
            result["malformed"] = True
            continue
        if _is_test(current):
            result["has_tests"] = True
        if _is_docs(current):
            result["has_docs"] = True
        if _is_generated_or_vendor(current) and current not in result["generated_files"]:
            result["generated_files"].append(current)
        added = raw[1:].strip()
        if _is_docs(current):
            if any(re.search(pattern, added) for pattern, _ in secret_patterns):
                result["security_notes"].append(f"example-like security text in documentation: {current}")
            continue
        for pattern, label in secret_patterns:
            if re.search(pattern, added):
                # A rendered report/example in source is not itself a credential.
                if "hardcoded credential" in added.lower() and "password =" in added.lower():
                    result["security_notes"].append(f"possible example text in {current}; not treated as a finding")
                    continue
                result["security_flags"].append({"file": current, "label": label,
                                                  "line": added[:160]})
    result["has_tests"] = result["has_tests"]
    return result


def finalize_analysis(analysis: dict, diff_text: str) -> dict:
    changed = analysis["total_additions"] + analysis["total_deletions"]
    analysis["total_changed_lines"] = changed
    if not diff_text.strip():
        analysis["trivial_reason"] = "the diff is empty"
    elif not analysis["files_changed"]:
        analysis["trivial_reason"] = "the diff contains no changed files"
    elif analysis["malformed"] or changed == 0:
        analysis["trivial_reason"] = "the diff is malformed or contains no substantive lines"
    elif changed <= 1 or (analysis["total_additions"] == 1 and analysis["total_deletions"] == 1):
        analysis["trivial_reason"] = "the diff contains only a trivial one-line change"
    else:
        analysis["reviewable"] = True
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


def generate_report(metadata: dict, diff_analysis: dict, evidence: dict | None = None) -> str:
    title = metadata.get("title") if isinstance(metadata.get("title"), str) else "Unknown PR"
    additions = diff_analysis["total_additions"]
    deletions = diff_analysis["total_deletions"]
    changed = len(diff_analysis["files_changed"])
    metadata_uncertainty, uncertainties = _metadata_context(metadata, diff_analysis)
    if not diff_analysis["reviewable"]:
        reason = diff_analysis["trivial_reason"] or "insufficient diff evidence"
        status = "No review — insufficient input" if "malformed" not in reason else "No review — unsafe input"
        lines = ["## PR Review Report", "", "### 📋 Summary", f"- **PR:** {title}",
                 f"- **Review status:** ⏸️ {status} ({reason}).",
                 "- **Overall assessment:** No review performed; the patch is not sufficient for a grounded review.",
                 "- **Confidence:** Not applicable (insufficient or unsafe input)", "",
                 "### ✅ Code Quality", "- No review performed.", "", "### 🔒 Security",
                 "- No security analysis performed.", "", "### 🧪 Tests", "- No review performed.", "",
                 "### 📖 Documentation", "- No review performed.", "", "### 💡 Suggestions",
                 "1. Provide a complete, substantive unified diff and valid PR metadata.", ""]
        return "\n".join(lines)

    issues = len(diff_analysis["security_flags"])
    if issues > 2:
        assessment = "🚫 Needs significant revision"
    elif issues or not diff_analysis["has_tests"]:
        assessment = "⚠️ Needs revision before merge"
    else:
        assessment = "✅ Looks good with minor suggestions"
    confidence = "Low" if issues or diff_analysis["generated_files"] else (
        "High" if not uncertainties and additions + deletions >= 20 and changed >= 2 and diff_analysis["has_tests"] else "Medium")
    lines = ["## PR Review Report", "", "### 📋 Summary", f"- **PR:** {title}",
             f"- **Diff evidence:** {changed} file(s), +{additions}/-{deletions} lines (from the patch).",
             f"- **Overall assessment:** {assessment}", f"- **Confidence:** {confidence}", ""]
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
        lines.append("- ✅ No high-confidence risky patterns found in added non-documentation lines.")
    for note in diff_analysis["security_notes"]:
        lines.append(f"- ℹ️ {note} (not counted as a code finding).")
    lines += ["", "### 🧪 Tests", "- ✅ Test files are included in the patch." if diff_analysis["has_tests"] else "- ⚠️ No test files detected in the patch.",
              "", "### 📖 Documentation", "- ✅ Documentation paths are included in the patch." if diff_analysis["has_docs"] else "- ℹ️ No documentation paths are included; assess whether public behavior changed.",
              "", "### 💡 Suggestions"]
    suggestions = []
    if not diff_analysis["has_tests"]: suggestions.append("Add tests for changed behavior and failure paths.")
    if issues: suggestions.append("Resolve the security finding(s) above and verify with focused tests.")
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
        return 0
    except InputError as exc:
        print(f"PR review unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
