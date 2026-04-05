from app.firmalar import firmalar_bp
from flask_login import login_required
from app.utils import admin_required
# -------------------------------------------------------------------------
# Sözleşme No Düzelt (Admin)
# -------------------------------------------------------------------------
import os
from io import BytesIO
from flask import render_template, url_for, redirect, flash, request, current_app, send_file
from datetime import date
from flask_login import current_user, login_required
from decimal import Decimal
from sqlalchemy import asc, desc
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from app.firmalar import firmalar_bp
from app.firmalar.forms import FirmaForm
from app.firmalar.models import Firma
from app.extensions import db
from app.services.firma_services import FirmaService
from app.services.base import ValidationError

# --- GÜVENLİK YARDIMCISI ---
def get_actor_id():
    """Kullanıcı giriş yapmışsa ID'sini döner, aksi halde None."""
    return getattr(current_user, 'id', None)


class ListPagination:
    """In-memory list için sayfalama yardımcısı."""
    def __init__(self, total, page, per_page):
        self.total = max(0, int(total or 0))
        self.per_page = max(1, int(per_page or 1))
        self.pages = (self.total + self.per_page - 1) // self.per_page if self.total else 0
        self.page = max(1, min(int(page or 1), self.pages or 1))

    @property
    def has_prev(self): return self.page > 1
    @property
    def has_next(self): return self.page < self.pages
    @property
    def prev_num(self): return self.page - 1
    @property
    def next_num(self): return self.page + 1

    def iter_pages(self, left_edge=1, left_current=1, right_current=2, right_edge=1):
        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    yield None
                yield num
                last = num


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {'1', 'true', 'evet', 'yes', 'x'}:
        return True
    if text in {'0', 'false', 'hayir', 'hayır', 'no', ''}:
        return False
    return default

# -------------------------------------------------------------------------
# 1. Aktif Firma Listeleme
# -------------------------------------------------------------------------
@firmalar_bp.route('/')
@firmalar_bp.route('/index')
@login_required
def index():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 25, type=int)
        if per_page not in {10, 25, 50, 100}:
            per_page = 25
        q = request.args.get('q', '', type=str)
        sort_by = request.args.get('sort_by', 'firma_adi', type=str)
        sort_dir = request.args.get('sort_dir', 'asc', type=str)

        allowed_sort_fields = {
            'firma_adi': Firma.firma_adi,
            'yetkili_adi': Firma.yetkili_adi,
            'vergi_no': Firma.vergi_no
        }
        if sort_by not in allowed_sort_fields:
            sort_by = 'firma_adi'
        if sort_dir not in ('asc', 'desc'):
            sort_dir = 'asc'
        
        query = FirmaService.get_active_firms(search_query=q)
        sort_column = allowed_sort_fields[sort_by]
        sort_expression = asc(sort_column) if sort_dir == 'asc' else desc(sort_column)
        query = query.order_by(None).order_by(sort_expression, desc(Firma.id))
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        from app.firmalar.forms import SozlesmeNoDuzeltForm
        return render_template(
            'firmalar/index.html',
            firmalar=pagination.items,
            pagination=pagination,
            per_page=per_page,
            q=q,
            sort_by=sort_by,
            sort_dir=sort_dir,
            form=SozlesmeNoDuzeltForm()
        )
    except Exception as e:
        current_app.logger.error(f"Firma listesi yüklenirken hata: {str(e)}")
        flash("Firma listesi şu an yüklenemiyor.", "danger")
        return redirect(url_for('main.index')) # Ana sayfaya yönlendir

# -------------------------------------------------------------------------
# 2. Pasif (Arşivlenmiş) Firma Listeleme
# -------------------------------------------------------------------------
@firmalar_bp.route('/pasif')
@login_required
def pasif_index():
    try:
        page = request.args.get('page', 1, type=int)
        q = request.args.get('q', '', type=str)
        
        query = FirmaService.get_inactive_firms(search_query=q)
        pagination = query.paginate(page=page, per_page=50, error_out=False)
        
        return render_template('firmalar/pasif_index.html', firmalar=pagination.items, pagination=pagination, q=q)
    except Exception as e:
        current_app.logger.error(f"Pasif firma listesi hatası: {str(e)}")
        flash("Arşivlenmiş firmalar yüklenemedi.", "danger")
        return redirect(url_for('firmalar.index'))

