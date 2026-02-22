from flask import Flask, render_template, request, redirect, session, jsonify
from backend.extensions import db
from backend.models import User, Accident
from datetime import datetime
import random

import os

app = Flask(__name__)
app.secret_key = "1122334455"

# ----------------------------
# DATABASE CONFIG
# ----------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "instance/database.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


# ----------------------------
# ROLE SELECTION PAGE
# ----------------------------
@app.route('/select-role')
def select_role():
    return render_template('select_role.html')


# ----------------------------
# LOGIN
# ----------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'GET':
        role = request.args.get('role')
        if not role:
            return redirect('/select-role')
        return render_template('login.html', role=role)

    email = request.form.get('email')
    password = request.form.get('password')

    user = User.query.filter_by(email=email).first()

    if user and user.password == password:
        session['role'] = user.role
        session['email'] = user.email
        return redirect('/')

    return render_template('login.html', error="Invalid login")
# ----------------------------
# LOGOUT
# ----------------------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/select-role')


# ----------------------------
# DASHBOARD
# ----------------------------
@app.route('/')
def dashboard():
    if 'role' not in session:
        return redirect('/select-role')

    return render_template(
        'dashboard.html',
        role=session['role'],
        email=session['email']
    )


# ----------------------------
# USERS API

# ----------------------------
@app.route('/users')
def get_users():
    users = User.query.all()
    return jsonify([{
        "id": u.id,
        "email": u.email,
        "role": u.role
    } for u in users])


@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()

    user = User(
        email=data["email"],
        password=data["password"],
        role=data["role"]
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "User created"}), 201


# ----------------------------
# TRAFFIC DATA (FAKE CHART DATA)
# ----------------------------
@app.route('/traffic_data')
def traffic_data():
    labels = [f"{h:02d}:00" for h in range(9, 20)]
    vehicles = [random.randint(200, 800) for _ in labels]
    alerts = [random.randint(0, 8) for _ in labels]

    return jsonify({
        "labels": labels,
        "vehicles": vehicles,
        "alerts": alerts
    })


# ----------------------------
# ALERTS DATA (FROM DATABASE)
# ----------------------------
@app.route('/alerts_data')
def alerts_data():

    if 'role' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    accidents = Accident.query.all()

    alerts = []

    for accident in accidents:
        alerts.append({
            "id": accident.id,
            "title": f"Accident #{accident.id}",
            "location": accident.location,
            "severity": "red",
            "severity_label": "High",
            "time": accident.timestamp.strftime("%I:%M %p") if accident.timestamp else "",
            "description": "Traffic accident detected",
            "lat": 24.774265,
            "lon": 46.738586,
            "status": "Pending"
        })

    return jsonify(alerts)


# ----------------------------
# ADD ACCIDENT (TESTING)
# ----------------------------
@app.route('/add_accident', methods=['POST'])
def add_accident():

    data = request.get_json()

    accident = Accident(
        timestamp=datetime.now(),
        location=data["location"],
        image_path=data.get("image_path", "")
    )

    db.session.add(accident)
    db.session.commit()

    return jsonify({"message": "Accident added"}), 201


# ----------------------------
# RUN
# ----------------------------
if __name__ == '__main__':
    app.run(debug=True)


print("Traffic guard started")