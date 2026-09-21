import json
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
template = root / "skills/nextjs-sqlite-template/CLAUDE.md"
fixture = root / "tests/greenfield"


REQUIRED_TEMPLATE_CONTRACT = [
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

# Prose outside a list is explanatory metadata, not a rule. Keeping this set
# explicit makes an added prose rule fail closed instead of escaping the rule
# reason check merely because it was not formatted as a list item.
ALLOWED_PROSE = {
    "Every enforceable rule in this file carries an explicit **Reason** so an assistant can apply the intent when the exact example does not fit.",
    "Example:",
}


def validate_template_text(text: str) -> None:
    missing = [item for item in REQUIRED_TEMPLATE_CONTRACT if item not in text]
    assert not missing, f"missing template contract: {missing}"
    assert "API routes are cached by default" not in text
    assert "Always close connections" not in text

    in_fence = False
    rules_without_reasons = []
    unexpected_prose = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or line.startswith("#"):
            continue
        if re.match(r"^(?:- |\d+\. )", line):
            if "Reason:" not in line:
                rules_without_reasons.append((number, line))
        elif line not in ALLOWED_PROSE:
            unexpected_prose.append((number, line))

    assert not in_fence, "unclosed Markdown code fence"
    assert not rules_without_reasons, (
        f"rules without explicit reasons: {rules_without_reasons}"
    )
    assert not unexpected_prose, (
        "prose outside the reason-checked rule structure: "
        f"{unexpected_prose}"
    )


def compact_typescript(source: str) -> str:
    return re.sub(r"\s+", " ", source).strip()


def validate_project_architecture(project: Path) -> None:
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
    service = (project / "lib/services/project.ts").read_text()
    migration = (project / "migrations/0001_initial.sql").read_text()
    context_check = (project / "CONTEXT_CHECK.md").read_text()

    assert 'export const runtime = "nodejs"' in route
    assert 'from "@/lib/services/project"' in route
    assert 'from "@/lib/validation/project"' in route
    assert "@/lib/db" not in route
    assert "listProjects(parsed.data.ownerId)" in compact_typescript(route)

    assert 'from "@/lib/db"' in query
    assert ".prepare(" in query and "SELECT *" not in query
    assert ".all(ownerId)" in compact_typescript(query)

    # Prove the middle architectural layer is real rather than merely present:
    # the route's service must delegate its only function body to the query
    # layer with the validated owner id. Exact body matching rejects fabricated
    # success-shaped fallback data and dead-code imports.
    compact_service = compact_typescript(service)
    expected_service = (
        'import { listProjectsByOwner } from "@/lib/db/queries/projects"; '
        "export function listProjects(ownerId: number) { "
        "return listProjectsByOwner(ownerId); }"
    )
    assert compact_service == expected_service, (
        "project service must directly delegate to the query layer without "
        "fallback data"
    )

    assert "ON DELETE CASCADE" in migration
    assert "idx_projects_owner_id" in migration
    assert "NO_CLARIFICATION_NEEDED" in context_check

    # Apply the checked-in migration to an actual empty SQLite database and
    # exercise its foreign-key policy and indexed query shape.
    database_path = project / "data" / "proof.db"
    database_path.parent.mkdir(exist_ok=True)
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
        remaining = connection.execute(
            "SELECT count(*) FROM projects"
        ).fetchone()[0]
        assert remaining == 0
    finally:
        connection.close()


def validate() -> None:
    text = template.read_text()
    validate_template_text(text)

    # Recreate a fresh project in a new directory, then paste the template
    # exactly as the acceptance criterion describes. The fixture has no
    # dependencies or generated output, so this proof installs nothing.
    with tempfile.TemporaryDirectory(prefix="nextjs-sqlite-greenfield-") as temp:
        project = Path(temp) / "new-project"
        shutil.copytree(fixture, project, ignore=shutil.ignore_patterns("CLAUDE.md"))
        shutil.copy2(template, project / "CLAUDE.md")
        assert (project / "CLAUDE.md").read_bytes() == template.read_bytes()
        validate_project_architecture(project)

    # Keep the checked-in pasted copy reviewable and byte-identical to source.
    assert (fixture / "CLAUDE.md").read_bytes() == template.read_bytes(), (
        "tests/greenfield/CLAUDE.md must be an unmodified paste of the template"
    )


if __name__ == "__main__":
    validate()
    print("template contract validation: PASS")
    print("fresh-project paste and architecture validation: PASS")
