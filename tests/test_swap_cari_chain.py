from datetime import date, timedelta
from decimal import Decimal
import uuid

from app.extensions import db
from app.cari.models import HizmetKaydi
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.services.firma_services import FirmaService
from app.services.cari_services import CariRaporService
from app.services.kiralama_services import KiralamaService


def _swap_contract():
    today = date.today()
    firma = Firma(
        firma_adi=f"Swap Cari Musteri {uuid.uuid4().hex[:8]}",
        yetkili_adi="Yetkili",
        iletisim_bilgileri="Adres",
        vergi_dairesi="Test VD",
        vergi_no=f"V{uuid.uuid4().hex[:10].upper()}",
        is_musteri=True,
        is_tedarikci=False,
    )
    db.session.add(firma)
    db.session.flush()

    kiralama = Kiralama(
        kiralama_form_no=f"PF-SWAP-CARI-{uuid.uuid4().hex[:8]}",
        firma_musteri_id=firma.id,
        kdv_orani=20,
    )
    db.session.add(kiralama)
    db.session.flush()

    eski = KiralamaKalemi(
        kiralama_id=kiralama.id,
        kiralama_baslangici=today - timedelta(days=11),
        kiralama_bitis=today - timedelta(days=1),
        kiralama_brm_fiyat=Decimal("100.00"),
        sonlandirildi=True,
        is_active=False,
    )
    yeni = KiralamaKalemi(
        kiralama_id=kiralama.id,
        parent_id=None,
        kiralama_baslangici=today,
        kiralama_bitis=today + timedelta(days=10),
        kiralama_brm_fiyat=Decimal("100.00"),
        sonlandirildi=False,
        is_active=True,
    )
    db.session.add_all([eski, yeni])
    db.session.commit()
    return firma, kiralama, eski, yeni


def test_swap_chain_keeps_old_machine_in_customer_cari(app):
    with app.app_context():
        firma, kiralama, eski, yeni = _swap_contract()

        rows = FirmaService.build_cari_rows(firma, date.today())
        rental_rows = {
            row['id']: row for row in rows
            if row.get('islem_turu') == 'kiralama'
        }

        assert set(rental_rows) == {eski.id, yeni.id}
        assert rental_rows[eski.id]['gun_sayisi'] == 11
        assert rental_rows[yeni.id]['gun_sayisi'] == 1
        assert sum(row['toplam'] for row in rental_rows.values()) == 1440.0


def test_daily_cari_sync_updates_accrual_and_firma_cache(app):
    with app.app_context():
        firma, kiralama, eski, yeni = _swap_contract()
        firma.cari_borc_kdvli = Decimal('0')
        firma.cari_son_guncelleme = None
        db.session.commit()

        result = KiralamaService.sync_all_cari_totals()
        db.session.refresh(firma)

        assert result['kiralama_sayisi'] == 1
        assert result['firma_sayisi'] == 1
        assert firma.cari_borc_kdvli == Decimal('1440.00')
        assert firma.cari_bakiye_kdvli == Decimal('1440.00')
        assert firma.cari_son_guncelleme is not None


