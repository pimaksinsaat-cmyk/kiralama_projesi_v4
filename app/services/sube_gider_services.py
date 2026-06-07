import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import inspect, or_

from app.extensions import db
from app.services.base import BaseService, ValidationError
from app.subeler.models import Sube, SubeGideri, SubeSabitGiderDonemi
from app.utils import bugun as _bugun


class SubeGiderService(BaseService):
    model = SubeGideri
    use_soft_delete = True
    updatable_fields = ['sube_id', 'arac_id', 'tarih', 'kategori', 'tutar', 'litre', 'birim_fiyat', 'km', 'istasyon', 'aciklama', 'fatura_no']

    @staticmethod
    def table_exists():
        return inspect(db.engine).has_table(SubeGideri.__tablename__)

    @staticmethod
    def _parse_date(value):
        if isinstance(value, str) and value:
            return datetime.strptime(value, '%Y-%m-%d').date()
        return value or None

    @staticmethod
    def _parse_decimal(value):
        if value in (None, ''):
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value).replace('.', '').replace(',', '.'))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @classmethod
    def _normalize_payload(cls, payload):
        normalized = dict(payload or {})
        normalized['sube_id'] = int(normalized['sube_id']) if normalized.get('sube_id') else None
        normalized['arac_id'] = int(normalized['arac_id']) if normalized.get('arac_id') else None
        normalized['tarih'] = cls._parse_date(normalized.get('tarih'))
        normalized['kategori'] = (normalized.get('kategori') or '').strip()
        normalized['litre'] = cls._parse_decimal(normalized.get('litre'))
        normalized['birim_fiyat'] = cls._parse_decimal(normalized.get('birim_fiyat'))
        normalized['km'] = int(normalized['km']) if normalized.get('km') not in (None, '') else None
        normalized['istasyon'] = (normalized.get('istasyon') or '').strip() or None
        normalized['aciklama'] = (normalized.get('aciklama') or '').strip() or None
        normalized['fatura_no'] = (normalized.get('fatura_no') or '').strip() or None
        return normalized

    @classmethod
    def validate(cls, instance, is_new=True):
        if not instance.sube_id:
            raise ValidationError('Sube secimi zorunludur.')
        if not Sube.query.filter_by(id=instance.sube_id, is_active=True).first():
            raise ValidationError('Secilen sube bulunamadi.')
        if not instance.tarih:
            raise ValidationError('Tarih zorunludur.')
        if not (instance.kategori or '').strip():
            raise ValidationError('Kategori zorunludur.')
        if instance.tutar is None or float(instance.tutar) <= 0:
            raise ValidationError('Tutar 0 dan buyuk olmalidir.')

    @classmethod
    def list_giderler(cls, sube_id):
        return cls._get_base_query().filter_by(sube_id=sube_id).order_by(SubeGideri.tarih.desc(), SubeGideri.id.desc()).all()

    @classmethod
    def list_giderler_for_month(cls, sube_id, year, month):
        period_start = date(year, month, 1)
        if month == 12:
            period_end = date(year + 1, 1, 1)
        else:
            period_end = date(year, month + 1, 1)

        return (
            cls._get_base_query()
            .filter(
                SubeGideri.sube_id == sube_id,
                SubeGideri.tarih >= period_start,
                SubeGideri.tarih < period_end,
            )
            .order_by(SubeGideri.tarih.desc(), SubeGideri.id.desc())
            .all()
        )

    @staticmethod
    def build_category_totals(giderler):
        kategori_toplamlar = {}
        for gider in giderler:
            kategori_toplamlar.setdefault(gider.kategori, 0.0)
            kategori_toplamlar[gider.kategori] += float(gider.tutar or 0)
        return kategori_toplamlar

    @classmethod
    def create_gider(cls, payload, actor_id=None):
        instance = cls.model(**cls._normalize_payload(payload))
        return cls.save(instance, is_new=True, actor_id=actor_id)

    @classmethod
    def delete_gider(cls, gider_id):
        return cls.delete(gider_id)


