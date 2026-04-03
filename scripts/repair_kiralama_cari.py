from app import create_app
from app.kiralama.models import Kiralama
from app.cari.models import HizmetKaydi
from app.services.kiralama_services import KiralamaService
from app.extensions import db
from datetime import datetime, timezone


def main():
    app = create_app()
    with app.app_context():
        orphan_rows = HizmetKaydi.query.filter(
            HizmetKaydi.is_deleted == False,
            HizmetKaydi.yon == 'giden',
            HizmetKaydi.aciklama.like('Kiralama Bekleyen Bakiye%')
        ).all()

        cleaned = 0
        for row in orphan_rows:
            if row.ozel_id and not db.session.get(Kiralama, row.ozel_id):
                row.is_deleted = True
                row.is_active = False
                row.deleted_at = datetime.now(timezone.utc)
                db.session.add(row)
                cleaned += 1

        kiralamalar = Kiralama.query.order_by(Kiralama.id.asc()).all()
        total = len(kiralamalar)
        ok = 0
        fail = 0

        for kiralama in kiralamalar:
            try:
                KiralamaService.guncelle_cari_toplam(kiralama.id, auto_commit=False)
                ok += 1
            except Exception as exc:
                db.session.rollback()
                fail += 1
                print(f"[HATA] Kiralama ID={kiralama.id} Form={kiralama.kiralama_form_no}: {exc}")

        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            print(f"[KRITIK] Toplu commit hatasi: {exc}")
            return

        print(f"Toplam kiralama: {total}")
        print(f"Basarili senkron: {ok}")
        print(f"Hatali kayit: {fail}")
        print(f"Temizlenen yetim cari kaydi: {cleaned}")


if __name__ == "__main__":
    main()