# -------------------------------------------------------------------------
# 3. Yeni Firma Ekleme
# -------------------------------------------------------------------------
@firmalar_bp.route('/ekle', methods=['GET', 'POST'])
@login_required
def ekle():
    form = FirmaForm()
    
    if form.validate_on_submit():
        try:
            # Servis katmanında tanımlı güncellenebilir alanları süzerek al
            data = {k: v for k, v in form.data.items() if k in FirmaService.updatable_fields}
            
            # Başlangıç değerlerini set et
            data.update({
                'bakiye': Decimal('0'),
                'sozlesme_rev_no': 0,
                'sozlesme_no': None
            })
            
            yeni_firma = Firma(**data)
            FirmaService.save(yeni_firma, actor_id=get_actor_id())
            
            flash(f"'{yeni_firma.firma_adi}' başarıyla sisteme kaydedildi.", "success")
            return redirect(url_for('firmalar.index'))
        except ValidationError as e:
            flash(str(e), "warning")
        except Exception as e:
            current_app.logger.error(f"Firma ekleme hatası: {str(e)}")
            flash("Kayıt sırasında sistemsel bir hata oluştu.", "danger")
            
    return render_template('firmalar/ekle.html', form=form, today_date=date.today().strftime('%d.%m.%Y'))

# -------------------------------------------------------------------------
# 4. Sözleşme Hazırla
# -------------------------------------------------------------------------
@firmalar_bp.route('/sozlesme-hazirla/<int:id>', methods=['POST'])
@login_required
def sozlesme_hazirla(id):
    try:
        app_path = os.path.join(os.getcwd(), 'app')
        FirmaService.sozlesme_hazirla(firma_id=id, base_app_path=app_path, actor_id=get_actor_id())
        flash("Sözleşme numarası başarıyla atandı ve arşiv klasörleri oluşturuldu.", "success")
    except ValidationError as e:
        flash(str(e), "warning")
    except Exception as e:
        current_app.logger.error(f"Sözleşme hazırlama hatası (Firma ID: {id}): {str(e)}")
        flash("Klasör yapısı oluşturulurken bir hata meydana geldi.", "danger")
    return redirect(url_for('firmalar.index'))

# -------------------------------------------------------------------------
# 5. Firma Düzenleme
# -------------------------------------------------------------------------
@firmalar_bp.route('/duzelt/<int:id>', methods=['GET', 'POST'])
@login_required
def duzelt(id):
    firma = FirmaService.get_by_id(id)
    if not firma:
        flash("Düzenlenmek istenen firma bulunamadı!", "danger")
        return redirect(url_for('firmalar.index'))
        
    form = FirmaForm(obj=firma)
    
    # Özel alanları form verisine elle eşle (Form yapısına göre)
    if request.method == 'GET':
        form.genel_sozlesme_no.data = firma.sozlesme_no
        form.sozlesme_rev_no.data = firma.sozlesme_rev_no
        form.sozlesme_tarihi.data = firma.sozlesme_tarihi

    if form.validate_on_submit():
        try:
            data = {k: v for k, v in form.data.items() if k in FirmaService.updatable_fields}
            
            # Formdaki özel alanları veritabanı alanlarıyla eşleştir
            data.update({
                'sozlesme_no': form.genel_sozlesme_no.data,
                'sozlesme_rev_no': form.sozlesme_rev_no.data,
                'sozlesme_tarihi': form.sozlesme_tarihi.data
            })
            
            FirmaService.update(id, data, actor_id=get_actor_id())
            flash(f"'{firma.firma_adi}' bilgileri başarıyla güncellendi.", 'success')
            return redirect(url_for('firmalar.index'))
        except ValidationError as e:
            flash(str(e), "danger")
        except Exception as e:
            current_app.logger.error(f"Firma güncelleme hatası (ID: {id}): {str(e)}")
            flash("Bilgiler güncellenirken bir hata oluştu.", "danger")
            
    return render_template('firmalar/duzelt.html', form=form, firma=firma)

