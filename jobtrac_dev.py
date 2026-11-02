import tkinter as tk
from tkinter import messagebox, filedialog, OptionMenu, ttk
import sqlite3
import json
import webbrowser
import threading
import os
import sys
import subprocess
from pathlib import Path
import shutil
import calendar
import math
import re
from datetime import date, datetime

from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError


# ============================================================
# CONFIGURATION
# ============================================================

# Credentials are loaded from a private api_config.json in the existing project.
# Do not place API keys in a file that will be committed to GitHub.
RESULTS_PER_SOURCE = 10


def load_api_config():
    path = Path(__file__).resolve().parent / "api_config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid api_config.json: " + str(exc)) from exc


def request_json(url, headers=None):
    request = Request(url, headers=headers or {"User-Agent": "JobTrac-Capstone/1.0"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "users.db"
JOBS_FILE = BASE_DIR / "jobs.json"
RESUME_DIR = BASE_DIR / "resumes"
RESUME_DIR.mkdir(exist_ok=True)


# ============================================================
# DATABASE SETUP & MIGRATION
# ============================================================

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    phone TEXT,
    location TEXT,
    resume_path TEXT
)
""")
conn.commit()

# Ensure older databases get any missing columns via migration
existing_columns = [col[1] for col in cursor.execute("PRAGMA table_info(users)").fetchall()]
for col_name, col_type in [
    ("first_name", "TEXT"),
    ("last_name", "TEXT"),
    ("email", "TEXT"),
    ("phone", "TEXT"),
    ("location", "TEXT"),
    ("resume_path", "TEXT")
]:
    if col_name not in existing_columns:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass


# ============================================================
# MAIN WINDOW
# ============================================================

root = tk.Tk()

root.title("JobTrac")
root.geometry("800x650")


# ============================================================
# GLOBAL VARIABLES
# ============================================================

username_entry = None
password_entry = None

# Registration entries
reg_username_entry = None
reg_password_entry = None
reg_first_name_entry = None
reg_last_name_entry = None
reg_email_entry = None
reg_phone_entry = None
reg_location_entry = None
selected_resume_path = None
resume_label = None

search_box = None
search_zip_entry = None
zip_mode_var = None
results = None  # Legacy Text widget reference; no longer used for search cards
results_container = None
search_button = None
current_username = ""


# ============================================================
# CLEAR WINDOW
# ============================================================

def clear_window():

    for widget in root.winfo_children():
        widget.destroy()


# ============================================================
# BROWSE RESUME
# ============================================================

def browse_resume():
    global selected_resume_path, resume_label
    file_path = filedialog.askopenfilename(
        title="Select Resume",
        filetypes=[
            ("PDF Documents", "*.pdf"),
            ("Word Documents", "*.docx"),
            ("All Files", "*.*")
        ]
    )
    if file_path:
        selected_resume_path = file_path
        filename = Path(file_path).name
        if resume_label:
            resume_label.config(text=f"Selected: {filename}", fg="green")


# ============================================================
# REGISTER USER
# ============================================================

def register_user():
    global selected_resume_path

    username = reg_username_entry.get().strip()
    password = reg_password_entry.get()
    first_name = reg_first_name_entry.get().strip()
    last_name = reg_last_name_entry.get().strip()
    email = reg_email_entry.get().strip()
    phone = reg_phone_entry.get().strip()
    location = reg_location_entry.get().strip()

    if not username or not password:
        messagebox.showerror("Error", "Username and password are required.")
        return

    stored_resume_path = ""
    if selected_resume_path and Path(selected_resume_path).exists():
        try:
            dest_path = RESUME_DIR / f"{username}_{Path(selected_resume_path).name}"
            shutil.copy(selected_resume_path, dest_path)
            stored_resume_path = str(dest_path)
        except Exception as e:
            messagebox.showwarning("Warning", f"Could not save resume file: {e}")

    try:
        cursor.execute(
            """
            INSERT INTO users (username, password, first_name, last_name, email, phone, location, resume_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (username, password, first_name, last_name, email, phone, location, stored_resume_path)
        )
        conn.commit()

        messagebox.showinfo("Success", "Account created successfully!")
        show_login_screen()

    except sqlite3.IntegrityError:
        messagebox.showerror("Error", "Username already exists.")
    except sqlite3.Error as exc:
        messagebox.showerror("Registration error", str(exc))


# ============================================================
# SHOW REGISTER SCREEN
# ============================================================

def show_register_screen():
    global reg_username_entry, reg_password_entry
    global reg_first_name_entry, reg_last_name_entry
    global reg_email_entry, reg_phone_entry
    global reg_location_entry
    global selected_resume_path, resume_label

    clear_window()
    selected_resume_path = None

    # Header / Back
    header = tk.Frame(root, height=50)
    header.pack(fill="x", padx=10, pady=10)

    tk.Button(
        header,
        text="Back to Login",
        command=show_login_screen
    ).pack(side="left")

    tk.Label(
        root,
        text="Create JobTrac Account",
        font=("Arial", 22, "bold"),
        fg="#000000"
    ).pack(pady=(0, 10))

    # Scrollable form container
    container = tk.Frame(root)
    container.pack(fill="both", expand=True, padx=20, pady=5)

    canvas = tk.Canvas(container)
    scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
    form_frame = tk.Frame(canvas)

    form_frame.bind(
        "<Configure>",
        lambda event: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas.create_window((0, 0), window=form_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def add_field(label_text, is_password=False):
        tk.Label(form_frame, text=label_text, font=("Arial", 11)).pack(anchor="w", pady=(5, 2))
        entry = tk.Entry(form_frame, width=40, font=("Arial", 11), show="*" if is_password else "")
        entry.pack(anchor="w", pady=2)
        return entry

    reg_first_name_entry = add_field("First Name")
    reg_last_name_entry = add_field("Last Name")
    reg_email_entry = add_field("Email Address")
    reg_phone_entry = add_field("Phone Number")
    reg_location_entry = add_field("Location (City, State, Country)")
    reg_username_entry = add_field("Username *")
    reg_password_entry = add_field("Password *", is_password=True)

    # Resume upload section
    tk.Label(form_frame, text="Resume Upload (PDF / DOCX)", font=("Arial", 11)).pack(anchor="w", pady=(10, 2))
    resume_btn_frame = tk.Frame(form_frame)
    resume_btn_frame.pack(anchor="w", pady=2)

    tk.Button(
        resume_btn_frame,
        text="Browse Resume...",
        command=browse_resume
    ).pack(side="left")

    resume_label = tk.Label(resume_btn_frame, text="No file selected", fg="gray", font=("Arial", 10))
    resume_label.pack(side="left", padx=10)

    # Submit Register Button
    tk.Button(
        form_frame,
        text="Register Account",
        command=register_user,
        width=25,
        bg="#000000",
        fg="white",
        font=("Arial", 11, "bold")
    ).pack(anchor="w", pady=(20, 20))


# ============================================================
# ACCOUNT INFORMATION VIEW
# ============================================================



def open_file_externally(file_path):
    if not file_path or not Path(file_path).exists():
        messagebox.showerror("Error", "Resume file does not exist on disk.")
        return
    
    try:
        if sys.platform == "win32":
            os.startfile(file_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", file_path], check=True)
        else:
            subprocess.run(["xdg-open", file_path], check=True)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to open file: {e}")



def edit_account_info(username):
    global current_username

    clear_window()
    root.title("Edit JobTrac Account")

    # Get the current account information, including password
    cursor.execute(
        """
        SELECT username, password, first_name, last_name,
               email, phone, location, resume_path
        FROM users
        WHERE username = ?
        """,
        (username,)
    )
    user_info = cursor.fetchone()

    if not user_info:
        messagebox.showerror("Error", "User details not found.")
        open_main_app(current_username)
        return

    (
        old_username, old_password, first_name, last_name,
        email, phone, location, resume_path
    ) = user_info

    # Track a newly selected resume without replacing the old one yet
    new_resume_path = {"path": None}

    # Header
    header = tk.Frame(root, bg="#000000", height=70)
    header.pack(fill="x")

    tk.Label(
        header,
        text="Edit Account Information",
        font=("Arial", 19, "bold"),
        bg="#000000",
        fg="white"
    ).pack(side="left", padx=20, pady=15)

    tk.Button(
        header,
        text="Back to Account",
        command=show_account_info
    ).pack(side="right", padx=15)

    # Form
    form = tk.LabelFrame(
        root,
        text=" Update Your Details ",
        font=("Arial", 13, "bold"),
        padx=25,
        pady=20
    )
    form.pack(fill="both", expand=True, padx=35, pady=20)

    def add_field(label_text, value="", show=None):
        tk.Label(
            form,
            text=label_text,
            font=("Arial", 10, "bold")
        ).pack(anchor="w", pady=(7, 2))

        entry = tk.Entry(
            form,
            width=40,
            font=("Arial", 11),
            show=show or ""
        )
        entry.pack(anchor="w", pady=(0, 3))
        entry.insert(0, value or "")
        return entry

    username_entry = add_field("Username *", old_username)
    first_name_entry = add_field("First Name", first_name)
    last_name_entry = add_field("Last Name", last_name)
    email_entry = add_field("Email Address", email)
    phone_entry = add_field("Phone Number", phone)
    location_entry = add_field("Location (City, State, Country)", location)      
    password_entry = add_field(
        "New Password (leave blank to keep current password)",
        show="*"
    )

    # Resume upload
    tk.Label(
        form,
        text="Resume",
        font=("Arial", 10, "bold")
    ).pack(anchor="w", pady=(12, 2))

    resume_name_label = tk.Label(
        form,
        text=(
            Path(resume_path).name
            if resume_path and Path(resume_path).exists()
            else "No resume uploaded"
        ),
        fg="green" if resume_path and Path(resume_path).exists()
        else "gray"
    )
    resume_name_label.pack(anchor="w", pady=3)

    def select_new_resume():
        file_path = filedialog.askopenfilename(
            title="Select New Resume",
            filetypes=[
                ("PDF Documents", "*.pdf"),
                ("Word Documents", "*.docx"),
                ("All Files", "*.*")
            ]
        )

        if file_path:
            new_resume_path["path"] = file_path
            resume_name_label.config(
                text=f"New resume: {Path(file_path).name}",
                fg="green"
            )

    tk.Button(
        form,
        text="Upload New Resume",
        command=select_new_resume
    ).pack(anchor="w", pady=5)

    def save_account_changes():
        global current_username

        updated_username = username_entry.get().strip()
        updated_first_name = first_name_entry.get().strip()
        updated_last_name = last_name_entry.get().strip()
        updated_email = email_entry.get().strip()
        updated_phone = phone_entry.get().strip()
        updated_location = location_entry.get().strip()
        new_password = password_entry.get()

        if not updated_username:
            messagebox.showerror(
                "Error",
                "Username is required."
            )
            return

        # Check whether another account already uses this username
        cursor.execute(
            "SELECT username FROM users WHERE username = ?",
            (updated_username,)
        )
        existing_user = cursor.fetchone()

        if existing_user and updated_username != old_username:
            messagebox.showerror(
                "Error",
                "That username is already taken."
            )
            return

        # Keep the existing password unless a new one is provided
        updated_password = new_password if new_password else old_password

        # Keep the existing resume unless a new one is selected
        updated_resume_path = resume_path or ""

        if new_resume_path["path"]:
            source_path = Path(new_resume_path["path"])

            try:
                RESUME_DIR.mkdir(parents=True, exist_ok=True)

                # Use a distinct filename for the updated resume
                destination = RESUME_DIR / (
                    f"{updated_username}_{source_path.name}"
                )

                shutil.copy2(source_path, destination)
                updated_resume_path = str(destination)

            except OSError as error:
                messagebox.showerror(
                    "Resume Error",
                    f"Could not save the new resume:\n{error}"
                )
                return

        try:
            cursor.execute(
                """
                UPDATE users
                SET username = ?,
                    password = ?,
                    first_name = ?,
                    last_name = ?,
                    email = ?,
                    phone = ?,
                    location = ?,
                    resume_path = ?
                WHERE username = ?
                """,
                (
                    updated_username,
                    updated_password,
                    updated_first_name,
                    updated_last_name,
                    updated_email,
                    updated_phone,
                    updated_location,
                    updated_resume_path,
                    old_username
                )
            )
            conn.commit()

            # Update the active session if the username changed
            current_username = updated_username

            messagebox.showinfo(
                "Success",
                "Your account information has been updated!"
            )

            show_account_info()

        except sqlite3.Error as error:
            conn.rollback()
            messagebox.showerror(
                "Database Error",
                f"Could not update your account:\n{error}"
            )

    # Action buttons
    button_frame = tk.Frame(form)
    button_frame.pack(anchor="w", pady=18)

    tk.Button(
        button_frame,
        text="Save Changes",
        command=save_account_changes,
        bg="#000000",
        fg="white",
        font=("Arial", 11, "bold"),
        padx=12,
        pady=5
    ).pack(side="left", padx=(0, 10))

    tk.Button(
        button_frame,
        text="Cancel",
        command=show_account_info,
        padx=12,
        pady=5
    ).pack(side="left")

    

def show_account_info():
    clear_window()
    
    

    # Header navigation
    header = tk.Frame(root, bg="#000000", height=70)
    header.pack(fill="x")

    tk.Label(
        header,
        text="Account Profile",
        font=("Arial", 20, "bold"),
        bg="#000000",
        fg="white"
    ).pack(side="left", padx=20, pady=15)

    tk.Button(
        header,
        text="Back to Search",
        command=lambda: open_main_app(current_username)
    ).pack(side="right", padx=10)

    tk.Button(
        header,
        text="Dashboard",
        command=open_dashboard
    ).pack(side="right", padx=5)
    
    tk.Button(
            header,
            text="Edit Account",
            command=lambda: edit_account_info(current_username)
        ).pack(side="right", padx=5)

    cursor.execute(
        """
        SELECT username, first_name, last_name, email, phone, location, resume_path
        FROM users WHERE username = ?
        """,
        (current_username,)
    )
    user_info = cursor.fetchone()

    if not user_info:
        messagebox.showerror("Error", "User details not found.")
        open_main_app(current_username)
        return

    username, first_name, last_name, email, phone, location, resume_path = user_info

    info_card = tk.LabelFrame(
        root,
        text=" Personal Details ",
        font=("Arial", 14, "bold"),
        padx=20,
        pady=20
    )
    info_card.pack(fill="both", expand=True, padx=40, pady=30)

    details = [
        ("Username:", username or "N/A"),
        ("First Name:", first_name or "N/A"),
        ("Last Name:", last_name or "N/A"),
        ("Email Address:", email or "N/A"),
        ("Phone Number:", phone or "N/A"),
        ("Location:", location or "N/A"),
    ]

    for idx, (label, val) in enumerate(details):
        tk.Label(
            info_card,
            text=label,
            font=("Arial", 11, "bold")
        ).grid(row=idx, column=0, sticky="w", pady=6)

        tk.Label(
            info_card,
            text=val,
            font=("Arial", 11)
        ).grid(row=idx, column=1, sticky="w", padx=15, pady=6)

    # Resume section
    resume_row = len(details)
    tk.Label(
        info_card,
        text="Resume File:",
        font=("Arial", 11, "bold")
    ).grid(row=resume_row, column=0, sticky="w", pady=10)

    if resume_path and Path(resume_path).exists():
        file_name = Path(resume_path).name
        res_frame = tk.Frame(info_card)
        res_frame.grid(row=resume_row, column=1, sticky="w", padx=15, pady=10)

        tk.Label(res_frame, text=file_name, font=("Arial", 11), fg="green").pack(side="left")
        tk.Button(
            res_frame,
            text="Open Resume",
            command=lambda p=resume_path: open_file_externally(p)
        ).pack(side="left", padx=10)
    else:
        tk.Label(
            info_card,
            text="No resume uploaded",
            font=("Arial", 11),
            fg="gray"
        ).grid(row=resume_row, column=1, sticky="w", padx=15, pady=10)


# ============================================================
# LOGIN
# ============================================================

def login():

    username = username_entry.get().strip()
    password = password_entry.get()

    if username == "" or password == "":

        messagebox.showerror(
            "Error",
            "Please enter a username and password."
        )

        return

    cursor.execute(
        """
        SELECT * FROM users
        WHERE username = ? AND password = ?
        """,
        (username, password)
    )

    user = cursor.fetchone()

    if user:

        open_main_app(username)

    else:

        messagebox.showerror(
            "Error",
            "Invalid username or password."
        )


# ============================================================
# LOAD JOBS
# ============================================================

def load_jobs():

    try:

        with open(JOBS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    except FileNotFoundError:

        return []


# ============================================================
# SAVE JOBS
# ============================================================

def save_jobs(jobs):

    with open(JOBS_FILE, "w", encoding="utf-8") as file:

        json.dump(
            jobs,
            file,
            indent=4
        )


# ============================================================
# ADD JOB
# ============================================================

def add_job(job):

    jobs = load_jobs()

    job_id = str(job.get("id", "")).strip()

    if not job_id:
        job_id = f"{job.get('title', 'job')}|{job.get('redirect_url', '')}"

    for saved_job in jobs:

        if str(saved_job.get("id", "")) == job_id:

            messagebox.showinfo(
                "JobTrac",
                "This job is already in your dashboard."
            )

            return

    new_job = {

        "id": job_id,

        "title": job.get(
            "title",
            "No title"
        ),

        "company": job.get(
            "company",
            {}
        ).get(
            "display_name",
            "Unknown company"
        ),

        "location": job.get(
            "location",
            {}
        ).get(
            "display_name",
            "Unknown location"
        ),

        "url": job.get(
            "redirect_url",
            ""
        ),

        "status": "Saved",
        "source": job.get("source", "Adzuna"),
        "notes": job.get("notes", "")
    }

    jobs.append(new_job)

    save_jobs(jobs)

    messagebox.showinfo(
        "JobTrac",
        "Job added to your dashboard!"
    )


# ============================================================
# MULTI-SOURCE JOB SEARCH: ADZUNA + THE MUSE + USAJOBS
# ============================================================

def location_zipcodes(record, location_text=""):
    """Use only postcode fields and location labels, not arbitrary job descriptions."""
    codes = set()
    if isinstance(record, dict):
        for field in ("postal_code", "postcode", "postalCode", "zip_code", "zipcode",
                      "zip", "ZipCode", "PostalCode", "Postalcode", "PostCode"):
            value = record.get(field)
            if value is not None:
                codes.update(re.findall(r"(?<!\d)\d{5}(?:-\d{4})?(?!\d)", str(value)))
    if location_text:
        codes.update(re.findall(r"(?<!\d)\d{5}(?:-\d{4})?(?!\d)", str(location_text)))
    return sorted(code[:5] for code in codes)


def location_coordinates(record):
    """Return the coordinates the job provider supplied, if any."""
    if not isinstance(record, dict):
        return []
    lat = record.get("latitude", record.get("Latitude"))
    lon = record.get("longitude", record.get("Longitude"))
    if lat is None or lon is None:
        return []
    try:
        lat, lon = float(lat), float(lon)
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return [(lat, lon)]
    except (TypeError, ValueError):
        pass
    return []


def normalized_job(source, external_id, title, company, location, url,
                   postal_codes=None, coordinates=None):
    """Convert provider records to JobTrac job cards, retaining location evidence."""
    identifier = str(external_id or url or title or "unknown")
    return {
        "id": f"{source.lower().replace(' ', '_')}:{identifier}",
        "title": title or "Untitled job",
        "company": {"display_name": company or "Unknown company"},
        "location": {"display_name": location or "Not specified"},
        "redirect_url": url or "",
        "source": source,
        "_zipcodes": postal_codes or [],
        "_coordinates": coordinates or [],
    }


def zip_center(zipcode):
    """Look up ZIP centroid for a 5-mile search. No third-party Python package."""
    try:
        data = request_json(f"https://api.zippopotam.us/us/{zipcode}")
        first = (data.get("places") or [])[0]
        return (float(first["latitude"]), float(first["longitude"]))
    except (IndexError, KeyError, TypeError, ValueError, HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"Couldn't locate ZIP {zipcode} for a nearby search: {exc}") from exc


def distance_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance using miles (ZIP centroid and provider coordinates)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.7613 * 2 * math.asin(min(1, math.sqrt(a)))


def matches_zip(job, zipcode, mode="Exact ZIP", center=None):
    """Never call a city-wide listing an exact ZIP match without location evidence."""
    if not zipcode:
        return True
    if zipcode in job.get("_zipcodes", []):
        return True
    if mode == "Within 5 miles" and center is not None:
        for lat, lon in job.get("_coordinates", []):
            if distance_miles(center[0], center[1], lat, lon) <= 5:
                return True
    return False


def fetch_adzuna(description, location="", zipcode=""):
    config = load_api_config()
    app_id = str(config.get("adzuna_app_id", "")).strip()
    app_key = str(config.get("adzuna_app_key", "")).strip()
    if not app_id or not app_key or "PASTE_" in app_id or "PASTE_" in app_key:
        raise ValueError("Add your Adzuna app ID and key to api_config.json")
    params = {"app_id": app_id, "app_key": app_key,
              "what": description, "results_per_page": 50 if zipcode else RESULTS_PER_SOURCE}
    if zipcode:
        params["where"] = zipcode
        params["distance"] = 8  # API uses kilometers; ZIP proximity is checked below.
    elif location:
        params["where"] = location
    data = request_json("https://api.adzuna.com/v1/api/jobs/us/search/1?" + urlencode(params))
    jobs = []
    for item in data.get("results", []):
        place = item.get("location") or {}
        label = place.get("display_name", "")
        jobs.append(normalized_job(
            "Adzuna", item.get("id"), item.get("title"),
            (item.get("company") or {}).get("display_name"), label,
            item.get("redirect_url"),
            postal_codes=location_zipcodes(item, label) + location_zipcodes(place),
            coordinates=location_coordinates(item) + location_coordinates(place),
        ))
    return jobs


def muse_category(description):
    """The Muse has category filters, not a free-text job-keyword parameter."""
    q = description.lower()
    if any(x in q for x in ("machine learning", "data scientist", "artificial intelligence")):
        return "Data Science"
    if any(x in q for x in ("analytics", "sql", "data engineer", "data analyst", "database")):
        return "Data and Analytics"
    if any(x in q for x in ("software", "python", "developer", "programmer", "coding")):
        return "Software Engineering"
    if any(x in q for x in ("cyber", "network", "help desk", "information technology", "tech support")):
        return "Computer and IT"
    if "engineer" in q:
        return "Science and Engineering"
    if any(x in q for x in ("teacher", "education")):
        return "Education"
    if "nurs" in q:
        return "Nurses"
    if "marketing" in q:
        return "Marketing"
    if any(x in q for x in ("retail", "cashier")):
        return "Retail"
    if "finance" in q or "account" in q:
        return "Accounting and Finance"
    return None


def fetch_muse(description, location="", zipcode=""):
    category = muse_category(description)
    config = load_api_config()
    api_key = str(config.get("muse_api_key", "")).strip()
    keywords = [word.lower() for word in description.split() if len(word) > 2]
    matching, related, seen = [], [], set()
    # Page size is defined by The Muse; search up to 3 pages and rank titles.
    for page in range(3):
        params = {"page": page}
        if category:
            params["category"] = category
        if api_key:
            params["api_key"] = api_key
        url = "https://www.themuse.com/api/public/jobs?" + urlencode(params)
        try:
            data = request_json(url)
        except Exception:
            if page == 0:
                raise
            break
        records = data.get("results") or []
        if not records:
            break
        for item in records:
            item_id = str(item.get("id") or (item.get("refs") or {}).get("landing_page") or "")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            title = item.get("name") or "Untitled job"
            locations = item.get("locations") or []
            location_text = ", ".join(place.get("name", "") for place in locations
                                      if isinstance(place, dict)) or "Not specified"
            job = normalized_job(
                "The Muse", item_id, title,
                (item.get("company") or {}).get("name"), location_text,
                (item.get("refs") or {}).get("landing_page"),
                postal_codes=location_zipcodes(item, location_text) + [
                    code for place in locations if isinstance(place, dict)
                    for code in location_zipcodes(place, place.get("name", ""))
                ],
                coordinates=[
                    coord for place in locations if isinstance(place, dict)
                    for coord in location_coordinates(place)
                ],
            )
            if keywords and any(word in title.lower() for word in keywords):
                matching.append(job)
            else:
                related.append(job)
        if len(matching) >= RESULTS_PER_SOURCE:
            break
        page_count = data.get("page_count")
        if isinstance(page_count, int) and page + 1 >= page_count:
            break
    # Only include approximate/category results if we recognized a category.
    return (matching + (related if category else []))[:RESULTS_PER_SOURCE]


def fetch_usajobs(description, location="", zipcode=""):
    config = load_api_config()
    email = str(config.get("usajobs_email", "")).strip()
    key = str(config.get("usajobs_key", "")).strip()
    if not email or not key or "PASTE_" in email or "PASTE_" in key:
        raise ValueError("Add your USAJOBS registered email and API key to api_config.json")
    params = {"Keyword": description, "ResultsPerPage": 100 if zipcode else RESULTS_PER_SOURCE, "Page": 1}
    if zipcode:
        params["LocationName"] = zipcode
        params["Radius"] = 5
        params["RemoteIndicator"] = "False"
    url = "https://data.usajobs.gov/api/search?" + urlencode(params)
    data = request_json(url, {
        "Host": "data.usajobs.gov", "User-Agent": email,
        "Authorization-Key": key, "Accept": "application/json",
    })
    jobs = []
    for item in (data.get("SearchResult") or {}).get("SearchResultItems", []):
        fields = item.get("MatchedObjectDescriptor") or {}
        location_rows = fields.get("PositionLocation") or []
        locations = ", ".join(loc.get("LocationName", "") for loc in location_rows
                              if isinstance(loc, dict)) or "Not specified"
        links = fields.get("ApplyURI") or []
        if isinstance(links, str):
            links = [links]
        link = (links[0] if links else "") or fields.get("PositionURI", "")
        jobs.append(normalized_job(
            "USAJOBS", fields.get("PositionID") or item.get("MatchedObjectId") or link,
            fields.get("PositionTitle"),
            fields.get("OrganizationName") or fields.get("DepartmentName"),
            locations, link,
            postal_codes=location_zipcodes(fields, fields.get("PositionLocationDisplay", "")) + [
                code for place in location_rows if isinstance(place, dict)
                for code in location_zipcodes(place, place.get("LocationName", ""))
            ],
            coordinates=[
                coord for place in location_rows if isinstance(place, dict)
                for coord in location_coordinates(place)
            ],
        ))
    return jobs


def search_jobs():
    global search_button
    description = search_box.get().strip()
    zipcode = search_zip_entry.get().strip()
    mode = zip_mode_var.get()
    if not description:
        show_search_error("Please enter a job title or keyword.")
        return
    if zipcode and not re.fullmatch(r"\d{5}", zipcode):
        show_search_error("ZIP code must be exactly 5 digits, such as 77030.")
        return
    try:
        cursor.execute("SELECT location FROM users WHERE username = ?", (current_username,))
        record = cursor.fetchone()
        user_location = (record[0] or "").strip() if record else ""
    except sqlite3.Error as exc:
        messagebox.showerror("Database error", str(exc))
        return
    search_button.config(state="disabled")
    clear_search_results()
    info = f"Searching jobs for {zipcode} ({mode})..." if zipcode else "Searching all 3 job sources..."
    tk.Label(results_container, text=info, anchor="w").pack(fill="x", padx=10, pady=10)
    threading.Thread(target=search_jobs_api,
                     args=(description, user_location, zipcode, mode), daemon=True).start()


def search_jobs_api(description, location="", zipcode="", mode="Exact ZIP"):
    jobs, errors = [], []
    center = None
    if zipcode and mode == "Within 5 miles":
        try:
            center = zip_center(zipcode)
        except ValueError as exc:
            root.after(0, lambda msg=str(exc): show_search_error(msg))
            return
    for name, fetcher in (("Adzuna", fetch_adzuna), ("The Muse", fetch_muse),
                          ("USAJOBS", fetch_usajobs)):
        try:
            matches = [job for job in fetcher(description, location, zipcode)
                       if matches_zip(job, zipcode, mode, center)]
            jobs.extend(matches[:RESULTS_PER_SOURCE])
            if zipcode and not matches:
                errors.append(f"{name}: no verifiable location matches")
        except HTTPError as exc:
            errors.append(f"{name}: HTTP {exc.code}")
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{name}: {exc}")
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    # Only matches with provider ZIP evidence or nearby coordinates are shown.
    root.after(0, lambda j=jobs, e=errors, z=zipcode, m=mode: display_search_results(
        {"results": j, "errors": e, "zipcode": z, "mode": m}))


def clear_search_results():
    if results_container is not None:
        for child in results_container.winfo_children():
            child.destroy()


def display_search_results(data):
    clear_search_results()
    jobs = data.get("results", [])
    errors = data.get("errors", [])
    zipcode = data.get("zipcode", "")
    mode = data.get("mode", "Exact ZIP")
    if zipcode:
        tk.Label(results_container,
                 text=(f"Location: {mode} — {zipcode}. "
                       "Listings without a verifiable ZIP or nearby coordinate are hidden. "
                       "Exact ZIP may return no jobs because APIs often omit postal codes."),
                 wraplength=660, justify="left", anchor="w", fg="#555555").pack(
                     fill="x", padx=5, pady=5)
    if not jobs:
        tk.Label(results_container, text="No jobs returned. Try another search term.",
                 anchor="w").pack(fill="x", padx=10, pady=10)
    else:
        tk.Label(results_container, text=f"Found {len(jobs)} jobs across the available APIs",
                 font=("Arial", 11, "bold"), anchor="w").pack(fill="x", padx=5, pady=5)
    if errors:
        tk.Label(results_container, text="API messages: " + " | ".join(errors),
                 fg="#9A3412", wraplength=650, justify="left", anchor="w").pack(
                     fill="x", padx=5, pady=5)
    for job in jobs:
        box = tk.LabelFrame(results_container, text=job.get("title", "Untitled job"),
                            font=("Arial", 12, "bold"), padx=12, pady=10,
                            bd=2, relief="groove")
        box.pack(fill="x", expand=True, padx=5, pady=5, anchor="n")
        tk.Label(box, text=f"Source: {job.get('source', '')}",
                 fg="#1F4E79", anchor="w").pack(fill="x")
        tk.Label(box, text=f"Company: {(job.get('company') or {}).get('display_name', '')}",
                 anchor="w").pack(fill="x")
        tk.Label(box, text=f"Location: {(job.get('location') or {}).get('display_name', '')}",
                 anchor="w").pack(fill="x")
        controls = tk.Frame(box)
        controls.pack(anchor="w", pady=(6, 0))
        link = job.get("redirect_url") or ""
        if link:
            # Use the same red underlined application link as the original JobTrac.
            apply_link = tk.Label(
                controls, text="Apply Here", fg="red", cursor="hand2",
                font=("Arial", 10, "underline")
            )
            apply_link.pack(side="left", padx=(0, 10))
            apply_link.bind("<Button-1>", lambda event, u=link: webbrowser.open(u))
        tk.Button(controls, text="Add to Dashboard",
                  command=lambda j=job: add_job(j)).pack(side="left", padx=3)
    search_button.config(state="normal")


def show_search_error(message):
    clear_search_results()
    tk.Label(results_container, text=message, anchor="w", wraplength=650).pack(
        fill="x", padx=10, pady=10)
    if search_button is not None:
        search_button.config(state="normal")


# ============================================================
# CHANGE JOB STATUS
# ============================================================

def change_status(job_id, status):

    jobs = load_jobs()

    for job in jobs:
        if str(job.get("id", "")) == job_id:
            job["status"] = status
            break

    save_jobs(jobs)
    open_dashboard()


# ============================================================
# DELETE JOB
# ============================================================

def delete_job(job_id):

    if not messagebox.askyesno(
        "Delete Job",
        "Are you sure you want to delete this job?"
    ):
        return

    jobs = load_jobs()

    jobs = [
        job for job in jobs
        if str(job.get("id", "")) != job_id
    ]

    save_jobs(jobs)
    open_dashboard()


# ============================================================
# DASHBOARD / INTERVIEW CALENDAR
# ============================================================

def open_interview_editor(job_id=None, initial_date=None):
    """Schedule or edit an interview associated with a saved job."""
    jobs = load_jobs()
    if not jobs:
        messagebox.showinfo("JobTrac", "Save a job before scheduling an interview.")
        return
    labels = [f"{index + 1}. {job.get('title', 'Job')} — {job.get('company', '')}"
              for index, job in enumerate(jobs)]
    selected = 0
    for index, job in enumerate(jobs):
        if str(job.get("id")) == str(job_id):
            selected = index
            break
    dialog = tk.Toplevel(root)
    dialog.title("Schedule Interview")
    dialog.geometry("500x375")
    dialog.transient(root)
    dialog.grab_set()
    frame = tk.Frame(dialog, padx=20, pady=15)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="Schedule an interview", font=("Arial", 15, "bold")).pack(anchor="w")
    tk.Label(frame, text="Saved job").pack(anchor="w", pady=(10, 2))
    selected_label = tk.StringVar(value=labels[selected])
    selector = ttk.Combobox(frame, values=labels, textvariable=selected_label, state="readonly", width=56)
    selector.pack(anchor="w", fill="x")
    tk.Label(frame, text="Date (YYYY-MM-DD)").pack(anchor="w", pady=(9, 2))
    date_entry = tk.Entry(frame)
    date_entry.pack(fill="x")
    date_entry.insert(0, jobs[selected].get("interview_date") or initial_date or date.today().isoformat())
    tk.Label(frame, text="Time (24-hour HH:MM)").pack(anchor="w", pady=(9, 2))
    time_entry = tk.Entry(frame)
    time_entry.pack(fill="x")
    time_entry.insert(0, jobs[selected].get("interview_time") or "10:00")
    tk.Label(frame, text="Interview notes (optional)").pack(anchor="w", pady=(9, 2))
    note_entry = tk.Entry(frame)
    note_entry.pack(fill="x")
    note_entry.insert(0, jobs[selected].get("interview_notes") or "")

    def save_interview():
        try:
            choice = labels.index(selected_label.get())
            day = datetime.strptime(date_entry.get().strip(), "%Y-%m-%d").date()
            time_value = datetime.strptime(time_entry.get().strip(), "%H:%M").strftime("%H:%M")
        except ValueError:
            messagebox.showerror("Invalid interview", "Use YYYY-MM-DD for date and HH:MM for time.", parent=dialog)
            return
        updated = jobs[choice]
        updated["interview_date"] = day.isoformat()
        updated["interview_time"] = time_value
        updated["interview_notes"] = note_entry.get().strip()
        save_jobs(jobs)
        dialog.destroy()
        open_dashboard(view="calendar", year=day.year, month=day.month, selected_day=day.day)

    def remove_interview():
        choice = labels.index(selected_label.get())
        updated = jobs[choice]
        updated.pop("interview_date", None)
        updated.pop("interview_time", None)
        updated.pop("interview_notes", None)
        save_jobs(jobs)
        dialog.destroy()
        open_dashboard(view="calendar")

    controls = tk.Frame(frame)
    controls.pack(anchor="w", pady=15)
    tk.Button(controls, text="Save Interview", command=save_interview,
              bg="#111111", fg="white").pack(side="left", padx=(0, 8))
    tk.Button(controls, text="Remove Interview", command=remove_interview).pack(side="left")


def show_interview_calendar(parent, jobs, year=None, month=None, selected_day=None):
    today = date.today()
    year = year or today.year
    month = month or today.month
    selected_day = selected_day or today.day
    dates_with_events = {}
    for job in jobs:
        interview_date = job.get("interview_date")
        if interview_date:
            dates_with_events.setdefault(interview_date, []).append(job)

    nav = tk.Frame(parent)
    nav.pack(fill="x", padx=12, pady=8)
    previous_month = date(year - 1, 12, 1) if month == 1 else date(year, month - 1, 1)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    tk.Button(nav, text="< Previous", command=lambda: open_dashboard(
        view="calendar", year=previous_month.year, month=previous_month.month,
        selected_day=1)).pack(side="left")
    tk.Label(nav, text=f"{calendar.month_name[month]} {year}",
             font=("Arial", 15, "bold")).pack(side="left", expand=True)
    tk.Button(nav, text="Next >", command=lambda: open_dashboard(
        view="calendar", year=next_month.year, month=next_month.month,
        selected_day=1)).pack(side="right")

    calendar_frame = tk.Frame(parent, padx=10, pady=8)
    calendar_frame.pack(fill="x")
    for col, weekday in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
        tk.Label(calendar_frame, text=weekday, font=("Arial", 10, "bold"),
                 width=10).grid(row=0, column=col, sticky="nsew")
        calendar_frame.grid_columnconfigure(col, weight=1)
    for row, week in enumerate(calendar.monthcalendar(year, month), start=1):
        for col, day in enumerate(week):
            if day == 0:
                tk.Label(calendar_frame, text=" ").grid(row=row, column=col, sticky="nsew")
                continue
            day_key = date(year, month, day).isoformat()
            scheduled = day_key in dates_with_events
            selected = day == selected_day
            text_value = f"{day}{' *' if scheduled else ''}"
            button = tk.Button(
                calendar_frame, text=text_value, width=7, height=2,
                bg="#D9EAF7" if scheduled else ("#EEEEEE" if selected else "white"),
                relief="sunken" if selected else "raised",
                command=lambda d=day: open_dashboard(
                    view="calendar", year=year, month=month, selected_day=d),
            )
            button.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
    tk.Label(parent, text="* Interview scheduled", fg="#1F4E79").pack(anchor="w", padx=20)
    selected_date = date(year, month, min(selected_day, calendar.monthrange(year, month)[1]))
    tk.Label(parent, text=f"Interviews for {selected_date.strftime('%B %d, %Y')}",
             font=("Arial", 11, "bold")).pack(anchor="w", padx=20, pady=(12, 4))
    events = dates_with_events.get(selected_date.isoformat(), [])
    if not events:
        tk.Label(parent, text="No interviews scheduled for this day.").pack(anchor="w", padx=20)
    for event in events:
        description = f"{event.get('interview_time', '')} — {event.get('title', 'Job')} at {event.get('company', '')}"
        if event.get("interview_notes"):
            description += f" | {event['interview_notes']}"
        tk.Label(parent, text=description, wraplength=650, justify="left").pack(anchor="w", padx=20)
    tk.Button(parent, text="+ Schedule Interview",
              command=lambda: open_interview_editor(initial_date=selected_date.isoformat()),
              bg="#111111", fg="white").pack(anchor="w", padx=20, pady=12)


def open_dashboard(view="jobs", year=None, month=None, selected_day=None):
    global search_box, results, search_button
    clear_window()
    header = tk.Frame(root, bg="#000000", height=70)
    header.pack(fill="x")
    tk.Label(header, text="JobTrac Dashboard", font=("Arial", 20, "bold"),
             bg="#000000", fg="white").pack(side="left", padx=20, pady=15)
    tk.Button(header, text="Account", command=show_account_info).pack(side="right", padx=5)
    tk.Button(header, text="Back to Search",
              command=lambda: open_main_app(current_username)).pack(side="right", padx=15)
    tk.Label(root, text="My Job Dashboard", font=("Arial", 18, "bold")).pack(pady=(9, 3))
    tabs = tk.Frame(root)
    tabs.pack(anchor="w", padx=20, pady=6)
    tk.Button(tabs, text="Saved Jobs", command=lambda: open_dashboard(view="jobs"),
              bg="#D9EAF7" if view == "jobs" else "white").pack(side="left", padx=3)
    tk.Button(tabs, text="Interview Calendar",
              command=lambda: open_dashboard(view="calendar"),
              bg="#D9EAF7" if view == "calendar" else "white").pack(side="left", padx=3)
    jobs = load_jobs()
    if view == "calendar":
        show_interview_calendar(root, jobs, year=year, month=month, selected_day=selected_day)
        return
    if not jobs:
        tk.Label(root, text="No jobs saved yet. Search or add a job first.").pack(pady=15)
        return
    container = tk.Frame(root)
    container.pack(fill="both", expand=True, padx=10, pady=5)
    canvas = tk.Canvas(container, highlightthickness=0)
    scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
    frame = tk.Frame(canvas)
    frame.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
    window = canvas.create_window((0, 0), window=frame, anchor="nw")
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    for job in jobs:
        job_frame = tk.Frame(frame, bd=1, relief="solid", padx=10, pady=10)
        job_frame.pack(fill="x", padx=10, pady=5)
        tk.Label(job_frame, text=job.get("title", "No title"),
                 font=("Arial", 12, "bold"), wraplength=600).pack(anchor="w")
        tk.Label(job_frame, text=f"Company: {job.get('company', 'Unknown company')}").pack(anchor="w")
        tk.Label(job_frame, text=f"Location: {job.get('location', 'Not specified')}").pack(anchor="w")
        tk.Label(job_frame, text=f"Source: {job.get('source', 'Manual/Existing')}").pack(anchor="w")
        tk.Label(job_frame, text=f"Status: {job.get('status', 'Saved')}",
                 font=("Arial", 10, "bold")).pack(anchor="w")
        tk.Label(job_frame, text=f"Notes: {job.get('notes') or 'No notes added'}",
                 wraplength=600, justify="left").pack(anchor="w")
        if job.get("interview_date"):
            tk.Label(job_frame, text=f"Interview: {job['interview_date']} at {job.get('interview_time', '')}",
                     fg="#1F4E79").pack(anchor="w")
        buttons = tk.Frame(job_frame)
        buttons.pack(anchor="w", pady=5)
        tk.Button(buttons, text="Open Job",
                  command=lambda url=job.get("url", ""): webbrowser.open(url) if url
                  else messagebox.showwarning("JobTrac", "No link available.")).pack(side="left", padx=2)
        tk.Button(buttons, text="Interview",
                  command=lambda jid=str(job.get("id", "")): open_interview_editor(jid)).pack(side="left", padx=2)
        for status in ("Applied", "Interviewing", "Offered", "Denied"):
            tk.Button(buttons, text=status,
                      command=lambda jid=str(job.get("id", "")), s=status: change_status(jid, s)
                      ).pack(side="left", padx=2)
        tk.Button(buttons, text="Delete",
                  command=lambda jid=str(job.get("id", "")): delete_job(jid)).pack(side="left", padx=2)


# ============================================================
# DELETE ACCOUNT
# ============================================================

    


# ============================================================
# Manual Job Entry
# ============================================================

def manual_job_entry():
    clear_window()

    root.title("JobTrac - Manual Job Entry")

    # Header
    header = tk.Frame(root, bg="#000000", height=70)
    header.pack(fill="x")

    tk.Label(
        header,
        text="Add a Job",
        font=("Arial", 20, "bold"),
        bg="#000000",
        fg="white"
    ).pack(side="left", padx=20, pady=15)

    tk.Button(
        header,
        text="Back to Search",
        command=lambda: open_main_app(current_username)
    ).pack(side="right", padx=10)

    tk.Button(
        header,
        text="Dashboard",
        command=open_dashboard
    ).pack(side="right", padx=5)

    # Form container
    form = tk.LabelFrame(
        root,
        text=" Enter Job Details ",
        font=("Arial", 13, "bold"),
        padx=25,
        pady=20
    )
    form.pack(fill="x", padx=40, pady=30)

    # Helper function to create form fields
    def add_field(label_text):
        tk.Label(
            form,
            text=label_text,
            font=("Arial", 11, "bold")
        ).pack(anchor="w", pady=(8, 3))

        entry = tk.Entry(
            form,
            width=45,
            font=("Arial", 11)
        )
        entry.pack(anchor="w", pady=(0, 5))

        return entry

    # Input fields
    job_title_entry = add_field("Job Title *")
    company_entry = add_field("Company *")
    location_entry = add_field("Location")
    url_entry = add_field("Application URL")
    notes_entry = add_field("Notes (optional)")

    def save_manual_job():
        title = job_title_entry.get().strip()
        company = company_entry.get().strip()
        location = location_entry.get().strip()
        url = url_entry.get().strip()
        notes = notes_entry.get().strip()
        

        # Validate required fields
        if not title or not company:
            messagebox.showerror(
                "Missing Information",
                "Please enter both a job title and company."
            )
            return

        # Validate URL if provided
        if url and not url.startswith(("http://", "https://")):
            messagebox.showerror(
                "Invalid URL",
                "The application URL must start with "
                "http:// or https://."
            )
            return

        # Load existing jobs
        jobs = load_jobs()

        # Check for duplicates
        for job in jobs:
            if (
                job.get("title", "").strip().lower() == title.lower()
                and job.get("company", "").strip().lower() == company.lower()
            ):
                messagebox.showwarning(
                    "Duplicate Job",
                    "This job already exists in your dashboard."
                )
                return

        # Create a job in the same format used by the dashboard
        new_job = {
            "id": f"manual_{__import__('uuid').uuid4().hex}",
            "title": title,
            "company": company,
            "location": location or "Not specified",
            "url": url,
            "notes": notes,
            "status": "Saved"
        }

        # Save the job
        try:
            jobs.append(new_job)
            save_jobs(jobs)
        except (OSError, TypeError, ValueError) as error:
            messagebox.showerror(
                "Save Error",
                f"Could not save the job:\n{error}"
            )
            return

        messagebox.showinfo(
            "Success",
            f"{title} at {company} was added to your dashboard!"
        )

        # Open dashboard to display the new job
        open_dashboard()

    # Buttons
    button_frame = tk.Frame(form)
    button_frame.pack(anchor="w", pady=20)

    tk.Button(
        button_frame,
        text="Save Job",
        command=save_manual_job,
        bg="#000000",
        fg="white",
        font=("Arial", 11, "bold"),
        padx=15,
        pady=6
    ).pack(side="left", padx=(0, 10))

    tk.Button(
        button_frame,
        text="Cancel",
        command=lambda: open_main_app(current_username),
        padx=15,
        pady=6
    ).pack(side="left")

    job_title_entry.focus()


# ============================================================
# MAIN JOBTRAC APPLICATION
# ============================================================

def open_main_app(username):

    global search_box, search_zip_entry, zip_mode_var, results, results_container, search_button
    global current_username

    current_username = username

    clear_window()

    header = tk.Frame(
        root,
        bg="#000000",
        height=70
    )

    header.pack(
        fill="x"
    )

    try:
        logo_image = tk.PhotoImage(
            file=BASE_DIR / "logo.png"
        )
        logo_image = logo_image.subsample(5, 5)  
        
        logo_label = tk.Label(
            header,
            image=logo_image,
            bg="#000000",
            width=250,
            height=80
        )

        logo_label.image = logo_image

        logo_label.pack(
            side="left",
            padx=20,
            pady=10
        )

    except tk.TclError:
        tk.Label(
            header,
            text="JobTrac",
            font=("Arial", 26, "bold"),
            bg="#000000",
            fg="white"
        ).pack(
            side="left",
            padx=20,
            pady=15
        )

    
    # Dropdown menu in the top-right corner
    menu_button = tk.Menubutton(
        header,
        text=" Menu ▾",
        bg="#000000",
        fg="white",
        activebackground="#333333",
        activeforeground="white",
        font=("Arial", 11, "bold"),
        relief="flat",
        padx=15,
        pady=10,
        cursor="hand2"
    )

    dropdown = tk.Menu(
        menu_button,
        tearoff=0,
        bg="white",
        fg="black",
        activebackground="#222222",
        activeforeground="white",
        font=("Arial", 11)
    )

    dropdown.add_command(
        label="Account",
        command=show_account_info
    )

    dropdown.add_command(
        label="Dashboard",
        command=open_dashboard
    )
    dropdown.add_command(
        label="Interview Calendar",
        command=lambda: open_dashboard(view="calendar")
    )
    dropdown.add_command(
            label="Manual Job Entry",
            command=manual_job_entry
    )

    dropdown.add_separator()

    dropdown.add_command(
        label="Logout",
        command=logout
    )

    menu_button.config(menu=dropdown)
    menu_button.pack(side="right", padx=20, pady=10)


    tk.Label(
        root,
        text=f"Welcome, {username}!",
        font=("Arial", 20, "bold")
    ).pack(
        pady=(25, 5)
    )

    tk.Label(
        root,
        text="Find your next job with JobTrac",
        font=("Arial", 12)
    ).pack(
        pady=(0, 15)
    )

    tk.Label(
        root,
        text="What type of job are you looking for?",
        font=("Arial", 12)
    ).pack(
        pady=5
    )

    search_box = tk.Entry(
        root,
        width=60,
        font=("Arial", 12)
    )

    search_box.pack(
        pady=5
    )

    # Optional ZIP location filter. Exact mode excludes unverifiable addresses.
    zip_frame = tk.Frame(root)
    zip_frame.pack(pady=(4, 6))
    tk.Label(zip_frame, text="ZIP code (optional):", font=("Arial", 11)).pack(side="left", padx=(0, 6))
    search_zip_entry = tk.Entry(zip_frame, width=9, font=("Arial", 11))
    search_zip_entry.pack(side="left", padx=(0, 10))
    zip_mode_var = tk.StringVar(value="Exact ZIP")
    tk.OptionMenu(zip_frame, zip_mode_var, "Exact ZIP", "Within 5 miles").pack(side="left")
    search_zip_entry.bind("<Return>", lambda event: search_jobs())

    search_box.bind(
        "<Return>",
        lambda event:
            search_jobs()
    )

    search_button = tk.Button(
        root,
        text="Search Jobs",
        command=search_jobs,
        font=("Arial", 11, "bold"),
        bg="#000000",
        fg="white",
        padx=20,
        pady=5
    )

    search_button.pack(
        pady=10
    )

    # Search results area with a vertical scrollbar.
    results_frame = tk.Frame(root)
    results_frame.pack(
        fill="both",
        expand=True,
        padx=20,
        pady=10
    )

    results_canvas = tk.Canvas(
        results_frame,
        highlightthickness=0,
        borderwidth=0
    )
    scrollbar = tk.Scrollbar(
        results_frame,
        orient="vertical",
        command=results_canvas.yview
    )

    # Job cards live in this frame, which is embedded in the canvas.
    results_container = tk.Frame(results_canvas)
    results_container.bind(
        "<Configure>",
        lambda event: results_canvas.configure(
            scrollregion=results_canvas.bbox("all")
        )
    )

    canvas_window = results_canvas.create_window(
        (0, 0),
        window=results_container,
        anchor="nw"
    )

    # Keep the inner frame the same width as the visible canvas.
    results_canvas.bind(
        "<Configure>",
        lambda event: results_canvas.itemconfigure(
            canvas_window,
            width=event.width
        )
    )
    results_canvas.configure(yscrollcommand=scrollbar.set)

    results_canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # Mouse-wheel scrolling for Windows/macOS and Linux.
    def _scroll_results(event):
        if getattr(event, "delta", 0):
            results_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif getattr(event, "num", None) == 4:
            results_canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            results_canvas.yview_scroll(1, "units")

    results_canvas.bind_all("<MouseWheel>", _scroll_results)
    results_canvas.bind_all("<Button-4>", _scroll_results)
    results_canvas.bind_all("<Button-5>", _scroll_results)


# ============================================================
# LOGOUT
# ============================================================

def logout():

    show_login_screen()


# ============================================================
# LOGIN SCREEN
# ============================================================

def show_login_screen():

    global username_entry
    global password_entry

    clear_window()

    tk.Label(
        root,
        text="JobTrac",
        font=("Arial", 30, "bold"),
        fg="#000000"
    ).pack(
        pady=(40, 5)
    )

    tk.Label(
        root,
        text="Login to your account",
        font=("Arial", 16)
    ).pack(
        pady=(0, 25)
    )

    login_frame = tk.Frame(
        root
    )

    login_frame.pack()

    tk.Label(
        login_frame,
        text="Username",
        font=("Arial", 11)
    ).pack(
        pady=(5, 2)
    )

    username_entry = tk.Entry(
        login_frame,
        width=35,
        font=("Arial", 11)
    )

    username_entry.pack(
        pady=5
    )

    tk.Label(
        login_frame,
        text="Password",
        font=("Arial", 11)
    ).pack(
        pady=(10, 2)
    )

    password_entry = tk.Entry(
        login_frame,
        width=35,
        show="*",
        font=("Arial", 11)
    )

    password_entry.pack(
        pady=5
    )

    tk.Button(
        login_frame,
        text="Login",
        command=login,
        width=20,
        bg="#000000",
        fg="white",
        font=("Arial", 11, "bold")
    ).pack(
        pady=(15, 5)
    )

    tk.Button(
        login_frame,
        text="Register",
        command=show_register_screen,
        width=20,
        bg="#000000",
        fg="white",
        font=("Arial", 11)
    ).pack(
        pady=5
    )

    password_entry.bind(
        "<Return>",
        lambda event:
            login()
    )

    username_entry.focus()


# ============================================================
# CLOSE APP
# ============================================================

def close_app():

    conn.close()

    root.destroy()


root.protocol(
    "WM_DELETE_WINDOW",
    close_app
)


# ============================================================
# START
# ============================================================

show_login_screen()

root.mainloop()