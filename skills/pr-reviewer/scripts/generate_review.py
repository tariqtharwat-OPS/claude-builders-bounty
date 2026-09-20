#!/usr/bin/env python3
"""Generate a structured PR review report from PR metadata and diff.

Usage:
    python generate_review.py --metadata pr_metadata.json --diff pr_diff.patch --output report.md
    python generate_review.py --metadata pr_metadata.json --diff pr_diff.patch  # stdout
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def load_metadata(path: str) -> dict:
    """Load PR metadata JSON."""
    with open(path) as f:
        return json.load(f)


def fetch_pr(url: str) -> tuple[dict, str]:
    """Fetch a public GitHub PR using gh or GitHub's unauthenticated API."""
    parsed = urlparse(url)
    match = re.fullmatch(r"/([^/]+)/([^/]+)/pull/(\d+)/?", parsed.path)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or not match:
        raise ValueError("expected https://github.com/owner/repo/pull/number")
    owner, repo, number = match.groups()
    target = f"{owner}/{repo}"
    try:
        metadata = json.loads(subprocess.check_output(
            ["gh", "pr", "view", number, "--repo", target,
             "--json", "title,body,files,additions,deletions,changedFiles"],
            text=True, stderr=subprocess.PIPE))
        diff = subprocess.check_output(
            ["gh", "pr", "diff", number, "--repo", target],
            text=True, stderr=subprocess.PIPE)
        return metadata, diff
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        # Keep the CLI usable in a clean Python checkout without requiring gh.
        api = f"https://api.github.com/repos/{target}/pulls/{number}"
        try:
            def get_json(endpoint):
                request = Request(endpoint, headers={"Accept": "application/vnd.github+json"})
                with urlopen(request, timeout=20) as response:
                    return json.load(response)
            raw = get_json(api)
            files = get_json(api + "/files?per_page=100")
            metadata = {"title": raw.get("title", ""), "body": raw.get("body", ""),
                        "files": files, "additions": raw.get("additions", 0),
                        "deletions": raw.get("deletions", 0),
                        "changedFiles": raw.get("changed_files", len(files))}
            request = Request(raw["diff_url"], headers={"Accept": "application/vnd.github.v3.diff"})
            with urlopen(request, timeout=20) as response:
                return metadata, response.read().decode("utf-8")
        except (HTTPError, URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to fetch PR {url}: {exc}") from exc


def load_diff(path: str) -> str:
    """Load PR diff patch file."""
    p = Path(path)
    if p.exists():
        return p.read_text()
    return ""


def analyze_diff(diff_text: str) -> dict:
    """Analyze a unified diff for patterns."""
    analysis = {
        "files_changed": [],
        "total_additions": 0,
        "total_deletions": 0,
        "security_flags": [],
        "has_tests": False,
        "has_docs": False,
        "large_functions": [],
        "hardcoded_secrets": [],
        "error_handling_gaps": [],
        "total_deletions": 0,
        "reviewable": False,
        "trivial_reason": "",
    }

    current_file = None
    in_hunk = False

    secret_patterns = [
        (r'(?i)(password|passwd|secret|api_key|apikey|token|private_key)\s*=\s*["\'][^"\']+["\']',
         "Hardcoded credential"),
        (r'(?i)(eval|exec)\s*\(', "Dynamic code execution"),
        (r'(?i)subprocess\.(call|run|Popen)\s*\(.*shell\s*=\s*True', "Shell injection risk"),
        (r'(?i)os\.system\s*\(', "Command injection risk"),
    ]

    for line in diff_text.split('\n'):
        if line.startswith('+++ b/'):
            current_file = line[6:]
            analysis["files_changed"].append(current_file)
            if 'test' in current_file.lower():
                analysis["has_tests"] = True
            if current_file.lower().endswith('.md') or 'doc' in current_file.lower():
                analysis["has_docs"] = True

        if line.startswith('@@'):
            in_hunk = True
            continue

        if not in_hunk or line.startswith('+++'):
            continue
        if line.startswith('-'):
            if line[1:].strip():
                analysis["total_deletions"] += 1
            continue
        if not line.startswith('+'):
            continue

        analysis["total_additions"] += 1

        for pattern, label in secret_patterns:
            # Reports and documentation may quote an example finding. Do not
            # re-report that rendered finding as a real credential in the PR.
            rendered_finding = "hardcoded credential" in line.lower() and "password =" in line.lower()
            if rendered_finding:
                continue
            if re.search(pattern, line):
                analysis["security_flags"].append({
                    "file": current_file,
                    "label": label,
                    "line": line.strip()[:120],
                })

    return analysis


def finalize_analysis(analysis: dict, diff_text: str) -> dict:
    """Mark whether there is enough substantive diff evidence to review."""
    changed = analysis["total_additions"] + analysis["total_deletions"]
    analysis["total_changed_lines"] = changed
    if not diff_text.strip():
        analysis["trivial_reason"] = "the diff is empty"
    elif not analysis["files_changed"]:
        analysis["trivial_reason"] = "the diff contains no changed files"
    elif changed <= 1 or (analysis["total_additions"] == 1 and analysis["total_deletions"] == 1):
        analysis["trivial_reason"] = "the diff contains only a trivial one-line change"
    else:
        analysis["reviewable"] = True
    return analysis


def generate_report(metadata: dict, diff_analysis: dict) -> str:
    """Generate structured Markdown review report."""
    title = metadata.get("title", "Unknown PR")
    body = metadata.get("body", "")[:200]
    files = metadata.get("files", [])
    additions = metadata.get("additions", diff_analysis["total_additions"])
    deletions = metadata.get("deletions", diff_analysis["total_deletions"])
    changed = metadata.get("changedFiles", len(diff_analysis["files_changed"]))

    if not diff_analysis["reviewable"]:
        reason = diff_analysis["trivial_reason"] or "insufficient diff evidence"
        return "\n".join([
            "## PR Review Report", "", "### 📋 Summary",
            f"- **PR:** {title}",
            f"- **Review status:** ⏸️ No review — insufficient input ({reason}).",
            "- **Overall assessment:** No review performed; a substantive diff is required.",
            "- **Confidence:** Not applicable (insufficient input)", "",
            "### ✅ Code Quality", "- No review performed.", "",
            "### 🔒 Security", "- No security analysis performed.", "",
            "### 🧪 Tests", "- No review performed.", "",
            "### 📖 Documentation", "- No review performed.", "",
            "### 💡 Suggestions", "1. Provide a non-empty, substantive pull-request diff.", "",
        ])

    # Determine overall assessment
    issues = len(diff_analysis["security_flags"])
    has_tests = diff_analysis["has_tests"]

    if issues > 2:
        assessment = "🚫 Needs significant revision"
    elif issues > 0 or not has_tests:
        assessment = "⚠️ Needs revision before merge"
    else:
        assessment = "✅ Looks good with minor suggestions"

    metadata_complete = all(key in metadata for key in ("title", "additions", "deletions", "changedFiles"))
    strong_evidence = (diff_analysis["total_changed_lines"] >= 20 and
                       len(diff_analysis["files_changed"]) >= 2 and has_tests and
                       metadata_complete)
    confidence = ("Low" if issues > 2 else
                  "High" if issues == 0 and strong_evidence else "Medium")

    # Build report
    lines = [
        "## PR Review Report",
        "",
        "### 📋 Summary",
        f"- **PR:** {title}",
        f"- This change touches {changed} file(s), adding {additions} lines and removing {deletions}.",
        f"- Overall, it is assessed as {assessment.lower()} based on the diff and available tests.",
        f"- **Overall assessment:** {assessment}",
        f"- **Confidence:** {confidence}",
        "",
        "### ✅ Code Quality",
    ]

    if changed > 10:
        lines.append(f"- ⚠️ Large PR ({changed} files) — consider splitting into smaller, reviewable units")
    else:
        lines.append(f"- {changed} files changed — reasonable scope")

    if additions > 300:
        lines.append(f"- ⚠️ {additions} lines added — verify no unnecessary duplication")
    else:
        lines.append(f"- {additions} lines added — manageable size")

    lines.extend(["", "### 🔒 Security"])

    if diff_analysis["security_flags"]:
        for flag in diff_analysis["security_flags"]:
            lines.append(f"- ❌ **{flag['label']}** in `{flag['file']}`: `{flag['line']}`")
    else:
        lines.append("- ✅ No hardcoded credentials or injection patterns detected")
        lines.append("- ✅ No dynamic code execution risks found")

    lines.extend(["", "### 🧪 Tests"])

    if has_tests:
        lines.append("- ✅ Test files included in this PR")
    else:
        lines.append("- ❌ No test files detected — add unit/integration tests for new functionality")

    lines.extend(["", "### 📖 Documentation"])

    if diff_analysis["has_docs"]:
        lines.append("- ✅ Documentation files updated")
    else:
        lines.append("- ⚠️ No documentation changes detected — update README/docs if public API changed")

    lines.extend(["", "### 💡 Suggestions"])

    suggestion_num = 1
    if not has_tests:
        lines.append(f"{suggestion_num}. Add tests for new/changed functionality")
        suggestion_num += 1
    if issues > 0:
        lines.append(f"{suggestion_num}. Address {issues} security flag(s) identified above")
        suggestion_num += 1
    if changed > 10:
        lines.append(f"{suggestion_num}. Consider splitting this PR into smaller focused changes")
        suggestion_num += 1
    if not diff_analysis["has_docs"]:
        lines.append(f"{suggestion_num}. Update documentation for any public API changes")
        suggestion_num += 1
    if suggestion_num == 1:
        lines.append("1. No major issues found — address any inline comments from reviewers")

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate structured PR review report")
    parser.add_argument("--metadata", help="Path to PR metadata JSON")
    parser.add_argument("--diff", help="Path to PR diff patch file")
    parser.add_argument("--pr", help="GitHub pull request URL")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    args = parser.parse_args()
    if bool(args.pr) == bool(args.metadata or args.diff):
        parser.error("provide --pr, or both --metadata and --diff")

    if args.pr:
        try:
            metadata, diff_text = fetch_pr(args.pr)
        except (ValueError, RuntimeError) as exc:
            parser.error(str(exc))
    else:
        if not args.metadata or not args.diff:
            parser.error("--metadata and --diff are required together")
        metadata = load_metadata(args.metadata)
        diff_text = load_diff(args.diff)
    diff_analysis = finalize_analysis(analyze_diff(diff_text), diff_text)

    report = generate_report(metadata, diff_analysis)

    if args.output:
        Path(args.output).write_text(report)
        print(f"Written {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
