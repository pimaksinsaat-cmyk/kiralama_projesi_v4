from app.extensions import db
from datetime import datetime, timezone, date
from decimal import Decimal
from sqlalchemy.inspection import inspect

class BaseModel(db.Model):
    """
    Sistemin Veritabanı Anayasası: Tüm modellerin (Firma, Odeme, HizmetKaydi vb.) 
    miras alacağı soyut (abstract) temel sınıf.
    ID, Aktif/Pasif durumu, Audit Log (Denetim İzi) ve Soft Delete (Mantıksal Silme) 
    alanlarını tüm tablolar için standartlaştırır.
    """
    
    __abstract__ = True 

    # ==========================================
    # 1. TEMEL KİMLİK VE DURUM
    # ==========================================
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    
    # Kaydın operasyonel durumu (Örn: Hesap donduruldu mu?)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # ==========================================
    # 2. AUDIT LOG (DENETİM İZİ)
    # ==========================================
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=lambda: datetime.now(timezone.utc))
    
    # İşlemi gerçekleştiren kullanıcıların takibi (BaseService ile entegre edilebilir)
    created_by_id = db.Column(db.Integer, nullable=True) 
    updated_by_id = db.Column(db.Integer, nullable=True)

    # ==========================================
    # 3. SOFT DELETE (MANTIKSAL SİLME)
    # ==========================================
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by_id = db.Column(db.Integer, nullable=True)

    # ==========================================
    # 4. YARDIMCI METODLAR (Persistence & Serialization)
    # ==========================================

    def save(self, commit=True):
        """Kayıt oluşturma veya güncelleme işlemini kolaylaştırır."""
        db.session.add(self)
        if commit:
            db.session.commit()
        return self

    def delete(self, soft=True, user_id=None):
        """
        Kaydı siler. Varsayılan olarak Soft Delete (is_deleted=True) yapar.
        Eğer soft=False verilirse veriyi fiziksel olarak uçurur.
        """
        if soft:
            self.is_deleted = True
            self.is_active = False
            self.deleted_at = datetime.now(timezone.utc)
            self.deleted_by_id = user_id
            db.session.add(self)
        else:
            db.session.delete(self)
        
        db.session.commit()

    def restore(self):
        """Soft-delete yapılmış bir kaydı geri getirir."""
        self.is_deleted = False
        self.is_active = True
        self.deleted_at = None
        db.session.add(self)
        db.session.commit()

    def to_dict(self, exclude=None):
        """
        Model objesini API yanıtları (JSON) için sözlüğe çevirir.
        Decimal, Date ve DateTime tiplerini otomatik olarak formatlar.
        """
        if exclude is None:
            exclude = []
            
        result = {}
        for column in inspect(self).mapper.column_attrs:
            if column.key in exclude:
                continue
                
            value = getattr(self, column.key)
            
            # Tip dönüşümleri (JSON uyumluluğu için)
            if isinstance(value, datetime):
                result[column.key] = value.isoformat()
            elif isinstance(value, date):
                result[column.key] = value.strftime('%Y-%m-%d')
            elif isinstance(value, Decimal):
                result[column.key] = float(value) # Ya da str(value)
            else:
                result[column.key] = value
        return result

    @classmethod
    def get_active(cls):
        """Silinmemiş ve aktif olan kayıtları getirmek için kısayol."""
        return cls.query.filter_by(is_deleted=False, is_active=True)