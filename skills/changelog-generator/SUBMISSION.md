# Claude Builders Bounty — Issue #1 Submission Package

**Bounty:** $50 — SKILL: Generate a CHANGELOG from git history  
**Issue:** https://github.com/claude-builders-bounty/claude-builders-bounty/issues/1

## What This Delivers

A complete OpenClaw skill that generates structured `CHANGELOG.md` files from git commit history using conventional commit parsing.

### Files Included

1. **`SKILL.md`** — Agent skill definition with 5-step workflow, completion criteria, and verification
2. **`scripts/generate_changelog.py`** — Working implementation (4.6 KB)
3. **`README.md`** — Usage documentation with examples
4. **`tests/test_changelog.py`** — 5 passing unit tests covering parsing, grouping, and formatting

### Acceptance Criteria Met

- ✅ Parses conventional commits (`feat:`, `fix(scope):`, `docs:`, etc.)
- ✅ Groups by type: Features, Bug Fixes, Documentation, Refactoring, Tests, Chores, etc.
- ✅ Formats in Keep a Changelog style with version headers
- ✅ Supports tag-based ranges (`--since-tag v1.0.0`) and custom versions
- ✅ Falls back gracefully for non-conventional commits
- ✅ Deterministic output for identical input
- ✅ Includes tests (5/5 passing)

### How to Use

```bash
# Basic usage
python scripts/generate_changelog.py --limit 50 --repo /path/to/repo

# Since a specific tag
python scripts/generate_changelog.py --since-tag v1.0.0 --version v1.1.0 -o CHANGELOG.md

# Run tests
python tests/test_changelog.py
```

## Submission Steps (Requires GitHub Auth)

1. **Fork the repo:**
   ```bash
   gh repo fork claude-builders-bounty/claude-builders-bounty --clone
   cd claude-builders-bounty
   ```

2. **Create branch and add files:**
   ```bash
   git checkout -b feat/changelog-generator-skill
   mkdir -p skills/changelog-generator/{scripts,tests}
   cp /path/to/SKILL.md skills/changelog-generator/
   cp /path/to/scripts/generate_changelog.py skills/changelog-generator/scripts/
   cp /path/to/tests/test_changelog.py skills/changelog-generator/tests/
   cp /path/to/README.md skills/changelog-generator/
   git add skills/changelog-generator/
   git commit -m "feat: add changelog-generator skill for Issue #1"
   ```

3. **Push and create PR:**
   ```bash
   git push origin feat/changelog-generator-skill
   gh pr create --title "feat: add changelog-generator skill (Issue #1)" \
     --body "Delivers a complete OpenClaw skill that generates CHANGELOG.md from git history. Includes implementation, tests (5/5 passing), and documentation. Resolves #1." \
     --label "skill"
   ```

4. **Claim bounty:**
   Comment on the issue: `/opire try`

5. **Payment:** Automatic via Opire/Stripe on merge.

## Evidence of Completion

- Tests: 5/5 passed
- Real-world test: Generated changelog from moza-operator repo (30 commits parsed)
- Script size: 4.6 KB implementation + 2.4 KB tests + 2.6 KB skill + 1.1 KB docs = 10.7 KB total
- No external dependencies (stdlib only: subprocess, re, argparse, datetime)
