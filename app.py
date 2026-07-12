import io
import os
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, redirect, url_for, request, flash, send_file, abort
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_CENTER

from models import (
    db, User, Patient, Prescription, PrescriptionItem, PatientMedication, Medicine,
    ClinicSettings, MEDICINE_CATEGORIES, FREQUENCY_OPTIONS, TIMING_OPTIONS, DURATION_UNITS,
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'clinic.db')}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

# Safety net: if the database file exists but is missing tables (e.g. init_db.py
# was never run, or was run against a different DATABASE_URL), create them here
# so the app doesn't hard-crash with "no such table" on first request.
with app.app_context():
    db.create_all()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "info"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --------------------------------------------------------------------------
# Access control helpers
# --------------------------------------------------------------------------
def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view_func(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_globals():
    return {"clinic": ClinicSettings.get(), "current_year": datetime.utcnow().year}


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_active_user:
                flash("This account has been deactivated. Contact an administrator.", "error")
                return redirect(url_for("login"))
            login_user(user)
            flash(f"Welcome back, {user.full_name or user.username}.", "success")
            return redirect(url_for("dashboard"))

        flash("Incorrect username or password.", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# Dashboard / patient list (search + filter live here for both roles)
# --------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    query = Patient.query

    if not current_user.is_admin:
        query = query.filter_by(created_by_id=current_user.id)

    search = request.args.get("q", "").strip()
    disease_filter = request.args.get("disease", "").strip()

    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(Patient.name.ilike(like), Patient.phone.ilike(like)))

    if disease_filter:
        query = query.filter(Patient.disease.ilike(f"%{disease_filter}%"))

    patients = query.order_by(Patient.created_at.desc()).all()

    # Distinct diseases for the filter dropdown, scoped the same way as the list
    disease_scope = Patient.query if current_user.is_admin else Patient.query.filter_by(created_by_id=current_user.id)
    diseases = sorted({p.disease for p in disease_scope.all() if p.disease})

    stats = {
        "total": len(patients),
        "this_week": sum(
            1 for p in patients if (datetime.utcnow() - p.created_at).days <= 7
        ),
    }

    return render_template(
        "dashboard.html",
        patients=patients,
        diseases=diseases,
        search=search,
        disease_filter=disease_filter,
        stats=stats,
    )


# --------------------------------------------------------------------------
# Medication line-item helpers (shared by add_patient / edit_patient)
# --------------------------------------------------------------------------
def _parse_medication_rows(form):
    """
    Reads the parallel arrays posted by the medication table in patient_form.html
    and returns a list of dicts, one per non-empty row, resolving each row against
    the medicine inventory where possible (falls back to a free-typed name).
    """
    names = form.getlist("med_name[]")
    doses = form.getlist("med_dose[]")
    frequencies = form.getlist("med_frequency[]")
    timings = form.getlist("med_timing[]")
    duration_values = form.getlist("med_duration_value[]")
    duration_units = form.getlist("med_duration_unit[]")
    quantities = form.getlist("med_qty[]")
    instructions = form.getlist("med_instructions[]")

    rows = []
    for i, raw_name in enumerate(names):
        name = raw_name.strip()
        if not name:
            continue  # skip blank rows left over from removed table rows

        # Try to resolve the typed name against inventory (exact match on the
        # "Name (Strength)" display form, then a plain-name fallback).
        medicine = Medicine.query.filter(
            db.func.lower(Medicine.name) == name.lower()
        ).first()
        if not medicine:
            for candidate in Medicine.query.filter(Medicine.name.ilike(f"%{name.split('(')[0].strip()}%")).all():
                if candidate.display_name.lower() == name.lower():
                    medicine = candidate
                    break

        def _get(lst, default=""):
            return lst[i].strip() if i < len(lst) else default

        rows.append({
            "medicine_id": medicine.id if medicine else None,
            "medicine_name": name,
            "dose": _get(doses),
            "frequency": _get(frequencies, "OD"),
            "timing": _get(timings, "After Food"),
            "duration_value": int(_get(duration_values) or 1),
            "duration_unit": _get(duration_units, "Days"),
            "quantity": int(_get(quantities) or 1),
            "instructions": _get(instructions),
            "sort_order": i,
        })
    return rows


def _replace_patient_medications(patient, rows):
    PatientMedication.query.filter_by(patient_id=patient.id).delete()
    for row in rows:
        db.session.add(PatientMedication(patient_id=patient.id, **row))


# --------------------------------------------------------------------------
# Patients
# --------------------------------------------------------------------------
@app.route("/patients/add", methods=["GET", "POST"])
@login_required
def add_patient():
    if request.method == "POST":
        patient = Patient(
            name=request.form.get("name", "").strip(),
            age=request.form.get("age", type=int) or 0,
            gender=request.form.get("gender", "").strip(),
            phone=request.form.get("phone", "").strip(),
            disease=request.form.get("disease", "").strip(),
            symptoms=request.form.get("symptoms", "").strip(),
            address=request.form.get("address", "").strip(),
            created_by_id=current_user.id,
        )
        db.session.add(patient)
        db.session.flush()  # assigns patient.id before we attach medication rows

        for row in _parse_medication_rows(request.form):
            db.session.add(PatientMedication(patient_id=patient.id, **row))

        db.session.commit()
        flash(f"Patient record created for {patient.name}.", "success")
        return redirect(url_for("view_patient", patient_id=patient.id))

    medicines = Medicine.query.order_by(Medicine.name.asc()).all()
    return render_template(
        "patient_form.html", patient=None, medications=[],
        medicines=medicines, form_action=url_for("add_patient"),
    )


def _get_scoped_patient(patient_id):
    patient = db.session.get(Patient, patient_id)
    if not patient:
        abort(404)
    if not current_user.is_admin and patient.created_by_id != current_user.id:
        abort(403)
    return patient


@app.route("/patients/<int:patient_id>")
@login_required
def view_patient(patient_id):
    patient = _get_scoped_patient(patient_id)
    return render_template("view_patient.html", patient=patient)


@app.route("/patients/<int:patient_id>/edit", methods=["GET", "POST"])
@login_required
def edit_patient(patient_id):
    patient = _get_scoped_patient(patient_id)

    if request.method == "POST":
        patient.name = request.form.get("name", "").strip()
        patient.age = request.form.get("age", type=int) or 0
        patient.gender = request.form.get("gender", "").strip()
        patient.phone = request.form.get("phone", "").strip()
        patient.disease = request.form.get("disease", "").strip()
        patient.symptoms = request.form.get("symptoms", "").strip()
        patient.address = request.form.get("address", "").strip()

        rows = _parse_medication_rows(request.form)
        _replace_patient_medications(patient, rows)

        db.session.commit()
        flash(f"Updated record for {patient.name}.", "success")
        return redirect(url_for("view_patient", patient_id=patient.id))

    medicines = Medicine.query.order_by(Medicine.name.asc()).all()
    return render_template(
        "patient_form.html", patient=patient, medications=patient.medications,
        medicines=medicines, form_action=url_for("edit_patient", patient_id=patient.id),
    )


@app.route("/patients/<int:patient_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_patient(patient_id):
    patient = db.session.get(Patient, patient_id) or abort(404)
    name = patient.name
    db.session.delete(patient)
    db.session.commit()
    flash(f"Deleted record for {name}.", "info")
    return redirect(url_for("dashboard"))


# --------------------------------------------------------------------------
# Prescription PDF + history
# --------------------------------------------------------------------------
@app.route("/patients/<int:patient_id>/prescription.pdf")
@login_required
def prescription_pdf(patient_id):
    patient = _get_scoped_patient(patient_id)
    clinic = ClinicSettings.get()

    # Snapshot the patient's current medication list into a new history record,
    # and deduct dispensed quantities from inventory where the item is linked
    # to a real Medicine.
    record = Prescription(
        patient_id=patient.id,
        disease=patient.disease,
        symptoms=patient.symptoms,
        generated_by_id=current_user.id,
    )
    db.session.add(record)
    db.session.flush()

    low_stock_warnings = []
    for line in patient.medications:
        db.session.add(PrescriptionItem(
            prescription_id=record.id,
            medicine_id=line.medicine_id,
            medicine_name=line.medicine_name,
            dose=line.dose,
            frequency=line.frequency,
            timing=line.timing,
            duration_value=line.duration_value,
            duration_unit=line.duration_unit,
            quantity=line.quantity,
            instructions=line.instructions,
            sort_order=line.sort_order,
        ))
        if line.medicine_id:
            medicine = db.session.get(Medicine, line.medicine_id)
            if medicine:
                medicine.stock_qty = max(0, medicine.stock_qty - line.quantity)
                if medicine.stock_status in ("low", "out"):
                    low_stock_warnings.append(medicine.name)

    db.session.commit()

    if low_stock_warnings:
        flash(f"Low/out of stock after dispensing: {', '.join(sorted(set(low_stock_warnings)))}.", "info")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )
    styles = getSampleStyleSheet()

    clinic_name_style = ParagraphStyle(
        "ClinicName", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=20, alignment=TA_CENTER, textColor=colors.HexColor("#20433F"),
        spaceAfter=2,
    )
    address_style = ParagraphStyle(
        "Address", parent=styles["Normal"], fontSize=9.5, alignment=TA_CENTER,
        textColor=colors.HexColor("#5B6B63"),
    )
    label_style = ParagraphStyle(
        "Label", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9,
        textColor=colors.HexColor("#8A6D1D"),
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"], fontSize=11, leading=15,
    )
    cell_style = ParagraphStyle(
        "Cell", parent=styles["Normal"], fontSize=9.5, leading=12.5,
    )
    cell_header_style = ParagraphStyle(
        "CellHeader", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8.5,
        textColor=colors.white,
    )
    section_title_style = ParagraphStyle(
        "SectionTitle", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=11.5, textColor=colors.HexColor("#20433F"), spaceBefore=10, spaceAfter=4,
    )

    story = []
    story.append(Paragraph(clinic.clinic_name, clinic_name_style))
    if clinic.tagline:
        story.append(Paragraph(clinic.tagline, address_style))
    story.append(Paragraph(clinic.address, address_style))
    contact_bits = [b for b in [clinic.phone and f"Phone: {clinic.phone}", clinic.email] if b]
    if contact_bits:
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(contact_bits), address_style))
    if clinic.registration_no:
        story.append(Paragraph(f"Reg. No: {clinic.registration_no}", address_style))

    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.4, color=colors.HexColor("#C9A227")))
    story.append(Spacer(1, 10))

    today = datetime.utcnow().strftime("%d %B %Y")
    info_table = Table(
        [
            [Paragraph("PATIENT NAME", label_style), Paragraph("DATE", label_style)],
            [Paragraph(patient.name, body_style), Paragraph(today, body_style)],
            [Paragraph("AGE / GENDER", label_style), Paragraph("PHONE", label_style)],
            [
                Paragraph(f"{patient.age} yrs" + (f" / {patient.gender}" if patient.gender else ""), body_style),
                Paragraph(patient.phone or "—", body_style),
            ],
        ],
        colWidths=[85 * mm, 85 * mm],
    )
    info_table.setStyle(TableStyle([
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("DIAGNOSIS", section_title_style))
    story.append(Paragraph(patient.disease or "—", body_style))

    if patient.symptoms:
        story.append(Paragraph("SYMPTOMS", section_title_style))
        story.append(Paragraph(patient.symptoms, body_style))

    story.append(Paragraph("Rx &nbsp;MEDICATION &amp; DOSAGE", section_title_style))

    items = list(record.items)
    if items:
        header = ["Medicine", "Dose", "Freq.", "Timing", "Duration", "Qty", "Instructions"]
        table_data = [[Paragraph(h, cell_header_style) for h in header]]
        for item in items:
            table_data.append([
                Paragraph(item.medicine_name, cell_style),
                Paragraph(item.dose or "—", cell_style),
                Paragraph(item.frequency or "—", cell_style),
                Paragraph(item.timing or "—", cell_style),
                Paragraph(item.duration_display, cell_style),
                Paragraph(str(item.quantity), cell_style),
                Paragraph(item.instructions or "—", cell_style),
            ])
        med_table = Table(
            table_data,
            colWidths=[34 * mm, 18 * mm, 14 * mm, 24 * mm, 20 * mm, 12 * mm, 28 * mm],
            repeatRows=1,
        )
        med_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#20433F")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4EF")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8D2C2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(med_table)
    else:
        story.append(Paragraph("No medication recorded.", body_style))

    if patient.address:
        story.append(Spacer(1, 8))
        story.append(Paragraph("ADDRESS", section_title_style))
        story.append(Paragraph(patient.address, body_style))

    story.append(Spacer(1, 30))
    sign_table = Table(
        [["_________________________", ""], ["Attending Physician / Staff", ""]],
        colWidths=[85 * mm, 85 * mm],
    )
    sign_table.setStyle(TableStyle([("ALIGN", (0, 0), (0, -1), "LEFT")]))
    story.append(sign_table)

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#D8D2C2")))
    story.append(Paragraph(
        f"Generated on {datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')} · This prescription is valid only with an authorised signature.",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7.5, alignment=TA_CENTER,
                       textColor=colors.HexColor("#8A9691"))
    ))

    doc.build(story)
    buffer.seek(0)

    filename = f"prescription_{patient.name.replace(' ', '_')}_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")