class SubeSabitGiderDonemiService(BaseService):
    model = SubeSabitGiderDonemi
    use_soft_delete = True
    updatable_fields = ['kategori', 'baslangic_tarihi', 'bitis_tarihi', 'aylik_tutar', 'periyot_gun_sayisi', 'periyot_tipi', 'periyot_degeri', 'kdv_orani', 'aciklama', 'is_active', 'apply_retroactively']

    @staticmethod
    def table_exists():
        return inspect(db.engine).has_table(SubeSabitGiderDonemi.__tablename__)

    @staticmethod
    def _parse_date(value):
        if isinstance(value, str) and value:
            return datetime.strptime(value, '%Y-%m-%d').date()
        return value or None

    @staticmethod
    def _parse_positive_int(value, default=30):
        if value in (None, ''):
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed

    @staticmethod
    def _normalize_period_type(value):
        value = (value or 'ay').strip()
        return value if value in ('gun', 'ay', 'yil') else 'ay'

    @staticmethod
    def _add_months(start_date, months):
        month_index = start_date.month - 1 + months
        year = start_date.year + month_index // 12
        month = month_index % 12 + 1
        day = min(start_date.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    @classmethod
    def _next_period_start(cls, start_date, period_type, period_value):
        if period_type == 'gun':
            return start_date + timedelta(days=period_value)
        if period_type == 'yil':
            return cls._add_months(start_date, period_value * 12)
        return cls._add_months(start_date, period_value)

    @classmethod
    def _calculate_periodized_overlap(cls, donem, effective_start, effective_end, report_start, report_end):
        period_type = cls._normalize_period_type(getattr(donem, 'periyot_tipi', None))
        period_value = int(getattr(donem, 'periyot_degeri', None) or 1)
        if period_value <= 0:
            period_value = 1

        period_amount = float(donem.aylik_tutar or 0)
        total = 0.0
        cursor = effective_start
        guard = 0

        while cursor <= effective_end and cursor <= report_end:
            next_start = cls._next_period_start(cursor, period_type, period_value)
            if next_start <= cursor:
                break

            period_end = min(next_start - timedelta(days=1), effective_end)
            overlap_start = max(cursor, report_start)
            overlap_end = min(period_end, report_end)
            if overlap_end >= overlap_start:
                period_days = (period_end - cursor).days + 1
                overlap_days = (overlap_end - overlap_start).days + 1
                total += period_amount * (overlap_days / period_days)

            cursor = next_start
            guard += 1
            if guard > 10000:
                raise ValidationError('Periyot hesabi cok fazla tekrar urettigi icin durduruldu.')

        return total

    @classmethod
    def build_timeline_metadata(cls, donemler, reference_date=None):
        reference_date = reference_date or _bugun()
        grouped = {}
        metadata = {}

        for donem in sorted(
            donemler,
            key=lambda row: ((row.kategori or ''), row.baslangic_tarihi or date.min, row.id or 0),
        ):
            grouped.setdefault(donem.kategori, []).append(donem)

        for kategori_donemleri in grouped.values():
            for index, donem in enumerate(kategori_donemleri):
                onceki_var = index > 0
                sonraki_donem = kategori_donemleri[index + 1] if index + 1 < len(kategori_donemleri) else None

                effective_start = donem.baslangic_tarihi
                effective_end = donem.bitis_tarihi

                if sonraki_donem and sonraki_donem.baslangic_tarihi:
                    next_boundary = sonraki_donem.baslangic_tarihi - timedelta(days=1)
                    if effective_end is None or effective_end > next_boundary:
                        effective_end = next_boundary

                if effective_start and effective_start > reference_date:
                    status = 'planned'
                elif effective_end and effective_end <= reference_date:
                    status = 'ended'
                else:
                    status = 'active'

                metadata[donem.id] = {
                    'effective_start': effective_start,
                    'effective_end': effective_end,
                    'status': status,
                    'status_label': {
                        'planned': 'Planli',
                        'active': 'Aktif',
                        'ended': 'Kapandi',
                    }[status],
                    'is_first_period': not onceki_var,
                    'has_next_period': sonraki_donem is not None,
                }

        return metadata

    @staticmethod
    def _resolve_period_status(donem, reference_date=None):
        reference_date = reference_date or _bugun()
        if donem.baslangic_tarihi and donem.baslangic_tarihi > reference_date:
            return 'planned'
        if donem.bitis_tarihi and donem.bitis_tarihi <= reference_date:
            return 'ended'
        return 'active'

    @classmethod
    def _sync_active_flag(cls, donem, reference_date=None):
        donem.is_active = cls._resolve_period_status(donem, reference_date=reference_date) == 'active'
        return donem

    @classmethod
    def _sync_category_flags(cls, sube_id, kategori, reference_date=None):
        donemler = (
            cls._get_base_query()
            .filter(
                SubeSabitGiderDonemi.sube_id == sube_id,
                SubeSabitGiderDonemi.kategori == kategori,
            )
            .order_by(SubeSabitGiderDonemi.baslangic_tarihi.asc(), SubeSabitGiderDonemi.id.asc())
            .all()
        )
        metadata = cls.build_timeline_metadata(donemler, reference_date=reference_date)
        for donem in donemler:
            donem.is_active = metadata.get(donem.id, {}).get('status') == 'active'
            db.session.add(donem)
        return metadata

    @classmethod
    def _normalize_payload(cls, payload):
        normalized = dict(payload or {})
        normalized['sube_id'] = int(normalized['sube_id']) if normalized.get('sube_id') else None
        normalized['kategori'] = (normalized.get('kategori') or '').strip()
        normalized['baslangic_tarihi'] = cls._parse_date(normalized.get('baslangic_tarihi'))
        normalized['bitis_tarihi'] = cls._parse_date(normalized.get('bitis_tarihi'))
        normalized['periyot_gun_sayisi'] = cls._parse_positive_int(normalized.get('periyot_gun_sayisi'), default=30)
        normalized['periyot_tipi'] = cls._normalize_period_type(normalized.get('periyot_tipi'))
        normalized['periyot_degeri'] = cls._parse_positive_int(normalized.get('periyot_degeri'), default=1)
        normalized['aciklama'] = (normalized.get('aciklama') or '').strip() or None
        normalized['apply_retroactively'] = False
        return normalized

    @classmethod
    def validate(cls, instance, is_new=True):
        if not instance.sube_id:
            raise ValidationError('Sube secimi zorunludur.')
        if not Sube.query.filter_by(id=instance.sube_id, is_active=True).first():
            raise ValidationError('Secilen sube bulunamadi.')
        if not (instance.kategori or '').strip():
            raise ValidationError('Kategori zorunludur.')
        if not instance.baslangic_tarihi:
            raise ValidationError('Baslangic tarihi zorunludur.')
        if instance.bitis_tarihi and instance.bitis_tarihi < instance.baslangic_tarihi:
            raise ValidationError('Bitis tarihi baslangic tarihinden once olamaz.')
        if instance.aylik_tutar is None or float(instance.aylik_tutar) <= 0:
            raise ValidationError('Periyot tutari 0 dan buyuk olmalidir.')
        if not instance.periyot_degeri or int(instance.periyot_degeri) <= 0:
            raise ValidationError('Periyot araligi 0 dan buyuk olmalidir.')
        if (instance.periyot_tipi or '').strip() not in ('gun', 'ay', 'yil'):
            raise ValidationError('Periyot tipi gecersiz.')

    @classmethod
    def list_donemler(cls, sube_id):
        return (
            cls._get_base_query()
            .filter_by(sube_id=sube_id)
            .order_by(SubeSabitGiderDonemi.baslangic_tarihi.desc(), SubeSabitGiderDonemi.id.desc())
            .all()
        )

    @classmethod
    def calculate_monthly_total(cls, sube_id, year, month):
        period_start = date(year, month, 1)
        if month == 12:
            period_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            period_end = date(year, month + 1, 1) - timedelta(days=1)

        # Icinde bulunulan ay ise hesabi bugune kadar kap
        today = _bugun()
        effective_period_end = min(period_end, today) if period_start <= today <= period_end else period_end
        if effective_period_end < period_start:
            return 0.0

        donemler = cls.list_donemler(sube_id)
        metadata = cls.build_timeline_metadata(donemler, reference_date=effective_period_end)

        toplam = 0.0
        for donem in donemler:
            meta = metadata.get(donem.id, {})
            effective_start = meta.get('effective_start') or period_start
            effective_end = meta.get('effective_end') or effective_period_end

            overlap_start = max(effective_start, period_start)
            overlap_end = min(effective_end, effective_period_end)
            if overlap_end < overlap_start:
                continue

            toplam += cls._calculate_periodized_overlap(
                donem,
                effective_start,
                effective_end,
                period_start,
                effective_period_end,
            )

        return toplam

    @classmethod
    def list_aktif_donemler(cls, sube_id, reference_date=None):
        reference_date = reference_date or _bugun()
        donemler = cls.list_donemler(sube_id)
        metadata = cls.build_timeline_metadata(donemler, reference_date=reference_date)
        return [donem for donem in donemler if metadata.get(donem.id, {}).get('status') == 'active']

    @classmethod
    def create_donem(cls, payload, actor_id=None):
        normalized = cls._normalize_payload(payload)
        instance = cls.model(**normalized)

        try:
            cls.validate(instance, is_new=True)

            cakisan_donemler = (
                cls._get_base_query()
                .filter(
                    SubeSabitGiderDonemi.sube_id == instance.sube_id,
                    SubeSabitGiderDonemi.kategori == instance.kategori,
                    SubeSabitGiderDonemi.baslangic_tarihi <= instance.baslangic_tarihi,
                    or_(SubeSabitGiderDonemi.bitis_tarihi.is_(None), SubeSabitGiderDonemi.bitis_tarihi >= instance.baslangic_tarihi),
                )
                .order_by(SubeSabitGiderDonemi.baslangic_tarihi.desc(), SubeSabitGiderDonemi.id.desc())
                .all()
            )

            ayni_baslangic = next((donem for donem in cakisan_donemler if donem.baslangic_tarihi == instance.baslangic_tarihi), None)
            if ayni_baslangic:
                ayni_baslangic.aylik_tutar = instance.aylik_tutar
                ayni_baslangic.periyot_gun_sayisi = instance.periyot_gun_sayisi
                ayni_baslangic.periyot_tipi = instance.periyot_tipi
                ayni_baslangic.periyot_degeri = instance.periyot_degeri
                ayni_baslangic.kdv_orani = instance.kdv_orani
                ayni_baslangic.aciklama = instance.aciklama
                ayni_baslangic.apply_retroactively = False
                db.session.add(ayni_baslangic)
                db.session.flush()
                cls._sync_category_flags(ayni_baslangic.sube_id, ayni_baslangic.kategori)
                db.session.commit()
                return ayni_baslangic

            sonraki_donem = (
                cls._get_base_query()
                .filter(
                    SubeSabitGiderDonemi.sube_id == instance.sube_id,
                    SubeSabitGiderDonemi.kategori == instance.kategori,
                    SubeSabitGiderDonemi.baslangic_tarihi > instance.baslangic_tarihi,
                )
                .order_by(SubeSabitGiderDonemi.baslangic_tarihi.asc(), SubeSabitGiderDonemi.id.asc())
                .first()
            )
            if sonraki_donem:
                instance.bitis_tarihi = sonraki_donem.baslangic_tarihi - timedelta(days=1)

            for donem in cakisan_donemler:
                donem.bitis_tarihi = instance.baslangic_tarihi - timedelta(days=1)
                db.session.add(donem)

            cls._apply_audit_log(instance, is_new=True, actor_id=actor_id)
            db.session.add(instance)
            db.session.flush()
            cls._sync_category_flags(instance.sube_id, instance.kategori)
            db.session.commit()
            return instance
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as exc:
            db.session.rollback()
            raise Exception('Sube sabit gider donemi kaydedilirken hata olustu.') from exc

    @classmethod
    def update_donem(cls, donem_id, payload, actor_id=None):
        donem = cls.get_by_id(donem_id)
        if not donem:
            raise ValidationError('Guncellenecek sabit gider donemi bulunamadi.')

        normalized = cls._normalize_payload(payload)
        eski_bitis_tarihi = donem.bitis_tarihi

        try:
            donem.baslangic_tarihi = normalized.get('baslangic_tarihi')
            donem.aylik_tutar = payload.get('aylik_tutar')
            donem.periyot_gun_sayisi = normalized.get('periyot_gun_sayisi')
            donem.periyot_tipi = normalized.get('periyot_tipi')
            donem.periyot_degeri = normalized.get('periyot_degeri')
            donem.kdv_orani = payload.get('kdv_orani')
            donem.aciklama = normalized.get('aciklama')
            donem.apply_retroactively = False

            cls.validate(donem, is_new=False)

            ayni_tarih_baska_donem = (
                cls._get_base_query()
                .filter(
                    SubeSabitGiderDonemi.id != donem.id,
                    SubeSabitGiderDonemi.sube_id == donem.sube_id,
                    SubeSabitGiderDonemi.kategori == donem.kategori,
                    SubeSabitGiderDonemi.baslangic_tarihi == donem.baslangic_tarihi,
                )
                .first()
            )
            if ayni_tarih_baska_donem:
                raise ValidationError('Ayni kategori icin bu baslangic tarihine sahip baska bir donem zaten var.')

            onceki_donem = (
                cls._get_base_query()
                .filter(
                    SubeSabitGiderDonemi.id != donem.id,
                    SubeSabitGiderDonemi.sube_id == donem.sube_id,
                    SubeSabitGiderDonemi.kategori == donem.kategori,
                    SubeSabitGiderDonemi.baslangic_tarihi < donem.baslangic_tarihi,
                )
                .order_by(SubeSabitGiderDonemi.baslangic_tarihi.desc(), SubeSabitGiderDonemi.id.desc())
                .first()
            )

            sonraki_donem = (
                cls._get_base_query()
                .filter(
                    SubeSabitGiderDonemi.id != donem.id,
                    SubeSabitGiderDonemi.sube_id == donem.sube_id,
                    SubeSabitGiderDonemi.kategori == donem.kategori,
                    SubeSabitGiderDonemi.baslangic_tarihi > donem.baslangic_tarihi,
                )
                .order_by(SubeSabitGiderDonemi.baslangic_tarihi.asc(), SubeSabitGiderDonemi.id.asc())
                .first()
            )

            if onceki_donem:
                onceki_donem.bitis_tarihi = donem.baslangic_tarihi - timedelta(days=1)
                db.session.add(onceki_donem)

            if sonraki_donem:
                donem.bitis_tarihi = sonraki_donem.baslangic_tarihi - timedelta(days=1)
            else:
                donem.bitis_tarihi = eski_bitis_tarihi if eski_bitis_tarihi and eski_bitis_tarihi >= donem.baslangic_tarihi else None

            if donem.bitis_tarihi and donem.bitis_tarihi < donem.baslangic_tarihi:
                raise ValidationError('Bitis tarihi baslangic tarihinden once olamaz.')

            cls._apply_audit_log(donem, is_new=False, actor_id=actor_id)
            db.session.add(donem)
            db.session.flush()
            cls._sync_category_flags(donem.sube_id, donem.kategori)
            db.session.commit()
            return donem
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as exc:
            db.session.rollback()
            raise Exception('Sabit gider donemi guncellenirken hata olustu.') from exc

    @classmethod
    def create_new_price_period(cls, donem_id, payload, actor_id=None):
        mevcut_donem = cls.get_by_id(donem_id)
        if not mevcut_donem:
            raise ValidationError('Yeni fiyat eklenecek sabit gider donemi bulunamadi.')

        normalized_payload = dict(payload or {})
        normalized_payload['sube_id'] = mevcut_donem.sube_id
        normalized_payload['kategori'] = mevcut_donem.kategori
        normalized_payload['apply_retroactively'] = False
        return cls.create_donem(normalized_payload, actor_id=actor_id)

    @classmethod
    def stop_donem(cls, donem_id, bitis_tarihi=None):
        donem = cls.get_by_id(donem_id)
        if not donem:
            raise ValidationError('Sonlandirilacak sabit gider donemi bulunamadi.')

        stop_date = cls._parse_date(bitis_tarihi) or _bugun()
        kategori_donemleri = (
            cls._get_base_query()
            .filter(
                SubeSabitGiderDonemi.sube_id == donem.sube_id,
                SubeSabitGiderDonemi.kategori == donem.kategori,
            )
            .order_by(SubeSabitGiderDonemi.baslangic_tarihi.asc(), SubeSabitGiderDonemi.id.asc())
            .all()
        )
        timeline = cls.build_timeline_metadata(kategori_donemleri)
        effective_start = timeline.get(donem.id, {}).get('effective_start')

        if effective_start and stop_date < effective_start:
            raise ValidationError('Bitis tarihi baslangic tarihinden once olamaz.')

        sonraki_donem = (
            cls._get_base_query()
            .filter(
                SubeSabitGiderDonemi.id != donem.id,
                SubeSabitGiderDonemi.sube_id == donem.sube_id,
                SubeSabitGiderDonemi.kategori == donem.kategori,
                SubeSabitGiderDonemi.baslangic_tarihi > donem.baslangic_tarihi,
            )
            .order_by(SubeSabitGiderDonemi.baslangic_tarihi.asc(), SubeSabitGiderDonemi.id.asc())
            .first()
        )
        if sonraki_donem and stop_date >= sonraki_donem.baslangic_tarihi:
            raise ValidationError('Bitis tarihi sonraki donemin baslangic tarihinden once olmalidir.')

        try:
            donem.bitis_tarihi = stop_date
            db.session.add(donem)
            db.session.flush()
            cls._sync_category_flags(donem.sube_id, donem.kategori)
            db.session.commit()
            return donem
        except Exception as exc:
            db.session.rollback()
            raise Exception('Sabit gider donemi sonlandirilirken hata olustu.') from exc

    @classmethod
    def undo_stop_donem(cls, donem_id):
        donem = cls.get_by_id(donem_id)
        if not donem:
            raise ValidationError('Geri alinacak sabit gider donemi bulunamadi.')

        sonraki_donem = (
            cls._get_base_query()
            .filter(
                SubeSabitGiderDonemi.id != donem.id,
                SubeSabitGiderDonemi.sube_id == donem.sube_id,
                SubeSabitGiderDonemi.kategori == donem.kategori,
                SubeSabitGiderDonemi.baslangic_tarihi > donem.baslangic_tarihi,
            )
            .order_by(SubeSabitGiderDonemi.baslangic_tarihi.asc(), SubeSabitGiderDonemi.id.asc())
            .first()
        )
        if sonraki_donem:
            raise ValidationError('Bu donemden sonra daha yeni bir donem oldugu icin geri alma yapilamaz.')

        if donem.bitis_tarihi is None:
            raise ValidationError('Bu sabit gider donemi zaten aktif durumda.')

        try:
            donem.bitis_tarihi = None
            db.session.add(donem)
            db.session.flush()
            cls._sync_category_flags(donem.sube_id, donem.kategori)
            db.session.commit()
            return donem
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as exc:
            db.session.rollback()
            raise Exception('Sabit gider durdurma islemi geri alinirken hata olustu.') from exc

    @classmethod
    def delete_donem(cls, donem_id):
        donem = cls.get_by_id(donem_id)
        if not donem:
            raise ValidationError('Silinecek sabit gider donemi bulunamadi.')

        try:
            onceki_donem = (
                cls._get_base_query()
                .filter(
                    SubeSabitGiderDonemi.id != donem.id,
                    SubeSabitGiderDonemi.sube_id == donem.sube_id,
                    SubeSabitGiderDonemi.kategori == donem.kategori,
                    SubeSabitGiderDonemi.baslangic_tarihi < donem.baslangic_tarihi,
                )
                .order_by(SubeSabitGiderDonemi.baslangic_tarihi.desc(), SubeSabitGiderDonemi.id.desc())
                .first()
            )

            sonraki_donem = (
                cls._get_base_query()
                .filter(
                    SubeSabitGiderDonemi.id != donem.id,
                    SubeSabitGiderDonemi.sube_id == donem.sube_id,
                    SubeSabitGiderDonemi.kategori == donem.kategori,
                    SubeSabitGiderDonemi.baslangic_tarihi > donem.baslangic_tarihi,
                )
                .order_by(SubeSabitGiderDonemi.baslangic_tarihi.asc(), SubeSabitGiderDonemi.id.asc())
                .first()
            )

            onceki_bagli_mi = (
                onceki_donem
                and (
                    onceki_donem.bitis_tarihi is None
                    or onceki_donem.bitis_tarihi == donem.baslangic_tarihi - timedelta(days=1)
                )
            )

            if onceki_bagli_mi:
                onceki_donem.bitis_tarihi = (
                    sonraki_donem.baslangic_tarihi - timedelta(days=1)
                    if sonraki_donem
                    else None
                )
                if onceki_donem.bitis_tarihi and onceki_donem.bitis_tarihi < onceki_donem.baslangic_tarihi:
                    raise ValidationError('Onceki donemin bitis tarihi gecersiz hale geliyor.')
                db.session.add(onceki_donem)

            db.session.delete(donem)
            db.session.flush()
            cls._sync_category_flags(donem.sube_id, donem.kategori)
            db.session.commit()
            return True
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as exc:
            db.session.rollback()
            raise Exception('Sabit gider donemi silinirken hata olustu.') from exc
