from backend.extensions import db
from datetime import datetime

# USERS TABLE
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # admin, police, viewer
    name = db.Column(db.String(200), nullable=False)  # admin, police, viewer

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "password": self.password,
            "role": self.role,
            "name": self.name
        }


# Alert TABLE
class Alert(db.Model):
    __tablename__ = "alert"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    location = db.Column(db.String(200))
    device_id = db.Column(db.String(50))
    type = db.Column(db.String(50), default="accident")
    confidence = db.Column(db.Float)
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    status = db.Column(db.String(50), default="Pending")

    def to_dict(self):
        return {
            "id": self.id,
            "title": "Traffic Accident Alert",
            "type": self.type or "accident",
            "confidence": self.confidence,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "time": self.timestamp.strftime("%I:%M %p"),
            "location": self.location,
            "device_id": self.device_id,
            "lat": self.lat,
            "lon": self.lon,
            "status": self.status,
            "severity": "high" if self.status == "Pending" else "medium",
            "severity_label": "High" if self.status == "Pending" else "Medium",
            "description": f"{self.type or 'accident'} detected by device {self.device_id}"
        }

# Device Table
class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)  # auto increment
    device_id = db.Column(db.String(50), unique=True)
    location = db.Column(db.String(200))

    def to_dict(self, last_update=None):
        return {
            "id": self.device_id,
            "device_id": self.device_id,
            "location": self.location,
            "status": "Online" if last_update else "No Updates",
            "last_update": last_update.strftime("%Y-%m-%d %H:%M:%S") if last_update else None,
            "lat": 24.7136,
            "lon": 46.6753
        }

# Feedback Table
# -------------------------------
# FEEDBACK TABLE (CRITICAL)
# -------------------------------
class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.Integer)
    device_id = db.Column(db.String(50))
    is_correct = db.Column(db.Boolean)  # True / False
    correct_label = db.Column(db.String(50))  # accident / no accident
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "is_correct": self.is_correct,
            "correct_label": self.correct_label,
            "device_id": self.device_id,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }


# MODEL UPDATES (FEDERATED)
class ModelUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(50))
    weights = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)