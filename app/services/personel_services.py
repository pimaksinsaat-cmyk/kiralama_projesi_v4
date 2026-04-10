from datetime import date, datetime, timedelta

from sqlalchemy import inspect, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.personel.models import Personel, PersonelIzin, PersonelMaasDonemi
from app.services.base import BaseService, ValidationError
from app.subeler.models import Sube
from app.utils import tr_ilike


class PersonelService(BaseService):
    model = Personel
    use_soft_delete = True
    period_cost_field_map = {
        'maas': 'aylik_maas',
        'yemek_ucreti': 'aylik_yemek_ucreti',
        'yol_ucreti': 'aylik_yol_ucreti',
    }
    period_additional_cost_fields = [
        'sgk_isveren_tutari',
        'yan_haklar_tutari',
        'diger_gider_tutari',
    ]
    updatable_fields = [
        'sube_id',
        'ad',
        'soyad',
        'tc_no',
        'telefon',
        'meslek',
        'maas',
        'yemek_ucreti',
        'yol_ucreti',
        'ise_giris_tarihi',
        'isten_cikis_tarihi',
    ]

    @staticmethod
    def table_exists():
        return inspect(db.engine).has_table(Personel.__tablename__)

    @staticmethod
    def salary_periods_table_exists():
        return inspect(db.engine).has_table(PersonelMaasDonemi.__tablename__)

    @staticmethod
    def _parse_date(value):
        if isinstance(value, str) and value:
            return datetime.strptime(value, '%Y-%m-%d').date()
        return value or None

    @classmethod
    def _normalize_payload(cls, payload):
        normalized = dict(payload or {})
        normalized['sube_id'] = normalized.get('sube_id') or None
        normalized['submission_token'] = (normalized.get('submission_token') or '').strip() or None
        normalized['ad'] = (normalized.get('ad') or '').strip()
        normalized['soyad'] = (normalized.get('soyad') or '').strip()
        normalized['tc_no'] = (normalized.get('tc_no') or '').strip() or None
        normalized['telefon'] = (normalized.get('telefon') or '').strip() or None
        normalized['meslek'] = (normalized.get('meslek') or '').strip() or None
        normalized['ise_giris_tarihi'] = cls._parse_date(normalized.get('ise_giris_tarihi'))
        normalized['isten_cikis_tarihi'] = cls._parse_date(normalized.get('isten_cikis_tarihi'))
        normalized['maas_gecerlilik_tarihi'] = cls._parse_date(normalized.get('maas_gecerlilik_tarihi'))
        return normalized

    @staticmethod
    def _normalize_amount(value):
        if value is None:
            return None
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        return round(amount, 2)

    @classmethod
    def validate(cls, instance, is_new=True):
        if is_new and not (instance.submission_token or '').strip():
            raise ValidationError('Form gonderim anahtari eksik. Sayfayi yenileyip tekrar deneyin.')

        if not (instance.ad or '').strip():
            raise ValidationError('Ad zorunludur.')

        if not (instance.soyad or '').strip():
            raise ValidationError('Soyad zorunludur.')

        if instance.tc_no:
            mevcut = cls._get_base_query().filter(Personel.tc_no == instance.tc_no)
            if not is_new:
                mevcut = mevcut.filter(Personel.id != instance.id)
            if mevcut.first():
                raise ValidationError('Bu TC kimlik numarasina sahip personel zaten kayitli.')

        if instance.sube_id:
            sube = Sube.query.filter_by(id=instance.sube_id).first()
            if not sube:
                raise ValidationError('Secilen sube bulunamadi.')

        if instance.ise_giris_tarihi and instance.isten_cikis_tarihi and instance.isten_cikis_tarihi < instance.ise_giris_tarihi:
            raise ValidationError('Isten cikis tarihi ise giris tarihinden once olamaz.')

    @classmethod
    def before_save(cls, instance, is_new=True):
        instance.submission_token = (instance.submission_token or '').strip() or None
        instance.ad = (instance.ad or '').strip()
        instance.soyad = (instance.soyad or '').strip()
        instance.tc_no = (instance.tc_no or '').strip() or None
        instance.telefon = (instance.telefon or '').strip() or None
        instance.meslek = (instance.meslek or '').strip() or None

    @staticmethod
    def _overlap_range(start_a, end_a, start_b, end_b):
        overlap_start = max(start_a, start_b)
        overlap_end = min(end_a, end_b)
        if overlap_start > overlap_end:
            return None
        return overlap_start, overlap_end

    @staticmethod
    def _days_between(start_date, end_date):
        if not start_date or not end_date or start_date > end_date:
            return 0
        return (end_date - start_date).days + 1

    @classmethod
    def _allocate_monthly_amount(cls, amount, overlap_start, overlap_end, month_start, month_end):
        normalized_amount = cls._normalize_amount(amount) or 0.0
        if normalized_amount <= 0:
            return 0.0

        overlap_days = cls._days_between(overlap_start, overlap_end)
        month_days = cls._days_between(month_start, month_end)
        if overlap_days <= 0 or month_days <= 0:
            return 0.0

        return normalized_amount * (overlap_days / month_days)

    @classmethod
    def _period_component_total(cls, source, fields):
        return sum(cls._normalize_amount(getattr(source, field, None)) or 0.0 for field in fields)

    @classmethod
    def get_period_total_amount(cls, donem):
        mapped_fields = list(cls.period_cost_field_map.values()) + cls.period_additional_cost_fields
        return cls._period_component_total(donem, mapped_fields)

    @classmethod
    def _has_period_costs(cls, **payload):
        return cls._period_component_total(type('PeriodPayload', (), payload)(), payload.keys()) > 0

    @staticmethod
    def _month_range(year, month):
        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(year, month + 1, 1) - timedelta(days=1)
        return month_start, month_end

    @staticmethod
    def _reference_date(reference_date=None):
        return reference_date or date.today()

    @classmethod
    def get_salary_periods(cls, personel):
        if not cls.salary_periods_table_exists():
            return []
        donemler = list(getattr(personel, 'maas_donemleri', []) or [])
        return sorted(
            donemler,
            key=lambda donem: (
                donem.baslangic_tarihi or date.min,
                donem.created_at or datetime.min,
                donem.id or 0,
            ),
            reverse=True,
        )

    @classmethod
    def get_current_salary_period(cls, personel, reference_date=None):
        reference_date = cls._reference_date(reference_date)
        for donem in cls.get_salary_periods(personel):
            bitis_tarihi = donem.bitis_tarihi or reference_date
            if donem.baslangic_tarihi and donem.baslangic_tarihi <= reference_date <= bitis_tarihi:
                return donem
        return None

    @classmethod
    def _unpaid_leave_days_in_range(cls, personel_id, range_start, range_end):
        """Verilen personelin [range_start, range_end] araliginda kalan ucretsiz izin gun sayisi."""
        if not personel_id or not range_start or not range_end or range_start > range_end:
            return 0
        try:
            izinler = PersonelIzin.query.filter(
                PersonelIzin.personel_id == personel_id,
                PersonelIzin.is_deleted == False,
                PersonelIzin.izin_turu == 'ucretsiz',
                PersonelIzin.baslangic_tarihi <= range_end,
                PersonelIzin.bitis_tarihi >= range_start,
            ).all()
        except Exception:
            return 0

        toplam_gun = 0
        for izin in izinler:
            ovr = cls._overlap_range(izin.baslangic_tarihi, izin.bitis_tarihi, range_start, range_end)
            if ovr:
                toplam_gun += cls._days_between(ovr[0], ovr[1])
        return toplam_gun

    @classmethod
    def get_monthly_cost_breakdown(cls, year, month, sube_id=None):
        if not cls.salary_periods_table_exists():
            return []

        month_start, month_end = cls._month_range(year, month)
        # Icinde bulunulan ay ise hesabi bugune kadar kap (ileriye donuk projeksiyon olmasin).
        today = date.today()
        effective_period_end = min(month_end, today) if month_start <= today <= month_end else month_end
        if effective_period_end < month_start:
            return []

        query = PersonelMaasDonemi.query.options(
            joinedload(PersonelMaasDonemi.personel),
            joinedload(PersonelMaasDonemi.sube),
        ).filter(
            PersonelMaasDonemi.baslangic_tarihi <= effective_period_end,
            or_(PersonelMaasDonemi.bitis_tarihi.is_(None), PersonelMaasDonemi.bitis_tarihi >= month_start),
        )

        if sube_id:
            query = query.filter(PersonelMaasDonemi.sube_id == sube_id)

        month_days = cls._days_between(month_start, month_end)
        rows = []
        for donem in query.all():
            effective_end = min(donem.bitis_tarihi, effective_period_end) if donem.bitis_tarihi else effective_period_end
            overlap = cls._overlap_range(donem.baslangic_tarihi, effective_end, month_start, effective_period_end)
            if not overlap:
                continue

            maas_tutari = cls._allocate_monthly_amount(donem.aylik_maas, overlap[0], overlap[1], month_start, month_end)
            yemek_tutari = cls._allocate_monthly_amount(donem.aylik_yemek_ucreti, overlap[0], overlap[1], month_start, month_end)
            yol_tutari = cls._allocate_monthly_amount(donem.aylik_yol_ucreti, overlap[0], overlap[1], month_start, month_end)
            sgk_tutari = cls._allocate_monthly_amount(donem.sgk_isveren_tutari, overlap[0], overlap[1], month_start, month_end)
            yan_haklar_tutari = cls._allocate_monthly_amount(donem.yan_haklar_tutari, overlap[0], overlap[1], month_start, month_end)
            diger_gider_tutari = cls._allocate_monthly_amount(donem.diger_gider_tutari, overlap[0], overlap[1], month_start, month_end)

            # Ucretsiz izin gunleri: sadece maastan orantili dusulur. Yemek ve yol onceden odendigi icin dusulmez.
            ucretsiz_izin_gun = cls._unpaid_leave_days_in_range(donem.personel_id, overlap[0], overlap[1]) if month_days > 0 else 0
            ucretsiz_izin_dusulen = 0.0
            if ucretsiz_izin_gun > 0 and month_days > 0:
                gunluk_maas = (cls._normalize_amount(donem.aylik_maas) or 0.0) / month_days
                dusulen_maas = min(maas_tutari, gunluk_maas * ucretsiz_izin_gun)
                maas_tutari -= dusulen_maas
                ucretsiz_izin_dusulen = dusulen_maas

            toplam_tutar = maas_tutari + yemek_tutari + yol_tutari + sgk_tutari + yan_haklar_tutari + diger_gider_tutari

            if toplam_tutar <= 0:
                continue

            rows.append(
                {
                    'personel_id': donem.personel_id,
                    'personel_adi': donem.personel.tam_ad if donem.personel else 'Personel silinmis',
                    'sube_id': donem.sube_id,
                    'sube_adi': donem.sube.isim if donem.sube else 'Subesiz',
                    'baslangic_tarihi': donem.baslangic_tarihi,
                    'bitis_tarihi': donem.bitis_tarihi,
                    'maas_tutari': maas_tutari,
                    'yemek_tutari': yemek_tutari,
                    'yol_tutari': yol_tutari,
                    'sgk_tutari': sgk_tutari,
                    'yan_haklar_tutari': yan_haklar_tutari,
                    'diger_gider_tutari': diger_gider_tutari,
                    'ucretsiz_izin_gun': ucretsiz_izin_gun,
                    'ucretsiz_izin_dusulen': ucretsiz_izin_dusulen,
                    'toplam_tutar': toplam_tutar,
                }
            )

        return sorted(rows, key=lambda row: (-row['toplam_tutar'], row['personel_adi']))

    @classmethod
    def _create_salary_period(cls, personel, *, baslangic_tarihi, aylik_maas, aylik_yemek_ucreti=None, aylik_yol_ucreti=None, sube_id, aciklama=None):
        normalized_maas = cls._normalize_amount(aylik_maas) or 0.0
        normalized_yemek = cls._normalize_amount(aylik_yemek_ucreti) or 0.0
        normalized_yol = cls._normalize_amount(aylik_yol_ucreti) or 0.0

        if normalized_maas + normalized_yemek + normalized_yol <= 0:
            return None

        donem = PersonelMaasDonemi(
            personel_id=personel.id,
            sube_id=sube_id,
            baslangic_tarihi=baslangic_tarihi,
            aylik_maas=normalized_maas,
            aylik_yemek_ucreti=normalized_yemek,
            aylik_yol_ucreti=normalized_yol,
            aciklama=aciklama,
        )
        db.session.add(donem)
        db.session.flush()
        return donem

    @classmethod
    def _validate_salary_effective_date(cls, personel, effective_date, current_period=None):
        if personel.ise_giris_tarihi and effective_date < personel.ise_giris_tarihi:
            raise ValidationError('Maas / sube degisiklik tarihi ise giris tarihinden once olamaz.')

        if current_period and current_period.baslangic_tarihi and effective_date < current_period.baslangic_tarihi:
            raise ValidationError('Degisiklik tarihi mevcut aktif maas doneminin baslangicindan once olamaz.')

        return effective_date

    @classmethod
    def _sync_salary_period_on_create(cls, personel, normalized_payload):
        if not cls.salary_periods_table_exists():
            return

        maas = normalized_payload.get('maas')
        yemek_ucreti = normalized_payload.get('yemek_ucreti')
        yol_ucreti = normalized_payload.get('yol_ucreti')
        if not cls._has_period_costs(maas=maas, yemek_ucreti=yemek_ucreti, yol_ucreti=yol_ucreti):
            return

        baslangic_tarihi = normalized_payload.get('ise_giris_tarihi') or date.today()
        cls._create_salary_period(
            personel,
            baslangic_tarihi=baslangic_tarihi,
            aylik_maas=maas,
            aylik_yemek_ucreti=yemek_ucreti,
            aylik_yol_ucreti=yol_ucreti,
            sube_id=normalized_payload.get('sube_id'),
            aciklama='Ilk ucret donemi',
        )

    @classmethod
    def _rewrite_salary_period_branch_history(cls, personel, yeni_sube_id):
        for donem in cls.get_salary_periods(personel):
            donem.sube_id = yeni_sube_id
            db.session.add(donem)

    @classmethod
    def _sync_salary_period_on_update(cls, personel, *, onceki_sube_id, onceki_maas, onceki_yemek_ucreti, onceki_yol_ucreti, yeni_sube_id, yeni_maas, yeni_yemek_ucreti, yeni_yol_ucreti, effective_date, rewrite_salary_history=False):
        if not cls.salary_periods_table_exists():
            return

        mevcut_donem = cls.get_current_salary_period(personel, reference_date=effective_date)
        yeni_maas_normalized = cls._normalize_amount(yeni_maas)
        onceki_maas_normalized = cls._normalize_amount(onceki_maas)
        yeni_yemek_normalized = cls._normalize_amount(yeni_yemek_ucreti)
        onceki_yemek_normalized = cls._normalize_amount(onceki_yemek_ucreti)
        yeni_yol_normalized = cls._normalize_amount(yeni_yol_ucreti)
        onceki_yol_normalized = cls._normalize_amount(onceki_yol_ucreti)

        if rewrite_salary_history and onceki_sube_id != yeni_sube_id:
            cls._rewrite_salary_period_branch_history(personel, yeni_sube_id)
            onceki_sube_id = yeni_sube_id

        donem_degisti = mevcut_donem is None or effective_date != mevcut_donem.baslangic_tarihi
        degisiklik_var = (
            donem_degisti
            or
            onceki_sube_id != yeni_sube_id
            or onceki_maas_normalized != yeni_maas_normalized
            or onceki_yemek_normalized != yeni_yemek_normalized
            or onceki_yol_normalized != yeni_yol_normalized
        )

        if not degisiklik_var:
            return

        cls._validate_salary_effective_date(personel, effective_date, mevcut_donem)

        if mevcut_donem and effective_date == mevcut_donem.baslangic_tarihi:
            if cls._has_period_costs(maas=yeni_maas, yemek_ucreti=yeni_yemek_ucreti, yol_ucreti=yeni_yol_ucreti):
                mevcut_donem.aylik_maas = yeni_maas_normalized or 0.0
                mevcut_donem.aylik_yemek_ucreti = yeni_yemek_normalized or 0.0
                mevcut_donem.aylik_yol_ucreti = yeni_yol_normalized or 0.0
                mevcut_donem.sube_id = yeni_sube_id
                mevcut_donem.aciklama = 'Donem ayni baslangic tarihinden guncellendi'
                db.session.add(mevcut_donem)
            else:
                db.session.delete(mevcut_donem)
            db.session.flush()
            return

        if mevcut_donem:
            mevcut_donem.bitis_tarihi = effective_date - timedelta(days=1)
            db.session.add(mevcut_donem)

        if cls._has_period_costs(maas=yeni_maas, yemek_ucreti=yeni_yemek_ucreti, yol_ucreti=yeni_yol_ucreti):
            cls._create_salary_period(
                personel,
                baslangic_tarihi=effective_date,
                aylik_maas=yeni_maas,
                aylik_yemek_ucreti=yeni_yemek_ucreti,
                aylik_yol_ucreti=yeni_yol_ucreti,
                sube_id=yeni_sube_id,
                aciklama='Ucret / donem degisikligi',
            )

        db.session.flush()

    @classmethod
    def is_ayrildi(cls, personel, reference_date=None):
        reference_date = cls._reference_date(reference_date)
        return bool(personel.isten_cikis_tarihi and personel.isten_cikis_tarihi <= reference_date)

    @classmethod
    def get_current_izin(cls, personel, reference_date=None):
        reference_date = cls._reference_date(reference_date)
        aktif_izinler = sorted(
            [izin for izin in getattr(personel, 'izinler', []) if not getattr(izin, 'is_deleted', False)],
            key=lambda izin: (izin.baslangic_tarihi or reference_date, izin.bitis_tarihi or reference_date),
            reverse=True,
        )

        for izin in aktif_izinler:
            if izin.baslangic_tarihi and izin.bitis_tarihi and izin.baslangic_tarihi <= reference_date <= izin.bitis_tarihi:
                return izin
        return None

    @classmethod
    def enrich_personel_list(cls, personeller, reference_date=None):
        reference_date = cls._reference_date(reference_date)
        for personel in personeller:
            personel.is_ayrildi = cls.is_ayrildi(personel, reference_date)
            personel.current_izin = None if personel.is_ayrildi else cls.get_current_izin(personel, reference_date)
            personel.is_izinli = personel.current_izin is not None
            personel.is_calisiyor = not personel.is_ayrildi and not personel.is_izinli
        return personeller

    @classmethod
    def filter_by_durum(cls, personeller, durum='tum', reference_date=None):
        durum = (durum or 'tum').strip().lower()
        if durum == 'izinli':
            return [personel for personel in cls.enrich_personel_list(personeller, reference_date) if personel.is_izinli]
        if durum == 'calismada':
            return [personel for personel in cls.enrich_personel_list(personeller, reference_date) if personel.is_calisiyor]
        return cls.enrich_personel_list(personeller, reference_date)

    @classmethod
    def list_personel(cls, sube_id=None, search_query=None):
        query = cls._get_base_query().options(
            joinedload(Personel.sube),
            joinedload(Personel.izinler),
        ).outerjoin(Sube)

        if sube_id:
            query = query.filter(Personel.sube_id == sube_id)

        if search_query:
            s = search_query.strip()
            query = query.filter(
                or_(
                    tr_ilike(Personel.ad, f'%{s}%'),
                    tr_ilike(Personel.soyad, f'%{s}%'),
                    Personel.tc_no.ilike(f'%{s}%'),
                    Personel.telefon.ilike(f'%{s}%'),
                    tr_ilike(Personel.meslek, f'%{s}%'),
                    tr_ilike(Sube.isim, f'%{s}%'),
                )
            )

        return query.order_by(Personel.soyad.asc(), Personel.ad.asc()).all()

    @classmethod
    def create_personel(cls, payload, actor_id=None):
        normalized = cls._normalize_payload(payload)
        instance = cls.model(**{key: value for key, value in normalized.items() if key != 'maas_gecerlilik_tarihi'})
        try:
            cls.validate(instance, is_new=True)
            cls._apply_audit_log(instance, is_new=True, actor_id=actor_id)
            cls.before_save(instance, is_new=True)

            db.session.add(instance)
            db.session.flush()

            cls._sync_salary_period_on_create(instance, normalized)

            cls.after_save(instance, is_new=True)
            db.session.commit()
            return instance
        except ValidationError:
            db.session.rollback()
            raise
        except IntegrityError as exc:
            db.session.rollback()
            error_text = str(getattr(exc, 'orig', exc)).lower()
            if 'submission_token' in error_text:
                raise ValidationError('Bu form zaten kaydedildi. Sayfa yavaslasa bile kaydet tusuna tekrar basmayin.') from exc
            if 'tc_no' in error_text:
                raise ValidationError('Bu TC kimlik numarasina sahip personel zaten kayitli.') from exc
            raise Exception(f'{cls.model.__name__} islemi sirasinda hata olustu.') from exc
        except Exception as exc:
            db.session.rollback()
            raise Exception(f'{cls.model.__name__} islemi sirasinda hata olustu.') from exc

    @classmethod
    def update_personel(cls, personel_id, payload, actor_id=None, rewrite_salary_history=False):
        instance = cls.get_by_id(personel_id)
        if not instance:
            raise ValidationError('Guncellenmek istenen personel bulunamadi.')

        normalized = cls._normalize_payload(payload)
        effective_date = normalized.get('maas_gecerlilik_tarihi') or date.today()
        onceki_sube_id = instance.sube_id
        onceki_maas = instance.maas
        onceki_yemek_ucreti = instance.yemek_ucreti
        onceki_yol_ucreti = instance.yol_ucreti

        try:
            for field in cls.updatable_fields:
                if field in normalized:
                    setattr(instance, field, normalized[field])

            cls.validate(instance, is_new=False)
            cls._apply_audit_log(instance, is_new=False, actor_id=actor_id)
            cls.before_save(instance, is_new=False)

            db.session.add(instance)
            db.session.flush()

            cls._sync_salary_period_on_update(
                instance,
                onceki_sube_id=onceki_sube_id,
                onceki_maas=onceki_maas,
                onceki_yemek_ucreti=onceki_yemek_ucreti,
                onceki_yol_ucreti=onceki_yol_ucreti,
                yeni_sube_id=instance.sube_id,
                yeni_maas=instance.maas,
                yeni_yemek_ucreti=instance.yemek_ucreti,
                yeni_yol_ucreti=instance.yol_ucreti,
                effective_date=effective_date,
                rewrite_salary_history=rewrite_salary_history,
            )

            cls.after_save(instance, is_new=False)
            db.session.commit()
            return instance
        except ValidationError:
            db.session.rollback()
            raise
        except Exception as exc:
            db.session.rollback()
            raise Exception(f'{cls.model.__name__} islemi sirasinda hata olustu.') from exc

    @classmethod
    def delete_personel(cls, personel_id, actor_id=None):
        return cls.delete(personel_id, actor_id=actor_id)

    @classmethod
    def hard_delete_personel(cls, personel_id):
        return cls.hard_delete(personel_id)


