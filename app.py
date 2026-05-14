import json
import random
from flask import Flask, render_template, request, redirect, session, jsonify, make_response, url_for

from backend.extensions import db
from Fedarated.federated import aggregate_models
from Fedarated.client import train_local_model
from werkzeug.security import generate_password_hash

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
# BASIC RBAC UTILITIES
# -------------------------------
def role_required(*allowed_roles, api=False):
    """Decorator factory to restrict access based on session role.

    - For HTML routes (api=False): unauthorized users are redirected to '/select-role'.
    - For API routes (api=True): returns JSON 403.
    """
    def decorator(fn):
        from functools import wraps

        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = session.get("role", "guest")
            if allowed_roles and role not in allowed_roles:
                # Decide response type
                if api or request.is_json or request.accept_mimetypes.best == "application/json":
                    return jsonify({"error": "Forbidden"}), 403
                # Redirect for HTML endpoints
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)

        return wrapper
    return decorator


# -------------------------------
# GUEST PREVIEW (no login)
# -------------------------------
@app.route("/guest-preview")
def guest_preview():
    # Directly set a guest session and open dashboard
    session["role"] = "guest"
    session["email"] = "guest@traffic.com"
    session["name"] = "Guest User"
    return redirect("/")


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
    # Allow homepage without login: treat as guest if no session
    role = session.get("role", "guest")
    name = session.get("name", "Guest User")

    return render_template(
        "dashboard.html",
        role=role,
        name=name
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
@role_required("authority", "admin", api=True)
def alerts_data():
    alerts = Alert.query.order_by(Alert.timestamp.desc()).all()
    return jsonify([alert.to_dict() for alert in alerts])


# -------------------------------
# UPDATE ALERT + TRIGGER FEDERATED TRAINING
# -------------------------------
@app.route("/update_alert", methods=["POST"])
@app.route("/alerts_update", methods=["POST"])
@role_required("authority", "admin", api=True)
def update_alert():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    alert = Alert.query.get(data.get("id"))
    if not alert:
        return jsonify({"error": "Alert not found"}), 404

    # CRITICAL: lock decision after first update
    if alert.status and alert.status != "Pending":
        return jsonify({"error": "Already decided"}), 400

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
    # Accept both multipart/form-data with file upload and legacy JSON
    try:
        print("[DETECT] Incoming request:", {
            "method": request.method,
            "content_type": request.content_type,
            "has_files": bool(request.files),
            "form_keys": list(request.form.keys()) if request.form else [],
        })
    except Exception:
        pass
    data = None
    image_path_rel = None

    if request.files:
        # Multipart upload
        data = request.form
        image_file = request.files.get("image")
        if image_file and image_file.filename:
            import os
            from datetime import datetime
            uploads_dir = os.path.join(app.root_path, "static", "uploads")
            os.makedirs(uploads_dir, exist_ok=True)

            # Create unique filename
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
            safe_name = image_file.filename.replace(" ", "_")
            filename = f"alert_{ts}_{safe_name}"
            save_path = os.path.join(uploads_dir, filename)
            image_file.save(save_path)

            # Store relative path to serve via /static
            image_path_rel = f"uploads/{filename}"
            try:
                print(f"[DETECT] Saved upload to static/{image_path_rel}")
            except Exception:
                pass
    else:
        # JSON fallback for backwards compatibility
        data = request.get_json(silent=True) or {}

    if not data:
        return jsonify({"error": "Invalid body"}), 400

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
        status="Pending",
        image_path=image_path_rel
    )

    db.session.add(alert)
    db.session.commit()

    try:
        print("[DETECT] Created alert:", {
            "id": alert.id,
            "device_id": alert.device_id,
            "type": alert.type,
            "status": alert.status,
            "image_path": alert.image_path,
            "confidence": alert.confidence,
        })
    except Exception:
        pass

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
@role_required("authority", "admin", api=True)
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
@role_required("authority", "admin", api=True)
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
@role_required("authority", "admin", api=True)
def global_model():
    result = aggregate_models()

    if not result:
        return jsonify({"message": "No data yet"})

    return jsonify(result)


# -------------------------------
# PUBLIC PAGES (Guest-accessible)
# -------------------------------
@app.route("/awareness")
def awareness_page():
    return render_template("awareness.html")


@app.route("/privacy")
def privacy_page():
    return render_template("privacy.html")


@app.route("/terms")
def terms_page():
    return render_template("terms.html")


# -------------------------------
# AUTHORITY PAGES
# -------------------------------
@app.route("/authority/logs")
@role_required("authority", "admin")
def authority_logs():
    alerts = Alert.query.order_by(Alert.timestamp.desc()).limit(100).all()
    feedbacks = Feedback.query.order_by(Feedback.timestamp.desc()).limit(100).all()
    return render_template("authority_logs.html", alerts=alerts, feedbacks=feedbacks)


@app.route("/export/reports")
@role_required("authority", "admin")
def export_reports():
    # Export alerts report as CSV
    from io import StringIO
    import csv

    alerts = Alert.query.order_by(Alert.timestamp.desc()).all()
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["id", "timestamp", "device_id", "type", "confidence", "status", "location", "lat", "lon"])
    for a in alerts:
        writer.writerow([
            a.id,
            a.timestamp.strftime("%Y-%m-%d %H:%M:%S") if a.timestamp else "",
            a.device_id or "",
            a.type or "",
            a.confidence if a.confidence is not None else "",
            a.status or "",
            a.location or "",
            a.lat if a.lat is not None else "",
            a.lon if a.lon is not None else "",
        ])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=traffic_reports.csv"
    output.headers["Content-Type"] = "text/csv"
    return output


# -------------------------------
# ADMIN PAGES
# -------------------------------
@app.route("/admin")
@role_required("admin")
def admin_home():
    users = User.query.order_by(User.id.asc()).all() if hasattr(User, 'query') else []
    devices = Device.query.order_by(Device.device_id.asc()).all()
    updates = ModelUpdate.query.order_by(ModelUpdate.timestamp.desc()).limit(50).all()
    return render_template("admin.html", users=users, devices=devices, updates=updates)


# -------------------------------
# ADMIN API: CREATE USER
# -------------------------------
@app.route("/admin/users", methods=["POST"])
@role_required("admin", api=True)
def admin_create_user():
    # Accept JSON or form-encoded
    data = request.get_json(silent=True) or request.form

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = (data.get("role") or "").strip().lower()

    # Basic validation
    if not name or not email or not password or not role:
        return jsonify({"error": "All fields (name, email, password, role) are required."}), 400

    # Email domain restriction
    if not email.endswith("@traffic.com"):
        return jsonify({"error": "Only @traffic.com emails are allowed."}), 400

    # Role allowlist aligned with app
    allowed_roles = {"admin", "authority", "guest"}
    if role not in allowed_roles:
        return jsonify({"error": f"Invalid role. Allowed: {', '.join(sorted(allowed_roles))}"}), 400

    # Uniqueness check against Users table
    existing = User.query.filter_by(email=email).first()
    if existing:
        return jsonify({"error": "Email already exists."}), 409

    # Hash password before storing
    pw_hash = generate_password_hash(password)

    user = User(email=email, password=pw_hash, role=role, name=name)
    db.session.add(user)
    db.session.commit()

    return jsonify({
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role
    }), 201


# -------------------------------
# RUN APP
# -------------------------------
if __name__ == "__main__":
    app.run(debug=True)