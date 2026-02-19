from flask import Blueprint, request, jsonify
from models import User, Accident
from extensions import db
from datetime import datetime

api = Blueprint("api", __name__)

# GET ALL USERS
@api.route("/users", methods=["GET"])
def get_users():
    users = User.query.all()
    return jsonify([user.to_dict() for user in users])


# CREATE USER
@api.route("/users", methods=["POST"])
def create_user():
    data = request.get_json()

    user = User(
        username=data["username"],
        password=data["password"],
        role=data["role"]
    )

    db.session.add(user)
    db.session.commit()

    return jsonify(user.to_dict()), 201


# CREATE ACCIDENT
@api.route("/accidents", methods=["POST"])
def create_accident():
    data = request.get_json()

    accident = Accident(
        timestamp=datetime.utcnow(),
        location=data["location"],
        image_path=data["image_path"]
    )

    db.session.add(accident)
    db.session.commit()

    return jsonify(accident.to_dict()), 201
