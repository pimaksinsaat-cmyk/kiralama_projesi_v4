import argparse
import os
import sys
from datetime import datetime, timezone

from flask import Flask

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import Config
from app.extensions import db
from app.cari.models import HizmetKaydi
from app.kiralama.models import KiralamaKalemi
# Mapper registry icin iliskili modellerin de import edilmesi gerekir.
# Aksi halde string-based relationship tanimlari cozulemeyebiliyor.
from app.makinedegisim.models import MakineDegisim  # noqa: F401
from app.filo.models import Ekipman  # noqa: F401


def build_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db_url = os.getenv("DATABASE_URL")
    if db_url:
        app.config["SQLALCHEMY_DATABASE_URI"] = db_url.replace("postgres://", "postgresql://")

    db.init_app(app)
    return app


def is_dis_kiralama_aciklama(text):
    text = (text or "").strip().lower()
    return text.startswith("dış kiralama") or text.startswith("dis kiralama")


def find_duplicate_dis_kiralama_hizmetleri(firma_id=None):
    query = HizmetKaydi.query.filter(
        HizmetKaydi.is_deleted.is_(False),
        HizmetKaydi.ozel_id.isnot(None),
    )
    if firma_id:
        query = query.filter(HizmetKaydi.firma_id == firma_id)

    candidates = query.order_by(HizmetKaydi.id.asc()).all()
    duplicates = []

    for h in candidates:
        if not is_dis_kiralama_aciklama(h.aciklama):
            continue
        kalem = db.session.get(KiralamaKalemi, h.ozel_id)
        # Yeni kayit mantigina gore aktif kaleme bagli dis kiralama faturasi
        # "Tedarik" satiriyla zaten temsil edilir; bu kaydi duplicate sayiyoruz.
        if kalem and kalem.is_active:
            duplicates.append((h, kalem))

    return duplicates


def soft_delete_hizmet(hizmet, reason):
    hizmet.is_deleted = True
    hizmet.is_active = False
    hizmet.deleted_at = datetime.now(timezone.utc)
    hizmet.aciklama = f"{hizmet.aciklama or ''} [AUTO_DUP_CLEAN:{reason}]".strip()
    db.session.add(hizmet)


def main():
    parser = argparse.ArgumentParser(
        description="Legacy cari mükerrer kayıtlarını temizler (Dış Kiralama Fatura vs Tedarik çakışması)."
    )
    parser.add_argument("--apply", action="store_true", help="Değişiklikleri veritabanına uygular.")
    parser.add_argument("--firma-id", type=int, help="Sadece verilen firma için tarama yapar.")
    parser.add_argument("--limit", type=int, default=0, help="Sadece ilk N adayı işle (0=sınırsız).")
    args = parser.parse_args()

    app = build_app()
    with app.app_context():
        duplicates = find_duplicate_dis_kiralama_hizmetleri(firma_id=args.firma_id)
        if args.limit and args.limit > 0:
            duplicates = duplicates[: args.limit]

        print(f"Toplam duplicate adayı: {len(duplicates)}")
        for h, kalem in duplicates:
            print(
                f"[Hizmet #{h.id}] firma={h.firma_id} ozel_id={h.ozel_id} "
                f"fatura_no={h.fatura_no or '-'} tutar={h.tutar} | kalem={kalem.id}"
            )

        if args.apply:
            for h, _ in duplicates:
                soft_delete_hizmet(h, reason="dis_kiralama_tedarik_cakisma")
            db.session.commit()
            print(f"Uygulandı. Soft-delete edilen kayıt: {len(duplicates)}")
        else:
            db.session.rollback()
            print("Dry-run tamamlandı. Değişiklik uygulanmadı.")


if __name__ == "__main__":
    main()
