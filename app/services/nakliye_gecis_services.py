"""Legacy kiralama nakliyelerini mali kayıtları değiştirmeden seferlere bağlar.

Bu modül normal form senkronundan bilinçli olarak ayrıdır. Dönüşüm sırasında
HizmetKaydi/Odeme/Hakedis satırı oluşturmaz, silmez veya mali alanlarını
güncellemez; yalnız mevcut nakliyeye dağıtım ekler ve mevcut müşteri nakliye
hizmetini bu dağıtıma bağlar.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import re
import uuid

from app.extensions import db
from app.cari.models import CariHareket, HizmetKaydi, Kasa, Odeme
from app.fatura.models import Hakedis
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.nakliyeler.models import (
    Nakliye,
    NakliyeDagitim,
    NakliyeGecisIslemi,
    NakliyeGecisKaydi,
)
from app.services.base import ValidationError
from app.services.nakliye_sefer_services import GIDER_KAYNAGI, NakliyeSeferService


MONEY = Decimal('0.01')
ALLOWED_TECHNICAL_SERVICE_FIELDS = {
    'nakliye_id',
    'nakliye_dagitim_id',
    'kiralama_kalemi_id',
    'kaynak',
}


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value.quantize(MONEY, rounding=ROUND_HALF_UP))
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _model_row(instance, fields):
    return {field: _json_value(getattr(instance, field, None)) for field in fields}


def _canonical_json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sync_firma_financial_cache(firma_id):
    """Firma bakiyesi ve cari rapor cache'ini mevcut transaction içinde yeniler."""
    if not firma_id:
        return
    from app.services.firma_services import FirmaService

    firma = db.session.get(Firma, firma_id)
    if not firma:
        return
    ozet = firma.bakiye_ozeti
    firma.bakiye = ozet['net_bakiye']
    FirmaService.guncelle_firma_cari_cache(firma_id, auto_commit=False)
    db.session.add(firma)


