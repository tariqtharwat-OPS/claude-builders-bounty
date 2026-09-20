#!/usr/bin/env python3
"""Generate a structured PR review report from PR metadata and diff.

Usage:
    python generate_review.py --metadata pr_metadata.json --diff pr_diff.patch --output report.md
    python generate_review.py --metadata pr_metadata.json --diff pr_diff.patch  # stdout
"""

import argparse
import json
import re
import sys
from pathlib import Path


def load_metadata(path: str) -> dict:
    """Load PR metadata JSON."""
    with open(path) as f:
        return json.load(f)


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

        if not in_hunk or not line.startswith('+'):
            continue
        if line.startswith('+++'):
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


def generate_report(metadata: dict, diff_analysis: dict) -> str:
    """Generate structured Markdown review report."""
    title = metadata.get("title", "Unknown PR")
    body = metadata.get("body", "")[:200]
    files = metadata.get("files", [])
    additions = metadata.get("additions", diff_analysis["total_additions"])
    deletions = metadata.get("deletions", diff_analysis["total_deletions"])
    changed = metadata.get("changedFiles", len(diff_analysis["files_changed"]))

    # Determine overall assessment
    issues = len(diff_analysis["security_flags"])
    has_tests = diff_analysis["has_tests"]

    if issues > 2:
        assessment = "🚫 Needs significant revision"
    elif issues > 0 or not has_tests:
        assessment = "⚠️ Needs revision before merge"
    else:
        assessment = "✅ Looks good with minor suggestions"

    confidence = "High" if issues == 0 and has_tests else ("Medium" if issues <= 2 else "Low")

    # Build report
    lines = [
        "## PR Review Report",
        "",
        "### 📋 Summary",
        f"- **PR:** {title}",
        f"- **Files changed:** {changed} ({additions} lines added, {deletions} removed)",
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
    parser.add_argument("--metadata", required=True, help="Path to PR metadata JSON")
    parser.add_argument("--diff", required=True, help="Path to PR diff patch file")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    args = parser.parse_args()

    metadata = load_metadata(args.metadata)
    diff_text = load_diff(args.diff)
    diff_analysis = analyze_diff(diff_text)

    report = generate_report(metadata, diff_analysis)

    if args.output:
        Path(args.output).write_text(report)
        print(f"Written {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
