import json
import os
import sys

from sqlalchemy import inspect, text


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import create_app
from app.extensions import db


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def get_tables(inspector):
    return sorted(inspector.get_table_names())


def get_single_primary_key(inspector, table):
    columns = inspector.get_pk_constraint(table).get('constrained_columns') or []
    if len(columns) == 1:
        return columns[0]
    return None


def get_simple_foreign_keys(inspector, table):
    for fk in inspector.get_foreign_keys(table):
        child_columns = fk.get('constrained_columns') or []
        parent_columns = fk.get('referred_columns') or []
        parent_table = fk.get('referred_table')

        if len(child_columns) != 1 or len(parent_columns) != 1 or not parent_table:
            continue

        yield {
            'child_col': child_columns[0],
            'parent_table': parent_table,
            'parent_col': parent_columns[0],
        }


def delete_fk_orphans(connection, inspector):
    deleted = []
    tables = get_tables(inspector)

    changed = True
    while changed:
        changed = False
        for table in tables:
            pk_col = get_single_primary_key(inspector, table)
            if not pk_col:
                continue

            for fk in get_simple_foreign_keys(inspector, table):
                child_col = fk['child_col']
                parent_table = fk['parent_table']
                parent_col = fk['parent_col']

                count_query = text(f'''
                    select count(*)
                    from {quote(table)} c
                    where c.{quote(child_col)} is not null
                      and not exists (
                          select 1 from {quote(parent_table)} p
                          where p.{quote(parent_col)} = c.{quote(child_col)}
                      )
                ''')
                count = connection.execute(count_query).scalar_one()
                if not count:
                    continue

                delete_query = text(f'''
                    delete from {quote(table)}
                    where {quote(pk_col)} in (
                        select c.{quote(pk_col)}
                        from {quote(table)} c
                        where c.{quote(child_col)} is not null
                          and not exists (
                              select 1 from {quote(parent_table)} p
                              where p.{quote(parent_col)} = c.{quote(child_col)}
                          )
                    )
                ''')
                connection.execute(delete_query)
                deleted.append({
                    'type': 'foreign_key',
                    'table': table,
                    'column': child_col,
                    'parent_table': parent_table,
                    'count': count,
                })
                changed = True

    return deleted


def delete_logical_orphans(connection):
    deleted = []

    logical_rules = [
        {
            'name': 'hizmet_kaydi_kiralama_bekleyen',
            'count_sql': """
                select count(*)
                from hizmet_kaydi h
                where h.aciklama like 'Kiralama Bekleyen Bakiye%'
                  and h.ozel_id is not null
                  and not exists (select 1 from kiralama k where k.id = h.ozel_id)
            """,
            'delete_sql': """
                delete from hizmet_kaydi
                where aciklama like 'Kiralama Bekleyen Bakiye%'
                  and ozel_id is not null
                  and not exists (select 1 from kiralama k where k.id = hizmet_kaydi.ozel_id)
            """,
        },
        {
            'name': 'hizmet_kaydi_nakliye_taseron',
            'count_sql': """
                select count(*)
                from hizmet_kaydi h
                where h.yon = 'gelen'
                  and h.nakliye_id is null
                  and h.ozel_id is not null
                  and h.aciklama like 'Nakliye Taşeron Gideri:%'
                  and not exists (select 1 from nakliye n where n.id = h.ozel_id)
            """,
            'delete_sql': """
                delete from hizmet_kaydi
                where yon = 'gelen'
                  and nakliye_id is null
                  and ozel_id is not null
                  and aciklama like 'Nakliye Taşeron Gideri:%'
                  and not exists (select 1 from nakliye n where n.id = hizmet_kaydi.ozel_id)
            """,
        },
    ]

    for rule in logical_rules:
        count = connection.execute(text(rule['count_sql'])).scalar_one()
        if not count:
            continue
        connection.execute(text(rule['delete_sql']))
        deleted.append({
            'type': 'logical',
            'rule': rule['name'],
            'count': count,
        })

    return deleted


def find_remaining_fk_issues(connection, inspector):
    issues = []

    for table in get_tables(inspector):
        for fk in get_simple_foreign_keys(inspector, table):
            count_query = text(f'''
                select count(*)
                from {quote(table)} c
                where c.{quote(fk['child_col'])} is not null
                  and not exists (
                      select 1 from {quote(fk['parent_table'])} p
                      where p.{quote(fk['parent_col'])} = c.{quote(fk['child_col'])}
                  )
            ''')
            count = connection.execute(count_query).scalar_one()
            if count:
                issues.append({
                    'table': table,
                    'column': fk['child_col'],
                    'parent_table': fk['parent_table'],
                    'count': count,
                })

    return issues


def main():
    app = create_app()

    with app.app_context():
        inspector = inspect(db.engine)

        with db.engine.begin() as connection:
            fk_deleted = delete_fk_orphans(connection, inspector)
            logical_deleted = delete_logical_orphans(connection)
            remaining_fk = find_remaining_fk_issues(connection, inspector)

        print(json.dumps({
            'database_backend': db.engine.url.get_backend_name(),
            'database_name': db.engine.url.database,
            'deleted': fk_deleted + logical_deleted,
            'remaining_foreign_key_issues': remaining_fk,
        }, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()