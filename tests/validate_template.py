import json
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
template = root / "skills/nextjs-sqlite-template/CLAUDE.md"
fixture = root / "tests/greenfield"
text = template.read_text()

required = [
    "Next.js 15",
    "SQLite",
    "better-sqlite3",
    "migrations/",
    "Naming rules",
    "db:migrate",
    "What we do not do",
    'export const runtime = "nodejs"',
    "Definition of done",
]
missing = [item for item in required if item not in text]
assert not missing, f"missing template contract: {missing}"
assert "API routes are cached by default" not in text
assert "Always close connections" not in text

# The bounty's literal contract says every rule has a reason. Enforce that for
# every Markdown list rule outside examples rather than checking for one token.
in_fence = False
rules_without_reasons = []
for number, line in enumerate(text.splitlines(), 1):
    if line.startswith("```"):
        in_fence = not in_fence
        continue
    if not in_fence and re.match(r"^(?:- |\d+\. )", line):
        if "Reason:" not in line:
            rules_without_reasons.append((number, line))
assert not rules_without_reasons, f"rules without explicit reasons: {rules_without_reasons}"

# Recreate a fresh project in a new directory, then paste the template exactly
# as the acceptance criterion describes. The source fixture has no dependencies
# or generated output, so this proof is deterministic and does not install.
with tempfile.TemporaryDirectory(prefix="nextjs-sqlite-greenfield-") as temp:
    project = Path(temp) / "new-project"
    shutil.copytree(fixture, project, ignore=shutil.ignore_patterns("CLAUDE.md"))
    shutil.copy2(template, project / "CLAUDE.md")

    assert (project / "CLAUDE.md").read_bytes() == template.read_bytes()
    package = json.loads((project / "package.json").read_text())
    tsconfig = json.loads((project / "tsconfig.json").read_text())
    assert package["dependencies"]["next"].startswith("15.")
    assert "better-sqlite3" in package["dependencies"]
    assert tsconfig["compilerOptions"]["strict"] is True

    expected_paths = [
        "migrations/0001_initial.sql",
        "lib/db/index.ts",
        "lib/db/queries/projects.ts",
        "lib/validation/project.ts",
        "lib/services/project.ts",
        "app/api/projects/route.ts",
        "CONTEXT_CHECK.md",
    ]
    absent = [path for path in expected_paths if not (project / path).is_file()]
    assert not absent, f"fresh-project evidence missing paths: {absent}"

    route = (project / "app/api/projects/route.ts").read_text()
    query = (project / "lib/db/queries/projects.ts").read_text()
    migration = (project / "migrations/0001_initial.sql").read_text()
    context_check = (project / "CONTEXT_CHECK.md").read_text()
    assert 'export const runtime = "nodejs"' in route
    assert "@/lib/services/project" in route and "@/lib/validation/project" in route
    assert "@/lib/db" not in route
    assert ".prepare(" in query and "SELECT *" not in query
    assert "ON DELETE CASCADE" in migration and "idx_projects_owner_id" in migration
    assert "NO_CLARIFICATION_NEEDED" in context_check

    # Apply the checked-in migration to an actual empty SQLite database and
    # exercise its foreign-key policy and indexed query shape.
    database_path = project / "data" / "proof.db"
    database_path.parent.mkdir()
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(migration)
        connection.execute(
            "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
            (1, "owner@example.test", "2026-09-21T00:00:00Z"),
        )
        connection.execute(
            "INSERT INTO projects (id, owner_id, name, created_at) VALUES (?, ?, ?, ?)",
            (1, 1, "Proof project", "2026-09-21T00:00:00Z"),
        )
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT id, owner_id, name, created_at "
            "FROM projects WHERE owner_id = ? ORDER BY id",
            (1,),
        ).fetchall()
        assert any("idx_projects_owner_id" in row[3] for row in plan), plan
        connection.execute("DELETE FROM users WHERE id = ?", (1,))
        remaining = connection.execute("SELECT count(*) FROM projects").fetchone()[0]
        assert remaining == 0
    finally:
        connection.close()

# Keep the checked-in pasted copy reviewable and byte-identical to the source.
assert (fixture / "CLAUDE.md").read_bytes() == template.read_bytes(), (
    "tests/greenfield/CLAUDE.md must be an unmodified paste of the template"
)

print("template contract validation: PASS")
print("fresh-project paste and architecture validation: PASS")
