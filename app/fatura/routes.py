from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
import logging

from app.extensions import db
from app.fatura import fatura_bp
from app.fatura.forms import HakedisOlusturForm
from app.fatura.models import Hakedis
from app.kiralama.models import Kiralama
from app.services.fatura_services import FaturaService
from app.services.base import ValidationError
from app.services.operation_log_service import OperationLogService

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# 1. LİSTE
# -------------------------------------------------------------------------
@fatura_bp.route('/')
@login_required
def index():
    """Tüm hakediş kayıtlarını listeler (iptal edilenler dahil, silinenler hariç)."""
    hakedisler = Hakedis.query.filter_by(is_deleted=False)\
                              .order_by(Hakedis.id.desc()).all()
    return render_template('fatura/index.html', hakedisler=hakedisler)


# -------------------------------------------------------------------------
# 2. OLUŞTUR
# -------------------------------------------------------------------------
@fatura_bp.route('/olustur', methods=['GET', 'POST'])
@login_required
def olustur():
    """Yeni bir hakediş taslağı oluşturma ekranı."""
    form = HakedisOlusturForm()

    # Sadece aktif ve silinmemiş sözleşmeleri listele
    kiralamalar = Kiralama.query.filter_by(is_deleted=False, is_active=True).all()
    form.kiralama_id.choices = [
        (k.id, f"{k.kiralama_form_no or 'No Yok'} - {k.firma_musteri.firma_adi}")
        for k in kiralamalar
    ]

    if form.validate_on_submit():
        try:
            # Tüm form verilerini servise geçir — servis commit'e kadar her şeyi yapar
            hakedis = FaturaService.hakedis_olustur(
                kiralama_id=form.kiralama_id.data,
                baslangic=form.baslangic_tarihi.data,
                bitis=form.bitis_tarihi.data,
                fatura_senaryosu=form.fatura_senaryosu.data,
                fatura_tipi=form.fatura_tipi.data,
                para_birimi=form.para_birimi.data,
                kur_degeri=form.kur_degeri.data,
                proje_adi=form.proje_adi.data,
                santiye_adresi=form.santiye_adresi.data,
                actor_id=current_user.id
            )
            flash(
                f"{hakedis.hakedis_no} numaralı hakediş taslağı başarıyla oluşturuldu.",
                "success"
            )
            OperationLogService.log(
                module='fatura', action='olustur',
                user_id=current_user.id, username=getattr(current_user, 'username', None),
                entity_type='Hakedis', entity_id=hakedis.id,
                description=f"{hakedis.hakedis_no} hakedış taslakğı oluşturuldu.",
                success=True
            )
            return redirect(url_for('fatura.detay', id=hakedis.id))

        except ValidationError as e:
            OperationLogService.log(
                module='fatura', action='olustur',
                user_id=current_user.id, username=getattr(current_user, 'username', None),
                entity_type='Hakedis',
                description=f"Hakedış oluşturma hatası: {str(e)}",
                success=False
            )
            flash(str(e), "warning")
        except Exception as e:
            OperationLogService.log(
                module='fatura', action='olustur',
                user_id=current_user.id, username=getattr(current_user, 'username', None),
                entity_type='Hakedis',
                description=f"Hakedış oluşturma hatası: {str(e)}",
                success=False
            )
            logger.error("Hakediş oluşturma hatası", exc_info=True)
            flash(f"Hata detayı: {str(e)}", "danger")

    return render_template('fatura/olustur.html', form=form)


# -------------------------------------------------------------------------
# 3. DETAY
# -------------------------------------------------------------------------
@fatura_bp.route('/detay/<int:id>')
@login_required
def detay(id):
    """Hakedişin kalemlerini ve hesaplama detaylarını gösterir."""
    hakedis = db.get_or_404(Hakedis, id)
    return render_template('fatura/detay.html', hakedis=hakedis)


# -------------------------------------------------------------------------
# 4. CARİYE İŞLE
# -------------------------------------------------------------------------
@fatura_bp.route('/cariye-isle/<int:id>', methods=['POST'])
@login_required
def cariye_isle(id):
    """Onaylanan hakedişi cari modüle (HizmetKaydi) borç olarak işler."""
    try:
        hakedis = FaturaService.cariye_isle(hakedis_id=id, actor_id=current_user.id)
        OperationLogService.log(
            module='fatura', action='cariye_isle',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description=f"Hakedış #{id} cari hesaba işlendi: {hakedis.genel_toplam} TL.",
            success=True
        )
        flash(
            f"Hakedış onaylandı ve cari hesaba "
            f"{hakedis.genel_toplam} TL borç kaydedildi.",
            "success"
        )
    except ValidationError as e:
        OperationLogService.log(
            module='fatura', action='cariye_isle',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description=f"Cari işleme hatası: {str(e)}",
            success=False
        )
        flash(str(e), "warning")
    except Exception:
        OperationLogService.log(
            module='fatura', action='cariye_isle',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description="Cari işleme sırasında system hatası.",
            success=False
        )
        logger.error(f"Cariye isleme hatasi — hakedis_id: {id}", exc_info=True)
        flash("Cari aktarım sırasında bir hata oluştu.", "danger")

    return redirect(url_for('fatura.detay', id=id))


