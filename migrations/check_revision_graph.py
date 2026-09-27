"""Alembic revizyon dosyalarinin kimlik ve baglanti grafigini dogrular."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


class MigrationGraphError(Exception):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def _literal_assignment(tree, name):
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                try:
                    return ast.literal_eval(node.value)
                except (ValueError, SyntaxError) as exc:
                    raise MigrationGraphError(
                        [f"{name} degeri sabit bir ifade olmali."]
                    ) from exc
    return None


def _revision_ids(value, field_name, path):
    if value is None:
        return ()
    if isinstance(value, str):
        if not value:
            raise MigrationGraphError([f"{path.name} icinde {field_name} bos."])
        return (value,)
    if isinstance(value, (tuple, list)):
        if not value or any(not isinstance(item, str) or not item for item in value):
            raise MigrationGraphError(
                [f"{path.name} icinde {field_name} gecersiz: {value!r}"]
            )
        return tuple(value)
    raise MigrationGraphError(
        [f"{path.name} icinde {field_name} metin veya liste olmali."]
    )


def load_revisions(versions_dir):
    versions_path = Path(versions_dir)
    problems = []
    revisions = {}

    for path in sorted(versions_path.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _literal_assignment(tree, "revision")
        if not isinstance(revision, str) or not revision:
            problems.append(f"{path.name} icinde revision tanimi yok.")
            continue
        if not path.name.startswith(f"{revision}_"):
            problems.append(
                f"{path.name} dosya adi {revision} revizyonu ile baslamiyor."
            )
        if revision in revisions:
            problems.append(
                "Revizyon "
                f"{revision} birden fazla dosyada tanimli: "
                f"{revisions[revision]['path'].name}, {path.name}."
            )
            continue
        try:
            parents = _revision_ids(
                _literal_assignment(tree, "down_revision"),
                "down_revision",
                path,
            )
            dependencies = _revision_ids(
                _literal_assignment(tree, "depends_on"),
                "depends_on",
                path,
            )
        except MigrationGraphError as exc:
            problems.extend(exc.problems)
            continue
        revisions[revision] = {
            "path": path,
            "parents": parents,
            "dependencies": dependencies,
        }

    if problems:
        raise MigrationGraphError(problems)
    return revisions


def validate_revision_graph(versions_dir):
    revisions = load_revisions(versions_dir)
    problems = []

    for revision, info in revisions.items():
        for parent in info["parents"] + info["dependencies"]:
            if parent not in revisions:
                problems.append(
                    f"{info['path'].name} icindeki {parent} revizyonu bulunamadi."
                )

    if problems:
        raise MigrationGraphError(problems)

    visiting = set()
    visited = set()

    def walk(revision, stack):
        if revision in visiting:
            start = stack.index(revision)
            cycle = stack[start:] + [revision]
            problems.append("Revizyon grafiginde dongu var: " + " -> ".join(cycle) + ".")
            return
        if revision in visited:
            return
        visiting.add(revision)
        stack.append(revision)
        for parent in revisions[revision]["parents"] + revisions[revision]["dependencies"]:
            walk(parent, stack)
        stack.pop()
        visiting.remove(revision)
        visited.add(revision)

    for revision in revisions:
        walk(revision, [])

    if problems:
        raise MigrationGraphError(problems)

    children = {
        parent
        for info in revisions.values()
        for parent in info["parents"]
    }
    heads = [revision for revision in revisions if revision not in children]
    if len(heads) != 1:
        listed = ", ".join(
            f"{revision} ({revisions[revision]['path'].name})" for revision in heads
        )
        raise MigrationGraphError(
            [
                "Migration grafiginde tek head olmali. "
                f"Bulunan head sayisi: {len(heads)}. {listed}."
            ]
        )
    return heads[0]


def main():
    versions_dir = Path(__file__).resolve().parent / "versions"
    try:
        head = validate_revision_graph(versions_dir)
    except MigrationGraphError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(head)
    return 0


if __name__ == "__main__":
    sys.exit(main())
