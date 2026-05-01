from app import app
from backend.extensions import db
from backend.models import Device

devices = [
    {
        "device_id": "ED-001",
        "location": "King Fahd Road North"
    },
    {
        "device_id": "ED-002",
        "location": "Olaya District"
    },
    {
        "device_id": "ED-003",
        "location": "King Abdullah Road"
    }
]

with app.app_context():
    for item in devices:
        existing_device = Device.query.filter_by(device_id=item["device_id"]).first()

        if not existing_device:
            device = Device(
                device_id=item["device_id"],
                location=item["location"]
            )
            db.session.add(device)

    db.session.commit()
    print("Devices seeded successfully.")