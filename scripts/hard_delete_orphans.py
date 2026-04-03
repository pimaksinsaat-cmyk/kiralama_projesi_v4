import json
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[1] / 'app.db'


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def get_tables(cursor):
    rows = cursor.execute(
        "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"
    ).fetchall()
    return [row[0] for row in rows]


def delete_fk_orphans(cursor):
    deleted = []
    tables = get_tables(cursor)

    changed = True
    while changed:
        changed = False
        for table in tables:
            fks = cursor.execute(f"PRAGMA foreign_key_list({quote(table)})").fetchall()
            for fk in fks:
                child_col = fk[3]
                parent_table = fk[2]
                parent_col = fk[4]

                count_query = f'''
                    select count(*)
                    from {quote(table)} c
                    where c.{quote(child_col)} is not null
                      and not exists (
                          select 1 from {quote(parent_table)} p
                          where p.{quote(parent_col)} = c.{quote(child_col)}
                      )
                '''
                count = cursor.execute(count_query).fetchone()[0]
                if not count:
                    continue

                delete_query = f'''
                    delete from {quote(table)}
                    where rowid in (
                        select c.rowid
                        from {quote(table)} c
                        where c.{quote(child_col)} is not null
                          and not exists (
                              select 1 from {quote(parent_table)} p
                              where p.{quote(parent_col)} = c.{quote(child_col)}
                          )
                    )
                '''
                cursor.execute(delete_query)
                deleted.append({
                    'type': 'foreign_key',
                    'table': table,
                    'column': child_col,
                    'parent_table': parent_table,
                    'count': count,
                })
                changed = True

    return deleted


def delete_logical_orphans(cursor):
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
        count = cursor.execute(rule['count_sql']).fetchone()[0]
        if not count:
            continue
        cursor.execute(rule['delete_sql'])
        deleted.append({
            'type': 'logical',
            'rule': rule['name'],
            'count': count,
        })

    return deleted


def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    fk_deleted = delete_fk_orphans(cursor)
    logical_deleted = delete_logical_orphans(cursor)

    conn.commit()
    remaining_fk = cursor.execute('PRAGMA foreign_key_check').fetchall()
    conn.close()

    print(json.dumps({
        'db_path': str(DB_PATH),
        'deleted': fk_deleted + logical_deleted,
        'remaining_foreign_key_issues': remaining_fk,
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()