"""
Audit: kalem id referanslari DB'den gelmeyen / gecersiz kayitlar.

Read-only. Calistirma:
  python scripts/audit_kalem_id_refs.py
"""
import os
import re
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sqlalchemy import text

from app import create_app
from app.cari.models import HizmetKaydi
from app.extensions import db
from app.kiralama.models import KiralamaKalemi
from app.nakliyeler.models import Nakliye


def main():
    app = create_app()
    with app.app_context():
        # Kalem baglantili cari: ozel_id gercek kalem.id olmali (nakliye/kiralama degil)
        q_kalem_cari = db.session.execute(text("""
            SELECT h.id, h.firma_id, h.ozel_id, h.nakliye_id, h.aciklama, h.yon, h.fatura_no
            FROM hizmet_kaydi h
            WHERE h.is_deleted = false
              AND h.ozel_id IS NOT NULL
              AND (
                    h.aciklama LIKE 'Taşeron Nakliye%'
                 OR h.aciklama LIKE 'Dönüş Nakliye%'
                 OR h.aciklama LIKE 'Dış Kiralama%'
                 OR h.aciklama LIKE 'Nakliye Taşeron Gideri:%'
              )
              AND NOT EXISTS (SELECT 1 FROM kiralama_kalemi kk WHERE kk.id = h.ozel_id)
            ORDER BY h.id
        """)).fetchall()

        # Bilerek kiralama.id kullanan bekleyen bakiye (kalem degil) - bilgi amacli
        q_bekleyen_id_cakisma = db.session.execute(text("""
            SELECT h.id, h.ozel_id, h.fatura_no, h.aciklama
            FROM hizmet_kaydi h
            WHERE h.is_deleted = false
              AND h.aciklama LIKE 'Kiralama Bekleyen Bakiye%'
              AND h.ozel_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM nakliye n WHERE n.id = h.ozel_id)
              AND NOT EXISTS (SELECT 1 FROM kiralama k WHERE k.id = h.ozel_id)
            ORDER BY h.id
        """)).fetchall()

        q2 = db.session.execute(text("""
            SELECT h.id, h.firma_id, h.ozel_id, h.nakliye_id, h.aciklama, h.yon
            FROM hizmet_kaydi h
            WHERE h.is_deleted = false
              AND h.ozel_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM kiralama_kalemi kk WHERE kk.id = h.ozel_id)
              AND NOT EXISTS (SELECT 1 FROM nakliye n WHERE n.id = h.ozel_id)
            ORDER BY h.id
        """)).fetchall()

        pat = re.compile(r"#(\d+)\s*$")
        q3 = []
        for n in Nakliye.query.filter(Nakliye.aciklama.like("%#%")).all():
            m = pat.search(n.aciklama or "")
            if not m:
                continue
            kid = int(m.group(1))
            kalem = db.session.get(KiralamaKalemi, kid)
            if not kalem:
                q3.append((n.id, n.kiralama_id, n.aciklama, kid, "KALEM_YOK"))
            elif n.kiralama_id and kalem.kiralama_id != n.kiralama_id:
                q3.append(
                    (n.id, n.kiralama_id, n.aciklama, kid, f"KIRALAMA_UYUMSUZ(kalem.kiralama={kalem.kiralama_id})")
                )

        q4 = db.session.execute(text("""
            SELECT h.id, h.firma_id, h.ozel_id, h.aciklama
            FROM hizmet_kaydi h
            JOIN nakliye n ON n.id = h.ozel_id
            WHERE h.is_deleted = false
              AND h.yon = 'gelen'
              AND h.nakliye_id IS NULL
              AND h.ozel_id IS NOT NULL
              AND h.aciklama LIKE 'Nakliye Taşeron Gideri:%'
              AND NOT EXISTS (SELECT 1 FROM kiralama_kalemi kk WHERE kk.id = h.ozel_id)
            ORDER BY h.id
        """)).fetchall()

        q5 = []
        for h in HizmetKaydi.query.filter(
            HizmetKaydi.is_deleted == False,
            HizmetKaydi.ozel_id.isnot(None),
            HizmetKaydi.aciklama.like("Taşeron Nakliye%"),
        ).all():
            k = db.session.get(KiralamaKalemi, h.ozel_id)
            if not k or not k.kiralama:
                continue
            if h.fatura_no and h.fatura_no != k.kiralama.kiralama_form_no:
                q5.append((h.id, h.ozel_id, h.fatura_no, k.kiralama.kiralama_form_no))

        legacy_gidis = db.session.execute(text("""
            SELECT n.id, n.kiralama_id, n.aciklama
            FROM nakliye n
            JOIN kiralama k ON k.id = n.kiralama_id
            WHERE n.aciklama = ('Gidiş: ' || k.kiralama_form_no)
               OR n.aciklama = ('Dönüş: ' || k.kiralama_form_no)
            ORDER BY n.id
        """)).fetchall()

        print("=== 1) Kalem cari: ozel_id gecerli kalem.id DEGIL (taseron/dis kiralama) ===")
        print(f"Toplam: {len(q_kalem_cari)}")
        for r in q_kalem_cari:
            ac = (r[4] or "")[:80]
            print(f"  hizmet_id={r[0]} firma={r[1]} ozel_id={r[2]} nakliye_id={r[3]} yon={r[5]} aciklama={ac}")

        print("\n=== 1b) Bekleyen bakiye: ozel_id nakliye ile cakisiyor ama kiralama degil ===")
        print(f"Toplam: {len(q_bekleyen_id_cakisma)}")
        for r in q_bekleyen_id_cakisma:
            print(f"  hizmet_id={r[0]} ozel_id={r[1]} fatura={r[2]} aciklama={(r[3] or '')[:70]}")

        print("\n=== 2) HizmetKaydi: ozel_id YETIM (ne kalem ne nakliye) ===")
        print(f"Toplam: {len(q2)}")
        for r in q2:
            print(f"  hizmet_id={r[0]} ozel_id={r[2]} aciklama={(r[4] or '')[:80]}")

        print("\n=== 3) Nakliye aciklama #kalem_id GECERSIZ / UYUMSUZ ===")
        print(f"Toplam: {len(q3)}")
        for r in q3:
            print(f"  nakliye_id={r[0]} kiralama_id={r[1]} ref_kalem={r[3]} durum={r[4]} aciklama={r[2]}")

        print("\n=== 4) Legacy standalone taseron (ozel_id=nakliye, Nakliye Taseron Gideri) ===")
        print(f"Toplam: {len(q4)}")
        for r in q4:
            print(f"  hizmet_id={r[0]} ozel_id(nakliye)={r[2]} aciklama={(r[3] or '')[:80]}")

        print("\n=== 5) Taseron hizmet: fatura_no != kalem kiralama formu ===")
        print(f"Toplam: {len(q5)}")
        for r in q5:
            print(f"  hizmet_id={r[0]} ozel_id(kalem)={r[1]} fatura={r[2]} kalem_form={r[3]}")

        print("\n=== 6) Nakliye: legacy aciklama (form no, #kalem yok) ===")
        print(f"Toplam: {len(legacy_gidis)}")
        for r in legacy_gidis:
            print(f"  nakliye_id={r[0]} kiralama_id={r[1]} aciklama={r[2]}")

        print("\nNo database changes were written.")


if __name__ == "__main__":
    main()
