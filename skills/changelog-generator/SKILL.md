---
name: changelog-generator
description: "Generate a structured CHANGELOG.md from git history by extracting conventional commits, grouping by type (feat/fix/chore/docs/refactor), and formatting with semantic versioning headers."
---

# Changelog Generator

## Purpose

Generate a clean, readable `CHANGELOG.md` from a Git repository's commit history using conventional commit parsing. Useful for release notes, project documentation, and automated changelog generation in CI/CD pipelines.

## Workflow

1. **Read repository state.**
   - Run `git log --oneline --no-merges` to get recent commit history.
   - Identify the last tag or use `HEAD~N` as the range boundary.
   - **Done when:** you have a list of commits with hashes, dates, and messages.

2. **Parse conventional commits.**
   - Extract commit type prefix: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `style`, `perf`.
   - Parse scope if present: `feat(auth): add login flow` → type=`feat`, scope=`auth`.
   - Extract description after the colon.
   - **Done when:** each commit is classified into a category with its description.

3. **Group by type and sort.**
   - Group commits under their type header.
   - Order types by priority: `feat` > `fix` > `docs` > `refactor` > `perf` > `test` > `chore` > `style`.
   - Within each group, sort by date descending (newest first).
   - **Done when:** commits are organized into categorized sections.

4. **Format the changelog.**
   - Write a `CHANGELOG.md` with:
     - Title: `# Changelog`
     - Version header: `## [Unreleased]` or `## [vX.Y.Z] - YYYY-MM-DD` if a tag exists.
     - Type sections: `### Features`, `### Bug Fixes`, `### Documentation`, etc.
     - Each entry: `- <description> (<short-hash>)`
   - Include an `[Unreleased]` section at top if no tag found.
   - **Done when:** the file follows standard Keep a Changelog format.

5. **Verify output.**
   - Read back the generated `CHANGELOG.md`.
   - Confirm it contains at least one entry per commit type found.
   - Check that all commit hashes referenced exist in the repo.
   - **Done when:** the changelog is complete, formatted correctly, and references valid commits.

## Notes

- If the repo has no conventional commits, fall back to listing all commits under `### Other Changes`.
- Preserve author attribution if requested: include `(Author Name)` after the hash.
- For large histories (>100 commits), limit to the last 50 unless a specific range is provided.
- Do not modify existing `CHANGELOG.md` content; append new entries only if the file already exists.
