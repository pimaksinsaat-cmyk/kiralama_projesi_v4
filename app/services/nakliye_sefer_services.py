"""Çoklu makine nakliye seferlerinin transaction sınırındaki iş kuralları."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import uuid
import copy

from sqlalchemy import or_

from app.araclar.models import Arac
from app.extensions import db
from app.services.base import ValidationError
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import Nakliye, NakliyeDagitim
from app.cari.models import HizmetKaydi
from app.fatura.models import Hakedis
from app.services.nakliye_services import _net_kdv_orani


SATIS_KAYNAGI = 'nakliye_dagitim_satis'
GIDER_KAYNAGI = 'nakliye_sefer_taseron_gider'


def _money(value):
    try:
        value = Decimal(str(value or '0'))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Nakliye tutarı geçerli bir sayı olmalıdır.')
    value = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if value < 0:
        raise ValidationError('Nakliye tutarı negatif olamaz.')
    return value


def _date(value, default=None):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            raise ValidationError('Nakliye tarihi geçerli olmalıdır.')
    return default


def _soft_delete(instance, actor_id=None):
    instance.is_deleted = True
    instance.is_active = False
    instance.deleted_at = datetime.now(timezone.utc)
    if actor_id is not None:
        instance.deleted_by_id = actor_id
    db.session.add(instance)


class NakliyeSeferService:
    @staticmethod
    def _legacy_taseron_yon_eslesir(hizmet, sefer_yonu):
        kaynak = (hizmet.kaynak or '').strip().lower()
        aciklama = (hizmet.aciklama or '').strip().casefold()
        if sefer_yonu == 'donus':
            return kaynak == 'donus_nakliye' or aciklama.startswith(
                ('dönüş nakliye:', 'donus nakliye:')
            )
        return kaynak == 'taseron_nakliye' or aciklama.startswith(
            ('taşeron nakliye bedeli', 'taseron nakliye bedeli')
        )

    @classmethod
    def legacy_taseron_service_candidates(
        cls, sefer, kiralama, kalem_id=None, sefer_yonu=None,
    ):
        """Eski form/kalem referanslı taşeron hareketini mali alanlarına dokunmadan bulur."""
        bilgi = cls.legacy_taseron_cari_bilgileri(sefer, kiralama)
        kalem_id = kalem_id or bilgi['kiralama_kalemi_id']
        if not (
            sefer.nakliye_tipi == 'taseron'
            and sefer.taseron_firma_id
            and _money(sefer.taseron_maliyet) > 0
            and kalem_id
            and kiralama.kiralama_form_no
        ):
            return []
        candidates = HizmetKaydi.query.filter(
            HizmetKaydi.firma_id == sefer.taseron_firma_id,
            HizmetKaydi.ozel_id == kalem_id,
            HizmetKaydi.fatura_no == kiralama.kiralama_form_no,
            HizmetKaydi.tutar == _money(sefer.taseron_maliyet),
            HizmetKaydi.yon == 'gelen',
            HizmetKaydi.is_deleted.is_(False),
            HizmetKaydi.is_active.is_(True),
        ).order_by(HizmetKaydi.id).all()
        return [
            hizmet for hizmet in candidates
            if cls._legacy_taseron_yon_eslesir(hizmet, sefer_yonu or sefer.yon)
        ]

    @staticmethod
    def _has_any_hakedis_link(hizmet):
        return bool(hizmet and Hakedis.query.filter(
            Hakedis.cari_hareket_id == hizmet.id,
            Hakedis.is_deleted.is_(False),
        ).first())

    @classmethod
    def _is_preserved_legacy_taseron(cls, hizmet, sefer, kiralama, kalem_id):
        return bool(
            hizmet
            and hizmet.ozel_id == kalem_id
            and hizmet.fatura_no == kiralama.kiralama_form_no
            and cls._legacy_taseron_yon_eslesir(hizmet, sefer.yon)
        )

    @staticmethod
    def _kalem_label(kalem):
        """Form kartlarÄ±nda kullanÄ±lacak kÄ±sa makine etiketi."""
        if getattr(kalem, 'is_dis_tedarik_ekipman', False):
            parts = [
                getattr(kalem, 'harici_ekipman_marka', None),
                getattr(kalem, 'harici_ekipman_model', None),
                getattr(kalem, 'harici_ekipman_seri_no', None),
            ]
            return ' '.join(str(part).strip() for part in parts if part).strip() or 'Harici ekipman'
        ekipman = getattr(kalem, 'ekipman', None)
        return (getattr(ekipman, 'kod', None) or f'Makine #{kalem.id}') if ekipman else f'Makine #{kalem.id}'

    @classmethod
    def _legacy_gidis_metinleri(cls, kiralama, raw, kalemler):
        """Yeni kiralamadaki ilk dağıtım için eski liste metinlerini üretir."""
        allocations = raw.get('dagitimlar') or raw.get('allocations') or []
        if not allocations:
            return None, None

        kalem = kalemler.get(cls._alloc_kalem_id(allocations[0]))
        if kalem is None:
            return None, None

        makine_adi = cls._kalem_label(kalem)
        firma_adi = (
            kiralama.firma_musteri.firma_adi
            if kiralama.firma_musteri and kiralama.firma_musteri.firma_adi
            else 'Müşteri'
        )
        is_yeri = (kiralama.makine_calisma_adresi or '').strip() or firma_adi
        ekipman = getattr(kalem, 'ekipman', None)
        sube_adi = (
            ekipman.sube.isim
            if ekipman and ekipman.sube and ekipman.sube.isim
            else None
        )
        if sube_adi:
            guzergah = (
                f"{makine_adi} {sube_adi} şubesinden {firma_adi} firmasının "
                f"{is_yeri}'ne götürüldü"
            )
        else:
            guzergah = f"{makine_adi} {firma_adi} firmasına götürüldü ({is_yeri})"

        form_no = kiralama.kiralama_form_no or ''
        return guzergah, f"Gidiş: {form_no} #{kalem.id}"

    @classmethod
    def legacy_taseron_cari_bilgileri(cls, sefer, kiralama):
        """Sefer giderini eski taşeron cari metniyle ilişkilendirir."""
        aktif_dagitimlar = sorted(
            (
                dagitim for dagitim in (getattr(sefer, 'dagitimlar', None) or [])
                if not dagitim.is_deleted and dagitim.is_active
            ),
            key=lambda dagitim: dagitim.id or 0,
        )
        ilk_kalem = None
        if aktif_dagitimlar:
            ilk_kalem = aktif_dagitimlar[0].kiralama_kalemi
            if ilk_kalem is None:
                ilk_kalem = db.session.get(
                    KiralamaKalemi, aktif_dagitimlar[0].kiralama_kalemi_id,
                )

        if ilk_kalem and ilk_kalem.ekipman and ilk_kalem.ekipman.kod:
            makine_adi = ilk_kalem.ekipman.kod
        elif ilk_kalem:
            makine_adi = ilk_kalem.harici_ekipman_marka or 'Dış Ekipman'
        else:
            makine_adi = 'Makine'

        form_no = kiralama.kiralama_form_no or ''
        return {
            'kiralama_kalemi_id': ilk_kalem.id if ilk_kalem else None,
            'form_no': form_no,
            'aciklama': f"Taşeron Nakliye Bedeli ({makine_adi}) - {form_no}",
        }

    @classmethod
    def sefer_modeli_payload(cls, kiralama):
        """Aktif sefer ve daÄŸÄ±tÄ±mlarÄ± form iÃ§in doÄŸrudan veritabanÄ±ndan okur."""
        # SonlandÄ±rÄ±lmÄ±ÅŸ kalemler de fiziksel sefer geÃ§miÅŸinde gÃ¶rÃ¼nmelidir.
        kalemler = [k for k in kiralama.kalemler if not k.is_deleted]
        kalem_map = {k.id: k for k in kalemler}
        payload = []
        for sefer in sorted(
            (s for s in kiralama.nakliyeler if not s.is_deleted and s.is_active),
            key=lambda item: (item.tarih or date.min, item.id or 0),
        ):
            dagitimlar = [
                d for d in sefer.dagitimlar
                if not d.is_deleted and d.is_active and d.kiralama_kalemi_id in kalem_map
            ]
            if not dagitimlar:
                continue
            payload.append({
                'id': sefer.id,
                'sefer_uuid': sefer.sefer_uuid,
                'yon': sefer.yon,
                'cift_yon': bool(getattr(sefer, 'cift_yon', False)),
                'tarih': sefer.tarih.isoformat() if sefer.tarih else date.today().isoformat(),
                'islem_tarihi': (sefer.islem_tarihi or sefer.tarih or date.today()).isoformat(),
                'guzergah': sefer.guzergah or '',
                'nakliye_tipi': sefer.nakliye_tipi or 'oz_mal',
                'arac_id': sefer.arac_id,
                'taseron_firma_id': sefer.taseron_firma_id,
                'taseron_maliyet': str(sefer.taseron_maliyet or 0),
                'taseron_kdv_orani': sefer.taseron_kdv_orani or 0,
                'taseron_tevkifat_orani': sefer.taseron_tevkifat_orani or '',
                'kdv_orani': sefer.kdv_orani or 0,
                'tevkifat_orani': sefer.tevkifat_orani,
                'plaka': sefer.plaka,
                'aciklama': sefer.aciklama,
                'gecis_kaynagi': getattr(sefer, 'gecis_kaynagi', None),
                'gecis_eksik_bilgiler': getattr(sefer, 'gecis_eksik_bilgiler', None),
                'dagitimlar': [
                    {
                        'kiralama_kalemi_id': d.kiralama_kalemi_id,
                        'tutar': str(d.tutar or 0),
                        'kalem_etiketi': cls._kalem_label(kalem_map[d.kiralama_kalemi_id]),
                        'faturali': bool(cls._faturali(cls._active_service(
                            nakliye_dagitim_id=d.id,
                            kaynak=SATIS_KAYNAGI,
                        ))),
                    }
                    for d in sorted(dagitimlar, key=lambda item: item.kiralama_kalemi_id)
                ],
            })
        return payload

    """Sefer + dağıtım + cari kayıtlarını tek transaction içinde senkronlar."""

    @staticmethod
    def aktif_gidis_tutari(kalem):
        """Kalemin aktif gidiş dağıtımlarındaki tek bacak toplamı."""
        allocations = [
            d for d in (getattr(kalem, 'nakliye_dagitimlari', None) or [])
            if not d.is_deleted and d.is_active
            and getattr(getattr(d, 'nakliye', None), 'is_deleted', True) is False
            and getattr(getattr(d, 'nakliye', None), 'is_active', True) is True
        ]
        total = Decimal('0.00')
        for dagitim in allocations:
            sefer = getattr(dagitim, 'nakliye', None)
            if getattr(sefer, 'yon', None) == 'donus':
                continue
            amount = Decimal(str(dagitim.tutar or 0))
            if getattr(sefer, 'cift_yon', False):
                amount /= Decimal('2')
            total += amount
        return total

    @staticmethod
    def aktif_donus_tutari(kalem):
        """Kalemin aktif gerçek dönüş dağıtımlarındaki toplam."""
        return sum(
            (
                Decimal(str(d.tutar or 0))
                for d in (getattr(kalem, 'nakliye_dagitimlari', None) or [])
                if not d.is_deleted
                and d.is_active
                and getattr(getattr(d, 'nakliye', None), 'is_deleted', True) is False
                and getattr(getattr(d, 'nakliye', None), 'is_active', True) is True
                and getattr(getattr(d, 'nakliye', None), 'yon', None) == 'donus'
            ),
            Decimal('0.00'),
        )

    @staticmethod
    def has_aktif_donus(kalem):
        """Aktif dönüş dağıtımı var mı; tutarın sıfır olması sonucu değiştirmez."""
        return any(
            not d.is_deleted
            and d.is_active
            and getattr(getattr(d, 'nakliye', None), 'is_deleted', True) is False
            and getattr(getattr(d, 'nakliye', None), 'is_active', True) is True
            and getattr(getattr(d, 'nakliye', None), 'yon', None) == 'donus'
            for d in (getattr(kalem, 'nakliye_dagitimlari', None) or [])
        )

    @staticmethod
    def planlanan_donus_tutari(kalem):
        """Aktif çift yönlü gidiş dağıtımından türeyen tek bacak dönüş bedeli."""
        return sum(
            (
                Decimal(str(d.tutar or 0)) / Decimal('2')
                for d in (getattr(kalem, 'nakliye_dagitimlari', None) or [])
                if not d.is_deleted
                and d.is_active
                and getattr(getattr(d, 'nakliye', None), 'is_deleted', True) is False
                and getattr(getattr(d, 'nakliye', None), 'is_active', True) is True
                and getattr(getattr(d, 'nakliye', None), 'yon', None) != 'donus'
                and getattr(getattr(d, 'nakliye', None), 'cift_yon', False)
            ),
            Decimal('0.00'),
        )

    @classmethod
    def kalem_donus_fatura_flag(cls, kalem):
        """Aktif çift yön politikası veya gerçek dönüş var mı?"""
        for dagitim in (getattr(kalem, 'nakliye_dagitimlari', None) or []):
            if dagitim.is_deleted or not dagitim.is_active:
                continue
            sefer = getattr(dagitim, 'nakliye', None)
            if not sefer or sefer.is_deleted or not sefer.is_active:
                continue
            if sefer.yon == 'donus':
                return True
            if sefer.yon == 'gidis' and sefer.cift_yon:
                return True
        return False

    @classmethod
    def kalem_satis_tutari(cls, kalem):
        """Gidiş + gerçek dönüş; gerçek dönüş yoksa çift yön planlanan dönüşü."""
        allocations = [
            d for d in (getattr(kalem, 'nakliye_dagitimlari', None) or [])
            if not d.is_deleted and d.is_active
            and getattr(getattr(d, 'nakliye', None), 'is_deleted', True) is False
            and getattr(getattr(d, 'nakliye', None), 'is_active', True) is True
        ]
        if not allocations:
            return Decimal(str(kalem.nakliye_satis_fiyat or 0))
        donus = (
            cls.aktif_donus_tutari(kalem)
            if cls.has_aktif_donus(kalem)
            else cls.planlanan_donus_tutari(kalem)
        )
        return cls.aktif_gidis_tutari(kalem) + donus

    @classmethod
    def dagitim_satis_tutari(cls, dagitim):
        """Nakliye listesi ve cari iÃ§in daÄŸÄ±tÄ±mÄ±n efektif satÄ±ÅŸ tutarÄ±."""
        amount = Decimal(str(getattr(dagitim, 'tutar', 0) or 0))
        sefer = getattr(dagitim, 'nakliye', None)
        if not sefer or sefer.yon != 'gidis' or not sefer.cift_yon:
            return amount

        kalem = getattr(dagitim, 'kiralama_kalemi', None)
        if kalem is not None and cls.has_aktif_donus(kalem):
            return amount / Decimal('2')
        return amount

    @classmethod
    def nakliye_satis_tutari(cls, nakliye):
        """Nakliye listesi/KDV raporlarÄ± iÃ§in efektif satÄ±ÅŸ matrahÄ±."""
        dagitimlar = [
            d for d in (getattr(nakliye, 'dagitimlar', None) or [])
            if not d.is_deleted and d.is_active
        ]
        if not dagitimlar:
            return Decimal(str(getattr(nakliye, 'tutar', 0) or 0))
        return sum((cls.dagitim_satis_tutari(d) for d in dagitimlar), Decimal('0.00'))

    @classmethod
    def _active_or_revive_distribution(cls, nakliye_id, kiralama_kalemi_id):
        """Dağıtımı aktif bulur veya en güncel soft-delete satırını canlandırır."""
        dagitim = NakliyeDagitim.query.filter_by(
            nakliye_id=nakliye_id,
            kiralama_kalemi_id=kiralama_kalemi_id,
        ).filter(
            NakliyeDagitim.is_deleted.is_(False),
            NakliyeDagitim.is_active.is_(True),
        ).first()
        if dagitim:
            return dagitim

        dagitim = NakliyeDagitim.query.filter_by(
            nakliye_id=nakliye_id,
            kiralama_kalemi_id=kiralama_kalemi_id,
        ).filter(
            NakliyeDagitim.is_deleted.is_(True),
        ).order_by(NakliyeDagitim.id.desc()).first()
        if dagitim:
            dagitim.is_deleted = False
            dagitim.is_active = True
            dagitim.deleted_at = None
            dagitim.deleted_by_id = None
            db.session.add(dagitim)
        return dagitim

    @staticmethod
    def _faturali(hizmet):
        if not hizmet:
            return False
        if getattr(hizmet, 'fatura_no', None):
            return True
        hakedis = Hakedis.query.filter(
            Hakedis.cari_hareket_id == hizmet.id,
            Hakedis.is_deleted.is_(False),
        ).first()
        return bool(hakedis and (
            hakedis.durum == 'faturalasti' or bool(hakedis.is_faturalasti)
        ))

    @classmethod
    def _guard_amount_change(cls, hizmet, amount):
        if hizmet and not hizmet.is_deleted and cls._faturali(hizmet):
            if _money(hizmet.tutar) != amount:
                raise ValidationError('Faturalı nakliye tutarı değiştirilemez; iade/ek fatura süreci kullanılmalıdır.')

    @classmethod
    def _sefer_faturali(cls, sefer):
        return any(
            not hizmet.is_deleted and cls._faturali(hizmet)
            for hizmet in (getattr(sefer, 'hizmet_kayitlari', None) or [])
        )

    @classmethod
    def _guard_invoiced_sefer_update(cls, sefer, raw):
        """Faturalı seferin mali anlamını veya dağıtımını değiştirmeyi engeller."""
        if not sefer or not cls._sefer_faturali(sefer):
            return
        current_allocations = {
            d.kiralama_kalemi_id: _money(d.tutar)
            for d in sefer.dagitimlar if not d.is_deleted and d.is_active
        }
        submitted_allocations = {
            cls._alloc_kalem_id(d): _money(d.get('tutar'))
            for d in (raw.get('dagitimlar') or raw.get('allocations') or [])
        }
        protected = {
            'yon': (sefer.yon, raw.get('yon')),
            'nakliye_tipi': (sefer.nakliye_tipi or 'oz_mal', raw.get('nakliye_tipi') or 'oz_mal'),
            'taseron_firma_id': (sefer.taseron_firma_id, int(raw.get('taseron_firma_id') or 0) or None),
            'kdv_orani': (int(sefer.kdv_orani or 0), int(raw.get('kdv_orani') or 0)),
            'tevkifat_orani': (sefer.tevkifat_orani or None, raw.get('tevkifat_orani') or None),
            'taseron_maliyet': (_money(sefer.taseron_maliyet), _money(raw.get('taseron_maliyet'))),
            'taseron_kdv_orani': (int(sefer.taseron_kdv_orani or 0), int(raw.get('taseron_kdv_orani') or 0)),
            'taseron_tevkifat_orani': (
                sefer.taseron_tevkifat_orani or None,
                (raw.get('taseron_tevkifat_orani') or '').strip() or None,
            ),
            'dagitimlar': (current_allocations, submitted_allocations),
        }
        changed = [name for name, (old, new) in protected.items() if old != new]
        if changed:
            raise ValidationError(
                'Faturalı seferin mali alanları veya makine dağıtımı değiştirilemez; '
                'iade/ek fatura süreci kullanılmalıdır.'
            )

    @staticmethod
    def _active_service(**filters):
        return HizmetKaydi.query.filter_by(**filters).filter(
            HizmetKaydi.is_deleted.is_(False), HizmetKaydi.is_active.is_(True)
        ).first()

    @classmethod
    def _service_for_sync(cls, **filters):
        """Aktif kaydı bulur; yoksa yalnızca faturasız soft-delete kaydı canlandırır."""
        active = cls._active_service(**filters)
        if active:
            return active
        candidates = HizmetKaydi.query.filter_by(**filters).filter(
            HizmetKaydi.is_deleted.is_(True)
        ).order_by(HizmetKaydi.id.desc()).all()
        for hizmet in candidates:
            if cls._faturali(hizmet):
                continue
            hizmet.is_deleted = False
            hizmet.is_active = True
            hizmet.deleted_at = None
            hizmet.deleted_by_id = None
            db.session.add(hizmet)
            return hizmet
        return None

    @classmethod
    def remove_kalem_allocations(cls, kiralama, kalem_ids, actor_id=None, archive_ids=None):
        """Formdan çıkarılan kalemlerin sefer dağıtımlarını ve cari kayıtlarını kapatır.

        Bu kontrol, görsel editörün gönderdiği state'ten bağımsızdır. Böylece
        eski/stale bir payload dağıtımı tekrar aktif bıraksa bile, kira formunda
        bulunmayan kalemin aktif dağıtımı transaction içinde pasifleştirilir.
        Fiziksel sefer korunur; seferin arşivlenmesi yalnızca açık kullanıcı
        talebiyle yapılır.
        """
        normalized_ids = set()
        for value in kalem_ids or []:
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if value > 0:
                normalized_ids.add(value)
        if not normalized_ids:
            return set()

        dagitimlar = (
            NakliyeDagitim.query
            .join(Nakliye, Nakliye.id == NakliyeDagitim.nakliye_id)
            .filter(
                Nakliye.kiralama_id == kiralama.id,
                NakliyeDagitim.kiralama_kalemi_id.in_(normalized_ids),
                NakliyeDagitim.is_deleted.is_(False),
                NakliyeDagitim.is_active.is_(True),
                Nakliye.is_deleted.is_(False),
            )
            .all()
        )
        affected_sefer_ids = set()
        for dagitim in dagitimlar:
            affected_sefer_ids.add(dagitim.nakliye_id)
            _soft_delete(dagitim, actor_id)
            for hizmet in HizmetKaydi.query.filter_by(nakliye_dagitim_id=dagitim.id).filter(
                HizmetKaydi.is_deleted.is_(False),
            ).all():
                _soft_delete(hizmet, actor_id)

        empty_sefer_ids = set()
        for sefer_id in affected_sefer_ids:
            sefer = db.session.get(Nakliye, sefer_id)
            if not sefer:
                continue
            aktif_dagitimlar = NakliyeDagitim.query.filter_by(nakliye_id=sefer.id).filter(
                NakliyeDagitim.is_deleted.is_(False),
                NakliyeDagitim.is_active.is_(True),
            ).all()
            sefer.tutar = sum((_money(d.tutar) for d in aktif_dagitimlar), Decimal('0.00'))
            sefer.hesapla_ve_guncelle()
            db.session.add(sefer)
            if not aktif_dagitimlar:
                empty_sefer_ids.add(sefer.id)

        # Formdan kalem düşünce sefer boş kalabilir; kullanıcıdan ayrıca
        # arşiv kartı beklemeden seferi kapat (stale JSON / kalem silme).
        for sefer_id in empty_sefer_ids:
            sefer = db.session.get(Nakliye, sefer_id)
            if sefer and not sefer.is_deleted:
                cls._archive_sefer(sefer, actor_id)

        # Kalem üzerindeki eski toplam alanı yeni dağıtım toplamıyla uyumlu
        # tut; bu alan sefer modelinde kaynak değil, yalnızca legacy/rapor
        # uyumluluğu için snapshot olarak korunur.
        for kalem in kiralama.kalemler:
            if getattr(kalem, 'is_deleted', False):
                continue
            db.session.expire(kalem, ['nakliye_dagitimlari'])
            kalem.nakliye_satis_fiyat = cls.kalem_satis_tutari(kalem)
            kalem.donus_nakliye_fatura_et = cls.kalem_donus_fatura_flag(kalem)
            cls._sync_kalem_arac_aynasi(kalem)
            db.session.add(kalem)
        return affected_sefer_ids

    @classmethod
    def _sync_distribution_service(cls, sefer, dagitim, kiralama, actor_id=None):
        hizmet = cls._service_for_sync(
            nakliye_dagitim_id=dagitim.id,
            kaynak=SATIS_KAYNAGI,
        )
        amount = _money(cls.dagitim_satis_tutari(dagitim))

        # Dönüşümle bağlanan geçmiş müşteri hareketinin mali ve belge alanları
        # değiştirilemez. Preflight bu kaydın dağıtım tutarıyla eşleşmesini
        # zaten zorunlu tutar; sonraki günlük cari senkronu yalnız teknik bağı
        # doğrular. Sıfır TL geçmiş hareket de bu nedenle pasifleştirilmez.
        if getattr(sefer, 'gecis_kaynagi', None) == 'legacy_kiralama_v1':
            if hizmet is None:
                if amount == 0:
                    return
                raise ValidationError(
                    f'Nakliye #{sefer.id} dönüşümle korunan müşteri cari hareketi bulunamadı.'
                )
            if _money(hizmet.tutar) != amount:
                raise ValidationError(
                    f'Nakliye #{sefer.id} dönüşümle korunan müşteri cari hareketinin '
                    'tutarı dağıtımla eşleşmiyor.'
                )
            hizmet.nakliye_id = sefer.id
            hizmet.nakliye_dagitim_id = dagitim.id
            hizmet.kiralama_kalemi_id = dagitim.kiralama_kalemi_id
            hizmet.kaynak = SATIS_KAYNAGI
            db.session.add(hizmet)
            return

        cls._guard_amount_change(hizmet, amount)
        if amount == 0:
            if hizmet:
                _soft_delete(hizmet, actor_id)
            return
        if hizmet is None:
            hizmet = HizmetKaydi(
                nakliye_dagitim_id=dagitim.id,
                kiralama_kalemi_id=dagitim.kiralama_kalemi_id,
                nakliye_id=sefer.id,
                firma_id=kiralama.firma_musteri_id,
                yon='giden',
                kaynak=SATIS_KAYNAGI,
                fatura_no=None,
                aciklama=f'Nakliye dağıtımı: {kiralama.kiralama_form_no} #{dagitim.kiralama_kalemi_id}',
            )
        hizmet.tutar = amount
        hizmet.firma_id = kiralama.firma_musteri_id
        hizmet.nakliye_id = sefer.id
        hizmet.nakliye_dagitim_id = dagitim.id
        hizmet.kiralama_kalemi_id = dagitim.kiralama_kalemi_id
        hizmet.yon = 'giden'
        hizmet.kaynak = SATIS_KAYNAGI
        hizmet.tarih = sefer.tarih or date.today()
        hizmet.islem_tarihi = sefer.islem_tarihi or sefer.tarih
        hizmet.kdv_orani = sefer.kdv_orani
        db.session.add(hizmet)

    @classmethod
    def _sync_taseron_service(cls, sefer, kiralama, actor_id=None):
        active = HizmetKaydi.query.filter_by(
            nakliye_id=sefer.id, kaynak=GIDER_KAYNAGI,
        ).filter(
            HizmetKaydi.is_deleted.is_(False),
            HizmetKaydi.is_active.is_(True),
        ).order_by(HizmetKaydi.id).all()
        if len(active) > 1:
            raise ValidationError(
                f'Nakliye #{sefer.id} için birden fazla aktif taşeron gideri var.'
            )
        hizmet = active[0] if active else None
        amount = _money(sefer.taseron_maliyet)
        cls._guard_amount_change(hizmet, amount)
        if amount == 0:
            if hizmet:
                _soft_delete(hizmet, actor_id)
            return
        if not sefer.taseron_firma_id:
            raise ValidationError('Taşeron gideri için taşeron firma seçilmelidir.')

        legacy_bilgi = cls.legacy_taseron_cari_bilgileri(sefer, kiralama)
        kalem_id = legacy_bilgi['kiralama_kalemi_id']
        legacy_candidates = cls.legacy_taseron_service_candidates(
            sefer, kiralama, kalem_id,
        )
        unlinked_legacy = [h for h in legacy_candidates if h.nakliye_id != sefer.id]
        if len(unlinked_legacy) > 1:
            raise ValidationError(
                f'Nakliye #{sefer.id} için birden fazla eski taşeron cari hareketi bulundu.'
            )
        if hizmet is not None and unlinked_legacy:
            raise ValidationError(
                f'Nakliye #{sefer.id} için hem eski hem yeni taşeron cari hareketi bulundu; '
                'güvenli onarım çalıştırılmalıdır.'
            )

        if hizmet is None and len(unlinked_legacy) == 1:
            hizmet = unlinked_legacy[0]
            hizmet.nakliye_id = sefer.id
            hizmet.nakliye_dagitim_id = None
            hizmet.kiralama_kalemi_id = kalem_id
            hizmet.kaynak = GIDER_KAYNAGI
            db.session.add(hizmet)
        elif hizmet is None:
            hizmet = cls._service_for_sync(
                nakliye_id=sefer.id, kaynak=GIDER_KAYNAGI,
            )
            if hizmet is None:
                hizmet = HizmetKaydi(
                    nakliye_id=sefer.id,
                    firma_id=sefer.taseron_firma_id,
                    yon='gelen',
                    kaynak=GIDER_KAYNAGI,
                    aciklama=legacy_bilgi['aciklama'],
                    fatura_no=None,
                )

        if cls._is_preserved_legacy_taseron(
            hizmet, sefer, kiralama, kalem_id,
        ):
            if (
                _money(hizmet.tutar) != amount
                or hizmet.firma_id != sefer.taseron_firma_id
            ):
                raise ValidationError(
                    f'Nakliye #{sefer.id} eski taşeron cari hareketinin mali alanları değiştirilemez.'
                )
            hizmet.nakliye_id = sefer.id
            hizmet.nakliye_dagitim_id = None
            hizmet.kiralama_kalemi_id = kalem_id
            hizmet.kaynak = GIDER_KAYNAGI
            db.session.add(hizmet)
            return

        hizmet.firma_id = sefer.taseron_firma_id
        hizmet.tutar = amount
        hizmet.nakliye_id = sefer.id
        hizmet.nakliye_dagitim_id = None
        hizmet.yon = 'gelen'
        hizmet.kaynak = GIDER_KAYNAGI
        hizmet.kiralama_kalemi_id = kalem_id
        hizmet.aciklama = legacy_bilgi['aciklama']
        hizmet.tarih = sefer.tarih or date.today()
        hizmet.islem_tarihi = sefer.islem_tarihi or sefer.tarih
        net_kdv = _net_kdv_orani(
            sefer.taseron_kdv_orani, sefer.taseron_tevkifat_orani,
        )
        hizmet.kdv_orani = int(net_kdv) if net_kdv is not None else None
        db.session.add(hizmet)

    @classmethod
    def sync_active_cari(cls, kiralama, actor_id=None):
        """Mevcut sefer/dağıtım carilerini yeni kayıt oluşturmadan senkronlar."""
        if not kiralama:
            return
        for sefer in (
            s for s in (kiralama.nakliyeler or [])
            if not s.is_deleted and s.is_active
        ):
            active_allocations = [
                d for d in (sefer.dagitimlar or [])
                if not d.is_deleted and d.is_active
            ]
            sefer.tutar = sum((_money(d.tutar) for d in active_allocations), Decimal('0.00'))
            sefer.hesapla_ve_guncelle()
            for dagitim in active_allocations:
                cls._sync_distribution_service(sefer, dagitim, kiralama, actor_id)
            cls._sync_taseron_service(sefer, kiralama, actor_id)
            db.session.add(sefer)
        active_kalemler = KiralamaKalemi.query.filter(
            KiralamaKalemi.kiralama_id == kiralama.id,
            KiralamaKalemi.is_deleted.is_(False),
            KiralamaKalemi.is_active.is_(True),
        ).all()
        for kalem in active_kalemler:
            db.session.expire(kalem, ['nakliye_dagitimlari'])
            kalem.nakliye_satis_fiyat = cls.kalem_satis_tutari(kalem)
            kalem.donus_nakliye_fatura_et = cls.kalem_donus_fatura_flag(kalem)
            cls._sync_kalem_arac_aynasi(kalem)
            db.session.add(kalem)

    @staticmethod
    def _alloc_kalem_id(alloc):
        try:
            return int(alloc.get('kiralama_kalemi_id') or alloc.get('kalem_id') or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _archive_sefer(cls, sefer, actor_id=None):
        if not sefer or sefer.is_deleted:
            return
        if cls._sefer_faturali(sefer):
            raise ValidationError(
                'Faturalı nakliye seferi arşivlenemez; iade/ek fatura süreci kullanılmalıdır.'
            )
        for dagitim in list(sefer.dagitimlar):
            if not dagitim.is_deleted:
                _soft_delete(dagitim, actor_id)
        for hizmet in HizmetKaydi.query.filter_by(nakliye_id=sefer.id).filter(
            HizmetKaydi.is_deleted.is_(False)
        ).all():
            _soft_delete(hizmet, actor_id)
        _soft_delete(sefer, actor_id)

    @classmethod
    def _load_allowed_kalemler(cls, kiralama, allowed_kalem_ids=None):
        query = KiralamaKalemi.query.filter(
            KiralamaKalemi.kiralama_id == kiralama.id,
            KiralamaKalemi.is_deleted.is_(False),
        )
        if allowed_kalem_ids is not None:
            allowed = set()
            for value in allowed_kalem_ids:
                try:
                    kid = int(value)
                except (TypeError, ValueError):
                    continue
                if kid > 0:
                    allowed.add(kid)
            if not allowed:
                return {}
            query = query.filter(KiralamaKalemi.id.in_(allowed))
        return {kalem.id: kalem for kalem in query.all()}

    @classmethod
    def _remap_temp_kalem_ids(cls, payload, kalem_temp_map):
        if not kalem_temp_map:
            return payload
        payload = copy.deepcopy(payload)
        for raw in payload:
            for alloc in (raw.get('dagitimlar') or raw.get('allocations') or []):
                if cls._alloc_kalem_id(alloc) <= 0 and alloc.get('kalem_temp_id') in kalem_temp_map:
                    alloc['kiralama_kalemi_id'] = kalem_temp_map[alloc['kalem_temp_id']]
        return payload

    @classmethod
    def _prune_payload_to_allowed_kalems(cls, payload, allowed_ids, archive_ids):
        kept = []
        archive_ids = set(archive_ids or [])
        for raw in payload or []:
            alloc_key = 'dagitimlar' if 'dagitimlar' in raw else 'allocations'
            allocs = list(raw.get('dagitimlar') or raw.get('allocations') or [])
            filtered = [alloc for alloc in allocs if cls._alloc_kalem_id(alloc) in allowed_ids]
            if filtered:
                raw = dict(raw)
                raw['dagitimlar'] = filtered
                if alloc_key == 'allocations':
                    raw['allocations'] = filtered
                kept.append(raw)
                continue
            sid = int(raw.get('id') or 0)
            if sid:
                archive_ids.add(sid)
        return kept, archive_ids

    @classmethod
    def _validate_payload(cls, kiralama, payload, archive_ids=None, allow_new_donus=False, allowed_kalem_ids=None):
        if not isinstance(payload, list):
            raise ValidationError('En az bir nakliye seferi girilmelidir.')
        if not payload:
            return {}
        kalemler = cls._load_allowed_kalemler(kiralama, allowed_kalem_ids=allowed_kalem_ids)
        directions = {}
        payload_directions = set()
        for raw in payload:
            for alloc in (raw.get('dagitimlar') or raw.get('allocations') or []):
                payload_directions.add((int(alloc.get('kiralama_kalemi_id') or alloc.get('kalem_id') or 0), raw.get('yon')))
        for raw in payload:
            yon = raw.get('yon')
            if yon not in ('gidis', 'donus'):
                raise ValidationError('Kiralama seferinin yönü gidiş veya dönüş olmalıdır.')
            if yon == 'donus' and not int(raw.get('id') or 0) and not allow_new_donus:
                raise ValidationError('Dönüş seferi kiralama formundan oluşturulamaz; sonlandırma kullanın.')
            allocations = raw.get('dagitimlar') or raw.get('allocations') or []
            if not allocations:
                raise ValidationError('Makinesiz sefer kaydedilemez.')
            nakliye_tipi = raw.get('nakliye_tipi') or 'oz_mal'
            arac_id = int(raw.get('arac_id') or 0) or None
            taseron_firma_id = int(raw.get('taseron_firma_id') or 0) or None
            existing_sefer = db.session.get(Nakliye, int(raw.get('id') or 0)) if int(raw.get('id') or 0) else None
            historical_missing = bool(
                existing_sefer
                and getattr(existing_sefer, 'gecis_kaynagi', None) == 'legacy_kiralama_v1'
                and getattr(existing_sefer, 'gecis_eksik_bilgiler', None)
            )
            if nakliye_tipi == 'taseron':
                if not taseron_firma_id and not historical_missing:
                    raise ValidationError('Taşeron sefer için firma seçmelisiniz.')
            elif not arac_id and not historical_missing:
                raise ValidationError('Öz mal sefer için araç seçmelisiniz.')
            elif arac_id and db.session.get(Arac, arac_id) is None:
                raise ValidationError('Öz mal sefer için araç seçmelisiniz.')
            for alloc in allocations:
                kid = cls._alloc_kalem_id(alloc)
                if kid not in kalemler:
                    raise ValidationError('Nakliye dağıtımı bu kiralamadaki bir kaleme ait olmalıdır.')
                if yon == 'donus' and (kid, 'gidis') not in payload_directions:
                    has_gidis = db.session.query(NakliyeDagitim.id).join(
                        Nakliye, Nakliye.id == NakliyeDagitim.nakliye_id
                    ).filter(
                        NakliyeDagitim.kiralama_kalemi_id == kid,
                        NakliyeDagitim.is_deleted.is_(False),
                        Nakliye.is_deleted.is_(False),
                        Nakliye.yon == 'gidis',
                    ).first()
                    if not has_gidis:
                        raise ValidationError('Gidiş seferi olmayan kalem için dönüş açılamaz.')
                amount = _money(alloc.get('tutar'))
                key = (kid, yon)
                if key in directions:
                    raise ValidationError('Aynı kalem için aynı yönde birden fazla aktif sefer olamaz.')
                directions[key] = amount
        return kalemler

    @staticmethod
    def _plaka_for_sefer(nakliye_tipi, arac_id, raw_plaka, existing_plaka=None):
        """Öz malda yalnızca Arac.plaka; taşeronda formdan gelen plaka."""
        if nakliye_tipi != 'taseron' and arac_id:
            arac = db.session.get(Arac, arac_id)
            if arac is None:
                raise ValidationError('Öz mal sefer için araç seçmelisiniz.')
            return arac.plaka
        submitted = (str(raw_plaka).strip() if raw_plaka else '')
        return submitted or ((existing_plaka or '').strip() or None)

    @staticmethod
    def _sync_kalem_arac_aynasi(kalem):
        aktif_gidis = []
        for dagitim in (kalem.nakliye_dagitimlari or []):
            if dagitim.is_deleted or not dagitim.is_active:
                continue
            sefer = getattr(dagitim, 'nakliye', None)
            if not sefer or sefer.is_deleted or not sefer.is_active or sefer.yon != 'gidis':
                continue
            aktif_gidis.append(sefer)
        if len({sefer.id for sefer in aktif_gidis}) > 1:
            raise ValidationError('Bir kalem icin birden fazla aktif gidis seferi bulunamaz.')
        sefer = aktif_gidis[0] if aktif_gidis else None
        kalem.nakliye_araci_id = (
            sefer.arac_id
            if sefer and sefer.nakliye_tipi != 'taseron' and sefer.arac_id
            else None
        )

    @classmethod
    def sync_kiralama(
        cls,
        kiralama,
        payload,
        actor_id=None,
        archive_ids=None,
        kalem_temp_map=None,
        allow_new_donus=False,
        allowed_kalem_ids=None,
        apply_legacy_gidis_defaults=False,
    ):
        """Yeni formun sefer listesini mevcut kiralamaya uygular.

        Çağıran transaction'ı kendisi commit eder; bu nedenle yarım seferler
        hata durumunda tüm kira kaydıyla birlikte rollback olur.
        """
        payload = cls._remap_temp_kalem_ids(payload, kalem_temp_map)
        archive_ids = {int(x) for x in (archive_ids or []) if str(x).isdigit()}
        allowed_kalemler = cls._load_allowed_kalemler(kiralama, allowed_kalem_ids=allowed_kalem_ids)
        payload, archive_ids = cls._prune_payload_to_allowed_kalems(
            payload, set(allowed_kalemler), archive_ids,
        )
        if not payload:
            for archive_id in archive_ids:
                sefer = db.session.get(Nakliye, archive_id)
                if not sefer or sefer.kiralama_id != kiralama.id or sefer.is_deleted:
                    continue
                cls._archive_sefer(sefer, actor_id)
            kiralama.nakliye_modeli = 'sefer'
            db.session.add(kiralama)
            return set()
        kalemler = cls._validate_payload(
            kiralama, payload, archive_ids=archive_ids, allow_new_donus=allow_new_donus,
            allowed_kalem_ids=allowed_kalem_ids,
        )
        submitted_sefer_ids = set()
        seen_allocations = set()
        for raw in payload:
            sid = int(raw.get('id') or 0)
            sefer = db.session.get(Nakliye, sid) if sid else None
            is_new_sefer = sefer is None
            if sefer and sefer.kiralama_id != kiralama.id:
                raise ValidationError('Sefer başka bir kiralamaya aittir.')
            if sefer is None:
                sefer = Nakliye(
                    kiralama_id=kiralama.id,
                    firma_id=kiralama.firma_musteri_id,
                    sefer_uuid=str(raw.get('sefer_uuid') or raw.get('temp_id') or uuid.uuid4()),
                )
            else:
                cls._guard_invoiced_sefer_update(sefer, raw)
            if sefer.kiralama_id is None:
                sefer.kiralama_id = kiralama.id
            sefer.firma_id = kiralama.firma_musteri_id
            sefer.yon = raw.get('yon')
            sefer.cift_yon = bool(raw.get('cift_yon')) and sefer.yon != 'donus'
            sefer.tarih = _date(raw.get('tarih'), date.today())
            sefer.islem_tarihi = _date(raw.get('islem_tarihi'), sefer.tarih)
            sefer.guzergah = (raw.get('guzergah') or '').strip()
            legacy_guzergah = None
            legacy_aciklama = None
            if apply_legacy_gidis_defaults and is_new_sefer and sefer.yon == 'gidis':
                legacy_guzergah, legacy_aciklama = cls._legacy_gidis_metinleri(
                    kiralama, raw, kalemler,
                )
                if sefer.guzergah.casefold() in {'kiralama gidişi', 'kiralama gidisi'}:
                    sefer.guzergah = legacy_guzergah or sefer.guzergah
            if not sefer.guzergah:
                raise ValidationError('Sefer güzergâhı boş bırakılamaz.')
            sefer.nakliye_tipi = raw.get('nakliye_tipi') or 'oz_mal'
            sefer.arac_id = int(raw.get('arac_id') or 0) or None
            sefer.taseron_firma_id = int(raw.get('taseron_firma_id') or 0) or None
            sefer.plaka = cls._plaka_for_sefer(
                sefer.nakliye_tipi,
                sefer.arac_id,
                raw.get('plaka'),
                existing_plaka=sefer.plaka,
            )
            submitted_aciklama = raw.get('aciklama')
            if legacy_aciklama and not str(submitted_aciklama or '').strip():
                sefer.aciklama = legacy_aciklama
            else:
                sefer.aciklama = submitted_aciklama or None
            sefer.kdv_orani = int(raw.get('kdv_orani') or 0)
            sefer.tevkifat_orani = raw.get('tevkifat_orani') or None
            sefer.taseron_maliyet = _money(raw.get('taseron_maliyet'))
            sefer.taseron_kdv_orani = int(raw.get('taseron_kdv_orani') or 0)
            taseron_tev = (raw.get('taseron_tevkifat_orani') or '').strip() or None
            sefer.taseron_tevkifat_orani = taseron_tev if sefer.nakliye_tipi == 'taseron' else None
            db.session.add(sefer)
            db.session.flush()
            submitted_sefer_ids.add(sefer.id)

            allocations = raw.get('dagitimlar') or raw.get('allocations') or []
            submitted_for_sefer = set()
            for alloc in allocations:
                kid = int(alloc.get('kiralama_kalemi_id') or alloc.get('kalem_id'))
                amount = _money(alloc.get('tutar'))
                existing_direction_query = db.session.query(NakliyeDagitim.id, NakliyeDagitim.nakliye_id).join(
                    Nakliye, Nakliye.id == NakliyeDagitim.nakliye_id
                ).filter(
                    NakliyeDagitim.kiralama_kalemi_id == kid,
                    NakliyeDagitim.is_deleted.is_(False),
                    Nakliye.is_deleted.is_(False),
                    Nakliye.yon == raw.get('yon'),
                )
                if archive_ids:
                    existing_direction_query = existing_direction_query.filter(~Nakliye.id.in_(archive_ids))
                existing_direction = existing_direction_query.first()
                if existing_direction and existing_direction.nakliye_id != sefer.id:
                    raise ValidationError('Aynı kalem için aynı yönde aktif bir sefer zaten var.')
                key = (sefer.id, kid)
                if key in seen_allocations:
                    raise ValidationError('Aynı seferde bir kalem yalnızca bir kez dağıtılabilir.')
                seen_allocations.add(key)
                submitted_for_sefer.add(kid)
                dagitim = cls._active_or_revive_distribution(sefer.id, kid)
                if dagitim is None:
                    dagitim = NakliyeDagitim(nakliye_id=sefer.id, kiralama_kalemi_id=kid)
                dagitim.tutar = amount
                dagitim.is_deleted = False
                dagitim.is_active = True
                dagitim.deleted_at = None
                db.session.add(dagitim)
                db.session.flush()
                cls._sync_distribution_service(sefer, dagitim, kiralama, actor_id)

            # Form tam liste gönderdiğinde çıkarılan kalem yalnızca dağıtımdan
            # çıkarılır; ortak fiziksel sefer ve diğer makineler silinmez.
            for old in list(sefer.dagitimlar):
                if old.is_deleted or old.kiralama_kalemi_id in submitted_for_sefer:
                    continue
                _soft_delete(old, actor_id)
                for h in HizmetKaydi.query.filter_by(nakliye_dagitim_id=old.id).filter(
                    HizmetKaydi.is_deleted.is_(False)
                ).all():
                    _soft_delete(h, actor_id)

            # Aynı legacy sefer regroup dönüşümünde birden fazla payload
            # satırında gelebilir; toplam her zaman aktif dağıtımlardan okunur.
            sefer.tutar = sum((
                _money(d.tutar) for d in NakliyeDagitim.query.filter_by(nakliye_id=sefer.id)
                .filter(NakliyeDagitim.is_deleted.is_(False), NakliyeDagitim.is_active.is_(True)).all()
            ), Decimal('0.00'))
            sefer.hesapla_ve_guncelle()
            cls._sync_taseron_service(sefer, kiralama, actor_id)
            if sefer.id in archive_ids:
                cls._archive_sefer(sefer, actor_id)

        # Arşivleme kullanıcının açık talebidir; payload'dan çıkarılan sefer
        # kendiliğinden silinmez. Karttan arşivlenen, payload'da olmayan mevcut
        # seferler burada dağıtım ve cari hareketleriyle birlikte kapatılır.
        for archive_id in archive_ids - submitted_sefer_ids:
            sefer = db.session.get(Nakliye, archive_id)
            if not sefer or sefer.kiralama_id != kiralama.id or sefer.is_deleted:
                continue
            cls._archive_sefer(sefer, actor_id)

        kiralama.nakliye_modeli = 'sefer'
        db.session.add(kiralama)
        for kalem in [k for k in kiralama.kalemler if not getattr(k, 'is_deleted', False)]:
            db.session.expire(kalem, ['nakliye_dagitimlari'])
            kalem.nakliye_satis_fiyat = cls.kalem_satis_tutari(kalem)
            kalem.donus_nakliye_fatura_et = cls.kalem_donus_fatura_flag(kalem)
            cls._sync_kalem_arac_aynasi(kalem)
            db.session.add(kalem)
        return submitted_sefer_ids

    @classmethod
    def legacy_conversion_payload(cls, kiralama):
        """Legacy 1:1 seferleri formun regroup edebileceği payload'a çevirir."""
        payload = []
        for kalem in [k for k in kiralama.kalemler if not k.is_deleted]:
            gidis = None
            donus = None
            for sefer in kiralama.nakliyeler:
                if sefer.is_deleted:
                    continue
                text = sefer.aciklama or ''
                if f'#{kalem.id}' not in text:
                    continue
                yon = sefer.yon
                if yon is None:
                    yon = 'donus' if re.search(r'Dönüş|Donus', text, re.I) else 'gidis'
                if yon == 'gidis' and gidis is None:
                    gidis = sefer
                elif yon == 'donus' and donus is None:
                    donus = sefer

            def item(sefer, yon, amount):
                return {
                    'id': sefer.id if sefer else None,
                    'sefer_uuid': sefer.sefer_uuid if sefer else str(uuid.uuid4()),
                    'yon': yon,
                    'tarih': (sefer.tarih if sefer else kalem.kiralama_baslangici).isoformat(),
                    'islem_tarihi': ((sefer.islem_tarihi or sefer.tarih) if sefer else kalem.kiralama_baslangici).isoformat(),
                    'guzergah': (sefer.guzergah if sefer else 'Legacy dönüşüm'),
                    'nakliye_tipi': (sefer.nakliye_tipi if sefer else ('taseron' if kalem.is_harici_nakliye else 'oz_mal')),
                    'arac_id': sefer.arac_id if sefer else kalem.nakliye_araci_id,
                    'taseron_firma_id': sefer.taseron_firma_id if sefer else kalem.nakliye_tedarikci_id,
                    'taseron_maliyet': str(sefer.taseron_maliyet or 0) if sefer else str(kalem.nakliye_alis_fiyat or 0),
                    'dagitimlar': [{'kiralama_kalemi_id': kalem.id, 'tutar': str(amount)}],
                }

            # PM25 dahil her kalem için zorunlu 0 TL gidiş oluşturulur.
            gidis_amount = Decimal('0')
            if gidis:
                allocation = next((d for d in gidis.dagitimlar if d.kiralama_kalemi_id == kalem.id and not d.is_deleted), None)
                gidis_amount = allocation.tutar if allocation else gidis.tutar
            payload.append(item(gidis, 'gidis', gidis_amount))
            if donus:
                allocation = next((d for d in donus.dagitimlar if d.kiralama_kalemi_id == kalem.id and not d.is_deleted), None)
                payload.append(item(donus, 'donus', allocation.tutar if allocation else (donus.tutar or Decimal('0'))))
        return payload

    @classmethod
    def convert_legacy(cls, kiralama, actor_id=None):
        """Geriye dönük çağrıları mali kayıt korumalı dönüşüme yönlendirir."""
        from app.services.nakliye_gecis_services import GuvenliNakliyeGecisService
        return GuvenliNakliyeGecisService.convert_single(kiralama, actor_id=actor_id)
