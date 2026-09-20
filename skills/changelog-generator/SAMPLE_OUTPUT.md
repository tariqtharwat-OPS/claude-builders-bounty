# Sample Output — Real Repository Test

Generated from the Moza operator workspace repository (`github.com/tariqtharwat-OPS/moza-operator`) on 2026-09-20.

**Command:**
```bash
python scripts/generate_changelog.py --limit 20 --repo .
```

**Output:**

```markdown
# Changelog

## [Unreleased]

### Features

- freeze legacy trader and add TradingAgents Binance shadow probe (afb06cb)

### Other Changes

- commerce: record Tenor bounty mechanism test (a0d5e86)
- commerce: record Omi bounty route kill (f9cd44f)
- record commerce negative-bounty filter test (154bb5b)
- evidence: reconcile RustChain and MoltJobs at 22:10 WITA (12cae7a)
- evidence: hand off Digital Markets to native paper worker (0f2d2dd)
- record pending GitHub receipt delivery (3ecd34f)
- record canonicalization proof and shadow regression receipts (691f75e)
- evidence: record scoped P02 acceptance (b6588fb)
- commerce: reconcile RustChain and MoltJobs settlement (d222271)
- evidence: record bounded shadow progress (709a64b)
- evidence: record P02 independent review blocker (01ff58a)
- Record current P02 isolation proof blocker (6d76b27)
- evidence: record bounded shadow progress 2026-09-16T132538Z (bbdff74)
- evidence: record bounded shadow continuation timeout (34c05a8)
- Record bounded shadow overlap reconciliation (fd5bf2e)
- evidence: accept capability regression suite (3c9c4ff)
- evidence: qualify PayanAgent free surfaces (b191cf5)
- Record BlindOracle payload readback (97f5dba)
- record bounded shadow timeout reconciliation (6a8e581)
```

**Verification:**
- Conventional commit (`feat:`) correctly categorized under Features
- Non-conventional commits correctly fall back to "Other Changes"
- Short hashes included
- Deterministic output for identical input
- Tested on a real, active repository with 20+ commits
