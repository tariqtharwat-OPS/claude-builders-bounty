# Real n8n execution evidence

- Runtime: n8n 2.39.8, Node.js 26.8.1, macOS arm64
- Workflow import: `n8n import:workflow --input=skills/n8n-weekly-summary/n8n-workflow.json`
- Execution: imported workflow ID `B5WeeklySummary20260921` via the manual trigger
- GitHub path: live public GitHub API for `octocat/Hello-World`
- Claude boundary: local deterministic HTTP double implementing the Anthropic messages response shape; production workflow still targets `https://api.anthropic.com/v1/messages` by default
- Delivery boundary: local deterministic Discord HTTP receiver; no real channel was contacted
- Observed final node: `Deliver to Discord`
- n8n execution status: `success`, finished=true, UI execution ID 1
- Workflow SHA-256: `7bbee3b6f04f567f3a7052b3828e4637c1850e3f2c64fae74ece14814d0f5eeb`
- Final empty-week execution readback: `Normalize Commits` produced `commits=[]`; `Prepare Claude Prompt` reported `counts.commits=0`; the real n8n path reached `Generate with Claude` and `Deliver to Discord` successfully using controlled local doubles.
- Final empty-week execution output SHA-256: `b323be3448718e82c43ee1dbb2b4e9f15436e8d8bc2b0ca205dca68f68a3d75f`

The first adversarial empty-week run exposed two failure modes: without `alwaysOutputData`, n8n could stop before Claude/delivery; with the sentinel enabled, an unfiltered normalizer could fabricate one blank commit. The release candidate both preserves the empty-week path and filters commit rows to valid GitHub commit objects. The final isolated n8n retest proved `commits=[]`, prompt count `0`, Claude invocation, and delivery without fabricated activity.

The screenshot is a headless capture of the real local n8n Executions page after that retest. It contains no API key, webhook secret, or private repository data.
