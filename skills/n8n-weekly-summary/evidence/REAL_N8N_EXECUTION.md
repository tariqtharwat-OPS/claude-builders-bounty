# Real n8n execution evidence

- Runtime: n8n 2.39.8, Node.js 26.8.1, macOS arm64
- Workflow import: `n8n import:workflow --input=skills/n8n-weekly-summary/n8n-workflow.json`
- Execution: imported workflow ID `B5WeeklySummary20260921` via the manual trigger
- GitHub path: live public GitHub API for `octocat/Hello-World`
- Claude boundary: local deterministic HTTP double implementing the Anthropic messages response shape; production workflow still targets `https://api.anthropic.com/v1/messages` by default
- Delivery boundary: local deterministic Discord HTTP receiver; no real channel was contacted
- Observed final node: `Deliver to Discord`
- n8n execution status: `success`, finished=true, UI execution ID 1
- Workflow SHA-256: `060b9df3dcba3a6c0a9b7b9dd7f78b521818abdc710499d608228e47059224dd`
- Full execution JSON SHA-256: `e51c3db0b6c6d4091e04574018f1fa9ce2ec6e6e1ca0f7858471346db061e3f8`
- Mock request log SHA-256: `596d7b84fcdecdb4dc5413a361a5795085ad0ed6c1c82b1a44d94fa47bd46719`

The first adversarial empty-week run exposed a plausible false success: GitHub returned zero items, normalization never ran, and n8n stopped successfully at the merge without calling Claude or delivery. The release candidate sets `alwaysOutputData: true` on all three GitHub requests and regression validation enforces it. Retest reached Claude and delivery; request-log readback observed exactly `/v1/messages` then `/discord`.

The screenshot is a headless capture of the real local n8n Executions page after that retest. It contains no API key, webhook secret, or private repository data.
