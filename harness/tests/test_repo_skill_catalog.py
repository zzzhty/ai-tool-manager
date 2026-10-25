from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import repo_skill_catalog  # noqa: E402


def write_skill(
    repo_root: Path,
    plugin: str,
    directory_name: str,
    *,
    catalog_name: str | None = None,
) -> Path:
    skill_dir = repo_root / "plugins" / plugin / "skills" / directory_name
    skill_dir.mkdir(parents=True)
    name = catalog_name or directory_name
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n",
        encoding="utf-8",
    )
    return skill_dir


class RepoSkillCatalogTests(unittest.TestCase):
    def test_catalog_uses_frontmatter_name_without_marketplace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            source = write_skill(root, "alpha", "physical-name", catalog_name="catalog-name")
            marketplace = root / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text("not json", encoding="utf-8")

            catalog = repo_skill_catalog.load_repo_skill_catalog(root)

        self.assertEqual(len(catalog.sources), 1)
        self.assertEqual(catalog.sources[0].name, "catalog-name")
        self.assertEqual(catalog.sources[0].directory_name, "physical-name")
        self.assertEqual(catalog.sources[0].path, source.resolve())

    def test_duplicate_catalog_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            write_skill(root, "alpha", "one", catalog_name="shared")
            write_skill(root, "beta", "two", catalog_name="shared")
            with self.assertRaisesRegex(SystemExit, "duplicate catalog skill names"):
                repo_skill_catalog.load_repo_skill_catalog(root)

    def test_missing_or_malformed_frontmatter_is_rejected(self) -> None:
        cases = {
            "missing-file": None,
            "missing-frontmatter": "# no frontmatter\n",
            "invalid-yaml": "---\nname: [\n---\n",
            "unsafe-name": "---\nname: ../escape\n---\n",
        }
        for label, content in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "repo"
                skill_dir = root / "plugins" / "alpha" / "skills" / label
                skill_dir.mkdir(parents=True)
                if content is not None:
                    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
                with self.assertRaises(SystemExit):
                    repo_skill_catalog.load_repo_skill_catalog(root)

    def test_skill_symlink_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            outside = write_skill(base / "outside", "alpha", "escaped")
            skills_root = root / "plugins" / "alpha" / "skills"
            skills_root.mkdir(parents=True)
            try:
                (skills_root / "escaped").symlink_to(outside, target_is_directory=True)
            except OSError as exc:  # pragma: no cover - platform privilege boundary
                self.skipTest(f"directory symlinks unavailable: {exc}")
            with self.assertRaisesRegex(SystemExit, "escapes repository authority"):
                repo_skill_catalog.load_repo_skill_catalog(root)

    def test_discovery_preserves_native_invocation_boundaries(self) -> None:
        cases = (
            ("explicit", "disable-model-invocation: true\n", "false", None),
            ("implicit", "disable-model-invocation: false\n", "true", None),
            ("codex-only", "", "false", None),
            ("lost-native-policy", "disable-model-invocation: true\n", "true", "policies disagree"),
            ("opposite-policy", "disable-model-invocation: false\n", "false", "policies disagree"),
            ("missing-native-file", "disable-model-invocation: true\n", None, "missing Codex invocation metadata"),
            ("string-flag", 'disable-model-invocation: "true"\n', "false", "must be a boolean"),
            ("string-policy", "", '"false"', "must be a boolean"),
            ("conflicting-flags", "disable-model-invocation: true\ndisable_model_invocation: false\n", "false", "conflicting model-invocation flags"),
        )
        for label, flags, native_policy, error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "repo"
                skill = write_skill(root, "alpha", "one")
                (skill / "SKILL.md").write_text(
                    f"---\nname: one\ndescription: fixture\n{flags}---\n",
                    encoding="utf-8",
                )
                if native_policy is not None:
                    (skill / "agents").mkdir()
                    (skill / "agents" / "openai.yaml").write_text(
                        "interface:\n  display_name: Fixture\n  short_description: Fixture skill\n"
                        f"policy:\n  allow_implicit_invocation: {native_policy}\n",
                        encoding="utf-8",
                    )
                if error:
                    with self.assertRaisesRegex(SystemExit, error):
                        repo_skill_catalog.load_repo_skill_catalog(root)
                else:
                    self.assertEqual(len(repo_skill_catalog.load_repo_skill_catalog(root).sources), 1)

    def test_native_metadata_schema_and_resources_are_enforced_at_both_entries(self) -> None:
        import yaml
        from validate_plugin import validate_skill_root

        cases = (
            ({"policy": {"allow_implicit_invocation": False}}, None),
            ({"policy": {"allow_implicit_invocations": False}}, "unknown Codex policy fields"),
            ({"policies": {}}, "unknown Codex metadata fields"),
            ({"interface": None}, "interface must be a mapping"),
            ({"interface": {"display_name": "Fixture"}}, "short_description must be non-empty"),
            ({"interface": {"display_name": "Fixture", "short_description": "Fixture", "icon_small": "../outside.png"}}, "must stay inside the plugin archive"),
            ({"interface": {"display_name": "Fixture", "short_description": "Fixture", "icon_small": "missing.png"}}, "cannot resolve Codex icon_small"),
            ({"interface": {"display_name": "Fixture", "short_description": "Fixture", "icon_small": "assets/icon.svg"}}, None),
        )
        for changes, error in cases:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "repo"
                skill = write_skill(root, "alpha", "one")
                (skill / "agents").mkdir()
                (skill / "assets").mkdir()
                (skill / "assets/icon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
                metadata = {"interface": {"display_name": "Fixture", "short_description": "Fixture skill"}, **changes}
                (skill / "agents/openai.yaml").write_text(yaml.safe_dump(metadata), encoding="utf-8")
                errors = []
                validate_skill_root(skill.parent, errors)
                if error:
                    self.assertTrue(any(error in message for message in errors), errors)
                    with self.assertRaisesRegex(SystemExit, error):
                        repo_skill_catalog.load_repo_skill_catalog(root)
                else:
                    self.assertEqual(errors, [])
                    self.assertEqual(len(repo_skill_catalog.load_repo_skill_catalog(root).sources), 1)

    def test_live_catalog_matches_all_repository_skill_frontmatter_names(self) -> None:
        catalog = repo_skill_catalog.load_repo_skill_catalog()
        self.assertGreaterEqual(len(catalog.sources), 29)
        self.assertEqual(len(catalog.sources), len(catalog.by_name))
        self.assertEqual(
            set(catalog.plugin_names),
            {"watcher", "workflow", "mattpocock-skills"},
        )
        for source in catalog.sources:
            self.assertTrue((source.path / "SKILL.md").is_file())

    def test_matt_selection_preserves_native_invocation_boundaries(self) -> None:
        import yaml

        catalog = repo_skill_catalog.load_repo_skill_catalog()
        selected = {
            source.name: source for source in catalog.sources
            if source.plugin == "mattpocock-skills"
        }
        self.assertEqual(len(selected), 20)
        self.assertNotIn("resolving-merge-conflicts", selected)
        self.assertIn("pr", selected)
        explicit_workflows = {
            "ask-matt", "grill-me", "grill-with-docs", "handoff", "implement",
            "improve-codebase-architecture", "retro", "teach", "to-spec", "triage",
        }
        for name, source in selected.items():
            with self.subTest(skill=name):
                frontmatter = yaml.safe_load(
                    (source.path / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
                )
                native = yaml.safe_load(
                    (source.path / "agents/openai.yaml").read_text(encoding="utf-8")
                )
                explicit = name in explicit_workflows
                self.assertEqual(frontmatter.get("disable-model-invocation", False), explicit)
                self.assertEqual(
                    native.get("policy", {}).get("allow_implicit_invocation", True),
                    not explicit,
                )

    def test_domain_modeling_resolves_the_current_glossary_reference(self) -> None:
        source = repo_skill_catalog.load_repo_skill_catalog().by_name["domain-modeling"]
        text = (source.path / "SKILL.md").read_text(encoding="utf-8")
        references = re.findall(r"\[GLOSSARY-FORMAT\.md\]\(([^)]+)\)", text)
        self.assertTrue(references)
        glossary_format = (source.path / "GLOSSARY-FORMAT.md").resolve(strict=True)
        for reference in references:
            with self.subTest(reference=reference):
                self.assertEqual((source.path / reference).resolve(strict=True), glossary_format)
        self.assertNotIn("CONTEXT-FORMAT.md", text)
        self.assertFalse((source.path / "CONTEXT-FORMAT.md").exists())


if __name__ == "__main__":
    unittest.main()
