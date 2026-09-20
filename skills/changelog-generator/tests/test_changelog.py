#!/usr/bin/env python3
"""Tests for changelog generator."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from generate_changelog import parse_commit, generate_changelog


def test_parse_conventional_commit():
    """Test parsing standard conventional commit format."""
    result = parse_commit("abc123 feat: add user authentication")
    assert result['type'] == 'feat'
    assert result['description'] == 'add user authentication'
    assert result['hash'] == 'abc123'
    print("✓ parse_conventional_commit passed")


def test_parse_scoped_commit():
    """Test parsing commit with scope."""
    result = parse_commit("def456 fix(auth): resolve login timeout")
    assert result['type'] == 'fix'
    assert result['scope'] == 'auth'
    assert result['description'] == 'resolve login timeout'
    print("✓ parse_scoped_commit passed")


def test_parse_non_conventional():
    """Test fallback for non-conventional commits."""
    result = parse_commit("ghi789 updated README file")
    assert result['type'] is None
    assert result['description'] == 'updated README file'
    print("✓ parse_non_conventional passed")


def test_generate_changelog_groups():
    """Test that commits are grouped by type."""
    commits = [
        parse_commit("a1 feat: add login"),
        parse_commit("b2 fix: resolve crash"),
        parse_commit("c3 docs: update readme"),
    ]
    output = generate_changelog(commits)
    assert '### Features' in output
    assert '### Bug Fixes' in output
    assert '### Documentation' in output
    assert 'add login' in output
    assert 'resolve crash' in output
    print("✓ generate_changelog_groups passed")


def test_generate_changelog_format():
    """Test output format matches Keep a Changelog style."""
    commits = [parse_commit("x1 feat: test feature")]
    output = generate_changelog(commits, version='v1.0.0', date='2026-09-19')
    assert '# Changelog' in output
    assert '## [v1.0.0] - 2026-09-19' in output
    assert '- test feature (x1)' in output
    print("✓ generate_changelog_format passed")


if __name__ == '__main__':
    test_parse_conventional_commit()
    test_parse_scoped_commit()
    test_parse_non_conventional()
    test_generate_changelog_groups()
    test_generate_changelog_format()
    print("\nAll tests passed ✓")
