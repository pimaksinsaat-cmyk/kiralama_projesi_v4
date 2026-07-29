from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.extensions import db
from app.cari.models import HizmetKaydi
from app.nakliyeler.models import Nakliye
from app.services.base import ValidationError


def _net_kdv_orani(kdv_orani, tevkifat_str):
    """Tevkifat uygulayarak efektif KDV oranını döner. Örn: 20 & '2/10' → 16"""
    if not tevkifat_str or not kdv_orani:
        return kdv_orani
    try:
        pay, payda = map(int, str(tevkifat_str).split('/'))
        return kdv_orani * (payda - pay) / payda
    except (ValueError, ZeroDivisionError):
        return kdv_orani


def _soft_delete_hizmet(kayit, actor_id=None, deleted_at=None):
    """HizmetKaydi kaydını commit etmeden soft-delete eder."""
    if not kayit or getattr(kayit, 'is_deleted', False):
        return
    deleted_at = deleted_at or datetime.now(timezone.utc)
    kayit.is_deleted = True
    kayit.is_active = False
    kayit.deleted_at = deleted_at
    if actor_id is not None and hasattr(kayit, 'deleted_by_id'):
        kayit.deleted_by_id = actor_id
    db.session.add(kayit)


def _restore_hizmet_flags(kayit, state=None):
    """Soft-deleted HizmetKaydi flag'lerini geri yükler (commit yok)."""
    state = state or {}
    kayit.is_deleted = state.get('is_deleted', False)
    kayit.is_active = state.get('is_active', True)
    kayit.deleted_at = state.get('deleted_at')
    if 'deleted_by_id' in state:
        kayit.deleted_by_id = state.get('deleted_by_id')
    elif not kayit.is_deleted:
        kayit.deleted_by_id = None
    db.session.add(kayit)


