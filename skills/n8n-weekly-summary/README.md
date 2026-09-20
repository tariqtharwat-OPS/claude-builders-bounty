# n8n + Claude API — Automated Weekly Dev Summary

**Bounty:** $200 — Issue #5  
**Repo:** https://github.com/claude-builders-bounty/claude-builders-bounty/issues/5

## What This Delivers

A complete n8n workflow that automatically generates weekly development summaries by:
1. Fetching recent commits, issues, and PRs from GitHub
2. Summarizing them using Claude API (Anthropic)
3. Formatting into a structured Markdown report
4. Sending via email (SMTP) or posting to Slack/Discord

## Files Included

- `n8n-workflow.json` — Complete n8n workflow export (ready to import)
- `README.md` — This file with setup instructions

## Setup Instructions

### 1. Install n8n
```bash
npm install -g n8n
n8n start
```

### 2. Import Workflow
- Open n8n UI (http://localhost:5678)
- Click "Import from File" → select `n8n-workflow.json`
- Configure credentials (see below)

### 3. Configure Credentials

**GitHub API:**
- Go to Settings → Credentials → Add Credential → GitHub
- Enter your GitHub personal access token (needs `repo` scope)

**Claude API (Anthropic):**
- Settings → Credentials → Add Credential → Anthropic
- Enter your Anthropic API key

**Email (SMTP):**
- Settings → Credentials → Add Credential → SMTP
- Configure your SMTP server (Gmail, SendGrid, etc.)

### 4. Customize Parameters
Edit the workflow nodes to set:
- `owner` and `repo` in GitHub nodes
- `recipient_email` in Send Email node
- Schedule frequency (default: weekly on Monday 9 AM)

### 5. Activate
Click "Activate" on the workflow. It will run automatically every week.

## Example Output

```markdown
## Weekly Development Summary - 2026-09-19

### 📊 Overview
- Total commits: 47
- New issues: 12
- Merged PRs: 8

### 🔥 Key Changes
- Added user authentication system
- Refactored database connection pooling
- Fixed critical security vulnerability in login flow

### 🐛 Bug Fixes
- Resolved timeout issue in API endpoint (#123)
- Fixed memory leak in background worker

### ✨ New Features
- Implemented real-time notifications
- Added export to CSV functionality

### 👀 Code Review Notes
- Consistent use of TypeScript across new files
- Good test coverage on critical paths

### 📈 Metrics
- Commit frequency: 6.7/day
- Issue resolution rate: 75%
```

## Error Handling

The workflow includes:
- Retry logic for failed API calls (3 attempts with exponential backoff)
- Fallback to basic summary if Claude API is unavailable
- Error notification via email if workflow fails

## Testing

1. Manually trigger the workflow in n8n UI
2. Verify GitHub data is fetched correctly
3. Check Claude API response format
4. Confirm email delivery

## Customization

- **Change frequency:** Edit Schedule Trigger node (supports cron expressions)
- **Add Slack/Discord:** Replace Send Email node with Slack/Discord node
- **Custom summary format:** Modify the prompt in Claude Summary node
- **Multiple repos:** Duplicate GitHub nodes and merge results

## Dependencies

- n8n (self-hosted or cloud)
- GitHub account with API access
- Anthropic API key (Claude)
- SMTP server or alternative notification channel

## License

MIT — Free to use, modify, and distribute.
