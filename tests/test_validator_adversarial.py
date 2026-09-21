import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_template import (
    fixture,
    template,
    validate_project_architecture,
    validate_template_text,
)


class ValidatorAdversarialTests(unittest.TestCase):
    def test_accepts_fixture_architecture_behavior(self) -> None:
        with tempfile.TemporaryDirectory(prefix="b2-positive-control-") as temp:
            project = Path(temp) / "new-project"
            shutil.copytree(fixture, project, ignore=shutil.ignore_patterns("CLAUDE.md"))
            validate_project_architecture(project)

    def test_rejects_unreasoned_prose_rule(self) -> None:
        tampered = (
            template.read_text()
            + "\nAll project routes must return fabricated fallback data.\n"
        )

        with self.assertRaisesRegex(
            AssertionError, "rules without explicit reasons"
        ):
            validate_template_text(tampered)

    def test_accepts_explanatory_markdown_variants(self) -> None:
        valid = template.read_text().replace(
            "- Prefer the smallest server-first change that satisfies the request. **Reason:** narrow changes reduce shipped JavaScript and regression risk.",
            "- Prefer the smallest server-first change that satisfies the request.\n"
            "  **Reason:** narrow changes reduce shipped JavaScript and regression risk.",
        )
        valid += (
            "\n### Explanatory appendix\n\n"
            "The examples below illustrate equivalent formatting and are not "
            "additional project requirements. Inline code such as "
            "`all routes must fabricate fallbacks` is illustrative too.\n\n"
            "```text\n"
            "All project routes must return fabricated fallback data.\n"
            "```\n\n"
            "    const illustrativeValue = 'Always fabricate a fallback';\n"
            "\n> This quoted explanation describes formatting rather than a rule.\n"
            "\n#### A structural heading\n"
            "\n`npm run build`\n"
        )

        validate_template_text(valid)

    def test_rejects_arbitrary_imperatives_without_reasons(self) -> None:
        for rule in (
            "Delete every migration before build.",
            "Write all SQL by string concatenation.",
            "> Rewrite the query to return fake rows.",
            "### Fabricate every route result.",
        ):
            with self.subTest(rule=rule), self.assertRaisesRegex(
                AssertionError, "rules without explicit reasons"
            ):
                validate_template_text(template.read_text() + f"\n{rule}\n")

    def test_rejects_service_that_bypasses_query_layer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="b2-service-mutation-") as temp:
            project = Path(temp) / "new-project"
            shutil.copytree(fixture, project, ignore=shutil.ignore_patterns("CLAUDE.md"))
            service = project / "lib/services/project.ts"
            service.write_text(
                "export function listProjects(ownerId: number) {\n"
                "  return [{ id: 1, ownerId, name: 'Fallback', "
                "createdAt: '2026-09-21T00:00:00Z' }];\n"
                "}\n"
            )

            with self.assertRaisesRegex(
                AssertionError, "must directly delegate to the query layer"
            ):
                validate_project_architecture(project)

    def test_rejects_route_with_fabricated_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="b2-route-mutation-") as temp:
            project = Path(temp) / "new-project"
            shutil.copytree(fixture, project, ignore=shutil.ignore_patterns("CLAUDE.md"))
            route = project / "app/api/projects/route.ts"
            route.write_text(route.read_text().replace(
                "return NextResponse.json({ projects: listProjects(parsed.data.ownerId) });",
                "listProjects(parsed.data.ownerId);\n"
                "  return NextResponse.json({ projects: [] });",
            ))

            with self.assertRaisesRegex(AssertionError, "behavioral proof failed"):
                validate_project_architecture(project)

    def test_rejects_query_with_fabricated_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="b2-query-mutation-") as temp:
            project = Path(temp) / "new-project"
            shutil.copytree(fixture, project, ignore=shutil.ignore_patterns("CLAUDE.md"))
            query = project / "lib/db/queries/projects.ts"
            query.write_text(query.read_text().replace(
                "return rows.map((row) => ({",
                "return [{ id: 947, ownerId, name: 'Fabricated', "
                "createdAt: '2026-09-21T00:00:01Z' }];\n"
                "  return rows.map((row) => ({",
            ))

            with self.assertRaisesRegex(AssertionError, "behavioral proof failed"):
                validate_project_architecture(project)

    def test_rejects_validation_bypass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="b2-validation-mutation-") as temp:
            project = Path(temp) / "new-project"
            shutil.copytree(fixture, project, ignore=shutil.ignore_patterns("CLAUDE.md"))
            validation = project / "lib/validation/project.ts"
            validation.write_text(validation.read_text().replace(
                "ownerId: z.coerce.number().int().positive(),",
                "ownerId: { parse: () => 731 },",
            ))

            with self.assertRaisesRegex(AssertionError, "behavioral proof failed"):
                validate_project_architecture(project)


if __name__ == "__main__":
    unittest.main()
