from app.extensions import db
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timezone
import logging

class ValidationError(Exception):
    """İş mantığı (Business logic) ve doğrulama hataları için özel istisna sınıfı."""
    pass

# Uygulamanın genel loglayıcısı
logger = logging.getLogger(__name__)

class BaseService:
    """
    Sistemin Anayasası: Tüm modüllerin ortak kullanacağı temel servis sınıfı. 
    Veritabanı operasyonlarını, iş mantığı kancalarını, Soft Delete ve Audit Log'u standartlaştırır.
    """
    model = None
    
    # BEYAZ LİSTE (Whitelist) - Güvenlik için alt sınıflarda ezilmesi (override) önerilir.
    updatable_fields = None 
    
    # SOFT DELETE - Eğer alt serviste True yapılırsa, kayıtlar veritabanından silinmez, gizlenir.
    use_soft_delete = False

    @classmethod
    def _validate_model(cls):
        """Geliştirici güvenliği: Modelin tanımlanıp tanımlanmadığını kontrol eder."""
        if cls.model is None:
            raise NotImplementedError(
                f"MİMARİ HATA: '{cls.__name__}' sınıfı için 'model' tanımlanmamış! "
                f"Lütfen '{cls.__name__}' sınıfının en üstüne 'model = SizinModeliniz' satırını ekleyin."
            )

    @classmethod
    def _get_base_query(cls, include_deleted=False):
        """
        GİZLİ KAHRAMAN: Okuma işlemlerinin temelini oluşturur.
        Eğer Soft Delete aktifse ve özellikle istenmemişse, silinmiş (is_deleted=True) kayıtları otomatik gizler.
        """
        cls._validate_model()
        query = cls.model.query
        
        # Eğer modelde is_deleted alanı varsa ve soft delete açıksa filtrele
        if cls.use_soft_delete and hasattr(cls.model, 'is_deleted') and not include_deleted:
            query = query.filter_by(is_deleted=False)
            
        return query

    @classmethod
    def _apply_audit_log(cls, instance, is_new, actor_id=None):
        """
        AUDIT LOG (Denetim İzi): İşlemi yapan kullanıcıyı ve zamanı otomatik işler.
        Modellerinizde created_at, updated_at, created_by_id, updated_by_id alanları varsa tetiklenir.
        """
        now = datetime.now(timezone.utc)
        if is_new:
            if hasattr(instance, 'created_at') and instance.created_at is None:
                instance.created_at = now
            if actor_id and hasattr(instance, 'created_by_id') and instance.created_by_id is None:
                instance.created_by_id = actor_id
        else:
            if hasattr(instance, 'updated_at'):
                instance.updated_at = now
            if actor_id and hasattr(instance, 'updated_by_id'):
                instance.updated_by_id = actor_id

    # --- OKUMA (READ) OPERASYONLARI ---

    @classmethod
    def get_all(cls, include_deleted=False):
        return cls._get_base_query(include_deleted).all()

    @classmethod
    def get_by_id(cls, id, include_deleted=False):
        """ID'ye göre tek bir kayıt getirir. Soft delete olanları varsayılan olarak getirmez."""
        return cls._get_base_query(include_deleted).filter_by(id=id).first()

    @classmethod
    def find_by(cls, include_deleted=False, **kwargs):
        """Belirli kriterlere göre çoklu kayıt getirir."""
        return cls._get_base_query(include_deleted).filter_by(**kwargs).all()

    @classmethod
    def find_one_by(cls, include_deleted=False, **kwargs):
        """Belirli kriterlere uyan İLK kaydı getirir."""
        return cls._get_base_query(include_deleted).filter_by(**kwargs).first()

    # --- KANCALAR (HOOKS) ---
    
    @classmethod
    def validate(cls, instance, is_new=True):
        pass

    @classmethod
    def before_save(cls, instance, is_new=True): 
        pass

    @classmethod
    def after_save(cls, instance, is_new=True): 
        pass

    @classmethod
    def before_delete(cls, instance): 
        pass

    @classmethod
    def after_delete(cls, instance):
        pass

    # --- YAZMA (WRITE) OPERASYONLARI ---

    @classmethod
    def save(cls, instance, is_new=True, auto_commit=True, actor_id=None):
        """
        Kayıt işlemi. actor_id verilirse Audit Log'a işlenir.
        """
        cls._validate_model()
        try:
            cls.validate(instance, is_new)
            
            # Otomatik Audit Log atamaları
            cls._apply_audit_log(instance, is_new, actor_id)
            
            cls.before_save(instance, is_new)
            
            db.session.add(instance)
            db.session.flush()
            
            cls.after_save(instance, is_new) 
            
            if auto_commit:
                db.session.commit()
                
            return instance
            
        except ValidationError as e:
            if auto_commit:
                db.session.rollback()
            raise e
        except Exception as e:
            if auto_commit:
                db.session.rollback()
            logger.error(f"Kayıt Hatası ({cls.__name__}): {str(e)}", exc_info=True)
            raise Exception(f"{cls.model.__name__} işlemi sırasında hata oluştu.") from e

    @classmethod
    def update(cls, id, data, auto_commit=True, allowed_fields=None, actor_id=None):
        """
        Kayıt günceller. actor_id verilirse güncelleyen kişi (updated_by_id) olarak Audit Log'a işlenir.
        """
        instance = cls.get_by_id(id)
        if not instance:
            raise ValidationError("Güncellenmek istenen kayıt bulunamadı.")
            
        whitelist = allowed_fields if allowed_fields is not None else cls.updatable_fields
            
        for key, value in data.items():
            if key == 'id':
                continue
            if whitelist is not None and key not in whitelist:
                continue
            if hasattr(instance, key):
                setattr(instance, key, value)
        
        return cls.save(instance, is_new=False, auto_commit=auto_commit, actor_id=actor_id)

    @classmethod
    def bulk_save(cls, instances, auto_commit=True, actor_id=None):
        cls._validate_model()
        try:
            for instance in instances:
                cls.validate(instance, is_new=True)
                cls._apply_audit_log(instance, is_new=True, actor_id=actor_id)
                cls.before_save(instance, is_new=True)
                db.session.add(instance)
            
            db.session.flush()
            
            for instance in instances:
                cls.after_save(instance, is_new=True)
                
            if auto_commit:
                db.session.commit()
                
            return instances
            
        except ValidationError as e:
            if auto_commit:
                db.session.rollback()
            raise e
        except Exception as e:
            if auto_commit:
                db.session.rollback()
            logger.error(f"Toplu Kayıt Hatası ({cls.__name__}): {str(e)}", exc_info=True)
            raise Exception("Toplu kayıt işlemi sırasında hata oluştu.") from e

    @classmethod
    def delete(cls, id, auto_commit=True, actor_id=None):
        """
        Silme işlemi. Eğer cls.use_soft_delete = True ise ve model destekliyorsa 
        veriyi fiziksel olarak silmez, 'is_deleted' bayrağını işaretler (Soft Delete).
        """
        instance = cls.get_by_id(id)
        if not instance:
            raise ValidationError("Silinmek istenen kayıt bulunamadı.")
            
        try:
            cls.before_delete(instance)
            
            # --- SOFT DELETE MANTIĞI ---
            if cls.use_soft_delete and hasattr(instance, 'is_deleted'):
                instance.is_deleted = True
                
                # Audit Log: Ne zaman ve kim tarafından silindi
                if hasattr(instance, 'deleted_at'):
                    instance.deleted_at = datetime.now(timezone.utc)
                if actor_id and hasattr(instance, 'deleted_by_id'):
                    instance.deleted_by_id = actor_id
                
                db.session.add(instance) # Silmiyoruz, güncelliyoruz
            else:
                # --- HARD DELETE MANTIĞI ---
                db.session.delete(instance)
                
            db.session.flush()
            
            cls.after_delete(instance)
            
            if auto_commit:
                db.session.commit()
                
            return True
            
        except ValidationError as e:
            if auto_commit:
                db.session.rollback()
            raise e
        except Exception as e:
            if auto_commit:
                db.session.rollback()
            logger.error(f"Silme Hatası ({cls.__name__} - ID:{id}): {str(e)}", exc_info=True)
            raise Exception("Bu kayıt silinemez. Başka verilerle bağlantılı olabilir.") from e