# -------------------------------------------------------------------------
# 6. Firma Bilgi / Cari Ekstre
# -------------------------------------------------------------------------
@firmalar_bp.route('/bilgi/<int:id>', methods=['GET'])
@login_required
def bilgi(id):
    # --- LOG: Taşeron Nakliye Bedeli ---
    try:
        nakliye_hareketler = [h for h in hareketler_all if (getattr(h, 'tur', None) == 'Nakliye') or (isinstance(h, dict) and h.get('tur') == 'Nakliye')]
        for i, islem in enumerate(nakliye_hareketler):
            if isinstance(islem, dict):
                log_str = f"[NAKLIYE] Hareket {i+1}: id={islem.get('id')}, aciklama={islem.get('aciklama')}, kdv_orani={islem.get('kdv_orani')}, tutar={islem.get('tutar')}"
            else:
                log_str = f"[NAKLIYE] Hareket {i+1}: id={getattr(islem, 'id', None)}, aciklama={getattr(islem, 'aciklama', None)}, kdv_orani={getattr(islem, 'kdv_orani', None)}, tutar={getattr(islem, 'tutar', None)}"
            current_app.logger.debug(log_str)
    except Exception as log_ex:
        current_app.logger.warning(f"[NAKLIYE] LOG sırasında hata: {log_ex}")

    try:
        tab = request.args.get('tab', 'hareket')

        hareket_per_page = request.args.get('hareket_per_page', 25, type=int)
        hareket_page     = request.args.get('hareket_page', 1, type=int)
        kiralama_per_page = request.args.get('kiralama_per_page', 25, type=int)
        kiralama_page     = request.args.get('kiralama_page', 1, type=int)

        allowed_pp = {10, 25, 50, 100}
        if hareket_per_page not in allowed_pp:   hareket_per_page = 25
        if kiralama_per_page not in allowed_pp:  kiralama_per_page = 25

        finans_verileri = FirmaService.get_financial_summary(id)

        # --- Cari Hareketler sayfalama ---
        hareketler_all = finans_verileri.pop('hareketler')
        h_pag = ListPagination(total=len(hareketler_all), page=hareket_page, per_page=hareket_per_page)
        hb = (h_pag.page - 1) * h_pag.per_page
        hareketler_sayfa = hareketler_all[hb: hb + h_pag.per_page]

        # --- LOG: Taşeron Nakliye Bedeli ---
        try:
            nakliye_hareketler = [h for h in hareketler_all if (getattr(h, 'tur', None) == 'Nakliye') or (isinstance(h, dict) and h.get('tur') == 'Nakliye')]
            for i, islem in enumerate(nakliye_hareketler):
                if isinstance(islem, dict):
                    log_str = f"[NAKLIYE] Hareket {i+1}: id={islem.get('id')}, aciklama={islem.get('aciklama')}, kdv_orani={islem.get('kdv_orani')}, tutar={islem.get('tutar')}"
                else:
                    log_str = f"[NAKLIYE] Hareket {i+1}: id={getattr(islem, 'id', None)}, aciklama={getattr(islem, 'aciklama', None)}, kdv_orani={getattr(islem, 'kdv_orani', None)}, tutar={getattr(islem, 'tutar', None)}"
                current_app.logger.debug(log_str)
        except Exception as log_ex:
            current_app.logger.warning(f"[NAKLIYE] LOG sırasında hata: {log_ex}")

        # --- Kiralamalar sayfalama ---
        firma = finans_verileri['firma']
        kiralamalar_all = sorted(firma.kiralamalar, key=lambda k: k.kiralama_form_no or '', reverse=True)
        k_pag = ListPagination(total=len(kiralamalar_all), page=kiralama_page, per_page=kiralama_per_page)
        kb = (k_pag.page - 1) * k_pag.per_page
        kiralamalar_sayfa = kiralamalar_all[kb: kb + k_pag.per_page]

        # --- LOG: firmalar.bilgi.html render öncesi ---
        try:
            current_app.logger.debug(f"[BILGI] Firma ID: {firma.id}, Adı: {firma.firma_adi}")
            current_app.logger.debug(f"[BILGI] Toplam hareket: {len(hareketler_all)}, Toplam kiralama: {len(kiralamalar_all)}")
            for i, islem in enumerate(hareketler_all[:3]):
                kdv = getattr(islem, 'kdv_orani', None)
                current_app.logger.debug(f"[BILGI] Hareket {i+1}: id={getattr(islem, 'id', None)}, tur={getattr(islem, 'tur', None)}, kdv_orani={kdv}")
            for i, kiralama in enumerate(kiralamalar_all[:3]):
                kdv = getattr(kiralama, 'kdv_orani', None)
                current_app.logger.debug(f"[BILGI] Kiralama {i+1}: id={getattr(kiralama, 'id', None)}, kdv_orani={kdv}")
        except Exception as log_ex:
            current_app.logger.warning(f"[BILGI] LOG sırasında hata: {log_ex}")

        return render_template(
            'firmalar/bilgi.html',
            **finans_verileri,
            hareketler=hareketler_sayfa,
            hareket_pagination=h_pag,
            hareket_per_page=hareket_per_page,
            kiralamalar_sayfa=kiralamalar_sayfa,
            kiralama_pagination=k_pag,
            kiralama_per_page=kiralama_per_page,
            tab=tab,
        )
    except ValidationError as e:
        flash(str(e), "danger")
        return redirect(url_for('firmalar.index'))
    except Exception as e:
        current_app.logger.error(f"Cari özet yükleme hatası (Firma ID: {id}): {str(e)}")
        flash("Finansal veriler şu an hesaplanamıyor.", "danger")
        return redirect(url_for('firmalar.index'))

