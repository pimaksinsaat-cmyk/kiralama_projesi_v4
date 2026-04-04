import argparse
import os
import sys
from decimal import Decimal

from flask import Flask
from sqlalchemy import or_

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import Config
from app.extensions import db

# Model importlari metadata ve sorgular icin gerekli.
from app.cari.models import HizmetKaydi
from app.firmalar.models import Firma  # noqa: F401
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.makinedegisim.models import MakineDegisim
from app.nakliyeler.models import Nakliye
from app.filo.models import Ekipman  # noqa: F401
from app.araclar.models import Arac  # noqa: F401
from app.subeler.models import Sube  # noqa: F401
from app.services.kiralama_services import KiralamaService


def build_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db_url = os.getenv('DATABASE_URL')
    if db_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url.replace('postgres://', 'postgresql://')

    db.init_app(app)
    return app


def make_external_machine_name(kalem):
    if kalem.ekipman and kalem.ekipman.kod:
        return kalem.ekipman.kod
    return f"{kalem.harici_ekipman_marka or ''} {kalem.harici_ekipman_model or ''}".strip()


def find_swap_nakliye(log):
    if log.swap_nakliye_id:
        nakliye = db.session.get(Nakliye, log.swap_nakliye_id)
        if nakliye:
            return nakliye

    return Nakliye.query.filter(
        Nakliye.kiralama_id == log.kiralama_id,
        Nakliye.aciklama.like(f"Makine Değişim (Swap) Operasyonu [Ref:{log.yeni_kalem_id}]%")
    ).order_by(Nakliye.id.desc()).first()


def find_swap_taseron_hizmeti(log, nakliye):
    if log.swap_taseron_hizmet_id:
        hizmet = db.session.get(HizmetKaydi, log.swap_taseron_hizmet_id)
        if hizmet:
            return hizmet

    if not nakliye:
        return None

    return HizmetKaydi.query.filter(
        HizmetKaydi.yon == 'gelen',
        or_(
            HizmetKaydi.nakliye_id == nakliye.id,
            HizmetKaydi.ozel_id == nakliye.id,
        )
    ).order_by(HizmetKaydi.id.desc()).first()


def find_swap_kira_hizmeti(log):
    if log.swap_kira_hizmet_id:
        hizmet = db.session.get(HizmetKaydi, log.swap_kira_hizmet_id)
        if hizmet:
            return hizmet

    kalem = log.yeni_satir
    if not kalem or not kalem.is_dis_tedarik_ekipman or not kalem.harici_ekipman_tedarikci_id:
        return None

    musteri_adi = kalem.kiralama.firma_musteri.firma_adi if kalem.kiralama and kalem.kiralama.firma_musteri else 'Bilinmeyen'
    aciklama = f"{musteri_adi} projesi {make_external_machine_name(kalem)} makinesi kira bedeli"

    return HizmetKaydi.query.filter(
        HizmetKaydi.firma_id == kalem.harici_ekipman_tedarikci_id,
        HizmetKaydi.yon == 'gelen',
        HizmetKaydi.fatura_no == (kalem.kiralama.kiralama_form_no if kalem.kiralama else None),
        or_(
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.ozel_id == log.kiralama_id,
            HizmetKaydi.aciklama == aciklama,
        )
    ).order_by(HizmetKaydi.id.desc()).first()


