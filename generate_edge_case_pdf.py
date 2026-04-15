#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Edge Case Test Results PDF Report Generator"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black, red, orange, green
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from datetime import datetime
import os

def create_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='EdgeTitle',
        fontSize=18,
        textColor=HexColor('#1a1a1a'),
        spaceAfter=8,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    ))
    styles.add(ParagraphStyle(
        name='EdgeHeading2',
        fontSize=11,
        textColor=HexColor('#c0392b'),
        spaceAfter=6,
        spaceBefore=8,
        fontName='Helvetica-Bold'
    ))
    styles.add(ParagraphStyle(
        name='EdgeBody',
        fontSize=9,
        alignment=TA_JUSTIFY,
        spaceAfter=4
    ))
    return styles

def generate_edge_case_pdf():
    filename = "EDGE_CASE_TEST_RAPORU.pdf"
    filepath = os.path.join(os.getcwd(), filename)

    doc = SimpleDocTemplate(filepath, pagesize=A4, topMargin=0.4*inch, bottomMargin=0.4*inch)
    story = []
    styles = create_styles()

    # TITLE
    story.append(Paragraph("EDGE CASE TEST RAPORU", styles['EdgeTitle']))
    story.append(Paragraph("Sinir Durumları ve Hata Senaryoları Analizi", styles['EdgeHeading2']))
    story.append(Spacer(1, 0.15*inch))

    # SUMMARY
    summary_data = [
        ["METRIK", "SONUC"],
        ["Toplam Test", "31"],
        ["Passed", "2 (6%)"],
        ["Failed", "29 (94%)"],
        ["Execution Time", "2.44s"],
        ["SONUC", "VALIDATION HATALARI DETAYLANDI"]
    ]

    summary_table = Table(summary_data, colWidths=[2.5*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#c0392b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#fadbd8')),
        ('BACKGROUND', (0, -1), (-1, -1), HexColor('#ec7063')),
        ('TEXTCOLOR', (0, -1), (-1, -1), white),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, black),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.2*inch))

    # TEST CATEGORIES
    story.append(Paragraph("TEST KATEGORİLERİ VE SONUÇLAR", styles['EdgeHeading2']))

    categories_data = [
        ["#", "KATEGORI", "TESTLER", "PASSED", "FAILED", "DURUM"],
        ["1", "Input Validation", "5", "1", "4", "KISMI"],
        ["2", "Boundary Conditions", "5", "0", "5", "FAIL"],
        ["3", "Duplicate Data", "4", "1", "3", "KISMI"],
        ["4", "Invalid Relationships", "4", "0", "4", "FAIL"],
        ["5", "String Constraints", "3", "0", "3", "FAIL"],
        ["6", "Data Consistency", "2", "0", "2", "FAIL"],
        ["7", "Concurrent Access", "2", "0", "2", "FAIL"],
        ["8", "Type Validation", "2", "0", "2", "FAIL"],
        ["9", "Special Cases", "4", "0", "4", "FAIL"],
    ]

    categories_table = Table(categories_data, colWidths=[0.3*inch, 1.4*inch, 0.7*inch, 0.6*inch, 0.6*inch, 0.8*inch])
    categories_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#34495e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ('TOPPADDING', (0, 1), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 2),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#ecf0f1')),
        ('GRID', (0, 0), (-1, -1), 0.5, black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ecf0f1'), HexColor('#ffffff')])
    ]))
    story.append(categories_table)
    story.append(Spacer(1, 0.2*inch))

    # CRITICAL FINDINGS
    story.append(Paragraph("KRITIK BULGULAR (MUST FIX)", styles['EdgeHeading2']))

    critical_text = """
    <b>1. Foreign Key Constraint Eksiklikleri:</b><br/>
    - Var olmayan firma_id ile record olusturulabiliyor<br/>
    - Var olmayan ekipman_id ile record olusturulabiliyor<br/>
    - Referential integrity ihlali, orphaned records<br/>
    <br/>
    <b>2. Unique Constraint Eksiklikleri:</b><br/>
    - Aynı vergi_no ile iki Firma olusturulabiliyor<br/>
    - Aynı kod ile iki Ekipman olusturulabiliyor<br/>
    - Aynı TC_no ile iki Personel olusturulabiliyor<br/>
    - Data duplication, business logic hatası<br/>
    <br/>
    <b>3. Sınır Değer Validasyonu Yok:</b><br/>
    - Negatif ücret kabul ediliyor<br/>
    - Negatif stok miktarı kabul ediliyor<br/>
    - Sıfır tutar kabul ediliyor<br/>
    - Muhasebe hataları, anomaliler<br/>
    <br/>
    <b>4. Date Range Validasyonu Yok:</b><br/>
    - bitis_tarihi < baslangic_tarihi kabul ediliyor<br/>
    - İş mantığı hatası, yanlış hesaplamalar<br/>
    """
    story.append(Paragraph(critical_text, styles['EdgeBody']))
    story.append(PageBreak())

    # RECOMMENDATIONS
    story.append(Paragraph("ONERILER - ONCELIK SIRASINA GORE", styles['EdgeHeading2']))

    recommendations = """
    <b>ACIL (MUST DO) - Üretim Öncesi:</b><br/>
    [ ] Foreign Key Constraints ekle - 1-2 saat<br/>
    [ ] Unique Constraints ekle - 30 dakika<br/>
    [ ] Sınır Değer Validasyonu - 1 saat<br/>
    Total: 2.5-3.5 saat<br/>
    <br/>
    <b>ONEMLI (SHOULD DO) - Sonraki Sprint:</b><br/>
    [ ] String Length Validation - 1 saat<br/>
    [ ] Type Validation - 1-2 saat<br/>
    [ ] Cascade Delete Policies - 1 saat<br/>
    Total: 3-4 saat<br/>
    <br/>
    <b>UZUN VADELI (NICE TO HAVE):</b><br/>
    [ ] Concurrent Access Handling - 2-3 saat<br/>
    [ ] Turkish Character Support - 30 dakika<br/>
    Total: 2.5-3.5 saat<br/>
    <br/>
    <b>TOPLAM TAHMINI SURE: 4-6 saat</b><br/>
    """
    story.append(Paragraph(recommendations, styles['EdgeBody']))
    story.append(Spacer(1, 0.15*inch))

    # RISK MATRIX
    story.append(Paragraph("RISK MATRISI", styles['EdgeHeading2']))

    risk_data = [
        ["RISK", "KRITIKLIK", "ETKI", "ZORLUK", "ONCELI"],
        ["FK Constraints Yok", "KRITIK", "Referential", "Orta", "P0"],
        ["Unique Constraints", "KRITIK", "Duplication", "Dusuk", "P0"],
        ["Negatif Values", "YUKSEK", "Bus.Logic", "Dusuk", "P1"],
        ["Date Range", "YUKSEK", "Hesaplama", "Dusuk", "P1"],
        ["String Length", "ORTA", "DB/UI", "Dusuk", "P1"],
        ["Concurrent Access", "ORTA", "Race Cond.", "Yuksek", "P2"],
    ]

    risk_table = Table(risk_data, colWidths=[1.2*inch, 1*inch, 1*inch, 0.8*inch, 0.7*inch])
    risk_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#8b0000')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ('TOPPADDING', (0, 1), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 2),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#fadbd8')),
        ('BACKGROUND', (1, 1), (1, -1), HexColor('#fadbd8')),
        ('GRID', (0, 0), (-1, -1), 0.5, black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#fadbd8'), HexColor('#f5b7b1')])
    ]))
    story.append(risk_table)
    story.append(Spacer(1, 0.2*inch))

    # BASARILI TESTLER
    story.append(Paragraph("BASARILI TESTLER (2/31)", styles['EdgeHeading2']))

    success_text = """
    <b>Test 1: Boş Ekipman Kodu - PASSED</b><br/>
    Status: PASSED<br/>
    Reason: IntegrityError constraint çalışıyor<br/>
    <br/>
    <b>Test 2: Çift Username - PASSED</b><br/>
    Status: PASSED<br/>
    Reason: Unique constraint çalışıyor<br/>
    <br/>
    <i>Sonuç: Veritabanı kısıtlamaları kısmen uygulanmış</i>
    """
    story.append(Paragraph(success_text, styles['EdgeBody']))
    story.append(Spacer(1, 0.2*inch))

    # SONUC
    story.append(Paragraph("GENEL SONUC", styles['EdgeHeading2']))

    conclusion = """
    <b>Durum:</b> ⚠️ Validation altyapısı EKSIK<br/>
    <b>Temel İş Akışı:</b> ✓ Çalışıyor<br/>
    <b>Data Integrity:</b> ✗ Constraints eksik<br/>
    <b>Input Validation:</b> ✗ Eksik<br/>
    <b>Business Logic:</b> ✗ Validation eksik<br/>
    <br/>
    <b>Önerilen Aksiyon:</b><br/>
    1. Edge case test bulguları review et<br/>
    2. Database constraints ekle (FK + Unique)<br/>
    3. Model-level validators implement et<br/>
    4. Re-run edge case tests (Target: 80%+ pass)<br/>
    5. Production deployment<br/>
    """
    story.append(Paragraph(conclusion, styles['EdgeBody']))

    # Footer
    footer = f"Kiralama Projesi v4 | Edge Case Test Raporu | {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph(f"<i>{footer}</i>", styles['EdgeBody']))

    doc.build(story)
    return filepath

if __name__ == '__main__':
    pdf_file = generate_edge_case_pdf()
    print(f"Edge Case PDF Report generated: {pdf_file}")
    if os.path.exists(pdf_file):
        size_kb = os.path.getsize(pdf_file) / 1024
        print(f"File size: {size_kb:.2f} KB")
