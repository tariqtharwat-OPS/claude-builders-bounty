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
        )

        validate_template_text(valid)

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


if __name__ == "__main__":
    unittest.main()
