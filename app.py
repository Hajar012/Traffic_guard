import json
import random
from flask import Flask, render_template, request, redirect, session, jsonify

from backend.extensions import db
from Fedarated.federated import aggregate_models
from Fedarated.client import train_local_model

app = Flask(__name__)

# -------------------------------
# CONFIG
# -------------------------------
app.secret_key = "1122334455"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize DB FIRST
db.init_app(app)

# Import models AFTER db.init_app(app)
from backend.models import User, Alert, Device, Feedback, ModelUpdate


# -------------------------------
# USER DATABASE
# -------------------------------
users = {
    "admin@traffic.com": {
        "password": "admin123",
        "role": "admin",
        "name": "Admin User"
    },
    "authority@traffic.com": {
        "password": "auth123",
        "role": "authority",
        "name": "Authority Officer"
    },
    "guest@traffic.com": {
        "password": "guest123",
        "role": "guest",
        "name": "Guest User"
    }
}


# -------------------------------
# ROLE SELECTION PAGE
# -------------------------------
@app.route("/select-role")
def select_role():
    return render_template("select_role.html")


# -------------------------------
# LOGIN PAGE
# -------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        role = request.args.get("role")
        if not role:
            return redirect("/select-role")
        return render_template("login.html", role=role)

    email = request.form.get("email")
    password = request.form.get("password")
    role = request.form.get("role")

    if email in users and users[email]["password"] == password:
        session["role"] = users[email]["role"]
        session["email"] = email
        session["name"] = users[email]["name"]
        return redirect("/")

    return render_template(
        "login.html",
        role=role,
        error="Invalid email or password"
    )


# -------------------------------
# LOGOUT
# -------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/select-role")


# -------------------------------
# DASHBOARD
# -------------------------------
@app.route("/")
def dashboard():
    if "role" not in session:
        return redirect("/select-role")

    return render_template(
        "dashboard.html",
        role=session["role"],
        name=session["name"]
    )


# -------------------------------
# TRAFFIC DATA API
# -------------------------------
@app.route("/traffic_data")
def traffic_data():
    labels = [f"{h:02d}:00" for h in range(9, 20)]
    vehicles = [random.randint(200, 800) for _ in labels]
    alerts = [random.randint(0, 8) for _ in labels]

    return jsonify({
        "labels": labels,
        "vehicles": vehicles,
        "alerts": alerts
    })


# -------------------------------
# DEVICE STATUS API
# -------------------------------
@app.route("/device_status")
def device_status():
    devices = Device.query.order_by(Device.device_id.asc()).all()
    result = []

    fallback_coordinates = [
        {"lat": 24.774265, "lon": 46.738586},  # King Fahd Road North
        {"lat": 24.7136, "lon": 46.6753},      # Olaya District
        {"lat": 24.7743, "lon": 46.7000},      # King Abdullah Road
        {"lat": 24.6800, "lon": 46.7200},      # King Fahd Road
        {"lat": 24.7350, "lon": 46.6900},      # Riyadh center
    ]

    for index, device in enumerate(devices):
        latest_update = ModelUpdate.query.filter_by(
            device_id=device.device_id
        ).order_by(
            ModelUpdate.timestamp.desc()
        ).first()

        coordinates = fallback_coordinates[index % len(fallback_coordinates)]

        result.append({
            "id": device.device_id,
            "device_id": device.device_id,
            "location": device.location,
            "status": "Online" if latest_update else "No Updates",
            "last_update": latest_update.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            if latest_update and latest_update.timestamp else None,
            "lat": coordinates["lat"],
            "lon": coordinates["lon"]
        })

    return jsonify(result)


# -------------------------------
# ALERTS API
# -------------------------------
@app.route("/alerts_data")
def alerts_data():
    alerts = Alert.query.order_by(Alert.timestamp.desc()).all()
    return jsonify([alert.to_dict() for alert in alerts])


