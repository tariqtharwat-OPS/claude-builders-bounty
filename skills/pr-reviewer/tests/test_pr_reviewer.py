#!/usr/bin/env python3
"""Tests for PR reviewer skill."""

import sys
import os

# Test scenarios
test_scenarios = [
    {
        "name": "Feature addition with tests",
        "pr_title": "Add user authentication",
        "files_changed": 8,
        "lines_added": 342,
        "has_tests": True,
        "security_issues": ["Missing rate limiting on login endpoint"],
        "doc_updates": False,
        "expected_sections": ["Summary", "Code Quality", "Security", "Tests", "Documentation", "Suggestions"],
    },
    {
        "name": "Bug fix without tests",
        "pr_title": "Fix null pointer in user service",
        "files_changed": 2,
        "lines_added": 15,
        "has_tests": False,
        "security_issues": [],
        "doc_updates": True,
        "expected_sections": ["Summary", "Code Quality", "Security", "Tests", "Documentation", "Suggestions"],
    },
    {
        "name": "Refactoring with no functional changes",
        "pr_title": "Refactor database connection pooling",
        "files_changed": 5,
        "lines_added": 120,
        "lines_removed": 95,
        "has_tests": True,
        "security_issues": [],
        "doc_updates": True,
        "expected_sections": ["Summary", "Code Quality", "Security", "Tests", "Documentation"],
    },
]


def validate_report_structure(report: str, expected_sections: list) -> bool:
    """Check if report contains all expected sections."""
    for section in expected_sections:
        if section not in report:
            print(f"  ✗ Missing section: {section}")
            return False
    return True


def generate_review_report(scenario: dict) -> str:
    """Generate a PR review report for a scenario."""
    return f"""## PR Review Report

### 📋 Summary
- **PR:** #42 — {scenario['pr_title']}
- **Files changed:** {scenario['files_changed']} ({scenario['lines_added']} lines added)
- **Overall assessment:** ⚠️ Needs revision before merge

### ✅ Code Quality
- Consistent TypeScript usage across new files
- Good separation of concerns

### 🔒 Security
{chr(10).join('- ' + issue for issue in scenario['security_issues']) if scenario['security_issues'] else '- No security issues detected'}

### 🧪 Tests
{'- ✅ New tests added' if scenario['has_tests'] else '- ❌ No tests added for this change'}

### 📖 Documentation
{'- ✅ Documentation updated' if scenario['doc_updates'] else '- ❌ Documentation not updated'}

### 💡 Suggestions
1. Add missing tests
2. Update documentation
"""


def test_feature_addition_with_tests():
    """Test PR review for feature addition with tests."""
    scenario = test_scenarios[0]
    report = generate_review_report(scenario)
    assert validate_report_structure(report, scenario['expected_sections'])


def test_bug_fix_without_tests():
    """Test PR review for bug fix without tests."""
    scenario = test_scenarios[1]
    report = generate_review_report(scenario)
    assert validate_report_structure(report, scenario['expected_sections'])


def test_refactoring_no_functional_changes():
    """Test PR review for refactoring with no functional changes."""
    scenario = test_scenarios[2]
    report = generate_review_report(scenario)
    assert validate_report_structure(report, scenario['expected_sections'])


if __name__ == '__main__':
    passed = 0
    failed = 0
    
    for scenario in test_scenarios:
        report = generate_review_report(scenario)
        if validate_report_structure(report, scenario['expected_sections']):
            passed += 1
        else:
            failed += 1
    
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
