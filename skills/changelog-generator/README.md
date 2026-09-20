# Changelog Generator Skill

Generates a structured `CHANGELOG.md` from git commit history using conventional commit parsing.

## Usage

```bash
python scripts/generate_changelog.py --limit 50 --repo /path/to/repo
python scripts/generate_changelog.py --since-tag v1.0.0 --version v1.1.0 -o CHANGELOG.md
```

## Acceptance Criteria

- [x] Parses conventional commit format (`feat:`, `fix(scope):`, etc.)
- [x] Groups commits by type (Features, Bug Fixes, Documentation, etc.)
- [x] Formats output in Keep a Changelog style
- [x] Supports tag-based ranges and custom version headers
- [x] Falls back gracefully for non-conventional commits
- [x] Produces deterministic output for identical input

## Example Output

```markdown
# Changelog

## [Unreleased]

### Features

- freeze legacy trader and add TradingAgents Binance shadow probe (afb06cb)

### Other Changes

- commerce: record Tenor bounty mechanism test (a0d5e86)
- evidence: reconcile RustChain and MoltJobs at 22:10 WITA (12cae7a)
```

## Files

- `SKILL.md` — Agent skill definition
- `scripts/generate_changelog.py` — Implementation
- `README.md` — This file