# -------------------------------------------------------------------------
# YAZDIR: Firma Cari Hareketleri (Tüm Kayıtlar, Sayfalama Yok)
# -------------------------------------------------------------------------
@firmalar_bp.route('/bilgi/<int:id>/yazdir')
@login_required
def bilgi_yazdir(id):
    try:
        tab = request.args.get('tab', 'hareket')
        finans_verileri = FirmaService.get_financial_summary(id)
        hareketler = finans_verileri.pop('hareketler')
        firma = finans_verileri['firma']
        kiralamalar_all = sorted(firma.kiralamalar, key=lambda k: k.id, reverse=True)
        return render_template(
            'firmalar/yazdir.html',
            **finans_verileri,
            hareketler=hareketler,
            kiralamalar=kiralamalar_all,
            tab=tab,
            rapor_tarihi=date.today().strftime('%d.%m.%Y'),
        )
    except Exception as e:
        flash("Yazdırma verisi yüklenemedi.", "danger")
        return redirect(url_for('firmalar.bilgi', id=id))


@firmalar_bp.route('/bilgi/<int:id>/excel')
@login_required
def bilgi_excel(id):
    try:
        tab = request.args.get('tab', 'hareket')
        finans_verileri = FirmaService.get_financial_summary(id)
        hareketler = finans_verileri.pop('hareketler')
        firma = finans_verileri['firma']
        kiralamalar = sorted(firma.kiralamalar, key=lambda k: k.id, reverse=True)
        rapor_tarihi = date.today().strftime('%d.%m.%Y')

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Kiralamalar' if tab == 'kiralama' else 'Cari Hareketler'
        sheet.sheet_view.showGridLines = False
        sheet.page_setup.orientation = sheet.ORIENTATION_LANDSCAPE
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True

        title_font = Font(name='Calibri', size=14, bold=True, color='1F1F1F')
        meta_font = Font(name='Calibri', size=10, color='44546A')
        header_font = Font(name='Calibri', size=10, bold=True, color='18324A')
        body_font = Font(name='Calibri', size=10, color='1F1F1F')
        total_font = Font(name='Calibri', size=10, bold=True, color='1F1F1F')

        header_fill = PatternFill(fill_type='solid', fgColor='DBE7F3')
        total_fill = PatternFill(fill_type='solid', fgColor='F0F0F0')

        thin_blue = Side(style='thin', color='D9E2F0')
        dark_blue = Side(style='medium', color='18324A')

        header_border = Border(top=dark_blue, bottom=dark_blue)
        cell_border = Border(bottom=thin_blue)
        total_border = Border(top=dark_blue)

        left_alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
        center_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        right_alignment = Alignment(horizontal='right', vertical='center', wrap_text=True)

        def set_cell(row, column, value, font=None, fill=None, border=None, alignment=None, number_format=None):
            cell = sheet.cell(row=row, column=column, value=value)
            if font:
                cell.font = font
            if fill:
                cell.fill = fill
            if border:
                cell.border = border
            if alignment:
                cell.alignment = alignment
            if number_format:
                cell.number_format = number_format
            return cell

        def item_value(item, key, default=None):
            if isinstance(item, dict):
                return item.get(key, default)
            return getattr(item, key, default)

        if tab == 'kiralama':
            headers = ['#', 'Form No', 'Ekipmanlar', 'Durumları', 'Genel Durum']
            column_widths = {'A': 6, 'B': 18, 'C': 54, 'D': 18, 'E': 22}
            sheet.merge_cells('A1:E1')
            set_cell(1, 1, 'Kiralama Listesi', font=title_font, alignment=left_alignment)
            sheet.merge_cells('A2:C2')
            set_cell(2, 1, f'Firma: {firma.firma_adi}', font=meta_font, alignment=left_alignment)
            sheet.merge_cells('D2:E2')
            set_cell(2, 4, f'Rapor Tarihi: {rapor_tarihi}', font=meta_font, alignment=left_alignment)

            header_row = 4
            for col_idx, header in enumerate(headers, start=1):
                align = center_alignment if col_idx in {1, 4, 5} else left_alignment
                set_cell(header_row, col_idx, header, font=header_font, fill=header_fill, border=header_border, alignment=align)

            current_row = 5
            for index, kiralama in enumerate(kiralamalar, start=1):
                kalemler = list(kiralama.kalemler or [])
                toplam = len(kalemler)
                biten = len([kalem for kalem in kalemler if kalem.sonlandirildi])
                if biten == 0:
                    genel_durum = 'Tamamı Sahada'
                elif biten == toplam:
                    genel_durum = 'Sözleşme Kapandı'
                else:
                    genel_durum = f'Parçalı Teslimat\n({biten}/{toplam} makine döndü)'

                grup_satir_sayisi = max(1, toplam)
                grup_baslangic = current_row
                grup_bitis = current_row + grup_satir_sayisi - 1

                if grup_satir_sayisi > 1:
                    sheet.merge_cells(start_row=grup_baslangic, start_column=1, end_row=grup_bitis, end_column=1)
                    sheet.merge_cells(start_row=grup_baslangic, start_column=2, end_row=grup_bitis, end_column=2)
                    sheet.merge_cells(start_row=grup_baslangic, start_column=5, end_row=grup_bitis, end_column=5)

                set_cell(grup_baslangic, 1, index, font=body_font, border=cell_border, alignment=center_alignment)
                set_cell(grup_baslangic, 2, kiralama.kiralama_form_no or 'Belirtilmemiş', font=body_font, border=cell_border, alignment=left_alignment)
                set_cell(grup_baslangic, 5, genel_durum, font=body_font, border=cell_border, alignment=center_alignment)

                if not kalemler:
                    set_cell(grup_baslangic, 3, 'Ekipman bilgisi yok', font=body_font, border=cell_border, alignment=left_alignment)
                    set_cell(grup_baslangic, 4, '-', font=body_font, border=cell_border, alignment=left_alignment)
                else:
                    for satir_ofset, kalem in enumerate(kalemler):
                        satir_no = grup_baslangic + satir_ofset
                        ekipman = getattr(kalem, 'ekipman', None)
                        if ekipman:
                            marka = (getattr(ekipman, 'marka', '') or '').strip()
                            model = (getattr(ekipman, 'model', '') or '').strip()
                            ekipman_adi = f'{marka} - {model}'.strip(' -')
                            kod = (getattr(ekipman, 'kod', '') or '').strip()
                            ekipman_metni = f'({kod}) {ekipman_adi}'.strip() if kod else (ekipman_adi or getattr(ekipman, 'tipi', 'Ekipman bilgisi yok'))
                        else:
                            marka = (getattr(kalem, 'harici_ekipman_marka', '') or '').strip()
                            model = (getattr(kalem, 'harici_ekipman_model', '') or '').strip()
                            ekipman_adi = f'{marka} - {model}'.strip(' -')
                            ekipman_metni = f'(Dış Tedarik) {ekipman_adi}'.strip() if ekipman_adi else 'Ekipman bilgisi yok'

                        if getattr(kalem, 'is_dis_tedarik_ekipman', False) and getattr(kalem, 'harici_tedarikci', None):
                            ekipman_metni = f"{ekipman_metni}\nTedarikçi: {kalem.harici_tedarikci.firma_adi}"

                        if kalem.sonlandirildi:
                            durum_metni = f"Bitti\n{kalem.kiralama_baslangici.strftime('%d.%m.%Y')} - {kalem.kiralama_bitis.strftime('%d.%m.%Y')}"
                        else:
                            durum_metni = f"Aktif\n{kalem.kiralama_baslangici.strftime('%d.%m.%Y')} tarihinden beri sahada"

                        set_cell(satir_no, 3, ekipman_metni, font=body_font, border=cell_border, alignment=left_alignment)
                        set_cell(satir_no, 4, durum_metni, font=body_font, border=cell_border, alignment=left_alignment)

                current_row = grup_bitis + 1

            if kiralamalar:
                sheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=5)
                set_cell(current_row, 1, f'TOPLAM: {len(kiralamalar)} kiralama kaydı', font=total_font, fill=total_fill, border=total_border, alignment=left_alignment)

        else:
            headers = ['#', 'Tarih', 'İşlem Türü', 'Açıklama', 'Matrah', 'KDV Oranı', 'KDV Tutarı', 'Borç', 'Alacak', 'Bakiye']
            column_widths = {'A': 6, 'B': 14, 'C': 16, 'D': 42, 'E': 14, 'F': 12, 'G': 14, 'H': 14, 'I': 14, 'J': 14}
            sheet.merge_cells('A1:J1')
            set_cell(1, 1, 'Cari Hesap Ekstresi', font=title_font, alignment=left_alignment)
            sheet.merge_cells('A2:E2')
            set_cell(2, 1, f'Firma: {firma.firma_adi}', font=meta_font, alignment=left_alignment)
            sheet.merge_cells('F2:J2')
            set_cell(2, 6, f'Rapor Tarihi: {rapor_tarihi}', font=meta_font, alignment=left_alignment)
            sheet.merge_cells('A3:D3')
            set_cell(3, 1, f"Toplam Borç: {finans_verileri.get('toplam_borc', 0):,.2f} TL".replace(',', 'X').replace('.', ',').replace('X', '.'), font=meta_font, alignment=left_alignment)
            sheet.merge_cells('E3:G3')
            set_cell(3, 5, f"Toplam Alacak: {abs(finans_verileri.get('toplam_alacak', 0)) :,.2f} TL".replace(',', 'X').replace('.', ',').replace('X', '.'), font=meta_font, alignment=left_alignment)
            sheet.merge_cells('H3:J3')
            set_cell(3, 8, f"Güncel Bakiye: {finans_verileri.get('guncel_bakiye', 0):,.2f} TL".replace(',', 'X').replace('.', ',').replace('X', '.'), font=meta_font, alignment=left_alignment)

            header_row = 5
            for col_idx, header in enumerate(headers, start=1):
                align = center_alignment if col_idx in {1, 2, 3, 6} else right_alignment if col_idx >= 5 else left_alignment
                set_cell(header_row, col_idx, header, font=header_font, fill=header_fill, border=header_border, alignment=align)

            current_row = 6
            for index, islem in enumerate(hareketler, start=1):
                islem_tur = item_value(islem, 'tur', '')
                islem_ozel_id = item_value(islem, 'ozel_id')
                islem_tur_tipi = item_value(islem, 'tur_tipi', '')
                islem_aciklama = item_value(islem, 'aciklama', '')
                islem_belge_no = item_value(islem, 'belge_no')
                islem_tarih = item_value(islem, 'tarih')
                islem_tutar = item_value(islem, 'tutar')
                islem_kdv_tutari = item_value(islem, 'kdv_tutari')
                islem_borc = item_value(islem, 'borc')
                islem_alacak = item_value(islem, 'alacak')
                islem_bakiye = item_value(islem, 'kumulatif_bakiye')
                islem_kiralama_alis_kdv = item_value(islem, 'kiralama_alis_kdv')
                islem_nakliye_alis_kdv = item_value(islem, 'nakliye_alis_kdv')
                islem_kdv_orani = item_value(islem, 'kdv_orani')

                is_kiralama = islem_tur == 'Kiralama' and islem_ozel_id
                is_nakliye = islem_tur == 'Nakliye' and islem_ozel_id
                if is_kiralama:
                    islem_turu = 'Kiralama'
                elif is_nakliye:
                    islem_turu = 'Nakliye'
                elif 'Fatura' in islem_tur or 'Hizmet' in islem_tur:
                    islem_turu = 'Fatura'
                elif islem_tur == 'Tahsilat (Giriş)':
                    islem_turu = 'Tahsilat'
                elif islem_tur == 'Ödeme (Çıkış)':
                    islem_turu = 'Ödeme'
                else:
                    islem_turu = islem_tur

                aciklama = islem_aciklama or ''
                if islem_belge_no:
                    belge_metni = f"Kasa: {islem_belge_no}" if islem_tur_tipi == 'odeme' else f"No: {islem_belge_no}"
                    aciklama = f"{aciklama}\n{belge_metni}" if aciklama else belge_metni

                if islem_kiralama_alis_kdv is not None:
                    kdv_orani = float(islem_kiralama_alis_kdv)
                elif islem_nakliye_alis_kdv is not None:
                    kdv_orani = float(islem_nakliye_alis_kdv)
                elif islem_kdv_orani is not None:
                    kdv_orani = float(islem_kdv_orani)
                else:
                    kdv_orani = None

                matrah = None
                if islem_tur_tipi != 'odeme' and islem_tutar not in (None, 0):
                    matrah = abs(float(islem_tutar))

                kdv_tutari = float(islem_kdv_tutari) if islem_kdv_tutari is not None else None
                borc = float(islem_borc) if islem_borc not in (None, 0) else None
                alacak = float(islem_alacak) if islem_alacak not in (None, 0) else None
                bakiye = float(islem_bakiye) if islem_bakiye is not None else 0

                row_data = [
                    index,
                    islem_tarih.strftime('%d.%m.%Y') if islem_tarih else '-',
                    islem_turu,
                    aciklama,
                    matrah,
                    kdv_orani,
                    kdv_tutari,
                    borc,
                    alacak,
                    bakiye,
                ]

                for col_idx, value in enumerate(row_data, start=1):
                    if col_idx in {5, 6, 7, 8, 9, 10} and value is not None:
                        number_format = '0.00' if col_idx == 6 else '#,##0.00'
                        set_cell(current_row, col_idx, value, font=body_font, border=cell_border, alignment=right_alignment, number_format=number_format)
                    else:
                        display_value = value if value not in (None, '') else '-'
                        align = center_alignment if col_idx in {1, 2, 3} else left_alignment
                        set_cell(current_row, col_idx, display_value, font=body_font, border=cell_border, alignment=align)
                current_row += 1

            if hareketler:
                sheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=7)
                set_cell(current_row, 1, 'NET BAKİYE:', font=total_font, fill=total_fill, border=total_border, alignment=right_alignment)
                set_cell(current_row, 8, float(finans_verileri.get('toplam_borc', 0) or 0), font=total_font, fill=total_fill, border=total_border, alignment=right_alignment, number_format='#,##0.00')
                set_cell(current_row, 9, abs(float(finans_verileri.get('toplam_alacak', 0) or 0)), font=total_font, fill=total_fill, border=total_border, alignment=right_alignment, number_format='#,##0.00')
                set_cell(current_row, 10, float(finans_verileri.get('guncel_bakiye', 0) or 0), font=total_font, fill=total_fill, border=total_border, alignment=right_alignment, number_format='#,##0.00')

        for column_letter, width in column_widths.items():
            sheet.column_dimensions[column_letter].width = width

        max_row = sheet.max_row
        start_row = 5 if tab == 'kiralama' else 6
        for row_idx in range(start_row, max_row + 1):
            sheet.row_dimensions[row_idx].height = 42 if tab == 'kiralama' else 34

        output = BytesIO()
        workbook.save(output)
        output.seek(0)

        file_stub = 'firma_kiralama_listesi' if tab == 'kiralama' else 'firma_cari_ekstresi'
        file_name = f'{file_stub}_{id}_{date.today().strftime("%Y%m%d")}.xlsx'
        return send_file(
            output,
            as_attachment=True,
            download_name=file_name,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
    except Exception as e:
        current_app.logger.error(f'Excel export hatası (Firma ID: {id}): {str(e)}')
        flash('Excel çıktısı hazırlanamadı.', 'danger')
        return redirect(url_for('firmalar.bilgi_yazdir', id=id, tab=request.args.get('tab', 'hareket')))


# -------------------------------------------------------------------------
# 7. Firmayı Arşive Kaldır (Silme - Kontrollü)
# -------------------------------------------------------------------------
@firmalar_bp.route('/sil/<int:id>', methods=['POST'])
@login_required
def sil(id):
    try:
        FirmaService.archive_with_check(id, actor_id=get_actor_id())
        flash("Firma başarıyla arşive kaldırıldı.", 'success')
    except ValidationError as e:
        flash(str(e), 'warning')
    except Exception as e:
        current_app.logger.error(f"Arşivleme hatası (ID: {id}): {str(e)}")
        flash("İşlem sırasında sistemsel bir hata oluştu.", 'danger')
    return redirect(url_for('firmalar.index'))

# -------------------------------------------------------------------------
# 8. Firmayı Aktifleştir (Arşivden Geri Al)
# -------------------------------------------------------------------------
@firmalar_bp.route('/aktiflestir/<int:id>', methods=['POST'])
@login_required
def aktiflestir(id):
    try:
        FirmaService.update(id, {'is_active': True}, actor_id=get_actor_id())
        flash("Firma başarıyla tekrar aktif hale getirildi.", "success")
    except Exception as e:
        current_app.logger.error(f"Aktifleştirme hatası (ID: {id}): {str(e)}")
        flash("İşlem başarısız oldu.", "danger")
    return redirect(url_for('firmalar.pasif_index'))

# -------------------------------------------------------------------------
# 9. İmza Yetkisi Kontrolü
# -------------------------------------------------------------------------
@firmalar_bp.route('/imza-kontrol/<int:id>', methods=['POST'])
@login_required
def imza_kontrol(id):
    try:
        FirmaService.update(
            id, 
            {'imza_yetkisi_kontrol_edildi': True, 'imza_yetkisi_kontrol_tarihi': date.today()}, 
            actor_id=get_actor_id()
        )
        flash("İmza yetkisi başarıyla onaylandı.", "success")
    except ValidationError as e:
        flash(str(e), "danger")
    except Exception as e:
        current_app.logger.error(f"İmza kontrol hatası (ID: {id}): {str(e)}")
        flash("Onay işlemi yapılamadı.", "danger")
    return redirect(url_for('firmalar.bilgi', id=id))


# -------------------------------------------------------------------------
# 10. Excel Dışa Aktar / İçe Yükle
# -------------------------------------------------------------------------
@firmalar_bp.route('/excel-disari-aktar', methods=['GET'])
@login_required
def excel_disari_aktar():
    firmalar = Firma.query.filter_by(is_active=True).order_by(Firma.firma_adi).all()

    wb = Workbook()
    ws = wb.active
    ws.title = 'Firmalar'

    headers = [
        'Firma Adi', 'Yetkili Adi', 'Telefon', 'Eposta', 'Iletisim Bilgileri',
        'Vergi Dairesi', 'Vergi No', 'Musteri Mi', 'Tedarikci Mi', 'Aktif Mi'
    ]
    ws.append(headers)

    for f in firmalar:
        ws.append([
            f.firma_adi,
            f.yetkili_adi,
            f.telefon,
            f.eposta,
            f.iletisim_bilgileri,
            f.vergi_dairesi,
            f.vergi_no,
            'Evet' if f.is_musteri else 'Hayir',
            'Evet' if f.is_tedarikci else 'Hayir',
            'Evet' if f.is_active else 'Hayir',
        ])

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    return send_file(
        stream,
        as_attachment=True,
        download_name=f"firmalar_{date.today().strftime('%Y%m%d')}.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


@firmalar_bp.route('/excel-ice-yukle', methods=['POST'])
@login_required
def excel_ice_yukle():
    file = request.files.get('excel_file')
    if not file or not file.filename:
        flash('Lütfen bir Excel dosyası seçiniz.', 'warning')
        return redirect(url_for('firmalar.index'))

    if not file.filename.lower().endswith('.xlsx'):
        flash('Sadece .xlsx uzantılı dosyalar destekleniyor.', 'danger')
        return redirect(url_for('firmalar.index'))

    try:
        wb = load_workbook(file, data_only=True)
        ws = wb.active
    except Exception as exc:
        flash(f'Excel dosyası okunamadı: {exc}', 'danger')
        return redirect(url_for('firmalar.index'))

    created = 0
    updated = 0
    skipped = 0
    errors = []

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        try:
            firma_adi = (row[0] or '').strip() if row[0] else ''
            yetkili_adi = (row[1] or '').strip() if row[1] else ''
            telefon = (row[2] or '').strip() if row[2] else None
            eposta = (row[3] or '').strip() if row[3] else None
            iletisim_bilgileri = (row[4] or '').strip() if row[4] else ''
            vergi_dairesi = (row[5] or '').strip() if row[5] else ''
            vergi_no = (row[6] or '').strip() if row[6] else ''
            is_musteri = _to_bool(row[7], default=True)
            is_tedarikci = _to_bool(row[8], default=False)
            is_active = _to_bool(row[9], default=True)

            if not vergi_no:
                skipped += 1
                continue

            firma_adi = firma_adi or f'Firma {vergi_no}'
            yetkili_adi = yetkili_adi or 'Belirtilmedi'
            iletisim_bilgileri = iletisim_bilgileri or (telefon or '-')
            vergi_dairesi = vergi_dairesi or 'Belirtilmedi'

            mevcut = Firma.query.filter_by(vergi_no=vergi_no).first()
            if mevcut:
                mevcut.firma_adi = firma_adi
                mevcut.yetkili_adi = yetkili_adi
                mevcut.telefon = telefon
                mevcut.eposta = eposta
                mevcut.iletisim_bilgileri = iletisim_bilgileri
                mevcut.vergi_dairesi = vergi_dairesi
                mevcut.is_musteri = is_musteri
                mevcut.is_tedarikci = is_tedarikci
                mevcut.is_active = is_active
                updated += 1
            else:
                yeni = Firma(
                    firma_adi=firma_adi,
                    yetkili_adi=yetkili_adi,
                    telefon=telefon,
                    eposta=eposta,
                    iletisim_bilgileri=iletisim_bilgileri,
                    vergi_dairesi=vergi_dairesi,
                    vergi_no=vergi_no,
                    is_musteri=is_musteri,
                    is_tedarikci=is_tedarikci,
                    is_active=is_active,
                    bakiye=Decimal('0'),
                )
                db.session.add(yeni)
                created += 1
        except Exception as exc:
            errors.append(f'Satır {row_idx}: {exc}')

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        flash(f'Excel içe aktarma başarısız: {exc}', 'danger')
        return redirect(url_for('firmalar.index'))

    flash(
        f'Excel içe aktarım tamamlandı. Yeni: {created}, Güncellenen: {updated}, Atlanan: {skipped}.',
        'success'
    )
    if errors:
        flash('Bazı satırlar işlenemedi: ' + ' | '.join(errors[:5]), 'warning')

    return redirect(url_for('firmalar.index'))

# -------------------------------------------------------------------------
# Sözleşme No Düzelt (Admin)
# -------------------------------------------------------------------------
from app.firmalar.forms import SozlesmeNoDuzeltForm

@firmalar_bp.route('/sozlesme_no_duzelt', methods=['POST'])
@login_required
@admin_required
def sozlesme_no_duzelt():
    form = SozlesmeNoDuzeltForm()
    if not form.validate_on_submit():
        flash('Form doğrulaması başarısız oldu. Lütfen tekrar deneyin.', 'danger')
        return redirect(url_for('firmalar.index'))
    firma_id = int(form.firma_id.data)
    yeni_sozlesme_no = form.sozlesme_no.data.strip()
    yeni_sozlesme_tarihi = form.sozlesme_tarihi.data
    firma = Firma.query.get(firma_id)
    if not firma:
        flash('Firma bulunamadı.', 'danger')
        return redirect(url_for('firmalar.index'))
    # Aynı sözleşme_no başka bir firmada var mı?
    if yeni_sozlesme_no:
        mevcut = Firma.query.filter(Firma.sozlesme_no == yeni_sozlesme_no, Firma.id != firma_id).first()
        if mevcut:
            flash('Bu sözleşme numarası başka bir firmada zaten kullanılıyor.', 'danger')
            return redirect(url_for('firmalar.index'))
    firma.sozlesme_no = yeni_sozlesme_no
    if yeni_sozlesme_tarihi:
        firma.sozlesme_tarihi = yeni_sozlesme_tarihi
    db.session.commit()
    flash('Sözleşme numarası ve tarihi başarıyla güncellendi.', 'success')
    return redirect(url_for('firmalar.index'))