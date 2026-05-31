"""
Audit DB/code variable consistency.

Read-only. It compares the live PostgreSQL schema with SQLAlchemy metadata and
reports suspicious Jinja/model field usages plus request/form field names.

Usage:
  python scripts/audit_db_code_variable_consistency.py
"""
import ast
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import RelationshipProperty
import inspect as py_inspect


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402


logging.getLogger('apscheduler').setLevel(logging.WARNING)


TECHNICAL_TABLE_NAMES = {'alembic_version'}
TECHNICAL_TABLE_PREFIXES = ('_backup_',)

TEMPLATE_DIR = Path(ROOT_DIR) / 'app' / 'templates'
CODE_SCAN_DIRS = [Path(ROOT_DIR) / 'app', Path(ROOT_DIR) / 'scripts']

JINJA_LOCAL_ROOTS = {
    'bootstrap',
    'category',
    'csrf_token',
    'current_user',
    'dict',
    'error',
    'errors',
    'field',
    'field_name',
    'form',
    'get_flashed_messages',
    'loop',
    'message',
    'modal',
    'range',
    'request',
    'safe_next_url',
    'self',
    'session',
    'super',
    'url_for',
}

DICT_LIKE_TEMPLATE_ROOTS = {
    'activeData',
    'dashboard',
    'data',
    'detay',
    'json',
    'makine_data',
    'pagination',
    'row',
    'satir',
    'stats',
    'tot_iscilik',
    'tot_malzeme',
    'tot_toplam',
}

ROUTE_ENRICHED_ATTRS = {
    'Arac': {
        'muayene_durum',
        'muayene_kalan_gun',
        'sigorta_durum',
        'sigorta_kalan_gun',
    },
    'BakimKaydi': {
        'malzeme_maliyeti',
        'toplam_servis_maliyeti',
    },
    'Ekipman': {
        'aktif_bakim_kaydi',
        'aktif_kiralama_bilgisi',
        'aktif_kiralama_var',
        'iade_iptal_kalem_id',
        'son_musteri_adi',
    },
    'Personel': {
        'current_izin',
        'is_ayrildi',
        'is_calisiyor',
        'is_izinli',
    },
    'StokKarti': {
        'son_birim_fiyat',
        'stok_degeri',
    },
}

JINJA_METHOD_OR_FILTER_ATTRS = {
    'all',
    'append',
    'classList',
    'contains',
    'data',
    'dataset',
    'errors',
    'focus',
    'format',
    'get',
    'getElementById',
    'hide',
    'items',
    'iter_pages',
    'join',
    'keys',
    'length',
    'lower',
    'querySelector',
    'querySelectorAll',
    'replace',
    'show',
    'split',
    'strftime',
    'strip',
    'submit',
    'toString',
    'trim',
    'upper',
    'value',
    'values',
}

ROOT_MODEL_ALIASES = {
    'arac': 'Arac',
    'bakim': 'AracBakim',
    'ekipman': 'Ekipman',
    'firma': 'Firma',
    'hakedis': 'Hakedis',
    'h': 'Hakedis',
    'hizmet': 'HizmetKaydi',
    'kalem': 'KiralamaKalemi',
    'kart': 'StokKarti',
    'kayit': 'BakimKaydi',
    'kiralama': 'Kiralama',
    'kasa': 'Kasa',
    'log': 'OperationLog',
    'nakliye': 'Nakliye',
    'odeme': 'Odeme',
    'parca': 'KullanilanParca',
    'personel': 'Personel',
    'stok_karti': 'StokKarti',
    'sube': 'Sube',
    'teklif': 'Teklif',
}


def _is_technical_table(table_name):
    return table_name in TECHNICAL_TABLE_NAMES or table_name.startswith(TECHNICAL_TABLE_PREFIXES)


def _fetch_db_columns():
    rows = db.session.execute(text("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """)).fetchall()
    result = defaultdict(dict)
    for table_name, column_name, data_type in rows:
        result[table_name][column_name] = data_type
    return dict(result)


def _metadata_columns():
    result = {}
    for table in db.metadata.sorted_tables:
        result[table.name] = {column.name: str(column.type) for column in table.columns}
    return result


def _model_maps():
    classes_by_name = {}
    classes_by_table = {}
    valid_attrs_by_class = {}
    relationships_by_class = {}

    for mapper in db.Model.registry.mappers:
        cls = mapper.class_
        classes_by_name[cls.__name__] = cls
        if getattr(cls, '__tablename__', None):
            classes_by_table[cls.__tablename__] = cls

        valid_attrs = set()
        relationships = {}
        for prop in mapper.attrs:
            valid_attrs.add(prop.key)
            if isinstance(prop, RelationshipProperty):
                relationships[prop.key] = prop.mapper.class_

        for name, value in py_inspect.getmembers(cls):
            if name.startswith('_'):
                continue
            if isinstance(value, property) or callable(value):
                valid_attrs.add(name)

        valid_attrs.update(ROUTE_ENRICHED_ATTRS.get(cls.__name__, set()))

        valid_attrs_by_class[cls] = valid_attrs
        relationships_by_class[cls] = relationships

    return classes_by_name, classes_by_table, valid_attrs_by_class, relationships_by_class