class CariSnapshotService:
    """Firma ve hareket bazında deterministik mali anlık görüntü üretir."""

    SERVICE_FIELDS = (
        'id', 'firma_id', 'nakliye_id', 'nakliye_dagitim_id',
        'kiralama_kalemi_id', 'ozel_id', 'kaynak', 'tarih', 'islem_tarihi',
        'tutar', 'yon', 'fatura_no', 'vade_tarihi', 'aciklama', 'kdv_orani',
        'kiralama_alis_kdv', 'nakliye_alis_kdv', 'is_active', 'is_deleted',
        'created_at', 'deleted_at',
    )
    PAYMENT_FIELDS = (
        'id', 'firma_musteri_id', 'kasa_id', 'tarih', 'islem_tarihi',
        'tutar', 'yon', 'fatura_no', 'vade_tarihi', 'aciklama',
        'is_active', 'is_deleted', 'created_at', 'deleted_at',
    )
    HAKEDIS_FIELDS = (
        'id', 'firma_id', 'kiralama_id', 'cari_hareket_id', 'hakedis_no',
        'fatura_no', 'para_birimi', 'toplam_matrah', 'toplam_kdv',
        'toplam_tevkifat', 'genel_toplam', 'durum', 'is_faturalasti',
        'is_active', 'is_deleted',
    )
    CARI_FIELDS = (
        'id', 'firma_id', 'tarih', 'para_birimi', 'yon', 'tutar',
        'kalan_tutar', 'durum', 'kaynak_modul', 'kaynak_id', 'ozel_id',
        'belge_no', 'referans_hareket_id', 'is_active', 'is_deleted',
    )
    TRANSITION_FIELDS = (
        'id', 'islem_id', 'kiralama_id', 'nakliye_id', 'nakliye_dagitim_id',
        'hizmet_kaydi_id', 'durum', 'once_json', 'sonra_json', 'notlar',
    )

    @classmethod
    def create_snapshot(cls):
        firms = Firma.query.order_by(Firma.id).all()
        services = HizmetKaydi.query.order_by(HizmetKaydi.id).all()
        payments = Odeme.query.order_by(Odeme.id).all()
        hakedisler = Hakedis.query.order_by(Hakedis.id).all()
        cari_rows = CariHareket.query.order_by(CariHareket.id).all()
        transition_rows = NakliyeGecisKaydi.query.order_by(NakliyeGecisKaydi.id).all()
        kasa_currency = {
            kasa.id: (kasa.para_birimi or 'TRY')
            for kasa in Kasa.query.order_by(Kasa.id).all()
        }

        summary = defaultdict(lambda: defaultdict(lambda: Decimal('0.00')))
        daily = defaultdict(lambda: defaultdict(lambda: Decimal('0.00')))
        for hareket in services:
            if hareket.is_deleted:
                continue
            currency = 'TRY'
            bucket = summary[(hareket.firma_id, currency)]
            key = 'hizmet_borc' if hareket.yon == 'giden' else 'hizmet_alacak'
            bucket[key] += Decimal(str(hareket.tutar or 0))
            day = hareket.islem_tarihi or hareket.tarih
            daily[(hareket.firma_id, currency, str(day))][key] += Decimal(str(hareket.tutar or 0))
        for hareket in payments:
            if hareket.is_deleted:
                continue
            currency = kasa_currency.get(hareket.kasa_id, 'TRY')
            bucket = summary[(hareket.firma_musteri_id, currency)]
            key = 'odeme' if hareket.yon == 'odeme' else 'tahsilat'
            bucket[key] += Decimal(str(hareket.tutar or 0))
            day = hareket.islem_tarihi or hareket.tarih
            daily[(hareket.firma_musteri_id, currency, str(day))][key] += Decimal(str(hareket.tutar or 0))

        summary_rows = []
        for (firma_id, currency), values in sorted(summary.items()):
            debit = values['hizmet_borc'] + values['odeme']
            credit = values['hizmet_alacak'] + values['tahsilat']
            summary_rows.append({
                'firma_id': firma_id,
                'para_birimi': currency,
                **{key: _json_value(values[key]) for key in (
                    'hizmet_borc', 'hizmet_alacak', 'odeme', 'tahsilat'
                )},
                'borc': _json_value(debit),
                'alacak': _json_value(credit),
                'bakiye': _json_value(debit - credit),
            })

        daily_rows = []
        for (firma_id, currency, day), values in sorted(daily.items()):
            daily_rows.append({
                'firma_id': firma_id,
                'para_birimi': currency,
                'tarih': day,
                **{key: _json_value(values[key]) for key in (
                    'hizmet_borc', 'hizmet_alacak', 'odeme', 'tahsilat'
                )},
            })

        firm_rows = [{
            'id': firm.id,
            'firma_adi': firm.firma_adi,
            'is_active': firm.is_active,
            'is_deleted': firm.is_deleted,
            'bakiye': _json_value(firm.bakiye),
            'cari_borc_kdvli': _json_value(firm.cari_borc_kdvli),
            'cari_alacak_kdvli': _json_value(firm.cari_alacak_kdvli),
            'cari_bakiye_kdvli': _json_value(firm.cari_bakiye_kdvli),
        } for firm in firms]

        baseline_issues = []
        try_by_firm = {
            row['firma_id']: Decimal(row['bakiye'])
            for row in summary_rows if row['para_birimi'] == 'TRY'
        }
        for firm in firm_rows:
            stored = Decimal(str(firm['bakiye'] or '0'))
            calculated = try_by_firm.get(firm['id'], Decimal('0.00'))
            if abs(stored - calculated) >= MONEY:
                baseline_issues.append({
                    'firma_id': firm['id'],
                    'tur': 'onceden_mevcut_hata',
                    'alan': 'firma.bakiye',
                    'saklanan': _json_value(stored),
                    'hesaplanan': _json_value(calculated),
                    'fark': _json_value(stored - calculated),
                })

        payload = {
            'schema_version': 1,
            'firmalar': firm_rows,
            'hizmet_kayitlari': [
                _model_row(row, cls.SERVICE_FIELDS) for row in services
            ],
            'odemeler': [_model_row(row, cls.PAYMENT_FIELDS) for row in payments],
            'hakedisler': [_model_row(row, cls.HAKEDIS_FIELDS) for row in hakedisler],
            'cari_hareketler': [_model_row(row, cls.CARI_FIELDS) for row in cari_rows],
            'nakliye_gecis_kayitlari': [
                _model_row(row, cls.TRANSITION_FIELDS) for row in transition_rows
            ],
            'firma_ozetleri': summary_rows,
            'gunluk_ozetler': daily_rows,
            'baslangic_tutarsizliklari': baseline_issues,
        }
        payload['sha256'] = hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()
        return payload

    @staticmethod
    def _index(rows):
        return {int(row['id']): row for row in rows}

    @classmethod
    def compare(cls, before, after):
        errors = []
        expected = []
        before_transition_ids = {
            row.get('id') for row in before.get('nakliye_gecis_kayitlari', [])
        }
        cleanup_logs = [
            row for row in after.get('nakliye_gecis_kayitlari', [])
            if row.get('id') not in before_transition_ids
            and row.get('durum') == 'mukerrer_pasif'
            and row.get('hizmet_kaydi_id') is not None
        ]
        cleanup_service_ids = {
            int(row['hizmet_kaydi_id']) for row in cleanup_logs
        }

        def compare_exact(section, key='id'):
            left = {row[key]: row for row in before.get(section, [])}
            right = {row[key]: row for row in after.get(section, [])}
            for missing in sorted(set(left) - set(right)):
                errors.append({'tur': 'donusum_kaynakli_hata', 'bolum': section, 'id': missing, 'hata': 'eksik_kayit'})
            for added in sorted(set(right) - set(left)):
                errors.append({'tur': 'donusum_kaynakli_hata', 'bolum': section, 'id': added, 'hata': 'yeni_kayit'})
            for row_id in sorted(set(left) & set(right)):
                if left[row_id] != right[row_id]:
                    errors.append({'tur': 'donusum_kaynakli_hata', 'bolum': section, 'id': row_id, 'hata': 'alan_degisikligi', 'once': left[row_id], 'sonra': right[row_id]})

        before_services = cls._index(before.get('hizmet_kayitlari', []))
        after_services = cls._index(after.get('hizmet_kayitlari', []))
        for missing in sorted(set(before_services) - set(after_services)):
            errors.append({'tur': 'donusum_kaynakli_hata', 'bolum': 'hizmet_kayitlari', 'id': missing, 'hata': 'eksik_hareket'})
        for added in sorted(set(after_services) - set(before_services)):
            added_row = after_services[added]
            if (
                added in cleanup_service_ids
                and added_row.get('is_deleted')
                and not added_row.get('is_active')
            ):
                expected.append({
                    'tur': 'beklenen_mukerrer_pasiflestirme',
                    'bolum': 'hizmet_kayitlari',
                    'id': added,
                    'alanlar': ['yeni_olup_pasiflestirilen_mukerrer'],
                })
            else:
                errors.append({'tur': 'donusum_kaynakli_hata', 'bolum': 'hizmet_kayitlari', 'id': added, 'hata': 'mukerrer_veya_yeni_hareket'})
        for row_id in sorted(set(before_services) & set(after_services)):
            old = before_services[row_id]
            new = after_services[row_id]
            changed = sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
            allowed = set(ALLOWED_TECHNICAL_SERVICE_FIELDS)
            if row_id in cleanup_service_ids:
                allowed.update({'is_active', 'is_deleted', 'deleted_at'})
            forbidden = [key for key in changed if key not in allowed]
            if forbidden:
                errors.append({
                    'tur': 'donusum_kaynakli_hata', 'bolum': 'hizmet_kayitlari',
                    'id': row_id, 'hata': 'mali_veya_belge_alani_degisikligi',
                    'alanlar': forbidden, 'once': old, 'sonra': new,
                })
            elif changed:
                expected.append({
                    'tur': (
                        'beklenen_mukerrer_pasiflestirme'
                        if row_id in cleanup_service_ids
                        else 'beklenen_teknik_baglanti_degisikligi'
                    ),
                    'bolum': 'hizmet_kayitlari', 'id': row_id,
                    'alanlar': changed,
                    'once': {key: old.get(key) for key in changed},
                    'sonra': {key: new.get(key) for key in changed},
                })

        transition_by_service = {
            row.get('hizmet_kaydi_id'): row
            for row in after.get('nakliye_gecis_kayitlari', [])
            if row.get('hizmet_kaydi_id') is not None
        }
        for change in expected:
            if change['id'] not in transition_by_service:
                errors.append({
                    'tur': 'donusum_kaynakli_hata',
                    'bolum': 'nakliye_gecis_kayitlari',
                    'id': change['id'],
                    'hata': 'teknik_degisiklik_gecis_gunlugunde_yok',
                })

        def expected_financial_rows(section):
            rows = [dict(row) for row in before.get(section, [])]
            if not cleanup_service_ids:
                return rows
            key_fields = (
                ('firma_id', 'para_birimi')
                if section == 'firma_ozetleri'
                else ('firma_id', 'para_birimi', 'tarih')
            )
            indexed = {tuple(row.get(k) for k in key_fields): row for row in rows}
            for service_id in cleanup_service_ids:
                service = before_services.get(service_id)
                if not service or service.get('is_deleted') or service.get('yon') != 'gelen':
                    continue
                key_values = [service.get('firma_id'), 'TRY']
                if section == 'gunluk_ozetler':
                    key_values.append(str(service.get('islem_tarihi') or service.get('tarih')))
                row = indexed.get(tuple(key_values))
                if not row:
                    continue
                amount = Decimal(str(service.get('tutar') or 0))
                row['hizmet_alacak'] = _json_value(
                    Decimal(str(row.get('hizmet_alacak') or 0)) - amount
                )
                if section == 'firma_ozetleri':
                    row['alacak'] = _json_value(
                        Decimal(str(row.get('alacak') or 0)) - amount
                    )
                    row['bakiye'] = _json_value(
                        Decimal(str(row.get('bakiye') or 0)) + amount
                    )
            amount_fields = (
                'hizmet_borc', 'hizmet_alacak', 'odeme', 'tahsilat'
            )
            return [
                row for row in rows
                if any(Decimal(str(row.get(field) or 0)) != 0 for field in amount_fields)
            ]

        def expected_firm_rows():
            rows = [dict(row) for row in before.get('firmalar', [])]
            indexed = {int(row['id']): row for row in rows}
            for service_id in cleanup_service_ids:
                service = before_services.get(service_id)
                if not service or service.get('is_deleted') or service.get('yon') != 'gelen':
                    continue
                row = indexed.get(int(service['firma_id']))
                if not row:
                    continue
                amount = Decimal(str(service.get('tutar') or 0))
                rate = next((
                    service.get(field)
                    for field in ('nakliye_alis_kdv', 'kiralama_alis_kdv', 'kdv_orani')
                    if service.get(field) is not None
                ), None)
                gross = amount * (
                    Decimal('1') + Decimal(str(rate or 0)) / Decimal('100')
                )
                row['bakiye'] = _json_value(
                    Decimal(str(row.get('bakiye') or 0)) + amount
                )
                row['cari_alacak_kdvli'] = _json_value(
                    Decimal(str(row.get('cari_alacak_kdvli') or 0)) - gross
                )
                row['cari_bakiye_kdvli'] = _json_value(
                    Decimal(str(row.get('cari_bakiye_kdvli') or 0)) + gross
                )
            return rows

        for section in ('firmalar', 'odemeler', 'hakedisler', 'cari_hareketler', 'firma_ozetleri', 'gunluk_ozetler'):
            if section in ('firma_ozetleri', 'gunluk_ozetler'):
                expected_rows = expected_financial_rows(section)
                if expected_rows != after.get(section, []):
                    errors.append({'tur': 'donusum_kaynakli_hata', 'bolum': section, 'hata': 'toplam_farki', 'once': expected_rows, 'sonra': after.get(section, [])})
            elif section == 'firmalar':
                expected_rows = expected_firm_rows()
                if expected_rows != after.get(section, []):
                    errors.append({'tur': 'donusum_kaynakli_hata', 'bolum': section, 'hata': 'alan_degisikligi', 'once': expected_rows, 'sonra': after.get(section, [])})
            else:
                compare_exact(section)

        return {
            'ok': not errors,
            'esik': '0.01',
            'kontrol_edilen_firma_sayisi': len(before.get('firmalar', [])),
            'kontrol_edilen_hizmet_sayisi': len(before_services),
            'hata_sayisi': len(errors),
            'beklenen_degisiklik_sayisi': len(expected),
            'hatalar': errors,
            'beklenen_teknik_degisiklikler': expected,
            'onceden_mevcut_hatalar': before.get('baslangic_tutarsizliklari', []),
        }


