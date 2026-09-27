from pathlib import Path
import tempfile

import pytest

from migrations.check_revision_graph import MigrationGraphError, validate_revision_graph


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = PROJECT_ROOT / "migrations" / "versions"


def _temporary_versions():
    cache_dir = PROJECT_ROOT / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=cache_dir)


def _write_revision(directory, name, revision, down_revision):
    directory.joinpath(name).write_text(
        f"revision = {revision!r}\ndown_revision = {down_revision!r}\n",
        encoding="utf-8",
    )


def test_repository_migration_graph_has_unique_revisions():
    assert validate_revision_graph(VERSIONS_DIR) == "e8b2c4d6f0a1"


def test_duplicate_revision_id_is_rejected():
    with _temporary_versions() as raw_dir:
        directory = Path(raw_dir)
        _write_revision(directory, "aaa111_ilk.py", "aaa111", None)
        _write_revision(directory, "aaa111_ikinci.py", "aaa111", None)

        with pytest.raises(MigrationGraphError, match="aaa111"):
            validate_revision_graph(directory)


def test_revision_cycle_is_rejected():
    with _temporary_versions() as raw_dir:
        directory = Path(raw_dir)
        _write_revision(directory, "aaa111_ilk.py", "aaa111", "bbb222")
        _write_revision(directory, "bbb222_ikinci.py", "bbb222", "aaa111")

        with pytest.raises(MigrationGraphError, match="dongu"):
            validate_revision_graph(directory)