class PersonelIzinService(BaseService):
    model = PersonelIzin
    use_soft_delete = True
    updatable_fields = [
        'izin_turu',
        'baslangic_tarihi',
        'bitis_tarihi',
        'gun_sayisi',
        'aciklama',
    ]

    @staticmethod
    def table_exists():
        return inspect(db.engine).has_table(PersonelIzin.__tablename__)

    @staticmethod
    def _parse_date(value):
        if isinstance(value, str) and value:
            return datetime.strptime(value, '%Y-%m-%d').date()
        return value or None

    @staticmethod
    def _calculate_gun_sayisi(baslangic_tarihi, bitis_tarihi):
        if not baslangic_tarihi or not bitis_tarihi:
            return None
        return max(1, (bitis_tarihi - baslangic_tarihi).days)

    @classmethod
    def _normalize_payload(cls, payload):
        normalized = dict(payload or {})
        normalized['baslangic_tarihi'] = cls._parse_date(normalized.get('baslangic_tarihi'))
        normalized['bitis_tarihi'] = cls._parse_date(normalized.get('bitis_tarihi'))
        normalized['gun_sayisi'] = cls._calculate_gun_sayisi(
            normalized.get('baslangic_tarihi'),
            normalized.get('bitis_tarihi'),
        )
        normalized['aciklama'] = (normalized.get('aciklama') or '').strip() or None
        return normalized

    @classmethod
    def validate(cls, instance, is_new=True):
        personel = PersonelService.get_by_id(instance.personel_id)
        if not personel:
            raise ValidationError('Izin eklenecek personel bulunamadi.')

        if not instance.baslangic_tarihi or not instance.bitis_tarihi:
            raise ValidationError('Baslangic ve bitis tarihi zorunludur.')

        if instance.bitis_tarihi < instance.baslangic_tarihi:
            raise ValidationError('Bitis tarihi baslangic tarihinden once olamaz.')

        instance.gun_sayisi = cls._calculate_gun_sayisi(instance.baslangic_tarihi, instance.bitis_tarihi)
        if instance.gun_sayisi is None or int(instance.gun_sayisi) < 1:
            raise ValidationError('Gun sayisi en az 1 olmalidir.')

    @classmethod
    def create_izin(cls, personel_id, payload, actor_id=None):
        personel = PersonelService.get_by_id(personel_id)
        if not personel:
            raise ValidationError('Personel bulunamadi.')

        instance = cls.model(personel_id=personel.id, **cls._normalize_payload(payload))
        return cls.save(instance, is_new=True, actor_id=actor_id)

    @classmethod
    def delete_izin(cls, izin_id, actor_id=None):
        return cls.delete(izin_id, actor_id=actor_id)