class GuvenliNakliyeGecisService:
    """Geçmiş seferleri finansal satırlara dokunmadan dönüştürür."""

    @staticmethod
    def _active_nakliyeler(kiralama):
        return [
            n for n in kiralama.nakliyeler
            if not n.is_deleted and n.is_active
        ]

    @staticmethod
    def _kalem_ids(kiralama):
        return {k.id for k in kiralama.kalemler if not k.is_deleted}

    @classmethod
    def _resolve_kalem(cls, kiralama, nakliye):
        allowed = cls._kalem_ids(kiralama)
        linked = {
            h.kiralama_kalemi_id for h in nakliye.hizmet_kayitlari
            if not h.is_deleted and h.kiralama_kalemi_id in allowed
        }
        if len(linked) == 1:
            return linked.pop(), 'hizmet_kaydi'
        if len(linked) > 1:
            raise ValidationError(f'Nakliye #{nakliye.id} birden fazla kiralama kalemine bağlı.')

        text = (nakliye.aciklama or '').strip()
        match = re.search(r'#(\d+)\s*$', text)
        reason = 'aciklama_kalem_no'
        if not match:
            match = re.search(r'\[Ref:(\d+)\]', text, re.I)
            reason = 'swap_ref'
        if match:
            kalem_id = int(match.group(1))
            if kalem_id in allowed:
                return kalem_id, reason
        raise ValidationError(f'Nakliye #{nakliye.id} için güvenilir kiralama kalemi bulunamadı.')

    @staticmethod
    def _resolve_yon(nakliye):
        if nakliye.yon in ('gidis', 'donus'):
            return nakliye.yon
        text = (nakliye.aciklama or '').strip()
        if re.match(r'^(Dönüş|Donus)', text, re.I):
            return 'donus'
        if re.match(r'^(Gidiş|Gidis|Makine Değişim)', text, re.I):
            return 'gidis'
        raise ValidationError(f'Nakliye #{nakliye.id} için gidiş/dönüş yönü belirlenemedi.')

    @staticmethod
    def _issues(nakliye):
        issues = []
        if nakliye.nakliye_tipi == 'taseron':
            if not nakliye.taseron_firma_id:
                issues.append('taseron_firma_eksik')
        elif not nakliye.arac_id and not (nakliye.plaka or '').strip():
            issues.append('arac_ve_plaka_eksik')
        return issues

    @classmethod
    def preflight(cls):
        decisions = []
        blockers = []
        automatic_repairs = []
        rentals = Kiralama.query.filter(
            Kiralama.is_deleted.is_(False),
            Kiralama.nakliye_modeli != 'sefer',
        ).order_by(Kiralama.id)
        for kiralama in rentals:
            directions = {}
            for nakliye in cls._active_nakliyeler(kiralama):
                try:
                    if bool(getattr(nakliye, 'cift_yon', False)):
                        raise ValidationError(
                            f'Nakliye #{nakliye.id} çift yönlü; legacy geçişte otomatik bölünemez.'
                        )
                    kalem_id, reason = cls._resolve_kalem(kiralama, nakliye)
                    yon = cls._resolve_yon(nakliye)
                    key = (kalem_id, yon)
                    if key in directions and directions[key] != nakliye.id:
                        raise ValidationError(
                            f'Kalem #{kalem_id} için {yon} yönünde birden fazla nakliye var: '
                            f'#{directions[key]}, #{nakliye.id}.'
                        )
                    directions[key] = nakliye.id

                    customer_services = [
                        h for h in nakliye.hizmet_kayitlari
                        if not h.is_deleted and h.is_active and h.yon == 'giden'
                    ]
                    if len(customer_services) > 1:
                        raise ValidationError(
                            f'Nakliye #{nakliye.id} için birden fazla aktif müşteri hareketi var: '
                            f'{",".join(str(h.id) for h in customer_services)}.'
                        )
                    if customer_services and customer_services[0].firma_id != kiralama.firma_musteri_id:
                        raise ValidationError(
                            f'Nakliye #{nakliye.id} müşteri hareketi #{customer_services[0].id} '
                            'kiralama müşterisiyle uyuşmuyor.'
                        )
                    nakliye_tutari = Decimal(str(nakliye.tutar or 0)).quantize(MONEY)
                    if nakliye_tutari > 0 and not customer_services:
                        raise ValidationError(
                            f'Nakliye #{nakliye.id} için aktif müşteri giden hareketi bulunamadı.'
                        )
                    if customer_services:
                        hizmet_tutari = Decimal(
                            str(customer_services[0].tutar or 0)
                        ).quantize(MONEY)
                        if hizmet_tutari != nakliye_tutari:
                            raise ValidationError(
                                f'Nakliye #{nakliye.id} müşteri hareketi '
                                f'#{customer_services[0].id} tutarı ({hizmet_tutari}) '
                                f'nakliye tutarıyla ({nakliye_tutari}) uyuşmuyor.'
                            )

                    taseron_hizmet_id = None
                    duplicate_service_id = None
                    active_incoming = HizmetKaydi.query.filter(
                        HizmetKaydi.nakliye_id == nakliye.id,
                        HizmetKaydi.yon == 'gelen',
                        HizmetKaydi.is_deleted.is_(False),
                        HizmetKaydi.is_active.is_(True),
                    ).order_by(HizmetKaydi.id).all()
                    if (
                        nakliye.nakliye_tipi == 'taseron'
                        and Decimal(str(nakliye.taseron_maliyet or 0)) > 0
                    ):
                        candidates = NakliyeSeferService.legacy_taseron_service_candidates(
                            nakliye, kiralama, kalem_id, sefer_yonu=yon,
                        )
                        if len(candidates) != 1:
                            raise ValidationError(
                                f'Nakliye #{nakliye.id} için tam bir eski taşeron cari hareketi '
                                f'beklenirken {len(candidates)} kayıt bulundu; adaylar: '
                                f'{",".join(str(h.id) for h in candidates) or "yok"}.'
                            )
                        old_service = candidates[0]
                        taseron_hizmet_id = old_service.id
                        linked_incoming = [
                            h for h in active_incoming if h.id != old_service.id
                        ]
                        collision_ids = [old_service.id] + [
                            h.id for h in linked_incoming
                        ]
                        if len(linked_incoming) > 1:
                            raise ValidationError(
                                f'Nakliye #{nakliye.id} aktif gelen hizmetleri '
                                f'{",".join(str(i) for i in collision_ids)} çakışıyor.'
                            )
                        if linked_incoming:
                            duplicate = linked_incoming[0]
                            safe_duplicate = (
                                duplicate.kaynak == GIDER_KAYNAGI
                                and duplicate.firma_id == old_service.firma_id
                                and Decimal(str(duplicate.tutar or 0)).quantize(MONEY)
                                == Decimal(str(old_service.tutar or 0)).quantize(MONEY)
                                and not duplicate.fatura_no
                                and not NakliyeSeferService._has_any_hakedis_link(duplicate)
                            )
                            if not safe_duplicate:
                                raise ValidationError(
                                    f'Nakliye #{nakliye.id} aktif gelen hizmetleri '
                                    f'{",".join(str(i) for i in collision_ids)} güvenli olmayan '
                                    'biçimde çakışıyor '
                                    '(firma/tutar/fatura/hakediş kontrolü başarısız).'
                                )
                            duplicate_service_id = duplicate.id
                            automatic_repairs.append({
                                'kiralama_id': kiralama.id,
                                'nakliye_id': nakliye.id,
                                'korunacak_hizmet_kaydi_id': old_service.id,
                                'pasife_alinacak_hizmet_kaydi_id': duplicate.id,
                            })
                    elif active_incoming:
                        raise ValidationError(
                            f'Nakliye #{nakliye.id} taşeron adayı olmamasına rağmen aktif '
                            f'gelen hizmetler içeriyor: '
                            f'{",".join(str(h.id) for h in active_incoming)}.'
                        )

                    decisions.append({
                        'kiralama_id': kiralama.id,
                        'nakliye_id': nakliye.id,
                        'kalem_id': kalem_id,
                        'yon': yon,
                        'eslesme': reason,
                        'taseron_hizmet_id': taseron_hizmet_id,
                        'pasife_alinacak_taseron_hizmet_id': duplicate_service_id,
                        'eksikler': cls._issues(nakliye),
                    })
                except ValidationError as exc:
                    blockers.append({
                        'kiralama_id': kiralama.id,
                        'nakliye_id': nakliye.id,
                        'hata': str(exc),
                    })

        blocked_rentals = {row['kiralama_id'] for row in blockers}
        decisions = [
            row for row in decisions if row['kiralama_id'] not in blocked_rentals
        ]
        automatic_repairs = [
            row for row in automatic_repairs
            if row['kiralama_id'] not in blocked_rentals
        ]
        return {
            'ok': not blockers,
            'kararlar': decisions,
            'otomatik_onarimlar': automatic_repairs,
            'engeller': blockers,
        }

    @classmethod
    def _convert_rental(cls, kiralama, decision_map, run, actor_id=None):
        converted = 0
        for nakliye in cls._active_nakliyeler(kiralama):
            decision = decision_map[nakliye.id]
            existing = [
                d for d in nakliye.dagitimlar
                if not d.is_deleted and d.is_active
            ]
            if existing:
                if len(existing) != 1 or existing[0].kiralama_kalemi_id != decision['kalem_id']:
                    raise ValidationError(f'Nakliye #{nakliye.id} mevcut dağıtımı dönüşüm kararıyla uyuşmuyor.')
                dagitim = existing[0]
                if Decimal(str(dagitim.tutar or 0)) != Decimal(str(nakliye.tutar or 0)):
                    raise ValidationError(f'Nakliye #{nakliye.id} mevcut dağıtım tutarı uyuşmuyor.')
            else:
                dagitim = NakliyeDagitim(
                    nakliye_id=nakliye.id,
                    kiralama_kalemi_id=decision['kalem_id'],
                    tutar=nakliye.tutar or Decimal('0.00'),
                )
                db.session.add(dagitim)
                db.session.flush()

            before = {
                'yon': nakliye.yon,
                'sefer_uuid': nakliye.sefer_uuid,
                'gecis_kaynagi': nakliye.gecis_kaynagi,
                'gecis_eksik_bilgiler': nakliye.gecis_eksik_bilgiler,
            }
            nakliye.yon = decision['yon']
            nakliye.sefer_uuid = nakliye.sefer_uuid or str(uuid.uuid4())
            nakliye.gecis_kaynagi = 'legacy_kiralama_v1'
            nakliye.gecis_eksik_bilgiler = _canonical_json(decision['eksikler']) if decision['eksikler'] else None
            db.session.add(nakliye)

            customer_services = [
                h for h in nakliye.hizmet_kayitlari
                if not h.is_deleted and h.is_active and h.yon == 'giden'
            ]
            service_id = None
            if customer_services:
                hizmet = customer_services[0]
                service_id = hizmet.id
                hizmet.nakliye_dagitim_id = dagitim.id
                hizmet.kiralama_kalemi_id = decision['kalem_id']
                hizmet.kaynak = 'nakliye_dagitim_satis'
                db.session.add(hizmet)

            supplier_services = [
                h for h in nakliye.hizmet_kayitlari
                if not h.is_deleted and h.is_active and h.yon == 'gelen'
            ]
            taseron_hizmet_id = decision.get('taseron_hizmet_id')
            if taseron_hizmet_id:
                taseron_hizmet = db.session.get(HizmetKaydi, taseron_hizmet_id)
                if taseron_hizmet is None or taseron_hizmet.is_deleted:
                    raise ValidationError(
                        f'Nakliye #{nakliye.id} için seçilen eski taşeron hareketi bulunamadı.'
                    )
                taseron_once = _model_row(
                    taseron_hizmet, CariSnapshotService.SERVICE_FIELDS,
                )
                duplicate_id = decision.get('pasife_alinacak_taseron_hizmet_id')
                if duplicate_id:
                    duplicate = db.session.get(HizmetKaydi, duplicate_id)
                    if not duplicate or duplicate.is_deleted or not duplicate.is_active:
                        raise ValidationError(
                            f'Nakliye #{nakliye.id} güvenli mükerrer hizmet '
                            f'#{duplicate_id} artık aktif değil.'
                        )
                    duplicate_once = _model_row(
                        duplicate, CariSnapshotService.SERVICE_FIELDS,
                    )
                    duplicate.is_deleted = True
                    duplicate.is_active = False
                    duplicate.deleted_at = datetime.now(timezone.utc)
                    duplicate.deleted_by_id = actor_id
                    db.session.add(duplicate)
                    db.session.flush()
                    db.session.add(NakliyeGecisKaydi(
                        islem_id=run.id,
                        kiralama_id=kiralama.id,
                        nakliye_id=nakliye.id,
                        nakliye_dagitim_id=dagitim.id,
                        hizmet_kaydi_id=duplicate.id,
                        durum='mukerrer_pasif',
                        once_json=_canonical_json(duplicate_once),
                        sonra_json=_canonical_json(_model_row(
                            duplicate, CariSnapshotService.SERVICE_FIELDS,
                        )),
                        notlar=_canonical_json({
                            'neden': 'conversion_safe_duplicate_cleanup',
                            'korunan_hizmet_kaydi_id': taseron_hizmet.id,
                        }),
                    ))
                taseron_hizmet.nakliye_id = nakliye.id
                taseron_hizmet.nakliye_dagitim_id = None
                taseron_hizmet.kiralama_kalemi_id = decision['kalem_id']
                taseron_hizmet.kaynak = GIDER_KAYNAGI
                db.session.add(taseron_hizmet)
                db.session.flush()
                if duplicate_id:
                    _sync_firma_financial_cache(taseron_hizmet.firma_id)
                    db.session.flush()
                db.session.add(NakliyeGecisKaydi(
                    islem_id=run.id,
                    kiralama_id=kiralama.id,
                    nakliye_id=nakliye.id,
                    nakliye_dagitim_id=dagitim.id,
                    hizmet_kaydi_id=taseron_hizmet.id,
                    durum='taseron_baglandi',
                    once_json=_canonical_json(taseron_once),
                    sonra_json=_canonical_json(_model_row(
                        taseron_hizmet, CariSnapshotService.SERVICE_FIELDS,
                    )),
                    notlar=_canonical_json({
                        'neden': 'legacy_taseron_kimligi_korundu',
                        'korunan_hizmet_kaydi_id': taseron_hizmet.id,
                    }),
                ))
            elif supplier_services:
                raise ValidationError(
                    f'Nakliye #{nakliye.id} taşeron hareketi deterministik olarak doğrulanamadı.'
                )

            after = {
                'yon': nakliye.yon,
                'sefer_uuid': nakliye.sefer_uuid,
                'gecis_kaynagi': nakliye.gecis_kaynagi,
                'gecis_eksik_bilgiler': nakliye.gecis_eksik_bilgiler,
                'nakliye_dagitim_id': dagitim.id,
                'kiralama_kalemi_id': decision['kalem_id'],
            }
            db.session.add(NakliyeGecisKaydi(
                islem_id=run.id,
                kiralama_id=kiralama.id,
                nakliye_id=nakliye.id,
                nakliye_dagitim_id=dagitim.id,
                hizmet_kaydi_id=service_id,
                once_json=_canonical_json(before),
                sonra_json=_canonical_json(after),
                notlar=_canonical_json({
                    'eslesme': decision['eslesme'], 'eksikler': decision['eksikler']
                }),
            ))
            converted += 1

        if converted == 0:
            db.session.add(NakliyeGecisKaydi(
                islem_id=run.id,
                kiralama_id=kiralama.id,
                durum='donusturuldu',
                notlar=_canonical_json({'neden': 'nakliyesiz_kiralama_gecisi'}),
            ))
        kiralama.nakliye_modeli = 'sefer'
        db.session.add(kiralama)
        return converted

    @classmethod
    def _existing_conversion_counts(cls):
        marked_trips = Nakliye.query.filter(
            Nakliye.gecis_kaynagi == 'legacy_kiralama_v1',
            Nakliye.is_deleted.is_(False),
        ).all()
        rental_ids = {row.kiralama_id for row in marked_trips if row.kiralama_id}
        conversion_logs = NakliyeGecisKaydi.query.filter_by(
            durum='donusturuldu',
        ).all()
        rental_ids.update(row.kiralama_id for row in conversion_logs)
        trip_ids = {row.id for row in marked_trips}
        trip_ids.update(row.nakliye_id for row in conversion_logs if row.nakliye_id)

        rental_count = len(rental_ids)
        trip_count = len(trip_ids)
        for previous in NakliyeGecisIslemi.query.order_by(
            NakliyeGecisIslemi.id
        ).all():
            try:
                report = json.loads(previous.rapor_json or '{}')
            except (TypeError, ValueError):
                report = {}
            # Onarım run'ları preflight/verification anahtarlarıyla ayrılır.
            if 'preflight' in report or 'verification' in report:
                continue
            if report or any(
                row.durum == 'donusturuldu' for row in previous.kayitlar
            ):
                rental_count = max(
                    rental_count,
                    int(previous.donusturulen_kiralama_sayisi or 0),
                )
                trip_count = max(
                    trip_count,
                    int(previous.donusturulen_sefer_sayisi or 0),
                )
        return rental_count, trip_count

    @classmethod
    def apply(cls, source_snapshot, actor_id=None, run_uuid=None):
        run_uuid = run_uuid or str(uuid.uuid4())
        run = NakliyeGecisIslemi.query.filter_by(run_uuid=run_uuid).first()
        if run and run.durum in ('tamamlandi', 'donusturuldu_mutabakat_bekliyor'):
            return run

        current = CariSnapshotService.create_snapshot()
        existing_rentals, existing_trips = cls._existing_conversion_counts()
        if run is None:
            if current['sha256'] != source_snapshot.get('sha256'):
                if not existing_rentals and not existing_trips:
                    raise ValidationError(
                        'Kaynak veriler önizlemeden sonra değişti; dönüşüm durduruldu.'
                    )
                resume_report = CariSnapshotService.compare(source_snapshot, current)
                if not resume_report['ok']:
                    raise ValidationError(
                        'Önceki dönüşüm dışındaki mali veya belge verileri değişti; '
                        'yeni run ile devam işlemi durduruldu.'
                    )
            run = NakliyeGecisIslemi(
                run_uuid=run_uuid,
                durum='uygulaniyor',
                kaynak_snapshot_sha256=source_snapshot['sha256'],
                once_firma_sayisi=len(source_snapshot.get('firmalar', [])),
                once_hareket_sayisi=len(source_snapshot.get('hizmet_kayitlari', [])),
                donusturulen_kiralama_sayisi=existing_rentals,
                donusturulen_sefer_sayisi=existing_trips,
                created_by_id=actor_id,
            )
            db.session.add(run)
            db.session.commit()
        else:
            if run.kaynak_snapshot_sha256 != source_snapshot.get('sha256'):
                raise ValidationError(
                    'Run kimliği farklı bir kaynak snapshot ile oluşturulmuş.'
                )
            resume_report = CariSnapshotService.compare(source_snapshot, current)
            if not resume_report['ok']:
                raise ValidationError(
                    'Yarım dönüşüm dışındaki mali veya belge verileri değişti; '
                    'devam işlemi durduruldu.'
                )
            run.durum = 'uygulaniyor'
            run.hata = None
            db.session.add(run)
            db.session.commit()

        preflight = cls.preflight()
        decision_map = {row['nakliye_id']: row for row in preflight['kararlar']}
        blocked_rentals = {row['kiralama_id'] for row in preflight['engeller']}
        failures = []
        converted_rentals = int(run.donusturulen_kiralama_sayisi or 0)
        converted_trips = int(run.donusturulen_sefer_sayisi or 0)
        rentals = Kiralama.query.filter(
            Kiralama.is_deleted.is_(False),
            Kiralama.nakliye_modeli != 'sefer',
        ).order_by(Kiralama.id).all()

        for kiralama in rentals:
            if kiralama.id in blocked_rentals:
                continue
            before_rental = CariSnapshotService.create_snapshot()
            try:
                trip_count = cls._convert_rental(
                    kiralama, decision_map, run, actor_id=actor_id,
                )
                db.session.flush()
                after_rental = CariSnapshotService.create_snapshot()
                reconciliation = CariSnapshotService.compare(
                    before_rental, after_rental,
                )
                if not reconciliation['ok']:
                    raise ValidationError(
                        f"Cari mutabakatında {reconciliation['hata_sayisi']} hata bulundu: "
                        f"{reconciliation['hatalar']}"
                    )
                converted_rentals += 1
                converted_trips += trip_count
                run.donusturulen_kiralama_sayisi = converted_rentals
                run.donusturulen_sefer_sayisi = converted_trips
                run.durum = 'uygulaniyor'
                run.rapor_json = _canonical_json({
                    'son_basarili_kiralama_id': kiralama.id,
                    'engeller': preflight['engeller'],
                    'hatalar': failures,
                })
                db.session.add(run)
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                run = NakliyeGecisIslemi.query.filter_by(run_uuid=run_uuid).one()
                failures.append({
                    'kiralama_id': kiralama.id,
                    'hata': str(exc),
                })
                run.durum = 'kismi_basarisiz'
                run.hata = str(exc)
                run.rapor_json = _canonical_json({
                    'engeller': preflight['engeller'],
                    'hatalar': failures,
                })
                db.session.add(run)
                db.session.commit()

        run = NakliyeGecisIslemi.query.filter_by(run_uuid=run_uuid).one()
        outstanding = list(preflight['engeller']) + failures
        run.durum = (
            'kismi_basarisiz'
            if outstanding
            else 'donusturuldu_mutabakat_bekliyor'
        )
        run.hata = (
            f'{len(outstanding)} kiralama engelli veya başarısız.'
            if outstanding else None
        )
        run.rapor_json = _canonical_json({
            'engeller': preflight['engeller'],
            'otomatik_onarimlar': preflight['otomatik_onarimlar'],
            'hatalar': failures,
        })
        db.session.add(run)
        db.session.commit()
        return run

    @classmethod
    def convert_single(cls, kiralama, actor_id=None):
        """UI'daki tekil geçiş için aynı korumalı dönüşümü tek transaction'da çalıştırır."""
        if kiralama.nakliye_modeli == 'sefer':
            return None
        before = CariSnapshotService.create_snapshot()
        preflight = cls.preflight()
        blockers = [
            row for row in preflight['engeller'] if row['kiralama_id'] == kiralama.id
        ]
        if blockers:
            raise ValidationError(blockers[0]['hata'])
        decisions = {
            row['nakliye_id']: row for row in preflight['kararlar']
            if row['kiralama_id'] == kiralama.id
        }
        run = NakliyeGecisIslemi(
            run_uuid=str(uuid.uuid4()),
            durum='uygulaniyor',
            kaynak_snapshot_sha256=before['sha256'],
            once_firma_sayisi=len(before['firmalar']),
            once_hareket_sayisi=len(before['hizmet_kayitlari']),
            created_by_id=actor_id,
        )
        db.session.add(run)
        db.session.flush()
        trip_count = cls._convert_rental(
            kiralama, decisions, run, actor_id=actor_id,
        )
        db.session.flush()
        after = CariSnapshotService.create_snapshot()
        report = CariSnapshotService.compare(before, after)
        if not report['ok']:
            raise ValidationError(
                f"Cari mutabakatında {report['hata_sayisi']} hata bulundu; dönüşüm geri alındı."
            )
        run.donusturulen_kiralama_sayisi = 1
        run.donusturulen_sefer_sayisi = trip_count
        run.durum = 'tamamlandi'
        run.rapor_json = _canonical_json(report)
        db.session.add(run)
        return run

    @staticmethod
    def finish_reconciliation(run_uuid, report):
        run = NakliyeGecisIslemi.query.filter_by(run_uuid=run_uuid).one()
        previous_report = {}
        if run.rapor_json:
            try:
                previous_report = json.loads(run.rapor_json)
            except (TypeError, ValueError):
                previous_report = {}
        run.rapor_json = _canonical_json({
            **previous_report,
            'genel_mutabakat': report,
        })
        if run.durum != 'kismi_basarisiz':
            run.durum = 'tamamlandi' if report.get('ok') else 'mutabakat_basarisiz'
        if not report.get('ok'):
            run.hata = f"Cari mutabakatında {report.get('hata_sayisi', 0)} hata bulundu."
        db.session.add(run)
        db.session.commit()
        return run


