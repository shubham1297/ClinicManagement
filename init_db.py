"""
Initializes the database: creates all tables and seeds default users
and clinic settings so the app is usable immediately after install.
"""
from datetime import date
from app import app
from models import db, User, ClinicSettings, Medicine


def init_database():
    with app.app_context():
        db.create_all()
        print("✓ Database tables created successfully!")

        if not User.query.filter_by(username="admin").first():
            admin = User(username="admin", full_name="Clinic Administrator", role="admin")
            admin.set_password("admin123")
            db.session.add(admin)
            print("✓ Admin user created (username: admin, password: admin123)")
        else:
            print("• Admin user already exists, skipping.")

        if not User.query.filter_by(username="staff").first():
            staff = User(username="staff", full_name="Front Desk Staff", role="staff")
            staff.set_password("staff123")
            db.session.add(staff)
            print("✓ Staff user created (username: staff, password: staff123)")
        else:
            print("• Staff user already exists, skipping.")

        db.session.commit()

        # Ensure a clinic settings row exists
        ClinicSettings.get()
        print("✓ Clinic settings initialized (edit under Admin > Clinic Settings)")

        if Medicine.query.count() == 0:
            sample_medicines = [
                Medicine(name="Paracetamol", strength="500 mg", category="Tablet",
                         generic_name="Paracetamol", manufacturer="Cipla", unit_price=2.0,
                         stock_qty=250, reorder_level=50, expiry_date=date(2028, 2, 28)),
                Medicine(name="Amoxicillin", strength="250 mg", category="Capsule",
                         generic_name="Amoxicillin", manufacturer="Sun Pharma", unit_price=8.5,
                         stock_qty=45, reorder_level=50, expiry_date=date(2027, 8, 31)),
                Medicine(name="Dolo 650", strength="650 mg", category="Tablet",
                         generic_name="Paracetamol", brand_name="Dolo", manufacturer="Micro Labs",
                         unit_price=3.5, stock_qty=10, reorder_level=30, expiry_date=date(2026, 12, 31)),
                Medicine(name="Pantoprazole", strength="40 mg", category="Tablet",
                         generic_name="Pantoprazole", manufacturer="Alkem", unit_price=6.0,
                         stock_qty=80, reorder_level=25, expiry_date=date(2027, 6, 30)),
            ]
            db.session.add_all(sample_medicines)
            print("✓ Sample medicines added to inventory (edit or delete anytime under Medicines)")
        else:
            print("• Medicines already exist, skipping sample data.")

        db.session.commit()

        print("✓ Database initialization complete!")
        print()
        print("⚠  Remember to change the default passwords before going live.")


if __name__ == "__main__":
    init_database()
