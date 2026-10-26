from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_registry import (  # noqa: E402
    REGISTRY_FILE,
    REGISTRY_SCHEMA_VERSION,
    HarnessRegistryError,
    ensure_codex_harness_covers_catalog,
    load_harness_registry,
    resolve_harness_plan,
)
from repo_skill_catalog import load_repo_skill_catalog  # noqa: E402


def write_registry(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_skill(root: Path, plugin: str, name: str) -> None:
    skill = root / "plugins" / plugin / "skills" / name
    skill.mkdir(parents=True)
    skill.joinpath("SKILL.md").write_text(
        f"---\nname: {name}\ndescription: fixture\n---\n",
        encoding="utf-8",
    )


class HarnessRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_harness_registry()

    def test_default_and_supported_harnesses_are_registry_owned(self) -> None:
        self.assertEqual(self.registry.default_harness, "codex")
        self.assertEqual(
            set(self.registry.choices),
            {
                "codex",
                "zcode",
                "claude-code",
                "copilot-cli",
                "vscode",
                "gemini-cli",
                "opencode",
                "openclaw",
                "pi-agent",
                "oh-my-pi",
            },
        )
        codex = self.registry.harnesses["codex"]
        self.assertEqual(codex.skills.driver, "codex-marketplace")
        self.assertEqual(codex.skills.reconciliation.prune_policy, "managed-stale")
        self.assertEqual(codex.skills.reconciliation.confirmation, "when-nonempty")
        self.assertIsNotNone(codex.skills.marketplace_migration)
        assert codex.skills.marketplace_migration is not None
        self.assertEqual(
            codex.skills.marketplace_migration.retired_marketplace_names,
            ("my-codex",),
        )
        self.assertEqual(
            set(self.registry.excluded_skill_roots),
            {"agents-skills"},
        )
        self.assertEqual(
            self.registry.instructions_source,
            REPO_ROOT / "agents/global-instructions.md",
        )
        self.assertEqual(
            self.registry.instructions_migration.migration_id,
            "split-global-project-instructions",
        )
        self.assertEqual(
            self.registry.instructions_migration.stage,
            "semantic-split",
        )
        self.assertEqual(
            self.registry.instructions_migration.peer_source,
            REPO_ROOT / "AGENTS.md",
        )
        self.assertEqual(
            self.registry.instructions_migration.required_predecessor_revision,
            "c1dfff914bd5c078138f9323b15e32de27527074",
        )

    def test_registry_schema_version_is_an_iso_date_shared_by_both_authorities(self) -> None:
        registry_payload = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        schema_payload = json.loads(
            REGISTRY_FILE.with_name("registry.schema.json").read_text(encoding="utf-8")
        )

        self.assertEqual(date.fromisoformat(REGISTRY_SCHEMA_VERSION).isoformat(), REGISTRY_SCHEMA_VERSION)
        self.assertEqual(registry_payload["schemaVersion"], REGISTRY_SCHEMA_VERSION)
        self.assertIn("schemaVersion", schema_payload["required"])
        self.assertEqual(
            schema_payload["properties"]["schemaVersion"],
            {"type": "string", "const": REGISTRY_SCHEMA_VERSION},
        )

    def test_aliases_resolve_the_same_plan_without_adding_distributions(self) -> None:
        expected = {"claude": "claude-code", "copilot": "copilot-cli", "gemini": "gemini-cli", "pi": "pi-agent", "omp": "oh-my-pi"}
        self.assertEqual(self.registry.aliases, expected)
        self.assertTrue(set(expected).isdisjoint(self.registry.choices))
        with tempfile.TemporaryDirectory() as tmp:
            for alias, canonical in expected.items():
                for platform in ("posix", "nt"):
                    with self.subTest(alias=alias, platform=platform):
                        options = dict(environ={}, user_home=Path(tmp), os_name=platform)
                        self.assertEqual(
                            resolve_harness_plan(self.registry, alias, **options),
                            resolve_harness_plan(self.registry, canonical, **options),
                        )

    def test_openclaw_state_profile_home_and_platform_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            relocated = home / "relocated"
            explicit = home / "custom-state"
            cases = (
                ({}, home / ".openclaw"),
                ({"OPENCLAW_PROFILE": "work"}, home / ".openclaw-work"),
                ({"OPENCLAW_PROFILE": " Dev_2 "}, home / ".openclaw-Dev_2"),
                ({"OPENCLAW_PROFILE": "DEFAULT"}, home / ".openclaw"),
                ({"OPENCLAW_HOME": str(relocated)}, relocated / ".openclaw"),
                ({"OPENCLAW_HOME": "~/relocated", "OPENCLAW_PROFILE": "work"}, relocated / ".openclaw-work"),
                ({"OPENCLAW_HOME": "null"}, home / ".openclaw"),
                ({"OPENCLAW_HOME": " undefined "}, home / ".openclaw"),
                ({"OPENCLAW_STATE_DIR": str(explicit), "OPENCLAW_PROFILE": "work"}, explicit),
                ({"OPENCLAW_STATE_DIR": "~/state", "OPENCLAW_HOME": str(relocated)}, relocated / "state"),
                ({"OPENCLAW_STATE_DIR": " ", "OPENCLAW_PROFILE": " "}, home / ".openclaw"),
            )
            for environment, expected in cases:
                for platform, materialization in (("posix", "directory-symlink"), ("nt", "directory-junction")):
                    with self.subTest(environment=environment, platform=platform):
                        plan = resolve_harness_plan(self.registry, "openclaw", environ=environment,
                                                    user_home=home, os_name=platform)
                        self.assertEqual(plan.root, expected)
                        self.assertEqual(plan.skills_root, expected / "skills")
                        self.assertEqual(plan.skills_materialization, materialization)
                        self.assertIsNone(plan.instructions_target)
                        self.assertIsNone(plan.instructions_materialization)
                        self.assertEqual(plan.instruction_shadow_paths, ())
                        self.assertEqual(plan.harness.extras, ())
                        self.assertIsNone(plan.marketplace_path)
                        self.assertEqual(plan.excluded_skill_roots, (home / ".agents/skills",))

    def test_openclaw_invalid_paths_and_profiles_fail_closed(self) -> None:
        cases = (
            {"OPENCLAW_STATE_DIR": "relative/state"},
            {"OPENCLAW_HOME": "relative/home"},
            {"OPENCLAW_PROFILE": "../work"},
            {"OPENCLAW_PROFILE": "work/other"},
            {"OPENCLAW_PROFILE": "work\\other"},
            {"OPENCLAW_PROFILE": "-work"},
            {"OPENCLAW_PROFILE": "a" * 65},
        )
        with tempfile.TemporaryDirectory() as tmp:
            for environment in cases:
                with self.subTest(environment=environment), self.assertRaises(HarnessRegistryError):
                    resolve_harness_plan(self.registry, "openclaw", environ=environment, user_home=Path(tmp))

    def test_skills_only_requires_explicit_exact_none_driver(self) -> None:
        from jsonschema import Draft202012Validator

        original = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        validator = Draft202012Validator(json.loads(REGISTRY_FILE.with_name("registry.schema.json").read_text()))
        validator.validate(original)
        mutations = (
            lambda data: data["harnesses"]["openclaw"].pop("instructions"),
            lambda data: data["harnesses"]["openclaw"].update(instructions=None),
            lambda data: data["harnesses"]["openclaw"]["instructions"].update(relativePath="AGENTS.md"),
            lambda data: data["harnesses"]["openclaw"].update(extras=["watcher-hooks"]),
            lambda data: data["harnesses"]["codex"].update(instructions={"driver": "none"}),
            lambda data: data["harnesses"]["openclaw"]["root"]["candidates"][0].update(append=".other"),
            lambda data: data["harnesses"]["openclaw"]["root"]["candidates"][0].update(name="OPENCLAW_STATE_DIR"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for index, mutate in enumerate(mutations):
                with self.subTest(case=index):
                    payload = json.loads(json.dumps(original))
                    mutate(payload)
                    self.assertFalse(validator.is_valid(payload))
                    path = Path(tmp) / "registry.json"
                    write_registry(path, payload)
                    with self.assertRaises(HarnessRegistryError):
                        load_harness_registry(path)

    def test_all_existing_harnesses_retain_their_instruction_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in self.registry.choices:
                if name == "openclaw":
                    continue
                with self.subTest(name=name):
                    plan = resolve_harness_plan(self.registry, name, environ={}, user_home=Path(tmp))
                    self.assertIsNotNone(plan.instructions_target)
                    self.assertIn(plan.instructions_materialization, {"copy", "symlink"})
                    self.assertNotEqual(plan.harness.instructions.driver, "none")

    def test_alias_schema_and_reader_reject_invalid_names_and_collisions(self) -> None:
        from jsonschema import Draft202012Validator

        original = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        schema = json.loads(REGISTRY_FILE.with_name("registry.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        validator.validate(original)
        cases = (
            ("not-array", "copilot", True),
            ("not-string", [1], True),
            ("invalid-name", ["../copilot"], True),
            ("untrimmed", [" copilot "], True),
            ("duplicate", ["copilot", "copilot"], True),
            ("canonical-collision", ["codex"], False),
            ("self-collision", ["copilot-cli"], False),
            ("alias-collision", ["claude"], False),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            for label, aliases, structural in cases:
                with self.subTest(label=label):
                    payload = json.loads(json.dumps(original))
                    payload["harnesses"]["copilot-cli"]["aliases"] = aliases
                    if structural:
                        self.assertFalse(validator.is_valid(payload))
                    write_registry(path, payload)
                    with self.assertRaises(HarnessRegistryError):
                        load_harness_registry(path)

    def test_environment_root_and_environment_home_append_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_root = Path(tmp)
            home = fixture_root / "users" / "tester"
            codex_root = fixture_root / "config" / "codex"
            claude_root = fixture_root / "config" / "claude"
            copilot_root = fixture_root / "config" / "copilot"
            gemini_home = fixture_root / "homes" / "gemini"
            pi_root = fixture_root / "config" / "pi-agent"
            codex = resolve_harness_plan(
                self.registry,
                "codex",
                environ={"CODEX_HOME": str(codex_root)},
                user_home=home,
            )
            claude = resolve_harness_plan(
                self.registry,
                "claude-code",
                environ={"CLAUDE_CONFIG_DIR": str(claude_root)},
                user_home=home,
            )
            copilot = resolve_harness_plan(
                self.registry,
                "copilot-cli",
                environ={"COPILOT_HOME": str(copilot_root)},
                user_home=home,
            )
            gemini = resolve_harness_plan(
                self.registry,
                "gemini-cli",
                environ={"GEMINI_CLI_HOME": str(gemini_home)},
                user_home=home,
            )
            pi = resolve_harness_plan(
                self.registry,
                "pi-agent",
                environ={"PI_CODING_AGENT_DIR": str(pi_root)},
                user_home=home,
            )

            self.assertEqual(codex.root, codex_root)
            self.assertEqual(claude.root, claude_root)
            self.assertEqual(copilot.root, copilot_root)
            self.assertEqual(gemini.root, gemini_home / ".gemini")
            self.assertEqual(pi.root, pi_root)

    def test_pi_agent_uses_its_native_global_configuration_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "users" / "tester"
            for os_name, materialization in (
                ("posix", "directory-symlink"),
                ("nt", "directory-junction"),
            ):
                with self.subTest(os_name=os_name):
                    plan = resolve_harness_plan(
                        self.registry,
                        "pi-agent",
                        environ={},
                        user_home=home,
                        os_name=os_name,
                    )

                    self.assertEqual(plan.root, home / ".pi/agent")
                    self.assertEqual(plan.skills_root, home / ".pi/agent/skills")
                    self.assertEqual(plan.skills_materialization, materialization)
                    self.assertEqual(plan.instructions_target, home / ".pi/agent/AGENTS.md")
                    self.assertEqual(plan.instructions_materialization, "copy")
                    self.assertEqual(
                        plan.instruction_shadow_paths,
                        (home / ".pi/agent/AGENTS.override.md",),
                    )

    def test_oh_my_pi_uses_its_native_agent_directory_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "users" / "tester"
            for os_name, materialization in (
                ("posix", "directory-symlink"),
                ("nt", "directory-junction"),
            ):
                with self.subTest(os_name=os_name):
                    plan = resolve_harness_plan(
                        self.registry,
                        "oh-my-pi",
                        environ={},
                        user_home=home,
                        os_name=os_name,
                    )

                    self.assertEqual(plan.root, home / ".omp/agent")
                    self.assertEqual(plan.skills_root, home / ".omp/agent/skills")
                    self.assertEqual(plan.skills_materialization, materialization)
                    self.assertEqual(plan.instructions_target, home / ".omp/agent/AGENTS.md")
                    self.assertEqual(plan.instructions_materialization, "copy")
                    self.assertEqual(plan.instruction_shadow_paths, ())

            relocated = home / "config" / "omp-agent"
            relocated_plan = resolve_harness_plan(
                self.registry,
                "oh-my-pi",
                environ={"PI_CODING_AGENT_DIR": str(relocated)},
                user_home=home,
            )
            self.assertEqual(relocated_plan.root, relocated)
            # Named profiles relocate Oh My Pi's agent directory and are not modeled here.
            profile_plan = resolve_harness_plan(
                self.registry,
                "oh-my-pi",
                environ={"OMP_PROFILE": "work"},
                user_home=home,
            )
            self.assertEqual(profile_plan.root, home / ".omp/agent")

    def test_bridge_ready_requires_two_regular_byte_identical_sources(self) -> None:
        original = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        instructions = original["sources"]["instructions"]
        instructions["current"] = "AGENTS.md"
        instructions["migration"]["stage"] = "bridge-ready"
        instructions["migration"]["peer"] = "agents/global-instructions.md"
        instructions["migration"].pop("requiredPredecessorRevision")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.joinpath("agents").mkdir(parents=True)
            repo.joinpath("AGENTS.md").write_text("current\n", encoding="utf-8")
            peer = repo / "agents/global-instructions.md"
            peer.write_text("different\n", encoding="utf-8")
            registry_path = Path(tmp) / "registry.json"
            write_registry(registry_path, original)

            with self.assertRaisesRegex(
                HarnessRegistryError,
                "must be byte-identical during bridge-ready",
            ):
                load_harness_registry(registry_path, repo_root=repo)

            peer.write_text("current\n", encoding="utf-8")
            registry = load_harness_registry(registry_path, repo_root=repo)
            self.assertEqual(
                registry.instructions_source,
                repo.resolve(strict=False) / "AGENTS.md",
            )

    def test_later_instruction_stages_require_a_predecessor(self) -> None:
        original = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        instructions = original["sources"]["instructions"]
        migration = instructions["migration"]
        migration["stage"] = "source-switched"
        instructions["current"] = "agents/global-instructions.md"
        migration["peer"] = "AGENTS.md"
        migration.pop("requiredPredecessorRevision")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.joinpath("agents").mkdir(parents=True)
            repo.joinpath("AGENTS.md").write_text("same\n", encoding="utf-8")
            repo.joinpath("agents/global-instructions.md").write_text(
                "same\n", encoding="utf-8"
            )
            path = Path(tmp) / "registry.json"
            write_registry(path, original)
            with self.assertRaisesRegex(
                HarnessRegistryError,
                "requiredPredecessorRevision is required",
            ):
                load_harness_registry(path, repo_root=repo)

            migration["requiredPredecessorRevision"] = "a" * 40
            write_registry(path, original)
            registry = load_harness_registry(path, repo_root=repo)
            self.assertEqual(
                registry.instructions_migration.required_predecessor_revision,
                "a" * 40,
            )

    def test_semantic_split_allows_the_global_and_project_sources_to_diverge(self) -> None:
        original = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.joinpath("agents").mkdir(parents=True)
            repo.joinpath("AGENTS.md").write_text(
                "project routing\n", encoding="utf-8"
            )
            repo.joinpath("agents/global-instructions.md").write_text(
                "global policy\n", encoding="utf-8"
            )
            registry_path = Path(tmp) / "registry.json"
            write_registry(registry_path, original)

            registry = load_harness_registry(registry_path, repo_root=repo)

        self.assertEqual(
            registry.instructions_source,
            repo.resolve(strict=False) / "agents/global-instructions.md",
        )

    def test_instruction_stage_requires_its_canonical_path_orientation(self) -> None:
        original = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        instructions = original["sources"]["instructions"]
        instructions["migration"]["stage"] = "bridge-ready"
        instructions["migration"].pop("requiredPredecessorRevision")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            write_registry(path, original)
            with self.assertRaisesRegex(
                HarnessRegistryError,
                "do not match the bridge-ready migration orientation",
            ):
                load_harness_registry(path)

    def test_fixed_and_excluded_roots_follow_user_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_root = Path(tmp)
            home = fixture_root / "users" / "tester"
            zcode = resolve_harness_plan(
                self.registry,
                "zcode",
                environ={},
                user_home=home,
            )
            opencode = resolve_harness_plan(
                self.registry,
                "opencode",
                environ={"XDG_CONFIG_HOME": str(fixture_root / "xdg")},
                user_home=home,
            )

            self.assertEqual(zcode.skills_root, home / ".zcode/skills")
            self.assertEqual(zcode.instructions_target, home / ".zcode/AGENTS.md")
            self.assertEqual(zcode.excluded_skill_roots, (home / ".agents/skills",))
            self.assertEqual(opencode.root, home / ".config/opencode")

    def test_removed_shared_harness_is_rejected_without_an_alias(self) -> None:
        with self.assertRaisesRegex(
            HarnessRegistryError,
            "unknown harness 'shared'",
        ):
            resolve_harness_plan(self.registry, "shared", environ={})

    def test_harness_skills_root_cannot_also_be_excluded(self) -> None:
        original = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        original["excludedSkillRoots"]["agents-skills"]["root"]["candidates"] = [
            {"source": "user-home", "append": ".zcode"}
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            write_registry(path, original)
            registry = load_harness_registry(path)
            with self.assertRaisesRegex(
                HarnessRegistryError,
                "skills root is also excluded",
            ):
                resolve_harness_plan(
                    registry,
                    "zcode",
                    environ={},
                    user_home=Path(tmp) / "home",
                )

    def test_gemini_instruction_filename_is_settings_derived(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / ".gemini" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(
                json.dumps({"context": {"fileName": "AGENTS.md"}}),
                encoding="utf-8",
            )
            plan = resolve_harness_plan(
                self.registry,
                "gemini-cli",
                environ={},
                user_home=home,
            )
            self.assertEqual(plan.instructions_target, home / ".gemini/AGENTS.md")

            settings.write_text(
                json.dumps({"context": {"fileName": ["ONE.md", "TWO.md"]}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(HarnessRegistryError, "multiple filenames"):
                resolve_harness_plan(
                    self.registry,
                    "gemini-cli",
                    environ={},
                    user_home=home,
                )

    def test_existing_instruction_symlink_does_not_change_the_managed_target_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_home = home / ".codex"
            source = home / "repo" / "AGENTS.md"
            source.parent.mkdir()
            source.write_text("instructions\n", encoding="utf-8")
            codex_home.mkdir()
            codex_home.joinpath("AGENTS.md").symlink_to(source)

            plan = resolve_harness_plan(
                self.registry,
                "codex",
                environ={"CODEX_HOME": str(codex_home)},
                user_home=home,
            )

        self.assertEqual(plan.instructions_target, codex_home / "AGENTS.md")

    def test_registry_rejects_unknown_fields_drivers_and_path_escape(self) -> None:
        original = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        cases = (
            ("unknown", lambda data: data.update({"command": "echo unsafe"}), "unsupported fields"),
            (
                "schema-version",
                lambda data: data.update({"schemaVersion": "v2"}),
                f"schemaVersion must be '{REGISTRY_SCHEMA_VERSION}'",
            ),
            (
                "driver",
                lambda data: data["harnesses"]["zcode"]["skills"].update(
                    {"driver": "shell-command"}
                ),
                "driver is unsupported",
            ),
            (
                "escape",
                lambda data: data["harnesses"]["zcode"]["instructions"].update(
                    {"relativePath": "../AGENTS.md"}
                ),
                "must not escape",
            ),
            (
                "windows-drive",
                lambda data: data["harnesses"]["zcode"]["instructions"].update(
                    {"relativePath": "C:AGENTS.md"}
                ),
                "must not escape",
            ),
            (
                "not-normalized",
                lambda data: data["harnesses"]["zcode"]["instructions"].update(
                    {"relativePath": "instructions//AGENTS.md"}
                ),
                "must be normalized",
            ),
            (
                "unsupported-projection-confirmation",
                lambda data: data["harnesses"]["zcode"]["skills"][
                    "reconciliation"
                ].update({"confirmation": "when-nonempty"}),
                "must be 'none' for directory projection",
            ),
            (
                "legacy-kind",
                lambda data: data["harnesses"]["zcode"].update({"kind": "native"}),
                "unsupported fields",
            ),
            (
                "legacy-shared-discovery",
                lambda data: data["harnesses"]["zcode"].update(
                    {"sharedSkillsDiscovery": "official"}
                ),
                "unsupported fields",
            ),
            (
                "forbidden-instructions",
                lambda data: data["harnesses"]["zcode"].update(
                    {"instructions": {"driver": "forbidden"}}
                ),
                "driver is unsupported",
            ),
        )
        for label, mutate, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                payload = json.loads(json.dumps(original))
                mutate(payload)
                path = Path(tmp) / "registry.json"
                write_registry(path, payload)
                with self.assertRaisesRegex(HarnessRegistryError, expected):
                    load_harness_registry(path)

    def test_registry_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            duplicate = root / "duplicate.json"
            duplicate.write_text(
                REGISTRY_FILE.read_text(encoding="utf-8").replace(
                    f'"schemaVersion": "{REGISTRY_SCHEMA_VERSION}",',
                    f'"schemaVersion": "{REGISTRY_SCHEMA_VERSION}",\n'
                    f'  "schemaVersion": "{REGISTRY_SCHEMA_VERSION}",',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(HarnessRegistryError, "duplicate JSON key"):
                load_harness_registry(duplicate)

    @unittest.skipIf(sys.platform == "win32", "symlink fixture requires POSIX")
    def test_repository_metadata_symlink_escape_is_rejected(self) -> None:
        original = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            outside = root / "outside"
            repo.mkdir()
            outside.mkdir()
            repo.joinpath("AGENTS.md").write_text("instructions\n", encoding="utf-8")
            repo.joinpath("agents").mkdir()
            repo.joinpath("agents/global-instructions.md").write_text(
                "instructions\n", encoding="utf-8"
            )
            repo.joinpath(".agents").symlink_to(outside, target_is_directory=True)
            registry_path = root / "registry.json"
            write_registry(registry_path, original)
            registry = load_harness_registry(registry_path, repo_root=repo)

            with self.assertRaisesRegex(
                HarnessRegistryError,
                "marketplace metadata resolves outside repository root",
            ):
                resolve_harness_plan(registry, "codex", repo_root=repo)

    def test_codex_package_set_must_cover_the_catalog_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_skill(repo, "alpha", "one")
            write_skill(repo, "beta", "two")
            catalog = load_repo_skill_catalog(repo)
            ensure_codex_harness_covers_catalog(
                catalog,
                ["alpha@test", "beta@test"],
                marketplace_name="test",
            )
            with self.assertRaisesRegex(SystemExit, "missing skills-bearing plugins"):
                ensure_codex_harness_covers_catalog(
                    catalog,
                    ["alpha@test"],
                    marketplace_name="test",
                )

    def test_explicit_empty_harness_does_not_fall_back_to_the_default(self) -> None:
        with self.assertRaisesRegex(HarnessRegistryError, "unknown harness ''"):
            resolve_harness_plan(self.registry, "")


if __name__ == "__main__":
    unittest.main()