def _root_model_for(root, classes_by_name, classes_by_table):
    if root in ROOT_MODEL_ALIASES:
        return classes_by_name.get(ROOT_MODEL_ALIASES[root])
    if root in classes_by_table:
        return classes_by_table[root]
    camel = ''.join(part.capitalize() for part in root.split('_'))
    return classes_by_name.get(camel)


def _target_for_relation_path(root, attrs, classes_by_name, classes_by_table, relationships_by_class):
    cls = _root_model_for(root, classes_by_name, classes_by_table)
    if not cls:
        return None
    current_cls = cls
    for attr in attrs:
        rel_target = relationships_by_class.get(current_cls, {}).get(attr)
        if rel_target is None:
            return None
        current_cls = rel_target
    return current_cls


def _line_for_offset(text_value, offset):
    return text_value.count('\n', 0, offset) + 1


def _extract_jinja_expressions(template_text):
    patterns = [
        re.compile(r"{{(.*?)}}", re.DOTALL),
        re.compile(r"{%(.*?)%}", re.DOTALL),
    ]
    for pattern in patterns:
        for match in pattern.finditer(template_text):
            yield match.group(1), match.start(1)


def _strip_string_literals(value):
    return re.sub(r"(['\"])(?:\\.|(?!\1).)*\1", "''", value)


def _template_loop_aliases(content, classes_by_name, classes_by_table, relationships_by_class):
    aliases = {}
    loop_pattern = re.compile(
        r"{%\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+"
        r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*%}"
    )
    collection_aliases = {
        'araclar': 'Arac',
        'bakim_kayitlari': 'AracBakim',
        'diger_kasalar': 'Kasa',
        'ekipmanlar': 'Ekipman',
        'hakedisler': 'Hakedis',
        'hareketler': None,
        'kayitlar': 'BakimKaydi',
        'kiralamalar': 'Kiralama',
        'nakliyeler': 'Nakliye',
        'personeller': 'Personel',
        'sabit_giderler': 'SubeSabitGiderDonemi',
        'stok_kartlari': 'StokKarti',
        'teklifler': 'Teklif',
    }
    for match in loop_pattern.finditer(content):
        alias = match.group(1)
        iterable = match.group(2)
        parts = iterable.split('.')
        if len(parts) > 1:
            target = _target_for_relation_path(
                parts[0],
                parts[1:],
                classes_by_name,
                classes_by_table,
                relationships_by_class,
            )
            if target:
                aliases[alias] = target
                continue

        class_name = collection_aliases.get(iterable)
        if class_name:
            target = classes_by_name.get(class_name)
            if target:
                aliases[alias] = target
    return aliases


def _scan_template_fields(classes_by_name, classes_by_table, valid_attrs_by_class, relationships_by_class):
    suspect = []
    info = []
    chain_pattern = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")

    for path in sorted(TEMPLATE_DIR.rglob('*.html')):
        rel_path = path.relative_to(ROOT_DIR)
        content = path.read_text(encoding='utf-8', errors='ignore')
        loop_aliases = _template_loop_aliases(content, classes_by_name, classes_by_table, relationships_by_class)
        for expression, offset in _extract_jinja_expressions(content):
            expression = _strip_string_literals(expression)
            line_no = _line_for_offset(content, offset)
            for match in chain_pattern.finditer(expression):
                chain = match.group(0)
                parts = chain.split('.')
                root = parts[0]
                first_attr = parts[1]

                if root in JINJA_LOCAL_ROOTS or root in DICT_LIKE_TEMPLATE_ROOTS:
                    info.append((str(rel_path), line_no, chain, 'template-local/dict-like root'))
                    continue
                if first_attr in JINJA_METHOD_OR_FILTER_ATTRS:
                    info.append((str(rel_path), line_no, chain, 'method/filter-like attr'))
                    continue

                cls = loop_aliases.get(root) or _root_model_for(root, classes_by_name, classes_by_table)
                if not cls:
                    info.append((str(rel_path), line_no, chain, 'unknown root'))
                    continue

                current_cls = cls
                traversed = [root]
                for attr in parts[1:]:
                    if attr in JINJA_METHOD_OR_FILTER_ATTRS:
                        break
                    valid_attrs = valid_attrs_by_class.get(current_cls, set())
                    if attr not in valid_attrs:
                        suspect.append(
                            (
                                str(rel_path),
                                line_no,
                                '.'.join(traversed + [attr]),
                                current_cls.__name__,
                                attr,
                            )
                        )
                        break
                    traversed.append(attr)
                    rel_target = relationships_by_class.get(current_cls, {}).get(attr)
                    if rel_target is None:
                        break
                    current_cls = rel_target

    return sorted(set(suspect)), sorted(set(info))


