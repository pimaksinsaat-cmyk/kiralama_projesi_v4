# coding: utf-8
"""
NİZAMETTİN AYDEMİR firmasını ve ilişkili tüm kayıtları kalıcı olarak siler.
KULLANIM: Scripti çalıştırmadan önce yedek alınız!
"""
from app import create_app
from app.extensions import db
from app.firmalar.models import Firma
from app.kiralama.models import Kiralama, KiralamaKalemi
from app.cari.models import Odeme, HizmetKaydi, CariHareket, CariMahsup
from app.fatura.models import Fatura
from app.nakliyeler.models import Nakliye
from app.filo.models import Filo
from app.stok.models import StokKarti, StokHareket
from app.ekipman.models import Ekipman

app = create_app()

with app.app_context():
    firma = Firma.query.filter(Firma.firma_adi == "NİZAMETTİN AYDEMİR").first()
    if not firma:
        print("Firma bulunamadı.")
        exit(1)
    print(f"Silinecek firma id: {firma.id}")

    # Kiralama ve kalemleri
    for kiralama in Kiralama.query.filter_by(firma_musteri_id=firma.id).all():
        KiralamaKalemi.query.filter_by(kiralama_id=kiralama.id).delete()
        db.session.delete(kiralama)

    # Ödemeler
    Odeme.query.filter_by(firma_musteri_id=firma.id).delete()

    # Hizmet Kayıtları
    HizmetKaydi.query.filter_by(firma_id=firma.id).delete()

    # Cari Hareketler
    CariHareket.query.filter_by(firma_id=firma.id).delete()

    # Cari Mahsuplar (borç/alacak hareketleri)
    for ch in CariHareket.query.filter_by(firma_id=firma.id).all():
        CariMahsup.query.filter((CariMahsup.borc_hareket_id==ch.id)|(CariMahsup.alacak_hareket_id==ch.id)).delete()

    # Faturalar
    Fatura.query.filter_by(firma_id=firma.id).delete()

    # Nakliyeler
    Nakliye.query.filter((Nakliye.firma_id==firma.id)|(Nakliye.taseron_firma_id==firma.id)).delete()

    # Filo
    Filo.query.filter_by(firma_id=firma.id).delete()

    # Stok Kartı ve Hareketleri
    for stok in StokKarti.query.filter_by(varsayilan_tedarikci_id=firma.id).all():
        StokHareket.query.filter_by(firma_id=firma.id).delete()
        db.session.delete(stok)

    # Ekipman
    Ekipman.query.filter_by(firma_tedarikci_id=firma.id).delete()

    # Son olarak firmayı sil
    db.session.delete(firma)
    db.session.commit()
    print("Tüm ilişkili kayıtlarla birlikte firma kalıcı olarak silindi.")
