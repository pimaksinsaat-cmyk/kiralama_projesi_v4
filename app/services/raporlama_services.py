from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, inspect, or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.araclar.models import Arac, AracBakim
from app.filo.models import Ekipman, BakimKaydi, StokHareket
from app.kiralama.models import KiralamaKalemi
from app.nakliyeler.models import Nakliye
from app.personel.models import PersonelMaasDonemi
from app.subeler.models import Sube, SubeGideri
from app.subeler.models import SubeSabitGiderDonemi


class RaporlamaService:
    """Sirket ve sube bazli raporlama hesaplarini merkezden yonetir."""

    @staticmethod
    def _sube_giderleri_table_exists():
        return inspect(db.engine).has_table(SubeGideri.__tablename__)

    @staticmethod
    def _personel_maas_donemleri_table_exists():
        return inspect(db.engine).has_table(PersonelMaasDonemi.__tablename__)

    @staticmethod
    def _sube_sabit_gider_donemleri_table_exists():
        return inspect(db.engine).has_table(SubeSabitGiderDonemi.__tablename__)

    @staticmethod
    def _arac_bakim_table_exists():
        return inspect(db.engine).has_table(AracBakim.__tablename__)

    @staticmethod
    def _resolve_latest_stock_prices(stok_karti_ids):
        if not stok_karti_ids:
            return {}

        price_map = {}
        stok_hareketleri = (
            StokHareket.query
            .filter(
                StokHareket.stok_karti_id.in_(stok_karti_ids),
                StokHareket.hareket_tipi == 'giris',
            )
            .order_by(StokHareket.stok_karti_id.asc(), StokHareket.tarih.desc(), StokHareket.id.desc())
            .all()
        )

        for hareket in stok_hareketleri:
            if hareket.stok_karti_id not in price_map:
                price_map[hareket.stok_karti_id] = float(hareket.birim_fiyat or 0)

        return price_map

    @classmethod
    def _build_maintenance_cost_rows(cls, start_date, end_date, sube_id=None, ekipman_ids=None):
        query = (
            BakimKaydi.query.options(
                joinedload(BakimKaydi.kullanilan_parcalar),
                joinedload(BakimKaydi.ekipman),
            )
            .join(Ekipman, BakimKaydi.ekipman_id == Ekipman.id)
            .filter(
                BakimKaydi.is_deleted == False,
                Ekipman.is_active == True,
                BakimKaydi.tarih >= start_date,
                BakimKaydi.tarih <= end_date,
            )
        )

        if sube_id:
            query = query.filter(Ekipman.sube_id == sube_id)

        if ekipman_ids is not None:
            if not ekipman_ids:
                return []
            query = query.filter(BakimKaydi.ekipman_id.in_(ekipman_ids))

        bakim_kayitlari = query.all()

        fiyat_gereken_stok_ids = {
            parca.stok_karti_id
            for bakim_kaydi in bakim_kayitlari
            for parca in bakim_kaydi.kullanilan_parcalar
            if parca.stok_karti_id and float(parca.birim_fiyat or 0) <= 0
        }
        latest_price_map = cls._resolve_latest_stock_prices(fiyat_gereken_stok_ids)

        cost_rows = []
        for bakim_kaydi in bakim_kayitlari:
            labor_cost = float(bakim_kaydi.toplam_iscilik_maliyeti or 0)
            material_cost = 0.0

            for parca in bakim_kaydi.kullanilan_parcalar:
                birim_fiyat = float(parca.birim_fiyat or 0)
                if birim_fiyat <= 0 and parca.stok_karti_id:
                    birim_fiyat = latest_price_map.get(parca.stok_karti_id, 0.0)
                material_cost += float(parca.kullanilan_adet or 0) * birim_fiyat

            cost_rows.append(
                {
                    "tarih": bakim_kaydi.tarih,
                    "ekipman_id": bakim_kaydi.ekipman_id,
                    "sube_id": bakim_kaydi.ekipman.sube_id if bakim_kaydi.ekipman else None,
                    "labor_cost": labor_cost,
                    "material_cost": material_cost,
                    "total_cost": labor_cost + material_cost,
                }
            )

        return cost_rows

    @classmethod
    def _build_vehicle_maintenance_cost_rows(cls, start_date, end_date, sube_id=None):
        if not cls._arac_bakim_table_exists():
            return []

        query = (
            AracBakim.query.options(joinedload(AracBakim.arac))
            .join(Arac, AracBakim.arac_id == Arac.id)
            .filter(
                AracBakim.is_deleted == False,
                Arac.is_active == True,
                AracBakim.tarih >= start_date,
                AracBakim.tarih <= end_date,
            )
        )

        if sube_id:
            query = query.filter(Arac.sube_id == sube_id)

        cost_rows = []
        for bakim_kaydi in query.all():
            cost_rows.append(
                {
                    "tarih": bakim_kaydi.tarih,
                    "arac_id": bakim_kaydi.arac_id,
                    "sube_id": bakim_kaydi.arac.sube_id if bakim_kaydi.arac else None,
                    "total_cost": float(bakim_kaydi.maliyet or 0),
                }
            )

        return cost_rows

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

    @staticmethod
    def _iterate_month_starts(start_date, end_date):
        current = date(start_date.year, start_date.month, 1)
        last = date(end_date.year, end_date.month, 1)

        while current <= last:
            yield current
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

    @staticmethod
    def _month_end(month_start):
        if month_start.month == 12:
            return date(month_start.year + 1, 1, 1) - timedelta(days=1)
        return date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)

    @classmethod
    def _allocate_monthly_amount(cls, amount, overlap_start, overlap_end, month_start, month_end):
        if not amount:
            return 0.0

        overlap_days = cls._days_between(overlap_start, overlap_end)
        month_days = cls._days_between(month_start, month_end)
        if overlap_days <= 0 or month_days <= 0:
            return 0.0

        return float(amount or 0) * (overlap_days / month_days)

    @staticmethod
    def _personel_period_total_amount(donem):
        return (
            float(donem.aylik_maas or 0)
            + float(getattr(donem, 'aylik_yemek_ucreti', 0) or 0)
            + float(getattr(donem, 'aylik_yol_ucreti', 0) or 0)
            + float(donem.sgk_isveren_tutari or 0)
            + float(donem.yan_haklar_tutari or 0)
            + float(donem.diger_gider_tutari or 0)
        )

    @classmethod
    def _calculate_personel_cost(cls, start_date, end_date, sube_id=None):
        if not cls._personel_maas_donemleri_table_exists():
            return 0.0

        total_cost = 0.0
        query = PersonelMaasDonemi.query.filter(
            PersonelMaasDonemi.baslangic_tarihi <= end_date,
            or_(PersonelMaasDonemi.bitis_tarihi.is_(None), PersonelMaasDonemi.bitis_tarihi >= start_date),
        )
        if sube_id:
            query = query.filter(PersonelMaasDonemi.sube_id == sube_id)

        today = date.today()
        for donem in query.all():
            effective_end = min(donem.bitis_tarihi or today, today)
            for month_start in cls._iterate_month_starts(start_date, end_date):
                month_end = cls._month_end(month_start)
                overlap = cls._overlap_range(donem.baslangic_tarihi, effective_end, month_start, month_end)
                if not overlap:
                    continue
                total_cost += cls._allocate_monthly_amount(
                    cls._personel_period_total_amount(donem),
                    overlap[0],
                    overlap[1],
                    month_start,
                    month_end,
                )

        return total_cost

    @classmethod
    def _calculate_sabit_gider_cost(cls, start_date, end_date, sube_id=None):
        if not cls._sube_sabit_gider_donemleri_table_exists():
            return 0.0

        total_cost = 0.0
        query = SubeSabitGiderDonemi.query.filter(
            or_(SubeSabitGiderDonemi.bitis_tarihi.is_(None), SubeSabitGiderDonemi.bitis_tarihi >= start_date),
        )
        if sube_id:
            query = query.filter(SubeSabitGiderDonemi.sube_id == sube_id)

        # Her (sube_id, kategori) için en eski kayıt: baslangic_tarihi ileride olsa bile
        # rapor döneminden itibaren aktif say (ilk kayıt her zaman geçerli).
        donemler = query.all()
        en_eski = {}
        for d in donemler:
            k = (d.sube_id, d.kategori)
            if k not in en_eski or d.baslangic_tarihi < en_eski[k]:
                en_eski[k] = d.baslangic_tarihi

        today = date.today()
        for donem in donemler:
            k = (donem.sube_id, donem.kategori)
            # İlk kayıt ilerideyse rapor döneminden itibaren aktif say
            if en_eski[k] == donem.baslangic_tarihi:
                effective_start = min(donem.baslangic_tarihi, start_date)
            else:
                if donem.baslangic_tarihi > end_date:
                    continue
                effective_start = donem.baslangic_tarihi
            effective_end = min(donem.bitis_tarihi or today, today)
            for month_start in cls._iterate_month_starts(start_date, end_date):
                month_end = cls._month_end(month_start)
                overlap = cls._overlap_range(effective_start, effective_end, month_start, month_end)
                if not overlap:
                    continue
                total_cost += cls._allocate_monthly_amount(
                    donem.aylik_tutar,
                    overlap[0],
                    overlap[1],
                    month_start,
                    month_end,
                )

        return total_cost

    @classmethod
    def _calculate_manual_sube_gider_cost(cls, start_date, end_date, sube_id=None):
        if not cls._sube_giderleri_table_exists():
            return 0.0

        query = SubeGideri.query.filter(
            SubeGideri.tarih >= start_date,
            SubeGideri.tarih <= end_date,
        )
        if sube_id:
            query = query.filter(SubeGideri.sube_id == sube_id)

        return float(sum(float(gider.tutar or 0) for gider in query.all()))

    @classmethod
    def _calculate_monthly_revenue_series(
        cls,
        start_date,
        end_date,
        sube_id=None,
        ekipman_ids=None,
    ):
        month_names = ["Oca", "Sub", "Mar", "Nis", "May", "Haz", "Tem", "Agu", "Eyl", "Eki", "Kas", "Ara"]

        month_starts = list(cls._iterate_month_starts(start_date, end_date))
        month_rows = []
        month_index = {}

        for idx, month_start in enumerate(month_starts):
            if month_start.month == 12:
                month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)

            label = f"{month_names[month_start.month - 1]} {month_start.year}"
            key = month_start.strftime("%Y-%m")
            row = {
                "key": key,
                "label": label,
                "month_start": month_start,
                "month_end": month_end,
                "kiralama_geliri": 0.0,
                "harici_gelir": 0.0,
                "harici_odeme": 0.0,
                "harici_kar": 0.0,
                "nakliye_geliri": 0.0,
                "ekipman_bakim_gideri": 0.0,
                "arac_bakim_gideri": 0.0,
                "bakim_gideri": 0.0,
                "manuel_sube_gideri": 0.0,
                "personel_gideri": 0.0,
                "sabit_gideri": 0.0,
                "sube_gideri": 0.0,
                "gelir": 0.0,
                "net_katki": 0.0,
            }
            month_rows.append(row)
            month_index[key] = idx

        rental_query = KiralamaKalemi.query.filter(
            KiralamaKalemi.is_active.is_(True),
            KiralamaKalemi.kiralama_bitis >= start_date,
            KiralamaKalemi.kiralama_baslangici <= end_date,
        )

        if ekipman_ids is not None:
            if not ekipman_ids:
                rental_kalemler = []
            else:
                rental_kalemler = rental_query.filter(KiralamaKalemi.ekipman_id.in_(ekipman_ids)).all()
        else:
            rental_kalemler = rental_query.all()

        for kalem in rental_kalemler:
            overlap = cls._overlap_range(
                kalem.kiralama_baslangici,
                kalem.kiralama_bitis,
                start_date,
                end_date,
            )
            if not overlap:
                continue

            overlap_start, overlap_end = overlap
            birim = float(kalem.kiralama_brm_fiyat or 0)

            for month_row in month_rows:
                month_overlap = cls._overlap_range(
                    overlap_start,
                    overlap_end,
                    month_row["month_start"],
                    month_row["month_end"],
                )
                if not month_overlap:
                    continue

                month_days = cls._days_between(month_overlap[0], month_overlap[1])
                month_row["kiralama_geliri"] += birim * month_days

        external_rental_kalemler = (
            KiralamaKalemi.query
            .filter(
                KiralamaKalemi.is_active.is_(True),
                KiralamaKalemi.is_dis_tedarik_ekipman.is_(True),
                KiralamaKalemi.kiralama_bitis >= start_date,
                KiralamaKalemi.kiralama_baslangici <= end_date,
            )
            .all()
        )

        for kalem in external_rental_kalemler:
            overlap = cls._overlap_range(
                kalem.kiralama_baslangici,
                kalem.kiralama_bitis,
                start_date,
                end_date,
            )
            if not overlap:
                continue

            overlap_start, overlap_end = overlap
            satis_birim = float(kalem.kiralama_brm_fiyat or 0)
            alis_birim = float(kalem.kiralama_alis_fiyat or 0)

            for month_row in month_rows:
                month_overlap = cls._overlap_range(
                    overlap_start,
                    overlap_end,
                    month_row["month_start"],
                    month_row["month_end"],
                )
                if not month_overlap:
                    continue

                month_days = cls._days_between(month_overlap[0], month_overlap[1])
                month_row["harici_gelir"] += satis_birim * month_days
                month_row["harici_odeme"] += alis_birim * month_days

        nakliye_query = Nakliye.query.filter(
            Nakliye.is_active.is_(True),
            Nakliye.tarih >= start_date,
            Nakliye.tarih <= end_date,
        )

        if sube_id:
            nakliye_query = nakliye_query.join(Arac, Nakliye.arac_id == Arac.id).filter(Arac.sube_id == sube_id)

        nakliye_rows = nakliye_query.all()
        for sefer in nakliye_rows:
            month_key = sefer.tarih.strftime("%Y-%m")
            idx = month_index.get(month_key)
            if idx is None:
                continue
            month_rows[idx]["nakliye_geliri"] += float(sefer.toplam_tutar or 0)

        maintenance_rows = cls._build_maintenance_cost_rows(
            start_date=start_date,
            end_date=end_date,
            sube_id=sube_id,
            ekipman_ids=ekipman_ids,
        )
        for maintenance_row in maintenance_rows:
            month_key = maintenance_row["tarih"].strftime("%Y-%m")
            idx = month_index.get(month_key)
            if idx is None:
                continue
            month_rows[idx]["ekipman_bakim_gideri"] += maintenance_row["total_cost"]

        vehicle_maintenance_rows = cls._build_vehicle_maintenance_cost_rows(
            start_date=start_date,
            end_date=end_date,
            sube_id=sube_id,
        )
        for maintenance_row in vehicle_maintenance_rows:
            month_key = maintenance_row["tarih"].strftime("%Y-%m")
            idx = month_index.get(month_key)
            if idx is None:
                continue
            month_rows[idx]["arac_bakim_gideri"] += maintenance_row["total_cost"]

        if cls._sube_giderleri_table_exists():
            gider_query = SubeGideri.query.filter(
                SubeGideri.tarih >= start_date,
                SubeGideri.tarih <= end_date,
            )
            if sube_id:
                gider_query = gider_query.filter(SubeGideri.sube_id == sube_id)

            for gider in gider_query.all():
                month_key = gider.tarih.strftime("%Y-%m")
                idx = month_index.get(month_key)
                if idx is None:
                    continue
                month_rows[idx]["manuel_sube_gideri"] += float(gider.tutar or 0)

        if cls._personel_maas_donemleri_table_exists():
            query = PersonelMaasDonemi.query.filter(
                PersonelMaasDonemi.baslangic_tarihi <= end_date,
                or_(PersonelMaasDonemi.bitis_tarihi.is_(None), PersonelMaasDonemi.bitis_tarihi >= start_date),
            )
            if sube_id:
                query = query.filter(PersonelMaasDonemi.sube_id == sube_id)

            for donem in query.all():
                effective_end = min(donem.bitis_tarihi or date.today(), date.today())
                for month_row in month_rows:
                    month_overlap = cls._overlap_range(
                        donem.baslangic_tarihi,
                        effective_end,
                        month_row["month_start"],
                        month_row["month_end"],
                    )
                    if not month_overlap:
                        continue
                    month_row["personel_gideri"] += cls._allocate_monthly_amount(
                        cls._personel_period_total_amount(donem),
                        month_overlap[0],
                        month_overlap[1],
                        month_row["month_start"],
                        month_row["month_end"],
                    )

        if cls._sube_sabit_gider_donemleri_table_exists():
            query = SubeSabitGiderDonemi.query.filter(
                or_(SubeSabitGiderDonemi.bitis_tarihi.is_(None), SubeSabitGiderDonemi.bitis_tarihi >= start_date),
            )
            if sube_id:
                query = query.filter(SubeSabitGiderDonemi.sube_id == sube_id)

            sabit_donemler = query.all()
            # Her (sube_id, kategori) için en eski kayıt tespit et
            en_eski_sabit = {}
            for d in sabit_donemler:
                k = (d.sube_id, d.kategori)
                if k not in en_eski_sabit or d.baslangic_tarihi < en_eski_sabit[k]:
                    en_eski_sabit[k] = d.baslangic_tarihi

            for donem in sabit_donemler:
                k = (donem.sube_id, donem.kategori)
                # İlk kayıt ilerideyse rapor döneminden itibaren aktif say
                if en_eski_sabit[k] == donem.baslangic_tarihi:
                    effective_start = min(donem.baslangic_tarihi, start_date)
                else:
                    if donem.baslangic_tarihi > end_date:
                        continue
                    effective_start = donem.baslangic_tarihi
                effective_end = min(donem.bitis_tarihi or date.today(), date.today())
                for month_row in month_rows:
                    month_overlap = cls._overlap_range(
                        effective_start,
                        effective_end,
                        month_row["month_start"],
                        month_row["month_end"],
                    )
                    if not month_overlap:
                        continue
                    month_row["sabit_gideri"] += cls._allocate_monthly_amount(
                        donem.aylik_tutar,
                        month_overlap[0],
                        month_overlap[1],
                        month_row["month_start"],
                        month_row["month_end"],
                    )

        for month_row in month_rows:
            month_row["bakim_gideri"] = month_row["ekipman_bakim_gideri"] + month_row["arac_bakim_gideri"]
            month_row["sube_gideri"] = (
                month_row["manuel_sube_gideri"]
                + month_row["personel_gideri"]
                + month_row["sabit_gideri"]
            )
            month_row["harici_kar"] = month_row["harici_gelir"] - month_row["harici_odeme"]
            month_row["gelir"] = (
                month_row["kiralama_geliri"]
                + month_row["harici_kar"]
                + month_row["nakliye_geliri"]
            )
            month_row["net_katki"] = month_row["gelir"] - month_row["bakim_gideri"] - month_row["sube_gideri"]
            month_row.pop("month_start", None)
            month_row.pop("month_end", None)

        return month_rows

    @classmethod
    def _merged_interval_days(cls, intervals):
        if not intervals:
            return 0

        sorted_intervals = sorted(intervals, key=lambda item: item[0])
        merged = []

        for current_start, current_end in sorted_intervals:
            if not merged:
                merged.append([current_start, current_end])
                continue

            last_start, last_end = merged[-1]
            if current_start <= (last_end + timedelta(days=1)):
                merged[-1][1] = max(last_end, current_end)
            else:
                merged.append([current_start, current_end])

        return sum(cls._days_between(item[0], item[1]) for item in merged)

    @staticmethod
    def _machine_availability_days(ekipman, start_date, end_date):
        if start_date > end_date:
            return 0

        return (end_date - start_date).days + 1

    @classmethod
    def _calculate_machine_metrics(cls, ekipmanlar, start_date, end_date):
        ekipman_ids = [item.id for item in ekipmanlar]
        if not ekipman_ids:
            return {}, {
                "machine_count": 0,
                "work_days": 0,
                "available_days": 0,
                "utilization_pct": 0.0,
                "revenue": 0.0,
            }

        kalemler = (
            KiralamaKalemi.query.filter(
                KiralamaKalemi.is_active.is_(True),
                KiralamaKalemi.ekipman_id.in_(ekipman_ids),
                KiralamaKalemi.kiralama_bitis >= start_date,
                KiralamaKalemi.kiralama_baslangici <= end_date,
            )
            .order_by(KiralamaKalemi.kiralama_baslangici.asc())
            .all()
        )

        intervals_by_machine = defaultdict(list)
        revenue_by_machine = defaultdict(float)

        for kalem in kalemler:
            overlap = cls._overlap_range(
                kalem.kiralama_baslangici,
                kalem.kiralama_bitis,
                start_date,
                end_date,
            )
            if not overlap:
                continue

            overlap_start, overlap_end = overlap
            overlap_days = cls._days_between(overlap_start, overlap_end)
            intervals_by_machine[kalem.ekipman_id].append((overlap_start, overlap_end))
            revenue_by_machine[kalem.ekipman_id] += float(kalem.kiralama_brm_fiyat or 0) * overlap_days

        metrics_by_machine = {}
        total_work_days = 0
        total_available_days = 0
        total_revenue = 0.0

        for ekipman in ekipmanlar:
            available_days = cls._machine_availability_days(ekipman, start_date, end_date)
            merged_work_days = cls._merged_interval_days(intervals_by_machine.get(ekipman.id, []))
            work_days = min(merged_work_days, available_days)
            utilization_pct = (work_days / available_days * 100.0) if available_days else 0.0
            revenue = revenue_by_machine.get(ekipman.id, 0.0)

            metrics_by_machine[ekipman.id] = {
                "work_days": work_days,
                "available_days": available_days,
                "utilization_pct": utilization_pct,
                "revenue": revenue,
            }

            total_work_days += work_days
            total_available_days += available_days
            total_revenue += revenue

        return metrics_by_machine, {
            "machine_count": len(ekipmanlar),
            "work_days": total_work_days,
            "available_days": total_available_days,
            "utilization_pct": (total_work_days / total_available_days * 100.0) if total_available_days else 0.0,
            "revenue": total_revenue,
        }

    @staticmethod
    def _default_branch_transport_row():
        return {
            "sefer_sayisi": 0,
            "gelir": 0.0,
            "maliyet": 0.0,
            "net": 0.0,
            "karlilik_pct": 0.0,
        }

    @classmethod
    def _calculate_maintenance_cost(cls, start_date, end_date, sube_id=None, ekipman_ids=None):
        maintenance_rows = cls._build_maintenance_cost_rows(
            start_date=start_date,
            end_date=end_date,
            sube_id=sube_id,
            ekipman_ids=ekipman_ids,
        )
        return float(sum(item["total_cost"] for item in maintenance_rows))

    @classmethod
    def _calculate_transport_metrics(cls, start_date, end_date, sube_id=None):
        nakliyeler = (
            Nakliye.query.options(joinedload(Nakliye.kendi_aracimiz))
            .filter(
                Nakliye.is_active.is_(True),
                Nakliye.tarih >= start_date,
                Nakliye.tarih <= end_date,
            )
            .all()
        )

        arac_query = Arac.query.filter(Arac.is_active.is_(True), Arac.is_nakliye_araci.is_(True))
        if sube_id:
            arac_query = arac_query.filter(Arac.sube_id == sube_id)
        oz_mal_araclar = arac_query.all()

        sube_adlari = {sube.id: sube.isim for sube in Sube.query.filter(Sube.is_active.is_(True)).all()}

        branch_rows = defaultdict(cls._default_branch_transport_row)
        vehicle_rows = {}
        total_taseron_odeme = 0.0

        for sefer in nakliyeler:
            branch_id = None
            branch_name = "Bilinmiyor"

            if sefer.kendi_aracimiz and sefer.kendi_aracimiz.sube_id:
                branch_id = sefer.kendi_aracimiz.sube_id
                branch_name = sube_adlari.get(branch_id, "Bilinmiyor")

            if sube_id and branch_id != sube_id:
                continue

            gelir = float(sefer.toplam_tutar or 0)
            maliyet = float(sefer.taseron_maliyet or 0)
            net = gelir - maliyet

            # Sube eslesmeyen taseron/eksik kayitlar, sube ozetinde belirsiz satir olusturmasin.
            if branch_id is not None:
                branch_rows[branch_id]["sefer_sayisi"] += 1
                branch_rows[branch_id]["gelir"] += gelir
                branch_rows[branch_id]["maliyet"] += maliyet
                branch_rows[branch_id]["net"] += net

            if sefer.arac_id:
                key = f"arac:{sefer.arac_id}"
                arac_etiket = sefer.kendi_aracimiz.plaka if sefer.kendi_aracimiz else (sefer.plaka or "Plaka Yok")
                arac_tipi = "oz_mal"
            else:
                key = f"dis:{sefer.taseron_firma_id or 0}:{sefer.plaka or ''}"
                arac_etiket = sefer.plaka or "Taseron / Plaka Yok"
                arac_tipi = "taseron"
                total_taseron_odeme += maliyet

            if key not in vehicle_rows:
                vehicle_rows[key] = {
                    "arac": arac_etiket,
                    "arac_tipi": arac_tipi,
                    "sube": branch_name,
                    "sefer_sayisi": 0,
                    "gelir": 0.0,
                    "maliyet": 0.0,
                    "net": 0.0,
                    "karlilik_pct": 0.0,
                }

            vehicle_rows[key]["sefer_sayisi"] += 1
            vehicle_rows[key]["gelir"] += gelir
            vehicle_rows[key]["maliyet"] += maliyet
            vehicle_rows[key]["net"] += net

        # Is yapmamis oz mal araclar da tabloda gorunsun.
        for arac in oz_mal_araclar:
            key = f"arac:{arac.id}"
            if key in vehicle_rows:
                continue

            vehicle_rows[key] = {
                "arac": arac.plaka or "Plaka Yok",
                "arac_tipi": "oz_mal",
                "sube": sube_adlari.get(arac.sube_id, "Bilinmiyor"),
                "sefer_sayisi": 0,
                "gelir": 0.0,
                "maliyet": 0.0,
                "net": 0.0,
                "karlilik_pct": 0.0,
            }

        total_gelir = 0.0
        total_maliyet = 0.0
        total_net = 0.0
        total_sefer = 0

        for row in branch_rows.values():
            row["karlilik_pct"] = (row["net"] / row["gelir"] * 100.0) if row["gelir"] else 0.0
            total_gelir += row["gelir"]
            total_maliyet += row["maliyet"]
            total_net += row["net"]
            total_sefer += row["sefer_sayisi"]

        for row in vehicle_rows.values():
            row["karlilik_pct"] = (row["net"] / row["gelir"] * 100.0) if row["gelir"] else 0.0

        return {
            "totals": {
                "sefer_sayisi": total_sefer,
                "gelir": total_gelir,
                "maliyet": total_maliyet,
                "taseron_odeme_toplam": total_taseron_odeme,
                "net": total_net,
                "karlilik_pct": (total_net / total_gelir * 100.0) if total_gelir else 0.0,
            },
            "branch_rows": branch_rows,
            "vehicle_rows": sorted(vehicle_rows.values(), key=lambda row: row["net"], reverse=True),
        }

    @classmethod
    def _calculate_monthly_transport_series(cls, start_date, end_date, sube_id=None):
        month_names = ["Oca", "Sub", "Mar", "Nis", "May", "Haz", "Tem", "Agu", "Eyl", "Eki", "Kas", "Ara"]

        month_rows = []
        month_index = {}
        for month_start in cls._iterate_month_starts(start_date, end_date):
            label = f"{month_names[month_start.month - 1]} {month_start.year}"
            key = month_start.strftime("%Y-%m")
            row = {
                "key": key,
                "label": label,
                "ozmal_gelir": 0.0,
                "dis_tedarik_gelir": 0.0,
                "toplam_gelir": 0.0,
            }
            month_index[key] = len(month_rows)
            month_rows.append(row)

        nakliyeler = (
            Nakliye.query.options(joinedload(Nakliye.kendi_aracimiz))
            .filter(
                Nakliye.is_active.is_(True),
                Nakliye.tarih >= start_date,
                Nakliye.tarih <= end_date,
            )
            .all()
        )

        for sefer in nakliyeler:
            branch_id = None
            if sefer.kendi_aracimiz and sefer.kendi_aracimiz.sube_id:
                branch_id = sefer.kendi_aracimiz.sube_id

            # Sube filtresi secildiyse mevcut nakliye metrikleri ile ayni kurali uygula.
            if sube_id and branch_id != sube_id:
                continue

            month_key = sefer.tarih.strftime("%Y-%m")
            idx = month_index.get(month_key)
            if idx is None:
                continue

            gelir = float(sefer.toplam_tutar or 0)
            if sefer.arac_id:
                month_rows[idx]["ozmal_gelir"] += gelir
            else:
                month_rows[idx]["dis_tedarik_gelir"] += gelir

        for row in month_rows:
            row["toplam_gelir"] = row["ozmal_gelir"] + row["dis_tedarik_gelir"]

        return month_rows

    @staticmethod
    def _projection_group_key(ekipman, projection_mode):
        if projection_mode == "kapasite":
            kapasite = ekipman.kaldirma_kapasitesi or 0
            return f"{kapasite} kg", kapasite

        if projection_mode == "ortam":
            if ekipman.ic_mekan_uygun and ekipman.arazi_tipi_uygun:
                return "Ic + Arazi", 3
            if ekipman.ic_mekan_uygun:
                return "Sadece Ic Mekan", 2
            if ekipman.arazi_tipi_uygun:
                return "Sadece Arazi", 1
            return "Belirtilmemis", 0

        yukseklik = ekipman.calisma_yuksekligi or 0
        return f"{yukseklik} mt", yukseklik

    @classmethod
    def _build_projection(cls, ekipmanlar, start_date, end_date, projection_mode="yukseklik"):
        mode_options = [
            {"value": "yukseklik", "label": "Calisma Yuksekligine Gore"},
            {"value": "kapasite", "label": "Kaldirma Kapasitesine Gore"},
            {"value": "ortam", "label": "Calisma Ortamina Gore"},
        ]

        valid_modes = {item["value"] for item in mode_options}
        if projection_mode not in valid_modes:
            projection_mode = "yukseklik"

        secenekler = []
        sort_values = {}
        groups = defaultdict(list)
        period_days = max(cls._days_between(start_date, end_date), 1)

        for ekipman in ekipmanlar:
            group_label, sort_val = cls._projection_group_key(ekipman, projection_mode)
            groups[group_label].append(ekipman)
            sort_values[group_label] = sort_val

        for group_label, group_machines in groups.items():
            _, totals = cls._calculate_machine_metrics(group_machines, start_date, end_date)
            revenue_per_work_day = (
                totals["revenue"] / totals["work_days"] if totals["work_days"] else 0.0
            )
            projected_work_days = period_days * (totals["utilization_pct"] / 100.0)
            projected_revenue = revenue_per_work_day * projected_work_days

            secenekler.append(
                {
                    "kriter": group_label,
                    "makine_sayisi": totals["machine_count"],
                    "kullanim_pct": totals["utilization_pct"],
                    "gelir": totals["revenue"],
                    "gelir_aktif_gun": revenue_per_work_day,
                    "tahmini_calisma_gun": projected_work_days,
                    "tahmini_ek_gelir": projected_revenue,
                    "skor": 0.0,
                }
            )

        max_projected_revenue = max((item["tahmini_ek_gelir"] for item in secenekler), default=0.0)

        for item in secenekler:
            item["skor"] = (
                item["tahmini_ek_gelir"] / max_projected_revenue * 100.0 if max_projected_revenue else 0.0
            )

        secenekler.sort(
            key=lambda item: (
                item["skor"],
                item["kullanim_pct"],
                sort_values.get(item["kriter"], 0),
            ),
            reverse=True,
        )
        onerilen = secenekler[0] if secenekler else None

        return {
            "secenekler": secenekler,
            "onerilen": onerilen,
            "projection_mode": projection_mode,
            "mode_options": mode_options,
            "formula_label": "Aktif gunluk gelir x donem gunu x kullanim orani",
        }

    @classmethod
    def _calculate_external_rental_metrics(cls, start_date, end_date, sube_id=None):
        # Harici kiralama kalemlerinde dogrudan sube baglantisi olmadigi icin sube filtresi uygulanamiyor.
        kalemler = (
            KiralamaKalemi.query
            .filter(
                KiralamaKalemi.is_active.is_(True),
                KiralamaKalemi.is_dis_tedarik_ekipman.is_(True),
                KiralamaKalemi.kiralama_bitis >= start_date,
                KiralamaKalemi.kiralama_baslangici <= end_date,
            )
            .order_by(KiralamaKalemi.kiralama_baslangici.desc())
            .all()
        )

        rows = []
        total_cost = 0.0
        total_revenue = 0.0

        for kalem in kalemler:
            overlap = cls._overlap_range(
                kalem.kiralama_baslangici,
                kalem.kiralama_bitis,
                start_date,
                end_date,
            )
            if not overlap:
                continue

            overlap_start, overlap_end = overlap
            gun = cls._days_between(overlap_start, overlap_end)
            alis_birim = float(kalem.kiralama_alis_fiyat or 0)
            satis_birim = float(kalem.kiralama_brm_fiyat or 0)
            toplam_odeme = alis_birim * gun
            toplam_gelir = satis_birim * gun
            kar = toplam_gelir - toplam_odeme
            total_cost += toplam_odeme
            total_revenue += toplam_gelir

            tedarikci = "-"
            if kalem.harici_tedarikci and kalem.harici_tedarikci.firma_adi:
                tedarikci = kalem.harici_tedarikci.firma_adi

            musteri = "-"
            if kalem.kiralama and kalem.kiralama.firma_musteri and kalem.kiralama.firma_musteri.firma_adi:
                musteri = kalem.kiralama.firma_musteri.firma_adi

            ekipman_etiket = " ".join(
                part for part in [
                    kalem.harici_ekipman_tipi or "",
                    kalem.harici_ekipman_marka or "",
                    kalem.harici_ekipman_model or "",
                ] if part
            ).strip() or "Harici Ekipman"

            rows.append(
                {
                    "kalem_id": kalem.id,
                    "musteri": musteri,
                    "tedarikci": tedarikci,
                    "ekipman": ekipman_etiket,
                    "baslangic": overlap_start,
                    "bitis": overlap_end,
                    "gun": gun,
                    "alis_birim": alis_birim,
                    "satis_birim": satis_birim,
                    "toplam_odeme": toplam_odeme,
                    "toplam_gelir": toplam_gelir,
                    "kar": kar,
                }
            )

        rows.sort(key=lambda item: item["toplam_odeme"], reverse=True)

        return {
            "count": len(rows),
            "total_cost": total_cost,
            "total_revenue": total_revenue,
            "total_profit": total_revenue - total_cost,
            "rows": rows,
        }

    @classmethod
    def build_dashboard(
        cls,
        start_date,
        end_date,
        sube_id=None,
        calisma_yuksekligi=None,
        projection_mode="yukseklik",
        machine_search="",
        machine_sube_id=None,
        machine_limit=50,
    ):
        aktif_subeler = Sube.query.filter(Sube.is_active.is_(True)).order_by(Sube.isim.asc()).all()
        sube_lookup = {sube.id: sube.isim for sube in aktif_subeler}

        base_query = Ekipman.query.filter(Ekipman.is_active.is_(True))
        if sube_id:
            base_query = base_query.filter(Ekipman.sube_id == sube_id)

        tum_kapsam_makineler = base_query.all()

        if calisma_yuksekligi:
            rapor_makineler = [
                item for item in tum_kapsam_makineler if item.calisma_yuksekligi == calisma_yuksekligi
            ]
        else:
            rapor_makineler = tum_kapsam_makineler

        if machine_sube_id:
            rapor_makineler = [item for item in rapor_makineler if item.sube_id == machine_sube_id]

        machine_code_options = sorted(
            {(item.kod or "").strip() for item in rapor_makineler if (item.kod or "").strip()},
            key=lambda value: value.lower(),
        )

        normalized_machine_search = (machine_search or "").strip().lower()
        if normalized_machine_search:
            rapor_makineler = [
                item for item in rapor_makineler
                if normalized_machine_search in (item.kod or "").lower()
            ]

        allowed_machine_limits = {25, 50, 100, 99999}
        if machine_limit not in allowed_machine_limits:
            machine_limit = 50

        metrics_by_machine, machine_totals = cls._calculate_machine_metrics(
            rapor_makineler, start_date, end_date
        )

        toplam_calisma = machine_totals["work_days"]
        equipment_maintenance_cost_rows = cls._build_maintenance_cost_rows(
            start_date=start_date,
            end_date=end_date,
            sube_id=sube_id,
            ekipman_ids=[item.id for item in rapor_makineler],
        )
        vehicle_maintenance_cost_rows = cls._build_vehicle_maintenance_cost_rows(
            start_date=start_date,
            end_date=end_date,
            sube_id=sube_id,
        )
        equipment_maintenance_cost = float(sum(item["total_cost"] for item in equipment_maintenance_cost_rows))
        vehicle_maintenance_cost = float(sum(item["total_cost"] for item in vehicle_maintenance_cost_rows))
        maintenance_cost = equipment_maintenance_cost + vehicle_maintenance_cost
        maintenance_cost_by_machine = defaultdict(float)
        maintenance_cost_by_branch = defaultdict(float)
        equipment_maintenance_cost_by_branch = defaultdict(float)
        vehicle_maintenance_cost_by_branch = defaultdict(float)
        for maintenance_row in equipment_maintenance_cost_rows:
            maintenance_cost_by_machine[maintenance_row["ekipman_id"]] += maintenance_row["total_cost"]
            maintenance_cost_by_branch[maintenance_row["sube_id"]] += maintenance_row["total_cost"]
            equipment_maintenance_cost_by_branch[maintenance_row["sube_id"]] += maintenance_row["total_cost"]
        for maintenance_row in vehicle_maintenance_cost_rows:
            maintenance_cost_by_branch[maintenance_row["sube_id"]] += maintenance_row["total_cost"]
            vehicle_maintenance_cost_by_branch[maintenance_row["sube_id"]] += maintenance_row["total_cost"]

        branch_machine_rows = defaultdict(
            lambda: {
                "makine_sayisi": 0,
                "work_days": 0,
                "available_days": 0,
                "utilization_pct": 0.0,
                "gelir": 0.0,
            }
        )

        machine_rows = []

        for ekipman in rapor_makineler:
            machine_stat = metrics_by_machine.get(ekipman.id, {})
            work_days = machine_stat.get("work_days", 0)
            available_days = machine_stat.get("available_days", 0)
            utilization_pct = machine_stat.get("utilization_pct", 0.0)
            revenue = machine_stat.get("revenue", 0.0)
            maintenance_cost_for_machine = maintenance_cost_by_machine.get(ekipman.id, 0.0)
            net_contribution = revenue - maintenance_cost_for_machine

            sube_name = sube_lookup.get(ekipman.sube_id, "Subesiz")
            calisma_payi = (work_days / toplam_calisma * 100.0) if toplam_calisma else 0.0

            branch_machine_rows[ekipman.sube_id]["makine_sayisi"] += 1
            branch_machine_rows[ekipman.sube_id]["work_days"] += work_days
            branch_machine_rows[ekipman.sube_id]["available_days"] += available_days
            branch_machine_rows[ekipman.sube_id]["gelir"] += revenue

            machine_rows.append(
                {
                    "ekipman_id": ekipman.id,
                    "kod": ekipman.kod,
                    "marka_model": f"{ekipman.marka} {ekipman.model or ''}".strip(),
                    "sube": sube_name,
                    "yukseklik": ekipman.calisma_yuksekligi,
                    "work_days": work_days,
                    "available_days": available_days,
                    "utilization_pct": utilization_pct,
                    "calisma_payi": calisma_payi,
                    "gelir": revenue,
                    "bakim_gideri": maintenance_cost_for_machine,
                    "net_katki": net_contribution,
                }
            )

        for row in branch_machine_rows.values():
            row["utilization_pct"] = (
                row["work_days"] / row["available_days"] * 100.0 if row["available_days"] else 0.0
            )

        transport_metrics = cls._calculate_transport_metrics(start_date, end_date, sube_id=sube_id)
        transport_totals = transport_metrics["totals"]
        external_rental_metrics = cls._calculate_external_rental_metrics(start_date, end_date, sube_id=sube_id)

        monthly_revenue_rows = cls._calculate_monthly_revenue_series(
            start_date=start_date,
            end_date=end_date,
            sube_id=sube_id,
            ekipman_ids=[item.id for item in rapor_makineler],
        )
        monthly_transport_rows = cls._calculate_monthly_transport_series(
            start_date=start_date,
            end_date=end_date,
            sube_id=sube_id,
        )

        if sube_id:
            branch_ids = {sube_id}
        else:
            # Sirket genelinde, veri olmasa bile aktif tum subeleri listele.
            branch_ids = {sube.id for sube in aktif_subeler}
            # Yalnizca subesi tanimli kayitlari birlestir.
            branch_ids |= {bid for bid in branch_machine_rows.keys() if bid is not None}
            branch_ids |= {bid for bid in transport_metrics["branch_rows"].keys() if bid is not None}
            branch_ids |= {row["sube_id"] for row in vehicle_maintenance_cost_rows if row.get("sube_id") is not None}

        sube_gideri_by_branch = defaultdict(float)
        personel_gideri_by_branch = defaultdict(float)
        sabit_gider_by_branch = defaultdict(float)
        manuel_sube_gideri_by_branch = defaultdict(float)
        if branch_ids:
            if cls._sube_giderleri_table_exists():
                sube_giderleri = SubeGideri.query.filter(
                    SubeGideri.sube_id.in_(list(branch_ids)),
                    SubeGideri.tarih >= start_date,
                    SubeGideri.tarih <= end_date,
                ).all()
                for gider in sube_giderleri:
                    manuel_sube_gideri_by_branch[gider.sube_id] += float(gider.tutar or 0)

            for branch_id in branch_ids:
                personel_gideri_by_branch[branch_id] = cls._calculate_personel_cost(start_date, end_date, sube_id=branch_id)
                sabit_gider_by_branch[branch_id] = cls._calculate_sabit_gider_cost(start_date, end_date, sube_id=branch_id)
                sube_gideri_by_branch[branch_id] = (
                    manuel_sube_gideri_by_branch[branch_id]
                    + personel_gideri_by_branch[branch_id]
                    + sabit_gider_by_branch[branch_id]
                )

        branch_rows = []
        for branch_id in branch_ids:
            machine_row = branch_machine_rows.get(
                branch_id,
                {
                    "makine_sayisi": 0,
                    "work_days": 0,
                    "available_days": 0,
                    "utilization_pct": 0.0,
                    "gelir": 0.0,
                },
            )
            transport_row = transport_metrics["branch_rows"].get(branch_id, cls._default_branch_transport_row())
            branch_maintenance_cost = maintenance_cost_by_branch.get(branch_id, 0.0)
            branch_equipment_maintenance_cost = equipment_maintenance_cost_by_branch.get(branch_id, 0.0)
            branch_vehicle_maintenance_cost = vehicle_maintenance_cost_by_branch.get(branch_id, 0.0)
            branch_sube_gideri = sube_gideri_by_branch.get(branch_id, 0.0)
            branch_personel_gideri = personel_gideri_by_branch.get(branch_id, 0.0)
            branch_sabit_gider = sabit_gider_by_branch.get(branch_id, 0.0)
            branch_manuel_gider = manuel_sube_gideri_by_branch.get(branch_id, 0.0)
            toplam_gelir = machine_row["gelir"] + transport_row["gelir"]
            toplam_katki = machine_row["gelir"] + transport_row["net"]

            branch_name = sube_lookup.get(branch_id, "Sube Atanmamis")
            branch_rows.append(
                {
                    "sube": branch_name,
                    "makine_sayisi": machine_row["makine_sayisi"],
                    "work_days": machine_row["work_days"],
                    "available_days": machine_row["available_days"],
                    "utilization_pct": machine_row["utilization_pct"],
                    "makine_calisma_payi": (
                        machine_row["work_days"] / toplam_calisma * 100.0 if toplam_calisma else 0.0
                    ),
                    "makine_geliri": machine_row["gelir"],
                    "nakliye_sefer": transport_row["sefer_sayisi"],
                    "nakliye_geliri": transport_row["gelir"],
                    "nakliye_maliyeti": transport_row["maliyet"],
                    "nakliye_net": transport_row["net"],
                    "nakliye_karlilik": transport_row["karlilik_pct"],
                    "ekipman_bakim_gideri": branch_equipment_maintenance_cost,
                    "arac_bakim_gideri": branch_vehicle_maintenance_cost,
                    "bakim_gideri": branch_maintenance_cost,
                    "manuel_sube_gideri": branch_manuel_gider,
                    "personel_gideri": branch_personel_gideri,
                    "sabit_gideri": branch_sabit_gider,
                    "sube_gideri": branch_sube_gideri,
                    "toplam_gelir": toplam_gelir,
                    "toplam_katki": toplam_katki,
                }
            )

        branch_total_gelir = sum(item["toplam_gelir"] for item in branch_rows)
        for item in branch_rows:
            item["gelir_payi"] = (item["toplam_gelir"] / branch_total_gelir * 100.0) if branch_total_gelir else 0.0

        branch_rows.sort(key=lambda item: item["toplam_gelir"], reverse=True)
        machine_rows.sort(key=lambda item: item["work_days"], reverse=True)
        machine_total_count = len(machine_rows)
        machine_rows = machine_rows[:machine_limit]
        machine_shown_count = len(machine_rows)

        projection = cls._build_projection(
            tum_kapsam_makineler,
            start_date,
            end_date,
            projection_mode=projection_mode,
        )

        sube_gideri_toplam = sum(row.get("sube_gideri", 0.0) for row in monthly_revenue_rows)
        net_katki_toplam = sum(row.get("net_katki", 0.0) for row in monthly_revenue_rows)

        return {
            "summary": {
                "machine_count": machine_totals["machine_count"],
                "work_days": machine_totals["work_days"],
                "available_days": machine_totals["available_days"],
                "utilization_pct": machine_totals["utilization_pct"],
                "machine_revenue": machine_totals["revenue"],
                "equipment_maintenance_cost": equipment_maintenance_cost,
                "vehicle_maintenance_cost": vehicle_maintenance_cost,
                "maintenance_cost": maintenance_cost,
                "sube_gideri_toplam": sube_gideri_toplam,
                "net_katki_toplam": net_katki_toplam,
                "external_rental_cost": external_rental_metrics["total_cost"],
                "external_rental_revenue": external_rental_metrics["total_revenue"],
                "external_rental_profit": external_rental_metrics["total_profit"],
                "external_rental_count": external_rental_metrics["count"],
                "transport_sefer": transport_totals["sefer_sayisi"],
                "transport_revenue": transport_totals["gelir"],
                "transport_cost": transport_totals["maliyet"],
                "transport_taseron_odeme": transport_totals.get("taseron_odeme_toplam", 0.0),
                "transport_net": transport_totals["net"],
                "transport_margin_pct": transport_totals["karlilik_pct"],
            },
            "branch_rows": branch_rows,
            "machine_rows": machine_rows,
            "transport_vehicle_rows": transport_metrics["vehicle_rows"],
            "external_rental_rows": external_rental_metrics["rows"],
            "monthly_revenue_rows": monthly_revenue_rows,
            "monthly_transport_rows": monthly_transport_rows,
            "projection": projection,
            "filters": {
                "start_date": start_date,
                "end_date": end_date,
                "sube_id": sube_id,
                "calisma_yuksekligi": calisma_yuksekligi,
                "projection_mode": projection["projection_mode"],
                "machine_search": machine_search,
                "machine_sube_id": machine_sube_id,
                "machine_limit": machine_limit,
                "machine_total_count": machine_total_count,
                "machine_shown_count": machine_shown_count,
            },
            "subeler": [{"id": sube.id, "isim": sube.isim} for sube in aktif_subeler],
            "machine_code_options": machine_code_options,
        }
