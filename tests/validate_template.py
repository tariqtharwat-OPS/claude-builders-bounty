from pathlib import Path
p=Path(__file__).resolve().parents[1]/"skills/nextjs-sqlite-template/CLAUDE.md"
s=p.read_text()
required=["Next.js 15","SQLite","better-sqlite3","migrations/","Naming rules","db:migrate","What we do not do","because","export const runtime = \"nodejs\"","Definition of done"]
missing=[x for x in required if x not in s]
assert not missing, missing
assert "API routes are cached by default" not in s
assert "Always close connections" not in s
print("template contract validation: PASS")