# -------------------------------------------------------------------------
# 4b. GİB FATURALANDI (durum: onaylandi → faturalasti, yeni cari kaydı YOK)
# -------------------------------------------------------------------------
@fatura_bp.route('/faturalandi/<int:id>', methods=['POST'])
@login_required
def faturalandi(id):
    try:
        hakedis = FaturaService.hakedis_durumu_guncelle(
            id, 'faturalasti', actor_id=current_user.id
        )
        OperationLogService.log(
            module='fatura', action='faturalandi',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description=f"Hakedış #{id} GİB faturalandı olarak işaretlendi: {hakedis.hakedis_no}.",
            success=True
        )
        flash(
            "Hakediş resmi fatura (GİB) ile faturalandı olarak işaretlendi. "
            "Cariye ek borç yazılmadı.",
            "success",
        )
    except ValidationError as e:
        OperationLogService.log(
            module='fatura', action='faturalandi',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description=f"GİB faturalama hatası: {str(e)}",
            success=False
        )
        flash(str(e), "warning")
    except Exception:
        OperationLogService.log(
            module='fatura', action='faturalandi',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description="GİB faturalama sırasında sistem hatası.",
            success=False
        )
        logger.error("Hakediş faturalandi hatası — hakedis_id: %s", id, exc_info=True)
        flash("İşlem sırasında bir hata oluştu.", "danger")

    return redirect(url_for('fatura.detay', id=id))


# -------------------------------------------------------------------------
# 5. İPTAL
# -------------------------------------------------------------------------
@fatura_bp.route('/iptal/<int:id>', methods=['POST'])
@login_required
def iptal(id):
    """Taslak durumundaki hakedişi iptal eder."""
    try:
        FaturaService.hakedis_iptal(hakedis_id=id, actor_id=current_user.id)
        OperationLogService.log(
            module='fatura', action='iptal',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description=f"Hakedış #{id} iptal edildi.",
            success=True
        )
        flash("Hakedış iptal edildi.", "warning")
    except ValidationError as e:
        OperationLogService.log(
            module='fatura', action='iptal',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description=f"Hakedış iptal hatası: {str(e)}",
            success=False
        )
        flash(str(e), "warning")
    except Exception:
        OperationLogService.log(
            module='fatura', action='iptal',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description="Hakedış iptal sistem hatası.",
            success=False
        )
        logger.error(f"Hakediş iptal hatası — hakedis_id: {id}", exc_info=True)
        flash("İptal işlemi sırasında bir hata oluştu.", "danger")

    return redirect(url_for('fatura.detay', id=id))


# -------------------------------------------------------------------------
# 6. SİL
# -------------------------------------------------------------------------
@fatura_bp.route('/sil/<int:id>', methods=['POST'])
@login_required
def sil(id):
    """
    Taslak veya iptal durumundaki hakedişi soft-delete ile arşive kaldırır.
    Onaylanmış veya faturalanmış hakedişler silinemez.
    """
    hakedis = db.get_or_404(Hakedis, id)

    if hakedis.durum not in ('taslak', 'iptal'):
        flash(
            "Onaylanmış veya faturalanmış hakedişler silinemez. "
            "Önce iptal edilmelidir.",
            "danger"
        )
        return redirect(url_for('fatura.detay', id=id))

    try:
        FaturaService.delete(id, actor_id=current_user.id)
        OperationLogService.log(
            module='fatura', action='delete',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description=f"Hakedış #{id} arşive kaldırıldı.",
            success=True
        )
        flash("Hakedış kaydı arşive kaldırıldı.", "info")
    except ValidationError as e:
        OperationLogService.log(
            module='fatura', action='delete',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description=f"Hakedış silme hatası: {str(e)}",
            success=False
        )
        flash(str(e), "warning")
    except Exception:
        OperationLogService.log(
            module='fatura', action='delete',
            user_id=current_user.id, username=getattr(current_user, 'username', None),
            entity_type='Hakedis', entity_id=id,
            description="Hakedış silme sistem hatası.",
            success=False
        )
        logger.error(f"Hakedış silme hatası — hakedis_id: {id}", exc_info=True)
        flash("Silme işlemi sırasında bir hata oluştu.", "danger")

    return redirect(url_for('fatura.index'))
# -------------------------------------------------------------------------
# 7. XML İNDİR (BuildError hatasını çözen eksik rota)
# -------------------------------------------------------------------------
@fatura_bp.route('/xml-indir/<int:id>')
@login_required
def xml_indir(id):
    """e-Fatura XML oluşturma ve indirme işlemi (Yer Tutucu)."""
    hakedis = db.get_or_404(Hakedis, id)
    
    # İleride buraya UBL-TR XML oluşturma kodları eklenecek
    flash("XML oluşturma ve e-Fatura indirme altyapısı yakında aktif edilecektir.", "info")
    
    return redirect(url_for('fatura.detay', id=hakedis.id))