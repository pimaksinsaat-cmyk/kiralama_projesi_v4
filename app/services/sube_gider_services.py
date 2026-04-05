from datetime import date, datetime, timedelta

from sqlalchemy import inspect, or_

from app.extensions import db
from app.services.base import BaseService, ValidationError
from app.subeler.models import Sube, SubeGideri, SubeSabitGiderDonemi


class SubeGiderService(BaseService):
    model = SubeGideri
    updatable_fields = ['sube_id', 'tarih', 'kategori', 'tutar', 'aciklama', 'fatura_no']

    @staticmethod
    def table_exists():
        return inspect(db.engine).has_table(SubeGideri.__tablename__)

    @staticmethod
    def _parse_date(value):
        if isinstance(value, str) and value:
            return datetime.strptime(value, '%Y-%m-%d').date()
        return value or None

    @classmethod
    def _normalize_payload(cls, payload):
        normalized = dict(payload or {})
        normalized['sube_id'] = int(normalized['sube_id']) if normalized.get('sube_id') else None
        normalized['tarih'] = cls._parse_date(normalized.get('tarih'))
        normalized['kategori'] = (normalized.get('kategori') or '').strip()
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
    updatable_fields = ['kategori', 'baslangic_tarihi', 'bitis_tarihi', 'aylik_tutar', 'kdv_orani', 'aciklama', 'is_active']

    @staticmethod
    def table_exists():
        return inspect(db.engine).has_table(SubeSabitGiderDonemi.__tablename__)

    @staticmethod
    def _parse_date(value):
        if isinstance(value, str) and value:
            return datetime.strptime(value, '%Y-%m-%d').date()
        return value or None

    @classmethod
    def _normalize_payload(cls, payload):
        normalized = dict(payload or {})
        normalized['sube_id'] = int(normalized['sube_id']) if normalized.get('sube_id') else None
        normalized['kategori'] = (normalized.get('kategori') or '').strip()
        normalized['baslangic_tarihi'] = cls._parse_date(normalized.get('baslangic_tarihi'))
        normalized['bitis_tarihi'] = cls._parse_date(normalized.get('bitis_tarihi'))
        normalized['aciklama'] = (normalized.get('aciklama') or '').strip() or None
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
            raise ValidationError('Aylik tutar 0 dan buyuk olmalidir.')

    @classmethod
    def list_donemler(cls, sube_id):
        return (
            cls._get_base_query()
            .filter_by(sube_id=sube_id)
            .order_by(SubeSabitGiderDonemi.is_active.desc(), SubeSabitGiderDonemi.baslangic_tarihi.desc(), SubeSabitGiderDonemi.id.desc())
            .all()
        )

    @classmethod
    def calculate_monthly_total(cls, sube_id, year, month):
        period_start = date(year, month, 1)
        if month == 12:
            period_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            period_end = date(year, month + 1, 1) - timedelta(days=1)

        donemler = (
            cls._get_base_query()
            .filter(
                SubeSabitGiderDonemi.sube_id == sube_id,
                SubeSabitGiderDonemi.baslangic_tarihi <= period_end,
                or_(SubeSabitGiderDonemi.bitis_tarihi.is_(None), SubeSabitGiderDonemi.bitis_tarihi >= period_start),
            )
            .all()
        )
        return sum(float(donem.aylik_tutar or 0) for donem in donemler)

    @classmethod
    def list_aktif_donemler(cls, sube_id):
        return (
            cls._get_base_query()
            .filter_by(sube_id=sube_id, is_active=True)
            .order_by(SubeSabitGiderDonemi.baslangic_tarihi.desc(), SubeSabitGiderDonemi.id.desc())
            .all()
        )

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
                ayni_baslangic.kdv_orani = instance.kdv_orani
                ayni_baslangic.aciklama = instance.aciklama
                ayni_baslangic.is_active = True
                db.session.add(ayni_baslangic)
                db.session.commit()
                return ayni_baslangic

            for donem in cakisan_donemler:
                donem.bitis_tarihi = instance.baslangic_tarihi - timedelta(days=1)
                donem.is_active = False
                db.session.add(donem)

            cls._apply_audit_log(instance, is_new=True, actor_id=actor_id)
            db.session.add(instance)
            db.session.commit()
            return instance
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as exc:
            db.session.rollback()
            raise Exception('Sube sabit gider donemi kaydedilirken hata olustu.') from exc

    @classmethod
    def stop_donem(cls, donem_id, bitis_tarihi=None):
        donem = cls.get_by_id(donem_id)
        if not donem:
            raise ValidationError('Sonlandirilacak sabit gider donemi bulunamadi.')

        stop_date = cls._parse_date(bitis_tarihi) or date.today()
        if stop_date < donem.baslangic_tarihi:
            raise ValidationError('Bitis tarihi baslangic tarihinden once olamaz.')

        try:
            donem.bitis_tarihi = stop_date
            donem.is_active = False
            db.session.add(donem)
            db.session.commit()
            return donem
        except Exception as exc:
            db.session.rollback()
            raise Exception('Sabit gider donemi sonlandirilirken hata olustu.') from exc