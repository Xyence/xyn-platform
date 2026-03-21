from pathlib import Path

from django.test import SimpleTestCase


class RuntimeDomainCouplingGuardTests(SimpleTestCase):
    def test_runtime_modules_do_not_contain_named_example_app_identifiers(self):
        runtime_root = Path(__file__).resolve().parents[1]
        ignored_path_parts = {"tests", "migrations", "__pycache__"}
        banned_identifiers = (
            "ai_real_estate_deal_finder",
            "real estate deal finder",
            "deal finder",
            "deal-finder",
            "_real_estate_factory_plan",
            "_looks_like_real_estate_deal_finder",
            "_real_estate_seed",
            "team lunch poll",
            "lunch poll",
        )

        hits: list[str] = []
        for module_path in runtime_root.rglob("*.py"):
            if any(part in ignored_path_parts for part in module_path.parts):
                continue
            contents = module_path.read_text(encoding="utf-8").lower()
            lines = contents.splitlines()
            for banned_identifier in banned_identifiers:
                if banned_identifier not in contents:
                    continue
                for line_number, line in enumerate(lines, start=1):
                    if banned_identifier in line:
                        relpath = module_path.relative_to(runtime_root)
                        hits.append(
                            f"{relpath}:{line_number} contains '{banned_identifier}'"
                        )

        self.assertEqual(
            [],
            hits,
            "Runtime modules must remain application-agnostic. "
            "Named example apps are allowed only in tests/docs/examples.\n"
            + "\n".join(hits),
        )
