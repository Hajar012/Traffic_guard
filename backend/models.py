from extensions import db
from datetime import datetime

# USERS TABLE
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # admin, police, viewer

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role
        }


# ACCIDENTS TABLE
class Accident(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime)
    location = db.Column(db.String(200))
    image_path = db.Column(db.String(200))

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "location": self.location,
            "image_path": self.image_path
        }
