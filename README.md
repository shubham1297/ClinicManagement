# Clinic Management System

A Flask-based clinic management application for small and mid-size practices. Staff can register patients and print prescriptions in seconds; administrators get a full view across the clinic, user management, and configurable clinic branding on every prescription.

Built as a practical, self-hostable alternative to paper prescription pads — the PDF output is designed to look and feel like one.

---

## Highlights

- **Role-based access** — Admin and Staff accounts see different scopes and permissions.
- **Medicine inventory** — A dedicated Medicines dashboard tracks name, strength, category, manufacturer, unit price, stock on hand, and expiry, with In Stock / Low Stock / Out of Stock status at a glance.
- **Prescriptions built from inventory** — The patient form's "Medication & Dosage" section is a real line-item table (Medicine, Dose, Frequency, Timing, Duration, Qty, Instructions), where the medicine name autocompletes against your inventory — not a free-text box.
- **Automatic stock deduction** — Generating a prescription PDF deducts the dispensed quantity from inventory and flags anything that drops into Low/Out of Stock.
- **Patient records** — Structured intake covering demographics, diagnosis, symptoms, medication, and address.
- **One-click prescription PDFs** — Clean, print-ready prescriptions with a clinic letterhead, a proper medication table, a signature line, and a timestamp.
- **Prescription history** — Every PDF generated is logged against the patient as a full snapshot (all medication lines included), so past visits are never lost even if the medicine is later edited or removed from inventory.
- **Search & filter** — Find a patient by name/phone or a medicine by name/category/manufacturer/stock status.
- **Clinic settings** — Admins edit the clinic name, address, phone, email, and registration number from the UI; it flows straight into the PDF header without touching code.
- **User management** — Admins can create additional staff or admin accounts, and activate/deactivate them, without a database console.

---

## Tech Stack

| Layer      | Choice                                  |
|------------|------------------------------------------|
| Backend    | Flask 3, Flask-SQLAlchemy, Flask-Login   |
| Database   | SQLite by default; PostgreSQL-ready      |
| PDF engine | ReportLab                                |
| Frontend   | Server-rendered Jinja templates, no build step required |

---

## Getting Started

### 1. Requirements

- Python 3.9+
- pip

### 2. Set up a virtual environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example file and fill in real values before deploying anywhere beyond your laptop:

```bash
cp .env.example .env
```

At minimum, set a strong `SECRET_KEY`. If you're on PostgreSQL, set `DATABASE_URL` too — see [Switching to PostgreSQL](#switching-to-postgresql).

### 5. Initialize the database

```bash
python init_db.py
```

Expected output:

```
✓ Database tables created successfully!
✓ Admin user created (username: admin, password: admin123)
✓ Staff user created (username: staff, password: staff123)
✓ Clinic settings initialized (edit under Admin > Clinic Settings)
✓ Sample medicines added to inventory (edit or delete anytime under Medicines)
✓ Database initialization complete!
```

### 6. Run the app

```bash
python app.py
```

Visit **http://localhost:5000**.

---

## Default Credentials

| Role  | Username | Password  | Scope |
|-------|----------|-----------|-------|
| Admin | `admin`  | `admin123`| Full access: all patients, user management, clinic settings |
| Staff | `staff`  | `staff123`| Their own patients only: add, view, edit, print, history |

> ⚠️ **Change both passwords before any real deployment.** Sign in as `admin`, go to **Users**, and either reset credentials via a new account or rotate the password directly in the database. Consider removing the demo-credentials box on the login page (`templates/login.html`) once you do.

---

## Using the App

### As Staff

1. Sign in with your credentials.
2. **Add Patient** — fill in name, age, diagnosis, symptoms, and address.
3. In the **Medication & Dosage** table, click **+ Add Medicine** for each drug: start typing a name to pull it from inventory (autocomplete), then set dose, frequency, timing, duration, quantity, and instructions per row. You can still type a medicine that isn't stocked — it prints fine, it just won't be linked to inventory or deduct stock.
4. From a patient's record: **Generate PDF** to print/download the prescription (this also deducts the prescribed quantities from inventory), **Edit** to update details or the medication list, or **History** to see every past prescription with its full medication table.
5. Use the search bar and condition filter on the **Patients** page to find a record quickly.

### As Admin

Everything staff can do, plus:

- **Medicines** — manage the inventory: add/edit medicines (name, generic/brand name, category, strength, manufacturer, price, stock, low-stock threshold, expiry), search and filter by category/manufacturer/stock status.
- **Patients** page shows records from every staff member, with an "Added by" column.
- **Users** — create new staff/admin accounts, deactivate accounts that should no longer log in.
- **Clinic Settings** — update the clinic name, tagline, address, phone, email, and registration number shown on every prescription PDF.
- **Delete** any patient record.

