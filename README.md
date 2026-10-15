# TourMate - ট্যুর হোক সহজ, হিসাব থাকুক নির্ভুল ✈️🎒

**TourMate** is a mobile-first, real-time group tour expense tracking and financial settlement web platform built with Django 5, Django Ninja, Tailwind CSS, Alpine.js, and Neon PostgreSQL.

---

## 🌟 Key Features

1. **Tour & Budget Management**:
   - Create and organize trips with custom titles and budget limits.
   - Real-time remaining balance, total deposits (Credit), and total expenses (Debit) overview.
   - Tour Archive mode: Lock tour calculations once finalized.

2. **Members & Roles**:
   - Invite and manage trip members.
   - Permission Roles: **Owner**, **Editor** (can add/edit expenses and deposits), and **Viewer** (read-only access).
   - Fun trip designations (Chief Organizer, Treasurer, Planner, Head of Catering, Sound Engineer, Navigation Specialist, etc.).

3. **Multi-payer & Individual Share Split**:
   - Common Fund and personal expense payments.
   - Tag all or specific members per expense for fair per-head calculations.
   - Activity audit trail logging all additions, updates, and deletes with actor timestamps.

4. **Settlement & Printable Reports**:
   - Real-time Balance Sheet calculating who is owed a refund (`REFUNDABLE`) vs. who needs to pay (`PAYABLE`).
   - Print-ready individual member ledger statements with itemized deposit and shared expense breakdown.
   - Full Tour Expense Statement and Final Settlement Report with signatures.
   - Built-in popup-safe iframe printing engine.

5. **Authentication & Communications**:
   - Seamless **Sign in with Google** via Google Identity Services (GIS).
   - Instant Demo login option.
   - Email invitation service via Gmail SMTP (toggleable via environment variable).

---

## 🛠️ Tech Stack

- **Backend**: Python 3.12, Django 5.0+, Django Ninja (Fast OpenAPI REST Framework)
- **Database**: PostgreSQL (Neon Cloud Serverless) / SQLite (Development)
- **Frontend**: Vanilla HTML5, Tailwind CSS, Alpine.js, Google Fonts (Hind Siliguri & Plus Jakarta Sans)
- **Auth**: JWT (PyJWT), Google OAuth 2.0 (GIS)
- **Email**: Django SMTP Backend (TLS on port 587)

---

## 🚀 Getting Started

### 1. Clone the repository
```bash
git clone https://github.com/Tanveer1301/tourmate.git
cd tourmate
```

### 2. Create and activate a virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

### 5. Run migrations
```bash
python manage.py migrate
```

### 6. Start development server
```bash
python manage.py runserver 127.0.0.1:8008
```
Visit `http://127.0.0.1:8008` in your browser.

---

## 📄 License
MIT License. Created by Tanveer.
