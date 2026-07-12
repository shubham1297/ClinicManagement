from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

MEDICINE_CATEGORIES = ["Tablet", "Capsule", "Syrup", "Injection", "Ointment", "Drops"]
FREQUENCY_OPTIONS = ["OD", "BD", "TDS", "QID", "SOS", "STAT"]
TIMING_OPTIONS = ["Before Food", "After Food", "With Food", "Empty Stomach", "Bedtime"]
DURATION_UNITS = ["Days", "Weeks", "Months"]


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False, default="")
    role = db.Column(db.String(20), nullable=False, default="staff")  # 'admin' or 'staff'
    is_active_user = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patients = db.relationship("Patient", backref="created_by", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"

    # Flask-Login uses is_active as a property; keep our own column name distinct
    @property
    def is_active(self):
        return self.is_active_user


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    gender = db.Column(db.String(20), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    disease = db.Column(db.String(200), nullable=False)
    symptoms = db.Column(db.Text, nullable=True)
    address = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    prescriptions = db.relationship(
        "Prescription", backref="patient", lazy=True, cascade="all, delete-orphan",
        order_by="desc(Prescription.created_at)"
    )
    medications = db.relationship(
        "PatientMedication", backref="patient", lazy=True, cascade="all, delete-orphan",
        order_by="PatientMedication.sort_order"
    )


class Medicine(db.Model):
    """A single item in the clinic's medicine inventory."""
    __tablename__ = "medicines"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    generic_name = db.Column(db.String(150), nullable=True)
    brand_name = db.Column(db.String(150), nullable=True)
    sku = db.Column(db.String(60), nullable=True)
    category = db.Column(db.String(30), nullable=False, default="Tablet")
    strength = db.Column(db.String(50), nullable=True)  # e.g. "500 mg"
    manufacturer = db.Column(db.String(150), nullable=True)
    unit_price = db.Column(db.Float, nullable=False, default=0.0)
    stock_qty = db.Column(db.Integer, nullable=False, default=0)
    reorder_level = db.Column(db.Integer, nullable=False, default=10)
    expiry_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def stock_status(self):
        if self.stock_qty <= 0:
            return "out"
        if self.stock_qty <= self.reorder_level:
            return "low"
        return "in"

    @property
    def display_name(self):
        return f"{self.name} ({self.strength})" if self.strength else self.name


class _MedicationLineMixin:
    """Shared columns for a prescribed-medicine line item (current or historical)."""
    dose = db.Column(db.String(60), nullable=False, default="")
    frequency = db.Column(db.String(20), nullable=False, default="OD")
    timing = db.Column(db.String(30), nullable=False, default="After Food")
    duration_value = db.Column(db.Integer, nullable=False, default=1)
    duration_unit = db.Column(db.String(20), nullable=False, default="Days")
    quantity = db.Column(db.Integer, nullable=False, default=1)
    instructions = db.Column(db.String(200), nullable=True, default="")
    medicine_name = db.Column(db.String(150), nullable=False)  # snapshot, survives medicine edits/deletes
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    @property
    def duration_display(self):
        return f"{self.duration_value} {self.duration_unit}"


class PatientMedication(_MedicationLineMixin, db.Model):
    """The patient's current, editable medication list — what the next PDF will use."""
    __tablename__ = "patient_medications"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey("medicines.id"), nullable=True)

    medicine = db.relationship("Medicine")


class Prescription(db.Model):
    """A historical record each time a prescription PDF is generated for a patient."""
    __tablename__ = "prescriptions"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    disease = db.Column(db.String(200), nullable=False)
    symptoms = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    generated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    generated_by = db.relationship("User")
    items = db.relationship(
        "PrescriptionItem", backref="prescription", lazy=True, cascade="all, delete-orphan",
        order_by="PrescriptionItem.sort_order"
    )


class PrescriptionItem(_MedicationLineMixin, db.Model):
    """A frozen snapshot of one medication line as it was at the moment a PDF was generated."""
    __tablename__ = "prescription_items"

    id = db.Column(db.Integer, primary_key=True)
    prescription_id = db.Column(db.Integer, db.ForeignKey("prescriptions.id"), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey("medicines.id"), nullable=True)

    medicine = db.relationship("Medicine")


class ClinicSettings(db.Model):
    """Singleton-style table holding editable clinic details used in the PDF header."""
    __tablename__ = "clinic_settings"

    id = db.Column(db.Integer, primary_key=True)
    clinic_name = db.Column(db.String(150), nullable=False, default="Shanti Clinic")
    tagline = db.Column(db.String(200), nullable=False, default="")
    address = db.Column(db.String(255), nullable=False, default="Ashok Nagar, Kankarbagh, Patna - 20")
    phone = db.Column(db.String(50), nullable=False, default="")
    email = db.Column(db.String(120), nullable=False, default="")
    registration_no = db.Column(db.String(100), nullable=False, default="")

    @staticmethod
    def get():
        settings = ClinicSettings.query.first()
        if not settings:
            settings = ClinicSettings()
            db.session.add(settings)
            db.session.commit()
        return settings