---

## Project Structure

```
Prescription/
├── app.py                    # Routes, auth, PDF generation, inventory logic
├── models.py                 # SQLAlchemy models: User, Patient, Medicine,
│                              #   PatientMedication, Prescription, PrescriptionItem, ClinicSettings
├── init_db.py                # Creates tables + seeds default users, clinic settings, sample medicines
├── requirements.txt
├── .env.example
├── static/
│   └── css/style.css         # Design system (tokens, layout, components)
└── templates/
    ├── base.html              # Shell + sidebar nav
    ├── _flashes.html
    ├── login.html
    ├── dashboard.html         # Patient list, search, filters
    ├── patient_form.html      # Shared add/edit form with medication line-item table
    ├── view_patient.html
    ├── history.html           # Past prescriptions, each with its own medication table
    ├── medicines_dashboard.html  # Inventory list, search, category/manufacturer/stock filters
    ├── medicine_form.html        # Tabbed add/edit medicine form
    ├── users.html
    ├── settings.html
    └── error.html
```

---

## Prescription PDF

Each generated PDF includes:

- Clinic letterhead — name, tagline, address, phone/email, registration number (all editable from **Clinic Settings**)
- Patient name, age, gender, phone, and date
- Diagnosis and symptoms
- A full **Rx** medication table — Medicine, Dose, Frequency, Timing, Duration, Qty, Instructions — one row per item added on the patient form
- A signature line for the attending physician
- A generation timestamp footer

Every time a PDF is generated:
1. The patient's current medication list is snapshotted into a new prescription history record (so later edits or inventory changes never alter past prescriptions).
2. Stock is deducted for any line linked to an inventory medicine, and you're notified if that pushes something into Low or Out of Stock.

---

## Configuration

### Change clinic details

No code changes needed — sign in as an admin and go to **Clinic Settings**. This updates the `ClinicSettings` row in the database and is reflected immediately on the next PDF generated.

### Change the secret key

Set `SECRET_KEY` in `.env` (loaded via `os.environ` in `app.py`). Never commit a real secret key to version control.

### Switching to PostgreSQL

1. Install a driver: `pip install psycopg2-binary`
2. Set `DATABASE_URL` in `.env`:
   ```
   DATABASE_URL=postgresql://username:password@localhost:5432/clinic_db
   ```
3. Create the database and user in PostgreSQL, then run `python init_db.py` again.

### Change the port

```bash
python -c "from app import app; app.run(debug=True, port=5001)"
```
or edit the `app.run(...)` call at the bottom of `app.py`.

---

## Security Checklist Before Going Live

- [ ] Set a strong, unique `SECRET_KEY`
- [ ] Change or remove the default `admin` / `staff` accounts
- [ ] Remove the demo-credentials hint on the login page
- [ ] Set `debug=False` in `app.py`
- [ ] Serve over HTTPS (e.g. behind Nginx or a managed platform)
- [ ] Move to PostgreSQL (or another managed DB) for anything beyond single-machine use
- [ ] Back up the database on a schedule

---

## Troubleshooting

**Port already in use** — change the port as described above, or stop whatever else is using 5000.

**Database errors after changing models** — this project doesn't include migrations yet (see Roadmap). Delete `clinic.db` and re-run `python init_db.py` in development. For production data, use a migration tool such as Flask-Migrate instead of deleting the database.

**Upgrading from an earlier copy of this project (pre-inventory)** — the schema changed: the free-text `medication` field was replaced with structured `Medicine` / `PatientMedication` / `PrescriptionItem` tables. There's no migration for this yet, so delete your existing `clinic.db` and run `python init_db.py` again; any previously entered patients/prescriptions will need to be re-entered.

**`ModuleNotFoundError`** — confirm your virtual environment is active, then re-run `pip install -r requirements.txt`.

---

## Roadmap

- [ ] Schema migrations (Flask-Migrate/Alembic) instead of destructive re-init
- [ ] Purchase orders / stock receiving (increase stock, not just deduct on dispense)
- [ ] Expiry-date alerts on the Medicines dashboard
- [ ] Multi-clinic / multi-location support
- [ ] Appointment scheduling
- [ ] Export patient list and inventory to CSV/Excel
- [ ] Password reset flow (self-service, not admin-driven)
- [ ] SMS/email reminders
- [ ] Digital signature capture

---

## License

Provided as-is for educational and commercial use.

**Version**: 3.0.0
**Last updated**: July 12, 2026