class TaseronCariBaglantiOnarimService:
    """Dönüştürülmüş seferleri eski taşeron cari kimliklerine güvenle bağlar."""

    @staticmethod
    def _active_allocations(sefer):
        return [
            d for d in sefer.dagitimlar
            if not d.is_deleted and d.is_active
        ]

    @classmethod
    def preflight(cls):
        decisions = []
        blockers = []
        rentals = Kiralama.query.filter(
            Kiralama.is_deleted.is_(False),
            Kiralama.nakliye_modeli == 'sefer',
        ).order_by(Kiralama.id).all()
        for kiralama in rentals:
            for sefer in cls._active_nakliyeler_for_repair(kiralama):
                try:
                    allocations = cls._active_allocations(sefer)
                    if len(allocations) != 1:
                        raise ValidationError(
                            f'Nakliye #{sefer.id} için tam bir aktif dağıtım bekleniyordu; '
                            f'{len(allocations)} kayıt bulundu.'
                        )
                    kalem_id = allocations[0].kiralama_kalemi_id
                    old_candidates = NakliyeSeferService.legacy_taseron_service_candidates(
                        sefer, kiralama, kalem_id,
                    )
                    if len(old_candidates) != 1:
                        raise ValidationError(
                            f'Nakliye #{sefer.id} için tam bir eski taşeron cari hareketi '
                            f'beklenirken {len(old_candidates)} kayıt bulundu.'
                        )
                    old_service = old_candidates[0]
                    canonicals = HizmetKaydi.query.filter_by(
                        nakliye_id=sefer.id, kaynak=GIDER_KAYNAGI,
                    ).filter(
                        HizmetKaydi.is_deleted.is_(False),
                        HizmetKaydi.is_active.is_(True),
                    ).order_by(HizmetKaydi.id).all()
                    duplicates = [h for h in canonicals if h.id != old_service.id]
                    if len(duplicates) > 1:
                        raise ValidationError(
                            f'Nakliye #{sefer.id} için birden fazla yeni mükerrer hareket bulundu.'
                        )
                    duplicate = duplicates[0] if duplicates else None
                    if duplicate:
                        if (
                            duplicate.firma_id != old_service.firma_id
                            or Decimal(str(duplicate.tutar or 0))
                            != Decimal(str(old_service.tutar or 0))
                            or duplicate.fatura_no
                            or NakliyeSeferService._has_any_hakedis_link(duplicate)
                        ):
                            raise ValidationError(
                                f'Nakliye #{sefer.id} mükerrer hareketi mali veya belge '
                                'bağlantısı nedeniyle otomatik kapatılamaz.'
                            )
                    already_linked = (
                        old_service.nakliye_id == sefer.id
                        and old_service.kaynak == GIDER_KAYNAGI
                        and old_service.kiralama_kalemi_id == kalem_id
                        and old_service.nakliye_dagitim_id is None
                    )
                    decisions.append({
                        'kiralama_id': kiralama.id,
                        'nakliye_id': sefer.id,
                        'nakliye_dagitim_id': allocations[0].id,
                        'kiralama_kalemi_id': kalem_id,
                        'taseron_firma_id': sefer.taseron_firma_id,
                        'korunacak_hizmet_kaydi_id': old_service.id,
                        'pasife_alinacak_hizmet_kaydi_id': duplicate.id if duplicate else None,
                        'durum': (
                            'mukerrer_temizlenecek' if duplicate
                            else 'zaten_bagli' if already_linked
                            else 'baglanti_kurulacak'
                        ),
                    })
                except ValidationError as exc:
                    blockers.append({
                        'kiralama_id': kiralama.id,
                        'nakliye_id': sefer.id,
                        'hata': str(exc),
                    })
        return {
            'ok': not blockers,
            'eslesme_sayisi': len(decisions),
            'baglanti_sayisi': sum(
                row['durum'] == 'baglanti_kurulacak' for row in decisions
            ),
            'mukerrer_temizleme_sayisi': sum(
                row['durum'] == 'mukerrer_temizlenecek' for row in decisions
            ),
            'zaten_bagli_sayisi': sum(
                row['durum'] == 'zaten_bagli' for row in decisions
            ),
            'kararlar': decisions,
            'engeller': blockers,
        }

    @staticmethod
    def _active_nakliyeler_for_repair(kiralama):
        return [
            sefer for sefer in kiralama.nakliyeler
            if (
                not sefer.is_deleted
                and sefer.is_active
                and sefer.nakliye_tipi == 'taseron'
                and Decimal(str(sefer.taseron_maliyet or 0)) > 0
            )
        ]

    @classmethod
    def apply(
        cls, actor_id=None, run_uuid=None, expected_snapshot_sha256=None,
        reference_snapshot=None,
    ):
        current = CariSnapshotService.create_snapshot()
        if (
            expected_snapshot_sha256
            and current['sha256'] != expected_snapshot_sha256
        ):
            raise ValidationError(
                'Taşeron bağlantı ön kontrolünden sonra veri değişti; onarım durduruldu.'
            )
        preflight = cls.preflight()
        run_uuid = run_uuid or str(uuid.uuid4())
        existing_run = NakliyeGecisIslemi.query.filter_by(run_uuid=run_uuid).first()
        if existing_run and existing_run.durum == 'tamamlandi':
            return existing_run, preflight
        if existing_run:
            raise ValidationError(f'{run_uuid} kimlikli onarım işlemi tamamlanmamış durumda.')

        run = NakliyeGecisIslemi(
            run_uuid=run_uuid,
            durum='uygulaniyor',
            kaynak_snapshot_sha256=current['sha256'],
            once_firma_sayisi=len(current.get('firmalar', [])),
            once_hareket_sayisi=len(current.get('hizmet_kayitlari', [])),
            created_by_id=actor_id,
        )
        db.session.add(run)
        db.session.commit()

        failures = []
        converted_rentals = set()
        converted_trips = 0
        for decision in preflight['kararlar']:
            if decision['durum'] == 'zaten_bagli':
                continue
            before_snapshot = CariSnapshotService.create_snapshot()
            try:
                old_service = db.session.get(
                    HizmetKaydi, decision['korunacak_hizmet_kaydi_id'],
                )
                duplicate_id = decision['pasife_alinacak_hizmet_kaydi_id']
                if duplicate_id:
                    duplicate = db.session.get(HizmetKaydi, duplicate_id)
                    duplicate_before = _model_row(
                        duplicate, CariSnapshotService.SERVICE_FIELDS,
                    )
                    duplicate.is_deleted = True
                    duplicate.is_active = False
                    duplicate.deleted_at = datetime.now(timezone.utc)
                    duplicate.deleted_by_id = actor_id
                    db.session.add(duplicate)
                    # Benzersiz indeks varken korunan eski kimliği bağlamadan önce
                    # yeni mükerreri aktif indeks kapsamından çıkar.
                    db.session.flush()
                    db.session.add(NakliyeGecisKaydi(
                        islem_id=run.id,
                        kiralama_id=decision['kiralama_id'],
                        nakliye_id=decision['nakliye_id'],
                        nakliye_dagitim_id=decision['nakliye_dagitim_id'],
                        hizmet_kaydi_id=duplicate.id,
                        durum='mukerrer_pasif',
                        once_json=_canonical_json(duplicate_before),
                        sonra_json=_canonical_json(_model_row(
                            duplicate, CariSnapshotService.SERVICE_FIELDS,
                        )),
                        notlar=_canonical_json({
                            'neden': 'post_conversion_duplicate_cleanup',
                            'korunan_hizmet_kaydi_id': old_service.id,
                        }),
                    ))
                before = _model_row(old_service, CariSnapshotService.SERVICE_FIELDS)
                old_service.nakliye_id = decision['nakliye_id']
                old_service.nakliye_dagitim_id = None
                old_service.kiralama_kalemi_id = decision['kiralama_kalemi_id']
                old_service.kaynak = GIDER_KAYNAGI
                db.session.add(old_service)
                db.session.flush()
                if duplicate_id:
                    _sync_firma_financial_cache(old_service.firma_id)
                    db.session.flush()
                db.session.add(NakliyeGecisKaydi(
                    islem_id=run.id,
                    kiralama_id=decision['kiralama_id'],
                    nakliye_id=decision['nakliye_id'],
                    nakliye_dagitim_id=decision['nakliye_dagitim_id'],
                    hizmet_kaydi_id=old_service.id,
                    durum='taseron_baglandi',
                    once_json=_canonical_json(before),
                    sonra_json=_canonical_json(_model_row(
                        old_service, CariSnapshotService.SERVICE_FIELDS,
                    )),
                    notlar=_canonical_json({
                        'neden': 'legacy_taseron_kimligi_korundu',
                    }),
                ))
                db.session.flush()
                active_incoming = HizmetKaydi.query.filter(
                    HizmetKaydi.nakliye_id == decision['nakliye_id'],
                    HizmetKaydi.yon == 'gelen',
                    HizmetKaydi.is_deleted.is_(False),
                    HizmetKaydi.is_active.is_(True),
                ).all()
                if len(active_incoming) != 1 or active_incoming[0].id != old_service.id:
                    raise ValidationError(
                        f"Nakliye #{decision['nakliye_id']} onarımından sonra tek aktif "
                        f"gelen hizmet beklenirken {[h.id for h in active_incoming]} bulundu."
                    )
                after_snapshot = CariSnapshotService.create_snapshot()
                reconciliation = CariSnapshotService.compare(
                    before_snapshot, after_snapshot,
                )
                if not reconciliation['ok']:
                    raise ValidationError(
                        'Taşeron bağlantı onarımı commit öncesi mutabakatı geçemedi: '
                        f"{reconciliation['hatalar']}"
                    )
                converted_rentals.add(decision['kiralama_id'])
                converted_trips += 1
                run.donusturulen_kiralama_sayisi = len(converted_rentals)
                run.donusturulen_sefer_sayisi = converted_trips
                db.session.add(run)
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                run = NakliyeGecisIslemi.query.filter_by(run_uuid=run_uuid).one()
                failures.append({
                    'kiralama_id': decision['kiralama_id'],
                    'nakliye_id': decision['nakliye_id'],
                    'hata': str(exc),
                })
                run.durum = 'kismi_basarisiz'
                run.hata = str(exc)
                db.session.add(run)
                db.session.commit()

        run = NakliyeGecisIslemi.query.filter_by(run_uuid=run_uuid).one()
        verification = cls.verify(reference_snapshot or current)
        all_errors = list(preflight['engeller']) + failures
        unexpected_verification_errors = [
            row for row in verification['hatalar']
            if row not in preflight['engeller']
        ] + list(verification['firma_mali_farklari'])
        all_errors.extend(unexpected_verification_errors)
        run.durum = 'kismi_basarisiz' if all_errors else 'tamamlandi'
        run.hata = (
            f'{len(all_errors)} taşeron seferi engelli veya başarısız.'
            if all_errors else None
        )
        execution_report = {
            **preflight,
            'islem_hatalari': failures,
        }
        run.rapor_json = _canonical_json({
            'preflight': execution_report,
            'verification': verification,
        })
        db.session.add(run)
        db.session.commit()
        return run, execution_report

    @classmethod
    def verify(cls, reference_snapshot=None):
        preflight = cls.preflight()
        active_services = HizmetKaydi.query.filter(
            HizmetKaydi.kaynak == GIDER_KAYNAGI,
            HizmetKaydi.is_deleted.is_(False),
            HizmetKaydi.is_active.is_(True),
        ).all()
        target_ids = {row['nakliye_id'] for row in preflight['kararlar']}
        target_services = [h for h in active_services if h.nakliye_id in target_ids]
        counts = defaultdict(int)
        for hizmet in target_services:
            counts[hizmet.nakliye_id] += 1
        errors = list(preflight['engeller'])
        for nakliye_id in sorted(target_ids):
            if counts[nakliye_id] != 1:
                errors.append({
                    'nakliye_id': nakliye_id,
                    'hata': f'{counts[nakliye_id]} aktif taşeron gideri bulundu.',
                })
        total = sum(
            (Decimal(str(h.tutar or 0)) for h in target_services),
            Decimal('0.00'),
        )
        financial_errors = []
        if reference_snapshot:
            after = CariSnapshotService.create_snapshot()
            comparison = CariSnapshotService.compare(reference_snapshot, after)
            financial_errors = comparison['hatalar']
        return {
            'ok': not errors and not financial_errors,
            'sefer_sayisi': len(target_ids),
            'aktif_hizmet_sayisi': len(target_services),
            'aktif_taseron_gider_toplami': _json_value(total),
            'baglantisiz_sayisi': sum(
                row['durum'] == 'baglanti_kurulacak' for row in preflight['kararlar']
            ),
            'mukerrer_sayisi': sum(
                row['durum'] == 'mukerrer_temizlenecek' for row in preflight['kararlar']
            ),
            'hatalar': errors,
            'firma_mali_farklari': financial_errors,
        }
