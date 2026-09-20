"""Acceptance tests for conservative, diff-grounded PR reviews."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "scripts" / "generate_review.py"
spec = importlib.util.spec_from_file_location("generate_review", SCRIPT)
reviewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviewer)


def metadata(**extra):
    value = {"title": "Example", "body": "", "files": [],
             "additions": 4, "deletions": 1, "changedFiles": 2}
    value.update(extra)
    return value


def patch_for(files=("src/a.py", "tests/test_a.py"), added=("one", "two"), deleted=()):
    chunks = []
    for name in files:
        old = len(deleted)
        new = len(added)
        if old and new:
            hunk = f"@@ -1,{old} +1,{new} @@"
        elif old:
            hunk = f"@@ -1,{old} +0,0 @@"
        else:
            hunk = f"@@ -0,0 +1,{new} @@"
        lines = [f"diff --git a/{name} b/{name}",
                 "--- /dev/null" if not old else f"--- a/{name}",
                 "+++ /dev/null" if not new else f"+++ b/{name}", hunk]
        lines += [f"-{line}" for line in deleted] + [f"+{line}" for line in added]
        chunks.append("\n".join(lines) + "\n")
    return "".join(chunks)


def report(meta, patch):
    analysis = reviewer.finalize_analysis(reviewer.analyze_diff(patch), patch)
    return analysis, reviewer.generate_report(meta, analysis)


def test_report_is_grounded_in_patch_and_has_required_sections():
    analysis, output = report(metadata(), patch_for())
    assert analysis["reviewable"] is True
    assert analysis["total_additions"] == 4
    assert analysis["files_changed"] == ["src/a.py", "tests/test_a.py"]
    assert "Diff evidence" in output
    for section in ("Summary", "Code Quality", "Security", "Tests", "Documentation", "Suggestions", "Confidence"):
        assert section in output


def test_small_clean_change_never_gets_easy_high_confidence():
    analysis, output = report(metadata(additions=2, deletions=0, changedFiles=1), patch_for(("tests/test_a.py",)))
    assert analysis["reviewable"] is True
    assert "**Confidence:** Medium" in output
    assert "**Confidence:** High" not in output


def test_confidence_is_semantic_not_a_schema_decoration():
    # A mutation that unconditionally returns High must fail these gates.
    cases = [
        (patch_for(("tests/test_a.py",), added=("one", "two")), metadata(additions=2, deletions=0, changedFiles=1)),
        (patch_for(("src/a.py", "tests/test_a.py"),
                   added=tuple(f"assert line{i}" for i in range(12))),
         metadata(additions=24, deletions=0, changedFiles=2)),
        (patch_for(("generated/app.js", "tests/test_a.py"), added=tuple(f"line{i}" for i in range(12))),
         metadata(additions=24, deletions=0, changedFiles=2)),
    ]
    for index, (patch, meta) in enumerate(cases):
        analysis, output = report(meta, patch)
        level = reviewer.confidence_level(analysis, reviewer._metadata_context(meta, analysis)[1])
        if index == 1:
            assert level == "High"
            assert "**Confidence:** High" in output
        else:
            assert level != "High"
            assert "**Confidence:** High" not in output


def test_metadata_is_not_authoritative_when_partial_or_mismatched():
    _, output = report({"title": "Partial"}, patch_for())
    assert "Uncertainty" in output
    assert "Confidence:** High" not in output
    _, output = report(metadata(additions=999, changedFiles=99), patch_for())
    assert "metadata claims 999 additions" in output


def test_security_finding_is_specific_and_docs_example_is_not_code_finding():
    code = patch_for(("app.py",), ('password = "not-a-real-secret"', "return True"))
    analysis, output = report(metadata(additions=2, deletions=0, changedFiles=1), code)
    assert analysis["security_flags"][0]["label"] == "Hardcoded credential"
    assert "Hardcoded credential" in output
    docs = patch_for(("docs/security.md",), ('password = "example-only"', "Never commit credentials."))
    analysis, output = report(metadata(additions=2, deletions=0, changedFiles=1), docs)
    assert not analysis["security_flags"]
    assert "not counted as a code finding" in output


def test_deletion_heavy_patch_is_reviewable_and_reports_actual_counts():
    analysis, output = report(metadata(additions=0, deletions=4, changedFiles=1),
                              patch_for(("old.py",), added=(), deleted=("a", "b", "c", "d")))
    assert analysis["reviewable"] is True
    assert "Diff evidence" in output and "+0/-4" in output


def test_empty_and_trivial_diffs_are_explicit_no_review():
    for patch in ("", patch_for(("README.md",), added=("new",), deleted=("old",))):
        analysis, output = report(metadata(), patch)
        assert analysis["reviewable"] is False
        assert "No review" in output
        assert "insufficient input" in output
        assert "No review performed" in output


def test_malformed_diff_is_safe_failure_not_a_polished_review():
    analysis, output = report(metadata(), "diff --git a/app.py b/app.py\n@@ broken\n+password = 'x'\n")
    assert analysis["reviewable"] is False
    assert "unsafe input" in output
    assert "No security analysis performed" in output


def test_hunk_counts_and_file_headers_are_strictly_validated():
    valid = ("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
             "@@ -1,1 +1,2 @@\n-old\n+new\n+another\n")
    assert reviewer.finalize_analysis(reviewer.analyze_diff(valid), valid)["reviewable"]

    truncated = valid.replace("+another\n", "")
    analysis, output = report(metadata(additions=1, deletions=1, changedFiles=1), truncated)
    assert analysis["malformed"] is True
    assert analysis["reviewable"] is False
    assert "unsafe input" in output

    missing_headers = ("diff --git a/src/a.py b/src/a.py\n@@ -0,0 +1,1 @@\n+new\n")
    analysis, _ = report(metadata(additions=1, deletions=0, changedFiles=1), missing_headers)
    assert analysis["malformed"] is True
    assert analysis["reviewable"] is False


def test_action_does_not_interpolate_or_allow_output_path_escape():
    action = (Path(__file__).parents[1] / "action.yml").read_text()
    assert '--output "$OUTPUT_FILE"' in action
    assert 'cat -- "$OUTPUT_FILE"' in action
    assert '--output ${{ inputs.output_file }}' not in action
    assert 'cat ${{ inputs.output_file }}' not in action
    assert 'output_file must be a non-empty path inside the workspace' in action


def test_binary_marker_cannot_be_followed_by_textual_hunks():
    patch = ("diff --git a/app.py b/app.py\n"
             "Binary files a/app.py and b/app.py differ\n"
             "@@ -1,1 +1,1 @@\n-old\n+new\n")
    analysis, output = report(metadata(), patch)
    assert analysis["malformed"] is True
    assert analysis["reviewable"] is False
    assert "unsafe input" in output


def test_duplicate_headers_and_traversal_paths_are_not_reviewable():
    duplicate = ("diff --git a/app.py b/app.py\n--- a/app.py\n--- a/app.py\n"
                 "+++ b/app.py\n@@ -1,1 +1,2 @@\n-old\n+new\n+more\n")
    traversal = ("diff --git a/../x.py b/../x.py\n--- a/../x.py\n+++ b/../x.py\n"
                 "@@ -0,0 +1,2 @@\n+assert one\n+assert two\n")
    for patch in (duplicate, traversal):
        analysis, output = report(metadata(), patch)
        assert analysis["malformed"] is True
        assert analysis["reviewable"] is False
        assert "unsafe input" in output


def test_high_confidence_requires_meaningful_test_coverage_evidence():
    patch = patch_for(("src/app.py", "tests/test_app.py"),
                      added=("implemented change", "assert result == expected"))
    analysis, _ = report(metadata(additions=4, deletions=0, changedFiles=2), patch)
    assert analysis["has_tests"] is True
    assert analysis["has_test_evidence"] is True
    assert reviewer.confidence_level(analysis, []) == "Medium"  # too small for High

    large = patch_for(("src/app.py", "tests/test_app.py"),
                      added=tuple("assert result == expected" for _ in range(12)))
    analysis, _ = report(metadata(additions=24, deletions=0, changedFiles=2), large)
    assert reviewer.confidence_level(analysis, []) == "High"

    filename_only = patch_for(("src/app.py", "tests/test_app.py"),
                              added=tuple(f"line{i}" for i in range(12)))
    analysis, _ = report(metadata(additions=24, deletions=0, changedFiles=2), filename_only)
    assert analysis["has_tests"] is True
    assert analysis["has_test_evidence"] is False
    assert reviewer.confidence_level(analysis, []) != "High"


def test_report_has_one_documentation_section():
    analysis, output = report(metadata(), patch_for())
    assert output.count("### 📖 Documentation") == 1


def test_binary_generated_and_large_changes_are_explicitly_uncertain():
    patch = ("diff --git a/generated/app.min.js b/generated/app.min.js\n"
             "Binary files a/generated/app.min.js and b/generated/app.min.js differ\n")
    analysis, output = report(metadata(changedFiles=1), patch)
    assert analysis["reviewable"] is False
    large = patch_for(tuple(f"src/{i}.py" for i in range(12)), added=tuple(f"line{i}" for i in range(30)))
    analysis, output = report(metadata(additions=360, deletions=0, changedFiles=12), large)
    assert analysis["reviewable"] is True
    assert "Large change surface" in output


def test_api_non_string_diff_url_fails_cleanly_without_traceback():
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout=20):
        if request.full_url.endswith("/files?per_page=100"):
            return Response()
        return Response()

    with patch.object(reviewer.subprocess, "check_output",
                      side_effect=subprocess.CalledProcessError(1, "gh")), \
         patch.object(reviewer, "urlopen", side_effect=[
             type("JSONResponse", (), {
                 "__enter__": lambda self: self,
                 "__exit__": lambda self, *args: False,
                 "read": lambda self: b'{"title":"x","body":"","diff_url":null}'})(),
             type("JSONResponse", (), {
                 "__enter__": lambda self: self,
                 "__exit__": lambda self, *args: False,
                 "read": lambda self: b'[]'})(),
         ]):
        try:
            reviewer.fetch_pr("https://github.com/o/r/pull/1")
        except reviewer.InputError as exc:
            assert "invalid diff_url" in str(exc)
        else:
            raise AssertionError("invalid diff_url must fail")


def test_cli_reports_inaccessible_or_malformed_inputs_without_traceback(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--metadata", str(tmp_path / "missing"),
                             "--diff", str(tmp_path / "missing.patch")], capture_output=True, text=True)
    assert result.returncode == 2
    assert "PR review unavailable" in result.stderr
    assert "Traceback" not in result.stderr
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    result = subprocess.run([sys.executable, str(SCRIPT), "--metadata", str(bad),
                             "--diff", str(tmp_path / "missing.patch")], capture_output=True, text=True)
    assert result.returncode == 2
    assert "metadata must be a JSON object" in result.stderr


def test_evidence_binding_is_emitted_verbatim():
    analysis = reviewer.finalize_analysis(reviewer.analyze_diff(patch_for()), patch_for())
    output = reviewer.generate_report(metadata(), analysis, {
        "CANDIDATE_SHA": "abc123", "WORKTREE": "/candidate", "CLEAN": "true",
        "EVIDENCE_FOR_SHA": "abc123", "AUDIT_FOR_SHA": "abc123"})
    for key in ("CANDIDATE_SHA", "WORKTREE", "CLEAN", "EVIDENCE_FOR_SHA", "AUDIT_FOR_SHA"):
        assert key in output
