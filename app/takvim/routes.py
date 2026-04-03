from flask import render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import date, datetime, timedelta
from app.extensions import db
from app.takvim import takvim_bp
from app.takvim.models import TakvimHatirlatma
from app.kiralama.models import KiralamaKalemi
from app.araclar.models import Arac


def _parse_iso_date(date_str, default):
    if not date_str:
        return default
    try:
        return datetime.fromisoformat(date_str).date()
    except (ValueError, TypeError):
        return default


@takvim_bp.route('', methods=['GET'])
@login_required
def takvim():
    return render_template('takvim/takvim.html')


@takvim_bp.route('/events', methods=['GET'])
@login_required
def takvim_events():
    today = date.today()
    range_start = _parse_iso_date(request.args.get('start'), today - timedelta(days=30))
    range_end = _parse_iso_date(request.args.get('end'), today + timedelta(days=120))

    if range_start > range_end:
        range_start, range_end = range_end, range_start

    events = []

    # 1) Yaklasan kiralama bitisleri
    kiralama_kalemleri = (
        KiralamaKalemi.query
        .filter(
            KiralamaKalemi.is_deleted == False,
            KiralamaKalemi.is_active == True,
            KiralamaKalemi.sonlandirildi == False,
            KiralamaKalemi.kiralama_bitis >= range_start,
            KiralamaKalemi.kiralama_bitis <= range_end,
        )
        .all()
    )

    for kalem in kiralama_kalemleri:
        ekipman_kodu = kalem.ekipman.kod if kalem.ekipman else 'Harici Ekipman'
        firma_adi = '-'
        if kalem.kiralama and kalem.kiralama.firma_musteri:
            firma_adi = kalem.kiralama.firma_musteri.firma_adi

        events.append({
            'title': f'Kiralama Bitis: {ekipman_kodu}',
            'start': kalem.kiralama_bitis.isoformat(),
            'allDay': True,
            'backgroundColor': '#f59e0b',
            'borderColor': '#d97706',
            'extendedProps': {
                'type': 'kiralama',
                'detay': f'Firma: {firma_adi}',
            },
        })

    # 2) Arac sigorta bitisleri
    sigorta_araclari = (
        Arac.query
        .filter(
            Arac.is_deleted == False,
            Arac.is_active == True,
            Arac.sigorta_tarihi.isnot(None),
            Arac.sigorta_tarihi >= range_start,
            Arac.sigorta_tarihi <= range_end,
        )
        .all()
    )

    for arac in sigorta_araclari:
        events.append({
            'title': f'Sigorta: {arac.plaka}',
            'start': arac.sigorta_tarihi.isoformat(),
            'allDay': True,
            'backgroundColor': '#ef4444',
            'borderColor': '#dc2626',
            'extendedProps': {
                'type': 'sigorta',
                'detay': arac.marka_model or '-',
            },
        })

    # 3) Arac muayene bitisleri
    muayene_araclari = (
        Arac.query
        .filter(
            Arac.is_deleted == False,
            Arac.is_active == True,
            Arac.muayene_tarihi.isnot(None),
            Arac.muayene_tarihi >= range_start,
            Arac.muayene_tarihi <= range_end,
        )
        .all()
    )

    for arac in muayene_araclari:
        events.append({
            'title': f'Muayene: {arac.plaka}',
            'start': arac.muayene_tarihi.isoformat(),
            'allDay': True,
            'backgroundColor': '#2563eb',
            'borderColor': '#1d4ed8',
            'extendedProps': {
                'type': 'muayene',
                'detay': arac.marka_model or '-',
            },
        })

    # 4) Kullanicinin kendi hatirlatmalari
    hatirlatmalar = (
        TakvimHatirlatma.query
        .filter(
            TakvimHatirlatma.is_deleted == False,
            TakvimHatirlatma.user_id == current_user.id,
            TakvimHatirlatma.tarih >= range_start,
            TakvimHatirlatma.tarih <= range_end,
        )
        .all()
    )

    for item in hatirlatmalar:
        events.append({
            'id': str(item.id),
            'title': f'Hatirlatma: {item.baslik}',
            'start': item.tarih.isoformat(),
            'allDay': True,
            'backgroundColor': '#10b981',
            'borderColor': '#059669',
            'extendedProps': {
                'type': 'hatirlatma',
                'detay': item.aciklama or '-',
                'hatirlatma_id': item.id,
                'aciklama': item.aciklama or '',
            },
        })

    return jsonify(events)


@takvim_bp.route('/hatirlatma', methods=['POST'])
@login_required
def takvim_hatirlatma_ekle():
    tarih_str = (request.form.get('tarih') or '').strip()
    baslik = (request.form.get('baslik') or '').strip()
    aciklama = (request.form.get('aciklama') or '').strip()

    if not tarih_str or not baslik:
        flash('Tarih ve baslik alanlari zorunludur.', 'warning')
        return redirect(url_for('takvim.takvim'))

    try:
        tarih = datetime.strptime(tarih_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Tarih formati gecersiz. YYYY-AA-GG kullaniniz.', 'danger')
        return redirect(url_for('takvim.takvim'))

    kayit = TakvimHatirlatma(
        user_id=current_user.id,
        tarih=tarih,
        baslik=baslik,
        aciklama=aciklama or None,
        created_by_id=current_user.id,
    )
    db.session.add(kayit)
    db.session.commit()

    flash('Hatirlatma eklendi.', 'success')
    return redirect(url_for('takvim.takvim'))


@takvim_bp.route('/hatirlatma/sil/<int:hatirlatma_id>', methods=['POST'])
@login_required
def takvim_hatirlatma_sil(hatirlatma_id):
    kayit = TakvimHatirlatma.query.filter_by(
        id=hatirlatma_id,
        user_id=current_user.id,
        is_deleted=False,
    ).first()

    if not kayit:
        flash('Hatirlatma bulunamadi veya silme yetkiniz yok.', 'warning')
        return redirect(url_for('takvim.takvim'))

    kayit.is_deleted = True
    kayit.is_active = False
    kayit.deleted_by_id = current_user.id
    db.session.commit()

    flash('Hatirlatma silindi.', 'success')
    return redirect(url_for('takvim.takvim'))