def test_supplier_swap_accrual_dedup_preserves_manual_rows(app):
    with app.app_context():
        musteri, kiralama, _, _ = _swap_contract()
        tedarikci = Firma(
            firma_adi=f"Swap Tedarikci {uuid.uuid4().hex[:8]}",
            yetkili_adi="Yetkili",
            iletisim_bilgileri="Adres",
            vergi_dairesi="Test VD",
            vergi_no=f"T{uuid.uuid4().hex[:10].upper()}",
            is_musteri=False,
            is_tedarikci=True,
        )
        db.session.add(tedarikci)
        db.session.flush()

        kalem = KiralamaKalemi.query.filter_by(kiralama_id=kiralama.id).first()
        kalem.is_active = True
        kalem.is_dis_tedarik_ekipman = True
        kalem.harici_ekipman_tedarikci_id = tedarikci.id
        kalem.kiralama_alis_fiyat = Decimal('50.00')
        db.session.add(kalem)
        db.session.add_all([
            HizmetKaydi(
                firma_id=tedarikci.id,
                ozel_id=kalem.id,
                fatura_no=kiralama.kiralama_form_no,
                tarih=date.today(),
                islem_tarihi=date.today(),
                tutar=Decimal('550.00'),
                yon='gelen',
                aciklama='Eski swap kira bedeli',
                kaynak='swap_dis_kiralama',
            ),
            HizmetKaydi(
                firma_id=tedarikci.id,
                ozel_id=kalem.id,
                fatura_no=kiralama.kiralama_form_no,
                tarih=date.today(),
                islem_tarihi=date.today(),
                tutar=Decimal('550.00'),
                yon='gelen',
                aciklama='Dış Kiralama: Makine',
            ),
            HizmetKaydi(
                firma_id=tedarikci.id,
                tarih=date.today(),
                islem_tarihi=date.today(),
                tutar=Decimal('25.00'),
                yon='gelen',
                aciklama='Manuel tedarikçi faturası',
                kaynak='manual',
            ),
        ])
        db.session.commit()

        KiralamaService.guncelle_tedarikci_cari_toplam(
            tedarikci.id,
            auto_commit=False,
            sync_firma_cache=False,
        )
        KiralamaService.sync_firma_caches({tedarikci.id}, auto_commit=False)
        db.session.commit()

        aktif_sistem = HizmetKaydi.query.filter(
            HizmetKaydi.firma_id == tedarikci.id,
            HizmetKaydi.ozel_id == kalem.id,
            HizmetKaydi.kaynak == 'dis_kiralama_tahakkuk',
            HizmetKaydi.is_deleted == False,
        ).all()
        assert len(aktif_sistem) == 1
        assert HizmetKaydi.query.filter_by(
            firma_id=tedarikci.id,
            kaynak='swap_dis_kiralama',
        ).first().is_deleted is True
        assert HizmetKaydi.query.filter_by(
            firma_id=tedarikci.id,
            kaynak='manual',
        ).first().is_deleted is False
        assert tedarikci.bakiye == tedarikci.bakiye_ozeti['net_bakiye']
        expected_kdvli = sum(
            Decimal(str(row.get('toplam') or 0))
            for row in FirmaService.build_cari_rows(tedarikci, date.today())
        )
        assert tedarikci.cari_bakiye_kdvli == expected_kdvli


def test_three_segment_swap_chain_is_single_customer_history(app):
    with app.app_context():
        firma, kiralama, eski, ikinci = _swap_contract()
        eski.chain_id = eski.id
        ikinci.chain_id = eski.id
        ikinci.is_active = False
        ikinci.sonlandirildi = True
        ucuncu = KiralamaKalemi(
            kiralama_id=kiralama.id,
            parent_id=ikinci.id,
            chain_id=eski.id,
            kiralama_baslangici=date.today() + timedelta(days=11),
            kiralama_bitis=date.today() + timedelta(days=20),
            kiralama_brm_fiyat=Decimal('100.00'),
            sonlandirildi=False,
            is_active=True,
        )
        db.session.add(ucuncu)
        db.session.commit()

        rows = FirmaService.build_cari_rows(firma, date.today() + timedelta(days=20))
        rental_rows = [
            row for row in rows
            if row.get('kiralama_id') == kiralama.id
            and row.get('islem_turu') == 'kiralama'
        ]
        assert {row['id'] for row in rental_rows} == {eski.id, ikinci.id, ucuncu.id}
        assert sum(row['gun_sayisi'] for row in rental_rows) == 32


def test_cari_durum_raporu_reads_firma_cache(app, monkeypatch):
    with app.app_context():
        firma, _, _, _ = _swap_contract()
        firma.cari_borc_kdvli = Decimal('321.00')
        firma.cari_alacak_kdvli = Decimal('21.00')
        firma.cari_bakiye_kdvli = Decimal('300.00')
        db.session.commit()

        def fail_live_build(*_args, **_kwargs):
            raise AssertionError('Cari durum raporu canli cari hesaplamamali')

        monkeypatch.setattr(FirmaService, 'build_cari_rows', fail_live_build)
        rapor, toplam = CariRaporService.get_durum_raporu()

        firma_row = next(row for row in rapor if row['id'] == firma.id)
        assert firma_row['bakiye_kdvli'] == Decimal('300.00')
        assert toplam['bakiye_kdvli'] == Decimal('300.00')