def ensure_swap_kira_hizmeti(log, dry_run):
    kalem = log.yeni_satir
    if not kalem or not kalem.is_dis_tedarik_ekipman or not kalem.harici_ekipman_tedarikci_id:
        return None, []

    notes = []
    musteri_adi = kalem.kiralama.firma_musteri.firma_adi if kalem.kiralama and kalem.kiralama.firma_musteri else 'Bilinmeyen'
    aciklama = f"{musteri_adi} projesi {make_external_machine_name(kalem)} makinesi kira bedeli"
    beklenen_tutar = Decimal(kalem.kiralama_alis_fiyat or 0)

    hizmet = find_swap_kira_hizmeti(log)
    if hizmet is None and beklenen_tutar > 0:
        hizmet = HizmetKaydi(
            firma_id=kalem.harici_ekipman_tedarikci_id,
            tarih=log.tarih.date(),
            tutar=beklenen_tutar,
            yon='gelen',
            aciklama=aciklama,
            fatura_no=kalem.kiralama.kiralama_form_no if kalem.kiralama else None,
            ozel_id=kalem.id,
        )
        db.session.add(hizmet)
        db.session.flush()
        notes.append('Eksik dış tedarik kira kaydı oluşturuldu')
        return hizmet, notes

    if hizmet is None:
        return None, notes

    if hizmet.ozel_id != kalem.id:
        notes.append(f'ozel_id {hizmet.ozel_id} -> {kalem.id}')
        hizmet.ozel_id = kalem.id
    if Decimal(hizmet.tutar or 0) != beklenen_tutar:
        notes.append(f'tutar {hizmet.tutar} -> {beklenen_tutar}')
        hizmet.tutar = beklenen_tutar
    if hizmet.aciklama != aciklama:
        notes.append('açıklama normalize edildi')
        hizmet.aciklama = aciklama
    if hizmet.tarih != log.tarih.date():
        notes.append('tarih normalize edildi')
        hizmet.tarih = log.tarih.date()
    if hizmet.fatura_no != (kalem.kiralama.kiralama_form_no if kalem.kiralama else None):
        hizmet.fatura_no = kalem.kiralama.kiralama_form_no if kalem.kiralama else None
        notes.append('form no normalize edildi')

    return hizmet, notes


def reconcile_swap_log(log):
    notes = []
    nakliye = find_swap_nakliye(log)
    if nakliye and log.swap_nakliye_id != nakliye.id:
        log.swap_nakliye_id = nakliye.id
        notes.append(f'swap_nakliye_id -> {nakliye.id}')

    taseron_hizmeti = find_swap_taseron_hizmeti(log, nakliye)
    if taseron_hizmeti:
        if log.swap_taseron_hizmet_id != taseron_hizmeti.id:
            log.swap_taseron_hizmet_id = taseron_hizmeti.id
            notes.append(f'swap_taseron_hizmet_id -> {taseron_hizmeti.id}')
        if nakliye and taseron_hizmeti.ozel_id != nakliye.id:
            taseron_hizmeti.ozel_id = nakliye.id
            notes.append('taşeron hizmet ozel_id düzeltildi')
        if nakliye and taseron_hizmeti.nakliye_id != nakliye.id:
            taseron_hizmeti.nakliye_id = nakliye.id
            notes.append('taşeron hizmet nakliye_id düzeltildi')

    kira_hizmeti, kira_notes = ensure_swap_kira_hizmeti(log, dry_run=False)
    notes.extend(kira_notes)
    if kira_hizmeti and log.swap_kira_hizmet_id != kira_hizmeti.id:
        log.swap_kira_hizmet_id = kira_hizmeti.id
        notes.append(f'swap_kira_hizmet_id -> {kira_hizmeti.id}')

    KiralamaService.guncelle_cari_toplam(log.kiralama_id, auto_commit=False)
    return notes


def main():
    parser = argparse.ArgumentParser(description='Swap kaynaklı hatalı finans kayıtlarını tarar ve düzeltir.')
    parser.add_argument('--apply', action='store_true', help='Değişiklikleri veritabanına uygular. Verilmezse dry-run çalışır.')
    parser.add_argument('--kiralama-id', type=int, help='Sadece belirtilen kiralamayı tara.')
    args = parser.parse_args()

    app = build_app()
    with app.app_context():
        query = MakineDegisim.query.order_by(MakineDegisim.id.asc())
        if args.kiralama_id:
            query = query.filter(MakineDegisim.kiralama_id == args.kiralama_id)

        scanned = 0
        changed = 0

        for log in query.all():
            scanned += 1
            notes = reconcile_swap_log(log)
            if notes:
                changed += 1
                print(f"[SWAP #{log.id}] kiralama={log.kiralama_id} yeni_kalem={log.yeni_kalem_id}")
                for note in notes:
                    print(f"  - {note}")

        if args.apply:
            db.session.commit()
            print(f"Tamamlandı. Taranan swap: {scanned}, düzeltme uygulanan: {changed}")
        else:
            db.session.rollback()
            print(f"Dry-run tamamlandı. Taranan swap: {scanned}, düzeltme adayı: {changed}")


if __name__ == '__main__':
    main()