from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.filo.models import KullanilanParca, StokHareket, StokKarti
from app.firmalar.models import Firma
from app.services.base import BaseService, ValidationError


def _clean_text(value):
    return (value or '').strip()


def _parse_decimal(value, *, required=False):
    if value is None or value == '':
        if required:
            raise ValidationError('Tutar alani zorunludur.')
        return None

    if isinstance(value, Decimal):
        return value

    text = str(value).strip().replace('TL', '').replace('tl', '').replace(' ', '')
    if ',' in text and '.' in text:
        text = text.replace('.', '').replace(',', '.')
    elif ',' in text:
        text = text.replace(',', '.')

    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError('Gecersiz tutar formati.') from exc


def _parse_int(value, *, required=False):
    if value is None or value == '':
        if required:
            raise ValidationError('Adet alani zorunludur.')
        return None

    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError('Adet alani sayi olmalidir.') from exc


def _parse_percentage(value, *, required=False):
    if value is None or value == '':
        if required:
            raise ValidationError('KDV orani giris hareketi icin zorunludur.')
        return None

    try:
        percentage = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError('KDV orani tam sayi olmalidir.') from exc

    if percentage < 0 or percentage > 100:
        raise ValidationError('KDV orani 0 ile 100 arasinda olmalidir.')

    return percentage


def _parse_date(value):
    if not value:
        return date.today()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except ValueError as exc:
        raise ValidationError('Tarih formati gecersiz.') from exc


class StokKartiService(BaseService):
    model = StokKarti
    use_soft_delete = True
    updatable_fields = {'parca_kodu', 'parca_adi', 'varsayilan_tedarikci_id'}

    @classmethod
    def validate(cls, instance, is_new=True):
        instance.parca_kodu = _clean_text(instance.parca_kodu)
        instance.parca_adi = _clean_text(instance.parca_adi)

        if not instance.parca_kodu:
            raise ValidationError('Parca kodu zorunludur.')
        if not instance.parca_adi:
            raise ValidationError('Parca adi zorunludur.')

        mevcut_kart = cls.model.query.filter(cls.model.parca_kodu == instance.parca_kodu).first()
        if mevcut_kart and mevcut_kart.id != instance.id:
            raise ValidationError(f"'{instance.parca_kodu}' kodlu stok karti zaten mevcut.")

        if instance.varsayilan_tedarikci_id:
            firma = Firma.query.filter_by(
                id=instance.varsayilan_tedarikci_id,
                is_deleted=False,
                is_tedarikci=True,
            ).first()
            if not firma:
                raise ValidationError('Secilen varsayilan tedarikci gecersiz.')

        if instance.mevcut_stok is None:
            instance.mevcut_stok = 0

        try:
            instance.mevcut_stok = int(instance.mevcut_stok)
        except (TypeError, ValueError) as exc:
            raise ValidationError('Mevcut stok tam sayi olmalidir.') from exc

        if instance.mevcut_stok < 0:
            raise ValidationError('Mevcut stok eksi olamaz.')

    @classmethod
    def before_delete(cls, instance):
        if int(instance.mevcut_stok or 0) > 0:
            raise ValidationError('Mevcut stogu sifir olmayan kart arsivlenemez.')

    @classmethod
    def create_card(cls, payload, actor_id=None):
        instance = cls.model(
            parca_kodu=_clean_text(payload.get('parca_kodu')),
            parca_adi=_clean_text(payload.get('parca_adi')),
            varsayilan_tedarikci_id=payload.get('varsayilan_tedarikci_id') or None,
            mevcut_stok=0,
        )
        return cls.save(instance, actor_id=actor_id)

    @classmethod
    def update_card(cls, card_id, payload, actor_id=None):
        data = {
            'parca_kodu': _clean_text(payload.get('parca_kodu')),
            'parca_adi': _clean_text(payload.get('parca_adi')),
            'varsayilan_tedarikci_id': payload.get('varsayilan_tedarikci_id') or None,
        }
        return cls.update(card_id, data, actor_id=actor_id)

    @classmethod
    def restore_card(cls, card_id, actor_id=None):
        kart = cls.get_by_id(card_id, include_deleted=True)
        if not kart:
            raise ValidationError('Geri yuklenecek stok karti bulunamadi.')

        kart.is_deleted = False
        kart.is_active = True
        kart.deleted_at = None
        kart.deleted_by_id = None
        return cls.save(kart, is_new=False, actor_id=actor_id)

    @classmethod
    def hard_delete_card(cls, card_id):
        kart = cls.get_by_id(card_id, include_deleted=True)
        if not kart:
            raise ValidationError('Silinmek istenen stok karti bulunamadi.')

        kullanim_sayisi = KullanilanParca.query.filter_by(stok_karti_id=card_id).count()
        if kullanim_sayisi > 0:
            raise ValidationError(
                f"Bu parca gecmis servis islemlerinde {kullanim_sayisi} kez kullanilmis, kalici olarak silinemez."
            )

        try:
            db.session.delete(kart)
            db.session.commit()
            return kart
        except Exception as exc:
            db.session.rollback()
            raise Exception('Stok karti kalici silinirken hata olustu.') from exc

    @classmethod
    def latest_price(cls, stok_karti_id):
        hareket = (
            StokHareket.query.filter(
                StokHareket.stok_karti_id == stok_karti_id,
                StokHareket.is_deleted == False,
            )
            .order_by(StokHareket.tarih.desc(), StokHareket.id.desc())
            .first()
        )
        return Decimal(hareket.birim_fiyat or 0) if hareket else Decimal('0')

    @classmethod
    def inventory_value_for_card(cls, stok_karti):
        return Decimal(stok_karti.mevcut_stok or 0) * cls.latest_price(stok_karti.id)

    @classmethod
    def total_inventory_value(cls):
        total = Decimal('0')
        for kart in cls.model.query.filter_by(is_deleted=False).all():
            total += cls.inventory_value_for_card(kart)
        return total