class RequestFieldVisitor(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.rows = []

    def visit_Call(self, node):
        source = _call_source_name(node.func)
        if source in {'request.form.get', 'request.args.get'} and node.args:
            field = _literal_string(node.args[0])
            if field:
                self.rows.append((str(self.path), node.lineno, source, field))
        self.generic_visit(node)

    def visit_Subscript(self, node):
        container = _name_of(node.value)
        if container in {'payload', 'data', 'k_data', 'firma_data'}:
            field = _literal_string(node.slice)
            if field:
                self.rows.append((str(self.path), node.lineno, f'{container}[]', field))
        self.generic_visit(node)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == 'updatable_fields':
                for field in _string_literals_in_node(node.value):
                    self.rows.append((str(self.path), node.lineno, 'updatable_fields', field))
            elif isinstance(target, ast.Attribute) and target.attr == 'updatable_fields':
                for field in _string_literals_in_node(node.value):
                    self.rows.append((str(self.path), node.lineno, 'updatable_fields', field))
        self.generic_visit(node)


def _call_source_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return '.'.join(reversed(parts))


def _name_of(node):
    if isinstance(node, ast.Name):
        return node.id
    return None


def _literal_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Index):  # pragma: no cover - old Python AST compatibility
        return _literal_string(node.value)
    return None


def _string_literals_in_node(node):
    values = []
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        for elt in node.elts:
            literal = _literal_string(elt)
            if literal:
                values.append(literal)
    return values


def _scan_form_or_request_fields(model_columns):
    known_columns = set()
    for columns in model_columns.values():
        known_columns.update(columns)

    rows = []
    for base_dir in CODE_SCAN_DIRS:
        for path in sorted(base_dir.rglob('*.py')):
            rel_path = path.relative_to(ROOT_DIR)
            try:
                tree = ast.parse(path.read_text(encoding='utf-8', errors='ignore'))
            except SyntaxError as exc:
                rows.append((str(rel_path), exc.lineno or 0, 'syntax-error', str(exc)))
                continue
            visitor = RequestFieldVisitor(rel_path)
            visitor.visit(tree)
            rows.extend(visitor.rows)

    result = []
    for rel_path, line_no, source, field in rows:
        status = 'matches-model-column' if field in known_columns else 'request-only-or-dynamic'
        result.append((rel_path, line_no, source, field, status))
    return sorted(set(result))


def _print_section(title, rows, formatter=str, max_rows=None):
    print(f"\n=== {title} ===")
    print(f"Toplam: {len(rows)}")
    rows_to_print = rows[:max_rows] if max_rows is not None else rows
    for row in rows_to_print:
        print(formatter(row))
    if max_rows is not None and len(rows) > max_rows:
        print(f"  ... {len(rows) - max_rows} more rows hidden; edit max_rows/full output if needed.")


def main():
    app = create_app()
    with app.app_context():
        db_columns = _fetch_db_columns()
        model_columns = _metadata_columns()
        classes_by_name, classes_by_table, valid_attrs_by_class, relationships_by_class = _model_maps()

        ignored_tables = {
            table_name: columns
            for table_name, columns in db_columns.items()
            if _is_technical_table(table_name)
        }

        comparable_db_columns = {
            table_name: columns
            for table_name, columns in db_columns.items()
            if not _is_technical_table(table_name)
        }

        db_only = []
        for table_name, columns in comparable_db_columns.items():
            if table_name not in model_columns:
                db_only.append((table_name, '*', f'table-only columns={len(columns)}'))
                continue
            for column_name, data_type in columns.items():
                if column_name not in model_columns[table_name]:
                    db_only.append((table_name, column_name, data_type))

        model_only = []
        for table_name, columns in model_columns.items():
            if table_name not in comparable_db_columns:
                model_only.append((table_name, '*', f'table-only columns={len(columns)}'))
                continue
            for column_name, data_type in columns.items():
                if column_name not in comparable_db_columns[table_name]:
                    model_only.append((table_name, column_name, data_type))

        template_suspect, template_info = _scan_template_fields(
            classes_by_name,
            classes_by_table,
            valid_attrs_by_class,
            relationships_by_class,
        )
        request_fields = _scan_form_or_request_fields(model_columns)

        _print_section(
            'DB_ONLY',
            sorted(db_only),
            lambda r: f"  {r[0]}.{r[1]} ({r[2]})",
        )
        _print_section(
            'MODEL_ONLY',
            sorted(model_only),
            lambda r: f"  {r[0]}.{r[1]} ({r[2]})",
        )
        _print_section(
            'TEMPLATE_SUSPECT_FIELDS',
            template_suspect,
            lambda r: f"  {r[0]}:{r[1]} {r[2]} -> {r[3]}.{r[4]} not found",
        )
        _print_section(
            'FORM_OR_REQUEST_FIELDS_INFO',
            request_fields,
            lambda r: f"  {r[0]}:{r[1]} {r[2]}('{r[3]}') [{r[4]}]",
        )
        _print_section(
            'IGNORED_TECHNICAL_TABLES',
            sorted((name, len(columns)) for name, columns in ignored_tables.items()),
            lambda r: f"  {r[0]} columns={r[1]}",
        )
        _print_section(
            'TEMPLATE_DICT_OR_UNKNOWN_INFO',
            template_info,
            lambda r: f"  {r[0]}:{r[1]} {r[2]} [{r[3]}]",
            max_rows=120,
        )

        print("\nNo database changes were written.")


if __name__ == "__main__":
    main()
