from app.kiralama import kiralama_bp
from app.models import Kiralama, Ekipman, Musteri
from app.forms import KiralamaForm
from flask import render_template, redirect, url_for, flash, jsonify, request
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_
from app import db
from datetime import datetime, timezone
from decimal import Decimal
import traceback
# --- 5. Kiralama Bilgi Sayfası ---
@kiralama_bp.route('/bilgi/<int:id>', methods=['GET', 'POST'])
def bilgi(id):
    """
    ID'si verilen müşterinin detaylı bilgilerini gösterir.
    """
    kiralama = Kiralama.query.get_or_404(id)
   
    
    return render_template('kiralama/bilgi.html', kiralama=kiralama)
