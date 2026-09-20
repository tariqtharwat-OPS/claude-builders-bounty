# n8n + Claude API — Automated Weekly Dev Summary

**Bounty:** $200 — Issue #5

## What This Delivers

A complete, importable n8n workflow (`n8n-workflow.json`) that automatically generates weekly development summaries by fetching GitHub activity and summarizing it with Claude API.

## Quick Setup (5 Steps)

1. **Import**: Open n8n → "Import from File" → select `n8n-workflow.json`
2. **Configure**: Edit the "Set Configuration" node with your values:
   - `GITHUB_OWNER` / `GITHUB_REPO` — target repository
   - `ANTHROPIC_API_KEY` — your Anthropic API key
   - `WEBHOOK_URL` — Discord or Slack webhook URL (if empty, falls back to email)
   - `LANGUAGE` — `EN` or `FR`
   - `recipient_email` — fallback email if no webhook
3. **Credentials**: Add GitHub API and Anthropic credentials in n8n Settings → Credentials
4. **Test**: Click "Execute Workflow" to verify GitHub fetching, Claude summarization, and delivery
5. **Activate**: Toggle workflow to "Active" — runs every Friday at 5:00 PM

## Workflow Architecture

```
[Schedule Trigger: Friday 5PM]
        ↓
[Set Configuration]
   ↓    ↓    ↓
[Closed Issues] [Merged PRs] [Commits]
   ↓    ↓    ↓
[Merge Activity Data]
        ↓
[Claude Summary (claude-sonnet-4-20250514)]
        ↓
   [Has Webhook?]
   ↓ yes    ↓ no
[Discord/Slack]  [Email]
```

## Configurable Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `GITHUB_OWNER` | GitHub org or user | `my-org` |
| `GITHUB_REPO` | Repository name | `my-project` |
| `ANTHROPIC_API_KEY` | Anthropic API key | `sk-ant-...` |
| `WEBHOOK_URL` | Discord/Slack webhook | `https://hooks.slack.com/...` |
| `LANGUAGE` | Summary language | `EN` or `FR` |
| `recipient_email` | Email fallback | `team@example.com` |

## Delivery

- **Primary**: Discord or Slack webhook (dual `content`/`text` payload for compatibility)
- **Fallback**: SMTP email (configured when no webhook URL is set)

## Example Output

```markdown
## Weekly Development Summary - 2026-09-19

### 📊 Overview
- Total commits: 47
- Issues closed: 12
- PRs merged: 8

### 🔥 Key Changes
- Added user authentication system
- Refactored database connection pooling

### 🐛 Bug Fixes
- Resolved timeout issue in API endpoint (#123)
- Fixed memory leak in background worker

### ✨ New Features
- Implemented real-time notifications
- Added CSV export functionality

### 📈 Metrics
- Commit frequency: 6.7/day
- Issue resolution rate: 75%
```

## License

MIT