@app.route("/patients/<int:patient_id>/history")
@login_required
def prescription_history(patient_id):
    patient = _get_scoped_patient(patient_id)
    return render_template("history.html", patient=patient)


# --------------------------------------------------------------------------
# Medicine inventory (admin-managed; readable by staff when prescribing)
# --------------------------------------------------------------------------
@app.route("/medicines")
@login_required
@admin_required
def medicines_dashboard():
    query = Medicine.query

    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    manufacturer = request.args.get("manufacturer", "").strip()
    stock_filter = request.args.get("stock", "").strip()  # "in" | "low" | "out"

    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(
            Medicine.name.ilike(like), Medicine.generic_name.ilike(like), Medicine.brand_name.ilike(like)
        ))
    if category:
        query = query.filter(Medicine.category == category)
    if manufacturer:
        query = query.filter(Medicine.manufacturer == manufacturer)

    medicines = query.order_by(Medicine.name.asc()).all()

    if stock_filter:
        medicines = [m for m in medicines if m.stock_status == stock_filter]

    manufacturers = sorted({m.manufacturer for m in Medicine.query.all() if m.manufacturer})

    stats = {
        "total": Medicine.query.count(),
        "low": sum(1 for m in Medicine.query.all() if m.stock_status == "low"),
        "out": sum(1 for m in Medicine.query.all() if m.stock_status == "out"),
    }

    return render_template(
        "medicines_dashboard.html", medicines=medicines, categories=MEDICINE_CATEGORIES,
        manufacturers=manufacturers, search=search, category=category,
        manufacturer=manufacturer, stock_filter=stock_filter, stats=stats,
    )


