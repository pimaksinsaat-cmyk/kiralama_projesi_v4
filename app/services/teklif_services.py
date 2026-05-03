from datetime import date
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.firmalar.models import Firma
from app.services.base import BaseService, ValidationError
from app.teklifler.models import TEKLIF_DURUMLARI, Teklif, TeklifKalemi


def _decimal(value, default=Decimal('0.00')):
    if value in (None, ''):
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


class TeklifService(BaseService):
    model = Teklif
    use_soft_delete = True

    @classmethod
    def get_next_teklif_no(cls, today=None):
        today = today or date.today()
        prefix = f"TEK-{today.year}-"
        last_no = (
            db.session.query(func.max(Teklif.teklif_no))
            .filter(Teklif.teklif_no.like(f'{prefix}%'))
            .scalar()
        )
        next_number = 1
        if last_no:
            try:
                next_number = int(str(last_no).rsplit('-', 1)[-1]) + 1
            except ValueError:
                next_number = 1
        return f"{prefix}{next_number:04d}"

    @classmethod
    def validate(cls, instance, is_new=True):
        if instance.durum not in TEKLIF_DURUMLARI:
            raise ValidationError('Geçersiz teklif durumu.')
        if not instance.firma_musteri_id and not (instance.aday_firma_adi or '').strip():
            raise ValidationError('Kayıtlı firma veya aday firma adı girilmelidir.')

    @classmethod
    def create_with_items(cls, teklif_data, kalemler_data, actor_id=None):
        teklif = Teklif(**teklif_data)
        if not teklif.teklif_no:
            teklif.teklif_no = cls.get_next_teklif_no(teklif.teklif_tarihi)
        try:
            cls.save(teklif, is_new=True, auto_commit=False, actor_id=actor_id)
            cls._replace_items(teklif, kalemler_data, actor_id=actor_id)
            db.session.commit()
            return teklif
        except Exception:
            db.session.rollback()
            raise

    @classmethod
    def update_with_items(cls, teklif_id, teklif_data, kalemler_data, actor_id=None):
        teklif = cls.get_by_id(teklif_id)
        if not teklif:
            raise ValidationError('Teklif bulunamadı.')
        try:
            for key, value in teklif_data.items():
                if key != 'teklif_no' and hasattr(teklif, key):
                    setattr(teklif, key, value)
            cls.save(teklif, is_new=False, auto_commit=False, actor_id=actor_id)
            cls._replace_items(teklif, kalemler_data, actor_id=actor_id)
            db.session.commit()
            return teklif
        except Exception:
            db.session.rollback()
            raise

    @classmethod
    def _replace_items(cls, teklif, kalemler_data, actor_id=None):
        for kalem in list(teklif.kalemler):
            db.session.delete(kalem)
        db.session.flush()

        created_any = False
        for raw in kalemler_data:
            if cls._is_empty_item(raw):
                continue
            kalem = TeklifKalemi(
                teklif_id=teklif.id,
                ekipman_id=(raw.get('ekipman_id') or None),
                makine_tipi=(raw.get('makine_tipi') or '').strip() or None,
                marka_model=(raw.get('marka_model') or '').strip() or None,
                calisma_yuksekligi=_decimal(raw.get('calisma_yuksekligi'), default=None),
                kaldirma_kapasitesi=raw.get('kaldirma_kapasitesi') or None,
                adet=raw.get('adet') or 1,
                calisacagi_konum=(raw.get('calisacagi_konum') or '').strip() or None,
                baslangic_tarihi=raw.get('baslangic_tarihi'),
                bitis_tarihi=raw.get('bitis_tarihi'),
                fiyat_tipi=raw.get('fiyat_tipi') if raw.get('fiyat_tipi') in ('gunluk', 'aylik') else 'gunluk',
                gunluk_fiyat=_decimal(raw.get('gunluk_fiyat')),
                nakliye_yon=raw.get('nakliye_yon') if raw.get('nakliye_yon') in ('tek_yon', 'cift_yon') else 'tek_yon',
                nakliye_fiyati=_decimal(raw.get('nakliye_fiyati')),
                satir_notu=(raw.get('satir_notu') or '').strip() or None,
            )
            BaseService._apply_audit_log(kalem, True, actor_id=actor_id)
            db.session.add(kalem)
            created_any = True

        if not created_any:
            raise ValidationError('En az bir teklif kalemi girilmelidir.')

    @staticmethod
    def _is_empty_item(raw):
        return not any([
            raw.get('ekipman_id'),
            (raw.get('makine_tipi') or '').strip(),
            (raw.get('marka_model') or '').strip(),
            raw.get('gunluk_fiyat'),
            raw.get('nakliye_fiyati'),
            (raw.get('calisacagi_konum') or '').strip(),
        ])

    @classmethod
    def durum_guncelle(cls, teklif_id, durum, actor_id=None):
        teklif = cls.get_by_id(teklif_id)
        if not teklif:
            raise ValidationError('Teklif bulunamadı.')
        teklif.durum = durum
        return cls.save(teklif, is_new=False, auto_commit=True, actor_id=actor_id)

    @classmethod
    def aday_musteriyi_firmaya_aktar(cls, teklif_id, firma_data, actor_id=None):
        teklif = cls.get_by_id(teklif_id)
        if not teklif:
            raise ValidationError('Teklif bulunamadı.')
        if teklif.firma_musteri_id:
            raise ValidationError('Bu teklif zaten kayıtlı bir firmaya bağlı.')

        firma = Firma(
            firma_adi=firma_data['firma_adi'],
            yetkili_adi=firma_data['yetkili_adi'],
            telefon=firma_data.get('telefon'),
            eposta=firma_data.get('eposta'),
            iletisim_bilgileri=firma_data['iletisim_bilgileri'],
            vergi_dairesi=firma_data['vergi_dairesi'],
            vergi_no=firma_data['vergi_no'],
            is_musteri=True,
            is_tedarikci=False,
        )
        try:
            BaseService._apply_audit_log(firma, True, actor_id=actor_id)
            db.session.add(firma)
            db.session.flush()
            teklif.firma_musteri_id = firma.id
            cls.save(teklif, is_new=False, auto_commit=False, actor_id=actor_id)
            db.session.commit()
            return firma
        except Exception:
            db.session.rollback()
            raise
