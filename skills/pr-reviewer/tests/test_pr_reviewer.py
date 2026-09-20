"""Tests for the actual PR reviewer implementation."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "generate_review.py"
spec = importlib.util.spec_from_file_location("generate_review", SCRIPT)
reviewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviewer)


def metadata(**extra):
    value = {"title": "Example", "body": "", "files": [],
             "additions": 4, "deletions": 1, "changedFiles": 2}
    value.update(extra)
    return value


def diff(files=("src/a.py", "tests/test_a.py"), body=None):
    body = body or "".join(
        [f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -0,0 +1,2 @@\n+one\n+two\n" for name in files]
    )
    return body


def report(meta, patch):
    analysis = reviewer.finalize_analysis(reviewer.analyze_diff(patch), patch)
    return analysis, reviewer.generate_report(meta, analysis)


def test_report_uses_real_analyzer_and_has_required_sections():
    analysis, output = report(metadata(), diff())
    assert analysis["reviewable"] is True
    assert analysis["total_additions"] == 4
    assert "Confidence" in output
    for section in ("Summary", "Code Quality", "Security", "Tests", "Documentation", "Suggestions"):
        assert section in output


def test_clean_small_pr_does_not_get_easy_high_confidence():
    patch = diff(files=("tests/test_a.py",), body="diff --git a/tests/test_a.py b/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -0,0 +1,2 @@\n+one\n+two\n")
    analysis, output = report(metadata(changedFiles=1), patch)
    assert analysis["reviewable"] is True
    assert "**Confidence:** Medium" in output
    assert "**Confidence:** High" not in output


def test_secret_pattern_is_reported_by_real_analyzer():
    patch = diff(body="diff --git a/app.py b/app.py\n+++ b/app.py\n@@ -0,0 +1,2 @@\n+password = \"not-a-real-secret\"\n+return True\n")
    analysis, output = report(metadata(), patch)
    assert analysis["security_flags"]
    assert "Hardcoded credential" in output
    assert "**Confidence:** High" not in output


def test_empty_and_trivial_diffs_are_explicit_no_review():
    for patch in ("", "diff --git a/README.md b/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n"):
        analysis, output = report(metadata(), patch)
        assert analysis["reviewable"] is False
        assert "No review" in output
        assert "insufficient input" in output
        assert "No review performed" in output