# -------------------------------
# UPDATE ALERT + TRIGGER FEDERATED TRAINING
# -------------------------------
@app.route("/update_alert", methods=["POST"])
@app.route("/alerts_update", methods=["POST"])
def update_alert():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    alert = Alert.query.get(data.get("id"))
    if not alert:
        return jsonify({"error": "Alert not found"}), 404

    new_status = data.get("status")
    if new_status not in ["Verified", "Rejected"]:
        return jsonify({
            "error": "Status must be either 'Verified' or 'Rejected'"
        }), 400

    alert.status = new_status

    is_correct = True if new_status == "Verified" else False
    correct_label = "accident" if is_correct else "no_accident"

    feedback = Feedback(
        alert_id=alert.id,
        device_id=alert.device_id,
        is_correct=is_correct,
        correct_label=correct_label
    )

    db.session.add(feedback)

    # Feedback triggers local training.
    # Only model weights are stored/sent, not raw detection data.
    updated_weights = train_local_model(
        alert.device_id,
        is_correct=is_correct
    )

    model_update = ModelUpdate(
        device_id=alert.device_id,
        weights=json.dumps(updated_weights)
    )

    db.session.add(model_update)
    db.session.commit()

    return jsonify({
        "message": "Alert updated and federated learning triggered",
        "alert_id": alert.id,
        "device_id": alert.device_id,
        "status": alert.status,
        "feedback_saved": True,
        "weights_stored": True
    })

# -------------------------------
# DETECTION API
# Saves a new alert from an edge device.
# -------------------------------
@app.route("/detect", methods=["POST"])
def detect():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    device_id = data.get("device_id")
    alert_type = data.get("type", "accident")
    confidence = data.get("confidence")

    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    device = Device.query.filter_by(device_id=device_id).first()

    fallback_locations = {
        "ED-001": {
            "location": "King Fahd Road North",
            "lat": 24.774265,
            "lon": 46.738586
        },
        "ED-002": {
            "location": "Olaya District",
            "lat": 24.7136,
            "lon": 46.6753
        },
        "ED-003": {
            "location": "King Abdullah Road",
            "lat": 24.7743,
            "lon": 46.7000
        }
    }

    fallback = fallback_locations.get(device_id, {
        "location": "Unknown Location",
        "lat": 24.7136,
        "lon": 46.6753
    })

    alert = Alert(
        device_id=device_id,
        type=alert_type,
        confidence=confidence,
        location=data.get("location") or (device.location if device else fallback["location"]),
        lat=data.get("lat", fallback["lat"]),
        lon=data.get("lon", fallback["lon"]),
        status="Pending"
    )

    db.session.add(alert)
    db.session.commit()

    return jsonify({
        "message": "Alert received",
        "alert_id": alert.id,
        "device_id": alert.device_id,
        "status": alert.status
    })


# -------------------------------
# FEEDBACK API
# Kept functional for direct feedback submissions.
# It also triggers local model training and stores JSON weights.
# -------------------------------
@app.route("/feedback", methods=["POST"])
def feedback():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    alert_id = data.get("alert_id")
    if not alert_id:
        return jsonify({"error": "alert_id is required"}), 400

    alert = Alert.query.get(alert_id)
    device_id = data.get("device_id") or (alert.device_id if alert else None)

    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    is_correct = bool(data.get("is_correct"))
    correct_label = data.get(
        "correct_label",
        "accident" if is_correct else "no_accident"
    )

    feedback_record = Feedback(
        alert_id=alert_id,
        device_id=device_id,
        is_correct=is_correct,
        correct_label=correct_label
    )

    db.session.add(feedback_record)

    updated_weights = train_local_model(
        device_id,
        is_correct=is_correct
    )

    model_update = ModelUpdate(
        device_id=device_id,
        weights=json.dumps(updated_weights)
    )

    db.session.add(model_update)
    db.session.commit()

    return jsonify({
        "status": "saved and learning triggered",
        "device_id": device_id,
        "weights_stored": True
    })


# -------------------------------
# FEDERATED UPDATE API
# Receives structured model weights from edge devices.
# Raw data is never sent, only model parameters.
# -------------------------------
@app.route("/federated/update", methods=["POST"])
def federated_update():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    device_id = data.get("device_id")
    weights = data.get("weights")

    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    if not isinstance(weights, dict):
        return jsonify({
            "error": "weights must be a structured JSON object"
        }), 400

    model_update = ModelUpdate(
        device_id=device_id,
        weights=json.dumps(weights)
    )

    db.session.add(model_update)
    db.session.commit()

    return jsonify({
        "message": "Update received",
        "device_id": device_id
    })


# -------------------------------
# GLOBAL MODEL API
# Aggregates all device updates using FedAvg.
# -------------------------------
@app.route("/global_model")
def global_model():
    result = aggregate_models()

    if not result:
        return jsonify({"message": "No data yet"})

    return jsonify(result)


# -------------------------------
# RUN APP
# -------------------------------
if __name__ == "__main__":
    app.run(debug=True)