class StokHareketService(BaseService):
    model = StokHareket
    use_soft_delete = False

    @classmethod
    def create_movement(cls, stok_karti_id, payload, actor_id=None):
        stok_karti = StokKarti.query.filter_by(id=stok_karti_id, is_deleted=False).first()
        if not stok_karti:
            raise ValidationError('Stok karti bulunamadi.')

        hareket_tipi = _clean_text(payload.get('hareket_tipi')) or 'giris'
        if hareket_tipi not in {'giris', 'cikis'}:
            raise ValidationError('Hareket tipi gecersiz.')

        adet = _parse_int(payload.get('adet'), required=True)
        if adet <= 0:
            raise ValidationError('Adet sifirdan buyuk olmalidir.')

        birim_fiyat = _parse_decimal(payload.get('birim_fiyat'), required=(hareket_tipi == 'giris'))
        if birim_fiyat is None:
            birim_fiyat = StokKartiService.latest_price(stok_karti.id)
        if birim_fiyat < 0:
            raise ValidationError('Birim fiyat eksi olamaz.')

        kdv_orani = _parse_percentage(payload.get('kdv_orani'), required=(hareket_tipi == 'giris'))

        firma_id = payload.get('firma_id') or stok_karti.varsayilan_tedarikci_id or None
        if firma_id:
            firma = Firma.query.filter_by(id=firma_id, is_deleted=False).first()
            if not firma:
                raise ValidationError('Secilen firma bulunamadi.')

        if hareket_tipi == 'cikis' and int(stok_karti.mevcut_stok or 0) < adet:
            raise ValidationError(
                f"'{stok_karti.parca_adi}' icin yeterli stok yok. Mevcut: {stok_karti.mevcut_stok or 0}"
            )

        try:
            hareket = cls.model(
                stok_karti_id=stok_karti.id,
                firma_id=firma_id,
                tarih=_parse_date(payload.get('tarih')),
                adet=adet,
                birim_fiyat=birim_fiyat,
                kdv_orani=kdv_orani,
                hareket_tipi=hareket_tipi,
                fatura_no=_clean_text(payload.get('fatura_no')) or None,
                aciklama=_clean_text(payload.get('aciklama')) or None,
            )

            stok_delta = adet if hareket_tipi == 'giris' else -adet
            stok_karti.mevcut_stok = int(stok_karti.mevcut_stok or 0) + stok_delta

            db.session.add(stok_karti)
            cls.save(hareket, actor_id=actor_id, auto_commit=False)
            db.session.commit()
            return hareket
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as exc:
            db.session.rollback()
            raise Exception('Stok hareketi kaydedilirken hata olustu.') from exc

    @classmethod
    def delete_movement(cls, stok_karti_id, hareket_id):
        hareket = cls.model.query.filter_by(id=hareket_id, stok_karti_id=stok_karti_id).first()
        if not hareket:
            raise ValidationError('Silinmek istenen stok hareketi bulunamadi.')

        stok_karti = StokKarti.query.filter_by(id=stok_karti_id, is_deleted=False).first()
        if not stok_karti:
            raise ValidationError('Bagli stok karti bulunamadi.')

        ters_stok_delta = -int(hareket.adet or 0) if hareket.hareket_tipi == 'giris' else int(hareket.adet or 0)
        yeni_stok = int(stok_karti.mevcut_stok or 0) + ters_stok_delta

        if yeni_stok < 0:
            raise ValidationError(
                "Bu giris kaydi silinirse mevcut stok eksiye dusecek. Once ilgili cikis/hareketleri duzeltin."
            )

        try:
            stok_karti.mevcut_stok = yeni_stok
            db.session.add(stok_karti)
            db.session.delete(hareket)
            db.session.commit()
            return hareket, stok_karti
        except Exception as exc:
            db.session.rollback()
            raise Exception('Stok hareketi silinirken hata olustu.') from exc