def _apply_medicine_form(medicine, form):
    medicine.name = form.get("name", "").strip()
    medicine.generic_name = form.get("generic_name", "").strip()
    medicine.brand_name = form.get("brand_name", "").strip()
    medicine.sku = form.get("sku", "").strip()
    medicine.category = form.get("category", "Tablet")
    medicine.strength = form.get("strength", "").strip()
    medicine.manufacturer = form.get("manufacturer", "").strip()
    medicine.unit_price = form.get("unit_price", type=float) or 0.0
    medicine.stock_qty = form.get("stock_qty", type=int) or 0
    medicine.reorder_level = form.get("reorder_level", type=int) or 10
    expiry_raw = form.get("expiry_date", "").strip()
    medicine.expiry_date = datetime.strptime(expiry_raw, "%Y-%m-%d").date() if expiry_raw else None


@app.route("/medicines/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_medicine():
    if request.method == "POST":
        medicine = Medicine()
        _apply_medicine_form(medicine, request.form)
        db.session.add(medicine)
        db.session.commit()
        flash(f"Added '{medicine.name}' to the inventory.", "success")
        return redirect(url_for("medicines_dashboard"))

    return render_template(
        "medicine_form.html", medicine=None, categories=MEDICINE_CATEGORIES,
        form_action=url_for("add_medicine"),
    )


@app.route("/medicines/<int:medicine_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_medicine(medicine_id):
    medicine = db.session.get(Medicine, medicine_id) or abort(404)

    if request.method == "POST":
        _apply_medicine_form(medicine, request.form)
        db.session.commit()
        flash(f"Updated '{medicine.name}'.", "success")
        return redirect(url_for("medicines_dashboard"))

    return render_template(
        "medicine_form.html", medicine=medicine, categories=MEDICINE_CATEGORIES,
        form_action=url_for("edit_medicine", medicine_id=medicine.id),
    )


@app.route("/medicines/<int:medicine_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_medicine(medicine_id):
    medicine = db.session.get(Medicine, medicine_id) or abort(404)
    name = medicine.name
    db.session.delete(medicine)
    db.session.commit()
    flash(f"Removed '{name}' from the inventory.", "info")
    return redirect(url_for("medicines_dashboard"))


# --------------------------------------------------------------------------
# Admin: user management + clinic settings
# --------------------------------------------------------------------------
@app.route("/admin/users", methods=["GET", "POST"])
@login_required
@admin_required
def manage_users():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role", "staff")

        if not username or not password:
            flash("Username and password are required.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username is already taken.", "error")
        else:
            user = User(username=username, full_name=full_name, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(f"User '{username}' created.", "success")
        return redirect(url_for("manage_users"))

    users = User.query.order_by(User.created_at.asc()).all()
    return render_template("users.html", users=users)


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_user(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("You can't deactivate your own account.", "error")
        return redirect(url_for("manage_users"))
    user.is_active_user = not user.is_active_user
    db.session.commit()
    flash(f"User '{user.username}' {'activated' if user.is_active_user else 'deactivated'}.", "info")
    return redirect(url_for("manage_users"))


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
@admin_required
def clinic_settings():
    settings = ClinicSettings.get()

    if request.method == "POST":
        settings.clinic_name = request.form.get("clinic_name", "").strip() or settings.clinic_name
        settings.tagline = request.form.get("tagline", "").strip()
        settings.address = request.form.get("address", "").strip()
        settings.phone = request.form.get("phone", "").strip()
        settings.email = request.form.get("email", "").strip()
        settings.registration_no = request.form.get("registration_no", "").strip()
        db.session.commit()
        flash("Clinic details updated.", "success")
        return redirect(url_for("clinic_settings"))

    return render_template("settings.html", settings=settings)


# --------------------------------------------------------------------------
@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="You don't have permission to view this page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="That page doesn't exist."), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)
