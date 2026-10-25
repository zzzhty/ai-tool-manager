from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plugin_package_identity import (  # noqa: E402
    canonical_plugin_package_digest,
    expected_plugin_identity,
    plugin_cache_identity_issues,
    repository_identity_issues,
    update_repository_identity,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class PluginPackageIdentityTests(unittest.TestCase):
    def make_repo(self, root: Path) -> tuple[Path, Path]:
        repo = root / "repo"
        plugin = repo / "plugins" / "alpha"
        (plugin / "skills" / "one").mkdir(parents=True)
        (plugin / "skills" / "one" / "SKILL.md").write_text(
            "---\nname: one\ndescription: fixture\n---\nbody\n",
            encoding="utf-8",
        )
        write_json(
            plugin / ".codex-plugin" / "plugin.json",
            {"name": "alpha", "version": "0.1.0+codex.old", "skills": "./skills/"},
        )
        write_json(
            repo / ".agents" / "plugins" / "marketplace.json",
            {
                "name": "fixture",
                "plugins": [
                    {
                        "name": "alpha",
                        "source": {"source": "local", "path": "./plugins/alpha"},
                    }
                ],
            },
        )
        (repo / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        return repo, plugin

    def test_release_aligned_identity_updates_manifest_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, plugin = self.make_repo(Path(tmp))
            payload = update_repository_identity(repo)
            version = json.loads(
                (plugin / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
            )["version"]
            self.assertRegex(version, r"^1\.0\.0\+codex\.[0-9a-f]{16}$")
            self.assertEqual(payload["releaseVersion"], "1.0.0")
            self.assertEqual(repository_identity_issues(repo), [])

    def test_release_authority_replaces_a_higher_previous_base_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, plugin = self.make_repo(Path(tmp))
            manifest = plugin / ".codex-plugin" / "plugin.json"
            previous = json.loads(manifest.read_text(encoding="utf-8"))
            previous["version"] = "1.2.3+codex.previous"
            write_json(manifest, previous)
            update_repository_identity(repo)
            identity = expected_plugin_identity(repo, plugin)
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["version"], identity.version)
            self.assertRegex(identity.version, r"^1\.0\.0\+codex\.[0-9a-f]{16}$")
            self.assertEqual(identity.version_authority, "release")
            self.assertEqual(repository_identity_issues(repo), [])

    def test_content_change_requires_a_new_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, plugin = self.make_repo(Path(tmp))
            update_repository_identity(repo)
            before = expected_plugin_identity(repo, plugin)
            skill = plugin / "skills" / "one" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
            after = expected_plugin_identity(repo, plugin)
            self.assertNotEqual(before.content_sha256, after.content_sha256)
            issues = repository_identity_issues(repo)
            self.assertTrue(any("requires version" in issue for issue in issues))

    def test_line_endings_are_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, plugin = self.make_repo(Path(tmp))
            update_repository_identity(repo)
            skill = plugin / "skills" / "one" / "SKILL.md"
            lf_payload = skill.read_bytes().replace(b"\r\n", b"\n")
            skill.write_bytes(lf_payload)
            digest_lf = expected_plugin_identity(repo, plugin).content_sha256
            skill.write_bytes(lf_payload.replace(b"\n", b"\r\n"))
            digest_crlf = expected_plugin_identity(repo, plugin).content_sha256
            self.assertEqual(digest_lf, digest_crlf)

    def test_cache_drift_is_detected_even_when_version_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, plugin = self.make_repo(Path(tmp))
            update_repository_identity(repo)
            cache = Path(tmp) / "cache"
            import shutil

            shutil.copytree(plugin, cache)
            self.assertEqual(plugin_cache_identity_issues(source_root=plugin, cache_root=cache), [])
            skill = cache / "skills" / "one" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "stale\n", encoding="utf-8")
            issues = plugin_cache_identity_issues(source_root=plugin, cache_root=cache)
            self.assertTrue(any("cache content identity differs" in issue for issue in issues))

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_links_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, plugin = self.make_repo(Path(tmp))
            (plugin / "linked").symlink_to(plugin / "skills", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "link or reparse point"):
                canonical_plugin_package_digest(plugin, base_version="1.0.0")

    def test_transient_python_cache_is_outside_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, plugin = self.make_repo(Path(tmp))
            before = expected_plugin_identity(repo, plugin).content_sha256
            transient = plugin / "skills" / "one" / "__pycache__"
            transient.mkdir()
            (transient / "helper.cpython-313.pyc").write_bytes(b"volatile")
            after = expected_plugin_identity(repo, plugin).content_sha256
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
