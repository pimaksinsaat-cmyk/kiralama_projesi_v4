from flask import Blueprint

# kiralama Blueprint'ini tanımlıyoruz
kiralama_bp = Blueprint('kiralama', __name__, template_folder='templates')

# Alttaki satırlar, rotaların uygulamaya dahil edilmesini sağlar.

@kiralama_bp.app_context_processor
def _kiralama_template_helpers():
    from app.services.kiralama_services import KiralamaService

    return {
        'hesapla_kalem_etkin_gun': KiralamaService.hesapla_kalem_etkin_gun,
        'dondurulabilir_bitis_tarihi': KiralamaService._dondurulabilir_bitis_tarihi,
        'toplam_muaf_gun_sayisi': KiralamaService.toplam_muaf_gun_sayisi,
    }
