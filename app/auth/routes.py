# app/auth/routes.py
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, timezone, timedelta
from app import db
from app.auth import auth_bp
from app.auth.models import User
from app.auth.forms import LoginForm
from app.models.operation_log import OperationLog
from app.utils import admin_required


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash('Hesabınız deaktif edilmiş.', 'danger')
                return render_template('auth/login.html', form=form)
            
            login_user(user, remember=form.beni_hatirla.data)
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            
            next_page = request.args.get('next')
            flash(f'Hoş geldiniz, {user.username}!', 'success')
            return redirect(next_page or url_for('main.index'))
        
        flash('Kullanıcı adı veya şifre hatalı.', 'danger')
    
    return render_template('auth/login.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Başarıyla çıkış yapıldı.', 'info')
    return redirect(url_for('auth.login'))
@auth_bp.route('/admin/kullanicilar')
@login_required
@admin_required
def kullanici_listesi():
    kullanicilar = User.query.order_by(User.username).all()
    return render_template('auth/admin.html', kullanicilar=kullanicilar)


@auth_bp.route('/admin/kullanici/log/<int:user_id>')
@login_required
@admin_required
def kullanici_loglari(user_id):
    user = db.get_or_404(User, user_id)

    today = datetime.today().date()
    week_ago = today - timedelta(days=7)

    start_date = (request.args.get('start_date') or week_ago.strftime('%Y-%m-%d')).strip()
    end_date = (request.args.get('end_date') or today.strftime('%Y-%m-%d')).strip()
    sort = (request.args.get('sort') or 'desc').strip().lower()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    if per_page not in (10, 20, 50, 100):
        per_page = 50

    query = OperationLog.query.filter(OperationLog.user_id == user_id)

    # Tarih aralığı filtreleri
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(OperationLog.created_at >= start_dt)
        except ValueError:
            flash('Başlangıç tarihi formatı hatalı.', 'warning')

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(OperationLog.created_at < end_dt)
        except ValueError:
            flash('Bitiş tarihi formatı hatalı.', 'warning')

    if sort == 'asc':
        query = query.order_by(OperationLog.created_at.asc())
    else:
        sort = 'desc'
        query = query.order_by(OperationLog.created_at.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        'auth/user_logs.html',
        user=user,
        logs=pagination.items,
        pagination=pagination,
        start_date=start_date,
        end_date=end_date,
        sort=sort,
        per_page=per_page,
    )

@auth_bp.route('/admin/kullanici/ekle', methods=['POST'])
@login_required
@admin_required
def kullanici_ekle():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    rol = request.form.get('rol', 'user')
    
    if not username or not password:
        flash('Kullanıcı adı ve şifre zorunludur.', 'warning')
        return redirect(url_for('auth.kullanici_listesi'))
    
    if User.query.filter_by(username=username).first():
        flash('Bu kullanıcı adı zaten mevcut.', 'danger')
        return redirect(url_for('auth.kullanici_listesi'))
    
    yeni = User(username=username, rol=rol)
    yeni.set_password(password)
    db.session.add(yeni)
    db.session.commit()
    flash(f'{username} kullanıcısı oluşturuldu.', 'success')
    return redirect(url_for('auth.kullanici_listesi'))

@auth_bp.route('/admin/kullanici/sil/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def kullanici_sil(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash('Kendinizi silemezsiniz!', 'danger')
        return redirect(url_for('auth.kullanici_listesi'))
    db.session.delete(user)
    db.session.commit()
    flash(f'{user.username} silindi.', 'success')
    return redirect(url_for('auth.kullanici_listesi'))

@auth_bp.route('/admin/kullanici/sifre/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def sifre_degistir(user_id):
    user = db.get_or_404(User, user_id)
    yeni_sifre = request.form.get('yeni_sifre', '').strip()
    if not yeni_sifre or len(yeni_sifre) < 4:
        flash('Şifre en az 4 karakter olmalıdır.', 'warning')
        return redirect(url_for('auth.kullanici_listesi'))
    user.set_password(yeni_sifre)
    db.session.commit()
    flash(f'{user.username} şifresi güncellendi.', 'success')
    return redirect(url_for('auth.kullanici_listesi'))

@auth_bp.route('/admin/kullanici/rol/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def rol_degistir(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash('Kendi rolünüzü değiştiremezsiniz!', 'danger')
        return redirect(url_for('auth.kullanici_listesi'))
    user.rol = 'admin' if user.rol == 'user' else 'user'
    db.session.commit()
    flash(f'{user.username} rolü {user.rol} olarak güncellendi.', 'success')
    return redirect(url_for('auth.kullanici_listesi'))