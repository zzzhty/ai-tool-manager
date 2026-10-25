from __future__ import annotations

import contextlib
import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import sync_agents_skills  # noqa: E402


def write_skill(plugin_root: Path, name: str) -> Path:
    skill_dir = plugin_root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill {name}\n---\n",
        encoding="utf-8",
    )
    return skill_dir


class Sandbox:
    """A temporary repository with two plugin directories and three skills."""

    def __init__(self, base: Path) -> None:
        self.repo_root = base / "repo"
        self.alpha_root = self.repo_root / "plugins" / "alpha"
        self.beta_root = self.repo_root / "plugins" / "beta"
        self.foo = write_skill(self.alpha_root, "foo")
        self.bar = write_skill(self.alpha_root, "bar")
        self.baz = write_skill(self.beta_root, "baz")
        self.target_root = base / "agents" / "skills"
        self.catalog = sync_agents_skills.load_repo_skill_catalog(self.repo_root)


class SyncLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.sandbox = Sandbox(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def test_sync_creates_links_and_is_idempotent(self) -> None:
        status = sync_agents_skills.sync_layer(
            self.sandbox.catalog, target_root=self.sandbox.target_root,
            dry_run=False, prune=True,
        )
        self.assertEqual(status, 0)
        for source in self.sandbox.catalog.sources:
            link = self.sandbox.target_root / source.name
            self.assertTrue(sync_agents_skills.is_projection_link(link), link)
            self.assertEqual(link.resolve(), source.path.resolve())

        again = sync_agents_skills.sync_layer(
            self.sandbox.catalog, target_root=self.sandbox.target_root,
            dry_run=False, prune=True,
        )
        self.assertEqual(again, 0)
        self.assertEqual(
            sorted(path.name for path in self.sandbox.target_root.iterdir()),
            ["bar", "baz", "foo"],
        )

    def test_posix_projection_declares_directory_symlinks(self) -> None:
        with (
            mock.patch.object(sync_agents_skills.os, "name", "posix"),
            mock.patch.object(Path, "symlink_to", autospec=True) as symlink_to,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                status = sync_agents_skills.sync_layer(
                    self.sandbox.catalog,
                    target_root=self.sandbox.target_root,
                    dry_run=False,
                    prune=False,
                )

        self.assertEqual(status, 0)
        self.assertEqual(symlink_to.call_count, len(self.sandbox.catalog.sources))
        for call in symlink_to.call_args_list:
            self.assertEqual(call.kwargs, {"target_is_directory": True})
            self.assertIn(call.args[0].name, {"foo", "bar", "baz"})
            self.assertTrue(call.args[1].is_dir())

    def test_sync_recovers_empty_canonical_directory_left_by_interruption(self) -> None:
        interrupted = self.sandbox.target_root / "foo"
        interrupted.mkdir(parents=True)

        status = sync_agents_skills.sync_layer(
            self.sandbox.catalog,
            target_root=self.sandbox.target_root,
            dry_run=False,
            prune=False,
        )

        self.assertEqual(status, 0)
        self.assertTrue(sync_agents_skills.is_projection_link(interrupted))
        self.assertEqual(interrupted.resolve(), self.sandbox.foo.resolve())

    def test_windows_projection_uses_a_directory_junction(self) -> None:
        link = self.sandbox.target_root / "foo"
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        with (
            mock.patch.object(sync_agents_skills.os, "name", "nt"),
            mock.patch.object(
                sync_agents_skills.subprocess,
                "run",
                return_value=completed,
            ) as run,
            mock.patch.object(Path, "symlink_to", autospec=True) as symlink_to,
        ):
            sync_agents_skills.create_projection_link(link, self.sandbox.foo)

        symlink_to.assert_not_called()
        command = run.call_args.args[0]
        self.assertEqual(
            command[:4],
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive"],
        )
        self.assertIn("New-Item -ItemType Junction", command[-1])
        self.assertNotIn(str(link), command[-1])
        self.assertNotIn(str(self.sandbox.foo), command[-1])
        self.assertEqual(
            run.call_args.kwargs["env"]["OH_MY_HARNESS_SKILL_LINK_PATH"],
            str(link),
        )
        self.assertEqual(
            run.call_args.kwargs["env"]["OH_MY_HARNESS_SKILL_LINK_TARGET"],
            str(self.sandbox.foo),
        )

    def test_junction_removal_uses_rmdir_after_destination_revalidation(self) -> None:
        junction = mock.Mock(spec=Path)

        with (
            mock.patch.object(
                sync_agents_skills,
                "managed_destination",
                return_value=self.sandbox.foo,
            ) as managed_destination,
            mock.patch.object(sync_agents_skills, "is_junction", return_value=True),
        ):
            sync_agents_skills.remove_projection_link(
                junction,
                self.sandbox.catalog,
                expected_destination=self.sandbox.foo,
            )

        managed_destination.assert_called_once_with(junction, self.sandbox.catalog)
        junction.rmdir.assert_called_once_with()
        junction.unlink.assert_not_called()

        junction.reset_mock()
        with mock.patch.object(
            sync_agents_skills,
            "managed_destination",
            return_value=self.sandbox.bar,
        ):
            with self.assertRaisesRegex(SystemExit, "changed or unmanaged"):
                sync_agents_skills.remove_projection_link(
                    junction,
                    self.sandbox.catalog,
                    expected_destination=self.sandbox.foo,
                )
        junction.rmdir.assert_not_called()
        junction.unlink.assert_not_called()

    def test_reparse_directory_is_never_treated_as_interrupted_empty_residue(self) -> None:
        reparse = mock.Mock(spec=Path)
        metadata = mock.Mock(
            st_mode=stat.S_IFDIR | 0o755,
            st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
        )
        reparse.lstat.return_value = metadata

        self.assertFalse(sync_agents_skills.is_empty_plain_directory(reparse))
        reparse.iterdir.assert_not_called()

    def test_plain_directory_does_not_require_pathlib_mount_support(self) -> None:
        ordinary = self.sandbox.target_root
        ordinary.mkdir(parents=True)

        with (
            mock.patch.object(
                Path,
                "is_mount",
                side_effect=NotImplementedError("unsupported on Windows Python 3.11"),
            ),
            mock.patch.object(
                sync_agents_skills.os.path,
                "ismount",
                return_value=False,
            ) as ismount,
        ):
            self.assertTrue(sync_agents_skills.is_plain_directory(ordinary))

        ismount.assert_called_once_with(ordinary)

    def test_windows_311_junction_uses_reparse_tag_fallback(self) -> None:
        junction = mock.Mock()
        junction.is_junction = None
        junction.lstat.return_value = mock.Mock(st_reparse_tag=0xA0000003)

        with mock.patch.object(sync_agents_skills.os, "name", "nt"):
            self.assertTrue(sync_agents_skills.is_junction(junction))

        junction.lstat.return_value = mock.Mock(st_reparse_tag=0xA000001A)
        with mock.patch.object(sync_agents_skills.os, "name", "nt"):
            self.assertFalse(sync_agents_skills.is_junction(junction))

    def test_interrupted_directory_removal_requires_exact_empty_canonical_target(self) -> None:
        target_root = self.sandbox.target_root
        canonical = target_root / "foo"
        canonical.mkdir(parents=True)
        sentinel = canonical / "keep.txt"
        sentinel.write_text("user content", encoding="utf-8")
        wrong_name = target_root / "other"
        wrong_name.mkdir()

        with self.assertRaisesRegex(SystemExit, "exact empty interrupted directory"):
            sync_agents_skills.remove_interrupted_empty_directory(
                canonical,
                target_root=target_root,
                catalog_name="foo",
            )
        with self.assertRaisesRegex(SystemExit, "exact empty interrupted directory"):
            sync_agents_skills.remove_interrupted_empty_directory(
                wrong_name,
                target_root=target_root,
                catalog_name="foo",
            )

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user content")
        self.assertTrue(wrong_name.is_dir())
        sentinel.unlink()
        sync_agents_skills.remove_interrupted_empty_directory(
            canonical,
            target_root=target_root,
            catalog_name="foo",
        )
        self.assertFalse(canonical.exists())

    def test_check_detects_missing_drift_and_unmanaged_entries(self) -> None:
        self.assertEqual(
            sync_agents_skills.check_layer(
                self.sandbox.catalog, target_root=self.sandbox.target_root, prune=True
            ),
            1,
        )

        sync_agents_skills.sync_layer(
            self.sandbox.catalog, target_root=self.sandbox.target_root,
            dry_run=False, prune=False,
        )
        # Repoint one managed link at another skill: managed drift.
        foo = self.sandbox.target_root / "foo"
        sync_agents_skills.remove_projection_link(
            foo,
            self.sandbox.catalog,
            expected_destination=self.sandbox.foo,
        )
        sync_agents_skills.create_projection_link(foo, self.sandbox.bar)
        # Replace one link with an unmanaged real directory.
        bar = self.sandbox.target_root / "bar"
        sync_agents_skills.remove_projection_link(
            bar,
            self.sandbox.catalog,
            expected_destination=self.sandbox.bar,
        )
        bar.mkdir()
        (bar / "keep.txt").write_text("user content", encoding="utf-8")
        report = io.StringIO()
        with contextlib.redirect_stdout(report):
            status = sync_agents_skills.check_layer(
                self.sandbox.catalog, target_root=self.sandbox.target_root, prune=True
            )
        self.assertEqual(status, 1)
        self.assertIn("drift:", report.getvalue())
        self.assertIn("unmanaged-entry:", report.getvalue())

    def test_check_flags_stale_managed_link_only_with_prune(self) -> None:
        sync_agents_skills.sync_layer(
            self.sandbox.catalog, target_root=self.sandbox.target_root,
            dry_run=False, prune=False,
        )
        ghost = self.sandbox.target_root / "ghost"
        sync_agents_skills.create_projection_link(ghost, self.sandbox.foo)
        without_prune = sync_agents_skills.check_layer(
            self.sandbox.catalog, target_root=self.sandbox.target_root, prune=False
        )
        self.assertEqual(without_prune, 0)
        with_prune = sync_agents_skills.check_layer(
            self.sandbox.catalog, target_root=self.sandbox.target_root, prune=True
        )
        self.assertEqual(with_prune, 1)

    def test_prune_retires_conflict_projection_and_preserves_user_files(self) -> None:
        target_root = self.sandbox.target_root
        retired = write_skill(
            self.sandbox.repo_root / "plugins" / "mattpocock-skills",
            "resolving-merge-conflicts",
        )
        before = sync_agents_skills.load_repo_skill_catalog(self.sandbox.repo_root)
        sync_agents_skills.sync_layer(
            before, target_root=target_root, dry_run=False, prune=True
        )
        stale = target_root / retired.name
        self.assertEqual(stale.resolve(), retired.resolve())
        user_skill = target_root / "user-skill"
        user_skill.mkdir()
        sentinel = user_skill / "SKILL.md"
        sentinel.write_text("user content", encoding="utf-8")
        note = target_root / "notes.txt"
        note.write_text("unrelated notes", encoding="utf-8")
        (retired / "SKILL.md").unlink()
        retired.rmdir()
        after = sync_agents_skills.load_repo_skill_catalog(self.sandbox.repo_root)

        self.assertNotIn(retired.name, after.by_name)
        report = io.StringIO()
        with contextlib.redirect_stdout(report):
            status = sync_agents_skills.check_layer(
                after, target_root=target_root, prune=True
            )
            sync_agents_skills.sync_layer(
                after, target_root=target_root, dry_run=True, prune=True
            )
        self.assertEqual(status, 1)
        self.assertIn(f"extra-managed: {stale}", report.getvalue())
        self.assertTrue(sync_agents_skills.is_projection_link(stale))

        status = sync_agents_skills.sync_layer(
            after, target_root=target_root, dry_run=False, prune=True
        )
        self.assertEqual(status, 0)
        self.assertFalse(os.path.lexists(stale))
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user content")
        self.assertEqual(note.read_text(encoding="utf-8"), "unrelated notes")
        self.assertEqual(
            sync_agents_skills.check_layer(after, target_root=target_root, prune=True),
            0,
        )

    def test_cleanup_removes_all_managed_links_and_exact_empty_residues(self) -> None:
        sync_agents_skills.sync_layer(
            self.sandbox.catalog,
            target_root=self.sandbox.target_root,
            dry_run=False,
            prune=False,
        )
        ghost = self.sandbox.target_root / "ghost"
        sync_agents_skills.create_projection_link(ghost, self.sandbox.foo)
        interrupted = self.sandbox.target_root / "foo"
        sync_agents_skills.remove_projection_link(
            interrupted,
            self.sandbox.catalog,
            expected_destination=self.sandbox.foo,
        )
        interrupted.mkdir()
        user_skill = self.sandbox.target_root / "user-skill"
        user_skill.mkdir()
        user_skill.joinpath("SKILL.md").write_text(
            "---\nname: user-skill\n---\n",
            encoding="utf-8",
        )

        sync_agents_skills.remove_all_managed_entries(
            self.sandbox.catalog,
            target_root=self.sandbox.target_root,
            dry_run=False,
        )

        self.assertEqual(
            sorted(path.name for path in self.sandbox.target_root.iterdir()),
            ["user-skill"],
        )

    def test_cleanup_dry_run_preserves_managed_entries(self) -> None:
        sync_agents_skills.sync_layer(
            self.sandbox.catalog,
            target_root=self.sandbox.target_root,
            dry_run=False,
            prune=False,
        )

        sync_agents_skills.remove_all_managed_entries(
            self.sandbox.catalog,
            target_root=self.sandbox.target_root,
            dry_run=True,
        )

        self.assertTrue(
            sync_agents_skills.is_projection_link(self.sandbox.target_root / "foo")
        )

    def test_cleanup_refuses_unmanaged_catalog_name_before_any_removal(self) -> None:
        sync_agents_skills.sync_layer(
            self.sandbox.catalog,
            target_root=self.sandbox.target_root,
            dry_run=False,
            prune=False,
        )
        occupied = self.sandbox.target_root / "foo"
        sync_agents_skills.remove_projection_link(
            occupied,
            self.sandbox.catalog,
            expected_destination=self.sandbox.foo,
        )
        occupied.mkdir()
        occupied.joinpath("keep.txt").write_text("user content", encoding="utf-8")

        with self.assertRaisesRegex(SystemExit, "refusing unmanaged skill projection entry"):
            sync_agents_skills.remove_all_managed_entries(
                self.sandbox.catalog,
                target_root=self.sandbox.target_root,
                dry_run=False,
            )

        self.assertEqual(
            occupied.joinpath("keep.txt").read_text(encoding="utf-8"),
            "user content",
        )
        self.assertTrue(
            sync_agents_skills.is_projection_link(self.sandbox.target_root / "bar")
        )

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_projection_operations_refuse_a_linked_target_root(self) -> None:
        external = self.sandbox.target_root.parents[1] / "external-skills"
        external.mkdir()
        self.sandbox.target_root.parent.mkdir(parents=True)
        self.sandbox.target_root.symlink_to(external, target_is_directory=True)

        with self.assertRaisesRegex(SystemExit, "root that is not an ordinary directory"):
            sync_agents_skills.sync_layer(
                self.sandbox.catalog,
                target_root=self.sandbox.target_root,
                dry_run=False,
                prune=True,
            )
        self.assertEqual(
            sync_agents_skills.check_layer(
                self.sandbox.catalog,
                target_root=self.sandbox.target_root,
                prune=True,
            ),
            1,
        )
        with self.assertRaisesRegex(SystemExit, "root that is not an ordinary directory"):
            sync_agents_skills.remove_all_managed_entries(
                self.sandbox.catalog,
                target_root=self.sandbox.target_root,
                dry_run=False,
            )
        self.assertEqual(list(external.iterdir()), [])

    def test_cleanup_cli_requires_an_explicit_target_and_mutation_confirmation(self) -> None:
        script = REPO_ROOT / "scripts" / "sync_agents_skills.py"
        without_target = subprocess.run(
            [sys.executable, str(script), "--repo-root", str(self.sandbox.repo_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(without_target.returncode, 2)
        self.assertIn("--target-root", without_target.stderr)

        unconfirmed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--repo-root",
                str(self.sandbox.repo_root),
                "--target-root",
                str(self.sandbox.target_root),
                "--remove-managed",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(unconfirmed.returncode, 2)
        self.assertIn("requires --yes", unconfirmed.stderr)

        preview = subprocess.run(
            [
                sys.executable,
                str(script),
                "--repo-root",
                str(self.sandbox.repo_root),
                "--target-root",
                str(self.sandbox.target_root),
                "--remove-managed",
                "--dry-run",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(preview.returncode, 0, preview.stderr)

    def test_sync_never_replaces_unmanaged_targets(self) -> None:
        target_root = self.sandbox.target_root
        target_root.mkdir(parents=True)
        unmanaged_directory = target_root / "foo"
        unmanaged_directory.mkdir()
        sentinel = unmanaged_directory / "keep.txt"
        sentinel.write_text("user content", encoding="utf-8")
        (target_root / "bar").write_text("unmanaged file", encoding="utf-8")
        outside = target_root / "outside-note"
        outside.mkdir()
        outside_note = outside / "keep.txt"
        outside_note.write_text("unrelated", encoding="utf-8")

        with self.assertRaises(SystemExit):
            sync_agents_skills.sync_layer(
                self.sandbox.catalog, target_root=target_root, dry_run=False, prune=False
            )

        sentinel.unlink()
        unmanaged_directory.rmdir()
        with self.assertRaises(SystemExit):
            sync_agents_skills.sync_layer(
                self.sandbox.catalog, target_root=target_root, dry_run=False, prune=False
            )

        (target_root / "bar").unlink()
        status = sync_agents_skills.sync_layer(
            self.sandbox.catalog, target_root=target_root, dry_run=False, prune=False
        )
        self.assertEqual(status, 0)
        self.assertEqual((target_root / "foo").resolve(), self.sandbox.foo.resolve())
        self.assertEqual((target_root / "bar").resolve(), self.sandbox.bar.resolve())
        self.assertEqual((target_root / "baz").resolve(), self.sandbox.baz.resolve())
        self.assertEqual(outside_note.read_text(encoding="utf-8"), "unrelated")

    def test_duplicate_skill_names_across_plugins_are_rejected(self) -> None:
        write_skill(self.sandbox.beta_root, "foo")
        with self.assertRaises(SystemExit):
            sync_agents_skills.load_repo_skill_catalog(self.sandbox.repo_root)

    def test_skill_directory_without_skill_file_is_rejected(self) -> None:
        malformed = self.sandbox.alpha_root / "skills" / "malformed"
        malformed.mkdir()
        with self.assertRaises(SystemExit):
            sync_agents_skills.load_repo_skill_catalog(self.sandbox.repo_root)


class RepositoryCatalogTests(unittest.TestCase):
    def test_live_repository_enumerates_the_three_skill_plugins(self) -> None:
        catalog = sync_agents_skills.load_repo_skill_catalog()
        plugins = {source.plugin for source in catalog.sources}
        self.assertEqual(plugins, {"watcher", "workflow", "mattpocock-skills"})
        self.assertGreaterEqual(len(catalog.sources), 29)
        for source in catalog.sources:
            self.assertEqual(source.name, source.path.name)
            self.assertTrue((source.path / "SKILL.md").is_file())

    def test_live_projection_exposes_every_present_skill_tree_entry(self) -> None:
        catalog = sync_agents_skills.load_repo_skill_catalog()
        listed = subprocess.run(
            [
                "git", "-C", str(catalog.repo_root), "ls-files", "-z",
                "--cached", "--others", "--exclude-standard", "--", "plugins",
            ],
            check=True,
            capture_output=True,
        ).stdout
        # Validate the working source, including new files and excluding deletions,
        # without changing the user's index or staging state.
        present_paths = tuple(
            catalog.repo_root / raw.decode("utf-8")
            for raw in listed.split(b"\0")
            if raw and b"/skills/" in raw
            and os.path.lexists(catalog.repo_root / raw.decode("utf-8"))
        )
        with tempfile.TemporaryDirectory() as tmp:
            temporary_root = Path(tmp)
            target_root = temporary_root / "agents" / "skills"
            with contextlib.redirect_stdout(io.StringIO()):
                status = sync_agents_skills.sync_layer(
                    catalog,
                    target_root=target_root,
                    dry_run=False,
                    prune=True,
                )
            self.assertEqual(status, 0)

            checked_entries = 0
            for source in catalog.sources:
                projected_root = target_root / source.name
                self.assertTrue(
                    sync_agents_skills.is_projection_link(projected_root),
                    projected_root,
                )
                self.assertEqual(projected_root.resolve(strict=True), source.path)
                source_entries = tuple(
                    path for path in present_paths if path.is_relative_to(source.path)
                )
                self.assertTrue(source_entries, source.path)
                for source_entry in source_entries:
                    relative = source_entry.relative_to(source.path)
                    projected_entry = projected_root / relative
                    resolved_source = source_entry.resolve(strict=True)
                    resolved_source.relative_to(catalog.repo_root)
                    self.assertEqual(projected_entry.resolve(strict=True), resolved_source)
                    checked_entries += 1

        self.assertEqual(checked_entries, len(present_paths))
        self.assertGreater(checked_entries, len(catalog.sources))


if __name__ == "__main__":
    unittest.main()
