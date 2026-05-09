from app import app
from backend.extensions import db
from backend.models import User

with app.app_context():
    u1 = User(email="admin@traffic.com", password="admin123", role="admin", name="Admin User")
    u2 = User(email="authority@traffic.com", password="auth123", role="authority", name="Authority User")
    u3 = User(email="guest@traffic.com", password="guest123", role="guest", name="Guest User")

    db.session.add_all([u1, u2, u3])
    db.session.commit()

    print("Users added!")