class NakliyeService:
    """Nakliye soft-delete, restore ve ortak sorgu yardımcıları."""

    UNDO_WINDOW_SECONDS = 60

    @staticmethod
    def active_filters():
        return Nakliye.active_filters()

    @staticmethod
    def undo_session_key(nakliye_id):
        return f"nakliye_undo_snapshot:{nakliye_id}"

    @staticmethod
    def _snapshot_datetime(value):
        if value is None:
            return None
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        return str(value)

    @classmethod
    def _parse_snapshot_datetime(cls, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalize_utc(cls, dt_value):
        if dt_value is None:
            return None
        if dt_value.tzinfo is None:
            return dt_value.replace(tzinfo=timezone.utc)
        return dt_value.astimezone(timezone.utc)

    @classmethod
    def soft_delete_instance(cls, nakliye, actor_id=None, deleted_at=None):
        """Tek nakliye kaydını commit etmeden soft-delete eder."""
        if not nakliye or getattr(nakliye, 'is_deleted', False):
            return
        deleted_at = deleted_at or datetime.now(timezone.utc)
        nakliye.is_deleted = True
        nakliye.is_active = False
        nakliye.deleted_at = deleted_at
        if actor_id is not None:
            nakliye.deleted_by_id = actor_id
        db.session.add(nakliye)

    @classmethod
    def soft_delete_related_cari(cls, nakliye_id, actor_id=None, deleted_at=None):
        """Nakliyeye bağlı cari kayıtlarını soft-delete eder (commit yok)."""
        deleted_at = deleted_at or datetime.now(timezone.utc)
        kayitlar = HizmetKaydi.query.filter(
            (HizmetKaydi.nakliye_id == nakliye_id)
            | (
                (HizmetKaydi.nakliye_id.is_(None))
                & (HizmetKaydi.ozel_id == nakliye_id)
                & (HizmetKaydi.yon == 'gelen')
                & (HizmetKaydi.aciklama.like('Nakliye Taşeron Gideri:%'))
            ),
            HizmetKaydi.is_deleted.is_(False),
        ).all()
        for kayit in kayitlar:
            _soft_delete_hizmet(kayit, actor_id=actor_id, deleted_at=deleted_at)
        return kayitlar

    @classmethod
    def soft_delete_matching(cls, *criterion, actor_id=None, deleted_at=None, soft_delete_cari=True):
        """Aktif eşleşen nakliyeleri soft-delete eder; soft-deleted kayıtları yok sayar."""
        deleted_at = deleted_at or datetime.now(timezone.utc)
        seferler = Nakliye.query.filter(
            *criterion,
            *Nakliye.active_filters(),
        ).all()
        for sefer in seferler:
            if soft_delete_cari:
                cls.soft_delete_related_cari(
                    sefer.id, actor_id=actor_id, deleted_at=deleted_at
                )
            cls.soft_delete_instance(sefer, actor_id=actor_id, deleted_at=deleted_at)
        return seferler

    @classmethod
    def get_active_or_404(cls, nakliye_id):
        nakliye = Nakliye.active_query().filter_by(id=nakliye_id).first()
        if not nakliye:
            from flask import abort
            abort(404)
        return nakliye

    @classmethod
    def _snapshot_model_state(cls, instance, extra_fields=None):
        fields = ['is_deleted', 'is_active', 'deleted_at', 'deleted_by_id']
        if extra_fields:
            fields.extend(extra_fields)
        state = {}
        for field in fields:
            if not hasattr(instance, field):
                continue
            value = getattr(instance, field)
            if isinstance(value, datetime):
                value = cls._snapshot_datetime(value)
            state[field] = value
        return state

    @classmethod
    def _related_hizmetler(cls, nakliye):
        return HizmetKaydi.query.filter(
            (HizmetKaydi.nakliye_id == nakliye.id)
            | (
                (HizmetKaydi.nakliye_id.is_(None))
                & (HizmetKaydi.ozel_id == nakliye.id)
                & (HizmetKaydi.yon == 'gelen')
                & (HizmetKaydi.aciklama.like('Nakliye Taşeron Gideri:%'))
            )
        ).all()

    @classmethod
    def _collect_firma_ids(cls, nakliye, hizmetler):
        firma_ids = {nakliye.firma_id, nakliye.taseron_firma_id}
        for hizmet in hizmetler:
            firma_ids.add(hizmet.firma_id)
        return {fid for fid in firma_ids if fid}

    @classmethod
    def _sync_firma_balances(cls, firma_ids):
        from app.services.firma_services import FirmaService
        from app.firmalar.models import Firma

        for firma_id in sorted(firma_ids):
            firma = db.session.get(Firma, firma_id)
            if not firma:
                continue
            ozet = firma.bakiye_ozeti
            firma.bakiye = ozet['net_bakiye']
            FirmaService.guncelle_firma_cari_cache(firma_id, auto_commit=False)
            db.session.add(firma)

    @classmethod
    def _create_delete_snapshot(cls, nakliye, hizmetler, actor_id=None):
        now = datetime.now(timezone.utc)
        return {
            'nakliye_id': nakliye.id,
            'actor_id': actor_id,
            'created_at': cls._snapshot_datetime(now),
            'expires_at': cls._snapshot_datetime(
                now + timedelta(seconds=cls.UNDO_WINDOW_SECONDS)
            ),
            'nakliye': cls._snapshot_model_state(nakliye),
            'hizmetler': {
                str(h.id): cls._snapshot_model_state(h) for h in hizmetler if h.id
            },
        }

    @classmethod
    def _validate_restore_snapshot(cls, nakliye_id, snapshot, actor_id=None):
        if not snapshot:
            raise ValidationError(
                "Geri alma bilgisi bulunamadı veya sunucu yeniden başlatıldı."
            )
        if snapshot.get('nakliye_id') != nakliye_id:
            raise ValidationError("Geri alma bilgisi bu nakliye kaydı ile eşleşmiyor.")
        if snapshot.get('actor_id') and actor_id and snapshot.get('actor_id') != actor_id:
            raise ValidationError(
                "Bu kaydı yalnızca silme işlemini yapan kullanıcı geri alabilir."
            )
        expires_at = cls._parse_snapshot_datetime(snapshot.get('expires_at'))
        if not expires_at:
            raise ValidationError("Geri alma için silinme zamanı bulunamadı.")
        if datetime.now(timezone.utc) > cls._normalize_utc(expires_at):
            raise ValidationError(
                f"Geri alma süresi doldu ({cls.UNDO_WINDOW_SECONDS} saniye). "
                "Kayıt artık geri getirilemez."
            )

    @classmethod
    def delete_with_relations(cls, nakliye_id, actor_id=None):
        """Bağımsız nakliyeyi soft-delete eder; snapshot döner."""
        nakliye = db.session.get(Nakliye, nakliye_id)
        if not nakliye:
            raise ValidationError("Nakliye bulunamadı.")
        if getattr(nakliye, 'is_deleted', False) or not nakliye.is_active:
            raise ValidationError("Nakliye zaten silinmiş veya pasif.")
        if nakliye.kiralama_id:
            raise ValidationError("Kiralama bağlantılı kayıtlar silinemez.")

        try:
            deleted_at = datetime.now(timezone.utc)
            hizmetler = cls._related_hizmetler(nakliye)
            affected_firma_ids = cls._collect_firma_ids(nakliye, hizmetler)
            snapshot = cls._create_delete_snapshot(nakliye, hizmetler, actor_id=actor_id)

            for kayit in hizmetler:
                if not getattr(kayit, 'is_deleted', False):
                    _soft_delete_hizmet(kayit, actor_id=actor_id, deleted_at=deleted_at)

            cls.soft_delete_instance(nakliye, actor_id=actor_id, deleted_at=deleted_at)
            db.session.flush()
            cls._sync_firma_balances(affected_firma_ids)
            db.session.commit()
            return snapshot
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            raise ValidationError(f"Silme hatası: {str(e)}") from e

    @classmethod
    def restore_with_relations(cls, nakliye_id, actor_id=None, snapshot=None):
        """Soft-delete edilmiş bağımsız nakliyeyi geri yükler."""
        nakliye = db.session.get(Nakliye, nakliye_id)
        if not nakliye:
            raise ValidationError("Nakliye bulunamadı.")
        if not getattr(nakliye, 'is_deleted', False):
            raise ValidationError("Nakliye silinmiş durumda değil.")

        cls._validate_restore_snapshot(nakliye_id, snapshot, actor_id=actor_id)

        try:
            hizmetler = cls._related_hizmetler(nakliye)
            affected_firma_ids = cls._collect_firma_ids(nakliye, hizmetler)

            nakliye_state = snapshot.get('nakliye') or {}
            nakliye.is_deleted = nakliye_state.get('is_deleted', False)
            nakliye.is_active = nakliye_state.get('is_active', True)
            nakliye.deleted_at = cls._parse_snapshot_datetime(
                nakliye_state.get('deleted_at')
            )
            nakliye.deleted_by_id = nakliye_state.get('deleted_by_id')
            db.session.add(nakliye)

            hizmet_states = snapshot.get('hizmetler') or {}
            for kayit in hizmetler:
                state = hizmet_states.get(str(kayit.id))
                if state:
                    parsed = dict(state)
                    if 'deleted_at' in parsed:
                        parsed['deleted_at'] = cls._parse_snapshot_datetime(
                            parsed.get('deleted_at')
                        )
                    _restore_hizmet_flags(kayit, state=parsed)

            db.session.flush()
            cls._sync_firma_balances(affected_firma_ids)
            db.session.commit()
            return nakliye
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            raise ValidationError(f"Geri alma hatası: {str(e)}") from e


class CariServis:
    """
    Tüm modüllerin (Nakliye vb.) cari hesap işlemlerini tek bir merkezden yöneten,
    kod tekrarını önleyen ve veri bütünlüğünü sağlayan servis katmanı.
    """

    @staticmethod
    def musteri_nakliye_senkronize_et(nakliye):
        """
        Nakliye kaydına göre müşterinin (satış) cari hareketini yönetir.
        """
        if not nakliye.is_active or getattr(nakliye, 'is_deleted', False):
            # Silinmis/pasif seferin cari hareketi yeniden aktiflestirilmemeli.
            for kayit in HizmetKaydi.query.filter_by(
                nakliye_id=nakliye.id, yon='giden'
            ).all():
                if not getattr(kayit, 'is_deleted', False):
                    _soft_delete_hizmet(kayit)
            return

        hizmet = (
            HizmetKaydi.query.filter_by(nakliye_id=nakliye.id, yon='giden')
            .order_by(HizmetKaydi.is_deleted.asc(), HizmetKaydi.id.asc())
            .first()
        )

        aciklama = f"Nakliye Hizmeti: {nakliye.plaka or ''} | {nakliye.guzergah}"

        nakliye_islem_tarihi = getattr(nakliye, 'islem_tarihi', None) or nakliye.tarih
        if hizmet:
            hizmet.firma_id = nakliye.firma_id
            hizmet.tarih = nakliye.tarih
            hizmet.islem_tarihi = nakliye_islem_tarihi
            hizmet.tutar = nakliye.toplam_tutar
            hizmet.aciklama = aciklama
            hk_kdv = getattr(nakliye, 'kdv_orani', None) or 0
            hizmet.kdv_orani = _net_kdv_orani(
                hk_kdv, getattr(nakliye, 'tevkifat_orani', None) or ''
            )
            hizmet.is_deleted = False
            hizmet.is_active = True
            hizmet.deleted_at = None
            hizmet.deleted_by_id = None
        else:
            hk_kdv = getattr(nakliye, 'kdv_orani', None) or 0
            hizmet = HizmetKaydi(
                firma_id=nakliye.firma_id,
                tarih=nakliye.tarih,
                islem_tarihi=nakliye_islem_tarihi,
                tutar=nakliye.toplam_tutar,
                yon='giden',
                aciklama=aciklama,
                nakliye_id=nakliye.id,
                kdv_orani=_net_kdv_orani(
                    hk_kdv, getattr(nakliye, 'tevkifat_orani', None) or ''
                ),
            )
            db.session.add(hizmet)

    @staticmethod
    def taseron_maliyet_senkronize_et(nakliye):
        """
        Taşeron nakliyelerde tedarikçinin alacak kaydını (maliyet) yönetir.
        """
        if not nakliye.is_active or getattr(nakliye, 'is_deleted', False):
            maliyet_kayitlari = HizmetKaydi.query.filter(
                db.or_(
                    HizmetKaydi.nakliye_id == nakliye.id,
                    db.and_(
                        HizmetKaydi.nakliye_id.is_(None),
                        HizmetKaydi.ozel_id == nakliye.id,
                        HizmetKaydi.yon == 'gelen',
                        HizmetKaydi.aciklama.like('Nakliye Taşeron Gideri:%'),
                    ),
                )
            ).all()
            for kayit in maliyet_kayitlari:
                if not getattr(kayit, 'is_deleted', False):
                    _soft_delete_hizmet(kayit)
            return

        eski_maliyet = (
            HizmetKaydi.query.filter_by(nakliye_id=nakliye.id, yon='gelen')
            .order_by(HizmetKaydi.is_deleted.asc(), HizmetKaydi.id.asc())
            .first()
        )
        if not eski_maliyet:
            eski_maliyet = (
                HizmetKaydi.query.filter(
                    HizmetKaydi.nakliye_id.is_(None),
                    HizmetKaydi.ozel_id == nakliye.id,
                    HizmetKaydi.yon == 'gelen',
                    HizmetKaydi.aciklama.like('Nakliye Taşeron Gideri:%'),
                )
                .order_by(HizmetKaydi.is_deleted.asc(), HizmetKaydi.id.asc())
                .first()
            )

        nakliye_islem_tarihi = getattr(nakliye, 'islem_tarihi', None) or nakliye.tarih
        if (
            nakliye.nakliye_tipi == 'taseron'
            and nakliye.taseron_firma_id
            and nakliye.taseron_maliyet
            and nakliye.taseron_maliyet > 0
        ):
            aciklama = (
                f"Nakliye Taşeron Gideri: {nakliye.guzergah} ({nakliye.plaka or ''})"
            )
            hk_kdv = getattr(nakliye, 'taseron_kdv_orani', None)
            if hk_kdv is None:
                hk_kdv = getattr(nakliye, 'kdv_orani', None)
            if hk_kdv is None:
                hk_kdv = 0
            if eski_maliyet:
                eski_maliyet.firma_id = nakliye.taseron_firma_id
                eski_maliyet.nakliye_id = nakliye.id
                eski_maliyet.ozel_id = None
                eski_maliyet.tutar = nakliye.taseron_maliyet
                eski_maliyet.tarih = nakliye.tarih
                eski_maliyet.islem_tarihi = nakliye_islem_tarihi
                eski_maliyet.aciklama = aciklama
                eski_maliyet.kdv_orani = hk_kdv
                eski_maliyet.nakliye_alis_kdv = hk_kdv
                eski_maliyet.is_deleted = False
                eski_maliyet.is_active = True
                eski_maliyet.deleted_at = None
                eski_maliyet.deleted_by_id = None
            else:
                yeni_maliyet = HizmetKaydi(
                    firma_id=nakliye.taseron_firma_id,
                    tarih=nakliye.tarih,
                    islem_tarihi=nakliye_islem_tarihi,
                    tutar=nakliye.taseron_maliyet,
                    yon='gelen',
                    aciklama=aciklama,
                    nakliye_id=nakliye.id,
                    kdv_orani=hk_kdv,
                    nakliye_alis_kdv=hk_kdv,
                )
                db.session.add(yeni_maliyet)
        elif eski_maliyet:
            _soft_delete_hizmet(eski_maliyet)

    @staticmethod
    def nakliye_cari_temizle(nakliye_id, actor_id=None, deleted_at=None):
        """
        Nakliye silindiğinde bağlı cari kayıtları soft-delete eder.
        """
        return NakliyeService.soft_delete_related_cari(
            nakliye_id, actor_id=actor_id, deleted_at=deleted_at
        )
