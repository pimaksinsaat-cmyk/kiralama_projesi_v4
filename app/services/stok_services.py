from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.filo.models import KullanilanParca, StokHareket, StokKarti, StokKategori
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


class StokKategoriService:

    @classmethod
    def hepsini_getir(cls, sadece_aktif=True):
        q = StokKategori.query
        if sadece_aktif:
            q = q.filter_by(is_active=True)
        return q.order_by(StokKategori.parent_id.nullsfirst(), StokKategori.kategori_adi).all()

    @classmethod
    def kok_kategoriler(cls):
        return StokKategori.query.filter_by(parent_id=None, is_active=True).order_by(StokKategori.kategori_adi).all()

    @classmethod
    def olustur(cls, kategori_adi, parent_id=None):
        kategori_adi = (kategori_adi or '').strip()
        if not kategori_adi:
            raise ValidationError('Kategori adi zorunludur.')
        if parent_id:
            parent = StokKategori.query.get(parent_id)
            if not parent or not parent.is_active:
                raise ValidationError('Ust kategori bulunamadi.')
        instance = StokKategori(kategori_adi=kategori_adi, parent_id=parent_id or None)
        db.session.add(instance)
        db.session.commit()
        return instance

    @classmethod
    def guncelle(cls, kategori_id, kategori_adi, parent_id=None):
        instance = StokKategori.query.get(kategori_id)
        if not instance:
            raise ValidationError('Kategori bulunamadi.')
        instance.kategori_adi = (kategori_adi or '').strip()
        instance.parent_id = parent_id or None
        db.session.commit()
        return instance

    @classmethod
    def sil(cls, kategori_id):
        instance = StokKategori.query.get(kategori_id)
        if not instance:
            raise ValidationError('Kategori bulunamadi.')
        if instance.kartlar.count() > 0:
            raise ValidationError('Bu kategoriye bagli stok kartlari var, silinemez.')
        if instance.alt_kategoriler:
            raise ValidationError('Alt kategorileri olan kategori silinemez.')
        instance.is_active = False
        db.session.commit()


class StokKartiService(BaseService):
    model = StokKarti
    use_soft_delete = True
    updatable_fields = {'parca_kodu', 'parca_adi', 'birim', 'kategori_id', 'ozellikler', 'varsayilan_tedarikci_id'}
    GECERLI_BIRIMLER = {'adet', 'kg', 'gr', 'lt', 'ml', 'mt', 'cm', 'mm', 'koli', 'paket', 'kutu', 'teneke', 'varil'}

    @classmethod
    def validate(cls, instance, is_new=True):
        instance.parca_kodu = _clean_text(instance.parca_kodu)
        instance.parca_adi = _clean_text(instance.parca_adi)

        if not instance.parca_kodu:
            raise ValidationError('Parca kodu zorunludur.')
        if not instance.parca_adi:
            raise ValidationError('Parca adi zorunludur.')
        if instance.birim and instance.birim not in cls.GECERLI_BIRIMLER:
            raise ValidationError(f"Gecersiz birim. Gecerli birimler: {', '.join(sorted(cls.GECERLI_BIRIMLER))}")

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

        if instance.mevcut_stok < 0:
            raise ValidationError('Mevcut stok eksi olamaz.')

    @classmethod
    def before_delete(cls, instance):
        if (instance.mevcut_stok or 0) > 0:
            raise ValidationError('Mevcut stogu sifir olmayan kart arsivlenemez.')

    @classmethod
    def _parse_ozellikler(cls, payload):
        import json
        raw = payload.get('ozellikler')
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}

    @classmethod
    def create_card(cls, payload, actor_id=None):
        instance = cls.model(
            parca_kodu=_clean_text(payload.get('parca_kodu')),
            parca_adi=_clean_text(payload.get('parca_adi')),
            birim=_clean_text(payload.get('birim')) or 'adet',
            kategori_id=payload.get('kategori_id') or None,
            ozellikler=cls._parse_ozellikler(payload),
            varsayilan_tedarikci_id=payload.get('varsayilan_tedarikci_id') or None,
            mevcut_stok=0,
        )
        return cls.save(instance, actor_id=actor_id)

    @classmethod
    def update_card(cls, card_id, payload, actor_id=None):
        data = {
            'parca_kodu': _clean_text(payload.get('parca_kodu')),
            'parca_adi': _clean_text(payload.get('parca_adi')),
            'birim': _clean_text(payload.get('birim')) or 'adet',
            'kategori_id': payload.get('kategori_id') or None,
            'ozellikler': cls._parse_ozellikler(payload),
            'varsayilan_tedarikci_id': payload.get('varsayilan_tedarikci_id') or None,
        }
        return cls.update(card_id, data, actor_id=actor_id)

    @classmethod
    def ozellige_gore_ara(cls, anahtar, deger):
        # Örnek: StokKartiService.ozellige_gore_ara('renk', 'kirmizi')
        # GIN index sayesinde büyük tablolarda da hızlı çalışır
        return (
            cls.model.query
            .filter(cls.model.is_deleted == False)
            .filter(cls.model.ozellikler[anahtar].astext == str(deger))
            .all()
        )

    @classmethod
    def kategoriye_gore_getir(cls, kategori_id, alt_kategoriler_dahil=False):
        if not alt_kategoriler_dahil:
            return cls.model.query.filter_by(kategori_id=kategori_id, is_deleted=False).all()
        # Alt kategorileri recursive olarak topla
        tum_idler = cls._alt_kategori_idleri(kategori_id)
        return cls.model.query.filter(
            cls.model.kategori_id.in_(tum_idler),
            cls.model.is_deleted == False,
        ).all()

    @classmethod
    def _alt_kategori_idleri(cls, kategori_id):
        idler = {kategori_id}
        alt = StokKategori.query.filter_by(parent_id=kategori_id, is_active=True).all()
        for a in alt:
            idler |= cls._alt_kategori_idleri(a.id)
        return idler

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

        adet = _parse_decimal(payload.get('adet'), required=True)
        if adet <= 0:
            raise ValidationError('Miktar sifirdan buyuk olmalidir.')

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

        if hareket_tipi == 'cikis' and (stok_karti.mevcut_stok or 0) < adet:
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
            stok_karti.mevcut_stok = (stok_karti.mevcut_stok or 0) + stok_delta

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

        ters_stok_delta = -(hareket.adet or 0) if hareket.hareket_tipi == 'giris' else (hareket.adet or 0)
        yeni_stok = (stok_karti.mevcut_stok or 0) + ters_stok_delta

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