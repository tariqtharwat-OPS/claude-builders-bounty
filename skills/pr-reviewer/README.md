# PR Reviewer Agent

Automatically review pull requests and produce structured Markdown output with code quality assessment, security concerns, test coverage check, and suggested improvements.

## What it does

1. Fetches PR metadata and diff via GitHub API / `gh` CLI
2. Analyzes code changes for security patterns, test coverage, documentation updates
3. Generates a structured Markdown report with sections: Summary, Code Quality, Security, Tests, Documentation, Suggestions
4. Posts the report as a PR comment (when run as a GitHub Action)

## Installation

### As a GitHub Action

```yaml
name: PR Review
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: PR Review
        uses: your-org/claude-builders-bounty/skills/pr-reviewer@main
        with:
          pr_number: ${{ github.event.pull_request.number }}
```

### As a CLI tool

```bash
# Fetch PR metadata and diff
gh pr view 42 --repo owner/repo --json title,body,files,additions,deletions,changedFiles > pr_metadata.json
gh pr diff 42 --repo owner/repo > pr_diff.patch

# Generate review report
python scripts/generate_review.py --metadata pr_metadata.json --diff pr_diff.patch -o report.md
```

## Example Output

```markdown
## PR Review Report

### 📋 Summary
- **PR:** Add user authentication
- **Files changed:** 8 (342 lines added, 45 removed)
- **Overall assessment:** ⚠️ Needs revision before merge

### ✅ Code Quality
- 8 files changed — reasonable scope
- 342 lines added — manageable size

### 🔒 Security
- ❌ **Hardcoded credential** in `src/auth.py`: `password = "secret123"`

### 🧪 Tests
- ✅ Test files included in this PR

### 📖 Documentation
- ⚠️ No documentation changes detected

### 💡 Suggestions
1. Address 1 security flag(s) identified above
2. Update documentation for any public API changes
```

## Acceptance Criteria

- [x] Works via GitHub Action (`action.yml`)
- [x] Works via CLI (`python scripts/generate_review.py`)
- [x] Structured Markdown output with Summary, Code Quality, Security, Tests, Documentation, Suggestions
- [x] Tested on 3 real PR scenarios (see `tests/test_pr_reviewer.py`)
- [x] README with setup instructions

## Files

- `action.yml` — GitHub Action definition
- `pr-reviewer-skill.md` — Agent skill definition (Claude Code / OpenClaw)
- `scripts/generate_review.py` — CLI implementation
- `tests/test_pr_reviewer.py` — Test suite (3 scenarios)
- `README.md` — This file
