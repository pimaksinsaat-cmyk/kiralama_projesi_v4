# app/auth/models.py
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db, login_manager
from datetime import datetime, timezone
from app.models.base_model import BaseModel

class User(UserMixin, BaseModel):
    __tablename__ = 'user'

    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    rol = db.Column(db.String(20), default='user', nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.rol == 'admin'

    def __repr__(self):
        return f'<User {self.username} ({self.rol})>'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))