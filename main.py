import tkinter as tk
from tkinter import messagebox, filedialog, OptionMenu
import sqlite3
import json
import webbrowser
import threading
import os
import sys
import subprocess
from pathlib import Path
import shutil

from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError, URLError


# ============================================================
# CONFIGURATION
# ============================================================

APP_ID = "7757f192"
APP_KEY = "8a25186bd7572c44b87a3819322588d3"

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
            (username, password, first_name, last_name, email, phone, stored_resume_path)
        )
        conn.commit()

        messagebox.showinfo("Success", "Account created successfully!")
        show_login_screen()

    except sqlite3.IntegrityError:
        messagebox.showerror("Error", "Username already exists.")


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

        "status": "Saved"
    }

    jobs.append(new_job)

    save_jobs(jobs)

    messagebox.showinfo(
        "JobTrac",
        "Job added to your dashboard!"
    )


# ============================================================
# SEARCH JOBS
# ============================================================

def search_jobs():
    """Validate the search and start the API request without blocking Tkinter."""
    global search_button

    description = search_box.get().strip()

    if not description:
        clear_search_results()
        tk.Label(
            results_container,
            text="Please enter a job title or keyword.",
            font=("Arial", 11),
            anchor="w"
        ).pack(fill="x", padx=10, pady=10)
        return

    # Read the signed-in user's location on the main Tkinter thread.
    # SQLite connections normally cannot be used from a worker thread.
    try:
        cursor.execute(
            "SELECT location FROM users WHERE username = ?",
            (current_username,)
        )
        row = cursor.fetchone()
        user_location = (row[0] or "").strip() if row else ""
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not load your location:\n{error}")
        return

    search_button.config(state="disabled")
    clear_search_results()
    tk.Label(
        results_container,
        text="Searching for jobs...\nPlease wait.",
        font=("Arial", 11),
        justify="left",
        anchor="w"
    ).pack(fill="x", padx=10, pady=10)

    # Run the network request in a worker thread so the GUI remains responsive.
    thread = threading.Thread(
        target=search_jobs_api,
        args=(description, user_location),
        daemon=True
    )
    thread.start()


# ============================================================
# ADZUNA API SEARCH
# ============================================================

def search_jobs_api(description, user_location=""):
    """Fetch jobs in a worker thread; update Tkinter only via root.after."""
    api_url = "https://api.adzuna.com/v1/api/jobs/us/search/1"

    params = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
        "what": description,
        "results_per_page": 10,
        "content-type": "application/json"
    }

    # Only send a location filter when the user's profile has one.
    if user_location:
        params["where"] = user_location

    request_url = f"{api_url}?{urlencode(params)}"

    try:
        with urlopen(request_url, timeout=20) as response:
            data = json.load(response)

        root.after(0, lambda result=data: display_search_results(result))

    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        message = f"Adzuna API error ({error.code})."
        if detail:
            message += f"\\n\\n{detail}"
        root.after(0, lambda msg=message: show_search_error(msg))

    except URLError as error:
        message = f"Could not connect to the job search service.\\n\\n{error.reason}"
        root.after(0, lambda msg=message: show_search_error(msg))

    except (TimeoutError, OSError) as error:
        message = f"The job search request failed. Please try again.\\n\\n{error}"
        root.after(0, lambda msg=message: show_search_error(msg))

    except Exception as error:
        message = f"Unexpected job search error: {error}"
        root.after(0, lambda msg=message: show_search_error(msg))


# ============================================================
# DISPLAY SEARCH RESULTS
# ============================================================

def clear_search_results():
    """Remove all result cards/messages from the results area."""
    if results_container is not None:
        for widget in results_container.winfo_children():
            widget.destroy()


def display_search_results(data):
    """Display search results as full-width, scrollable job cards."""
    clear_search_results()
    jobs = data.get("results", []) if isinstance(data, dict) else []

    if not jobs:
        tk.Label(
            results_container,
            text=(
                "No jobs found for that search. Try a different title or keyword, "
                "or update your location in Account."
            ),
            font=("Arial", 11),
            justify="left",
            anchor="w",
            wraplength=650
        ).pack(fill="x", padx=10, pady=10)
        search_button.config(state="normal")
        return

    tk.Label(
        results_container,
        text=f"Found {len(jobs)} job(s).",
        font=("Arial", 11, "bold"),
        anchor="w"
    ).pack(fill="x", padx=5, pady=(2, 8))

    for job in jobs:
        title = job.get("title") or "No title"
        company_data = job.get("company") or {}
        location_data = job.get("location") or {}

        company = company_data.get("display_name") or "Unknown company"
        location = location_data.get("display_name") or "Unknown location"
        job_url = job.get("redirect_url") or ""
        job_id = job.get("id", "N/A")

        # Each card stretches to the full available width of the results area.
        job_box = tk.LabelFrame(
            results_container,
            text=title,
            font=("Arial", 12, "bold"),
            padx=12,
            pady=10,
            bd=2,
            relief="groove"
        )
        job_box.pack(fill="x", expand=True, padx=5, pady=5, anchor="n")

        tk.Label(
            job_box,
            text=f"Company: {company}",
            font=("Arial", 10),
            anchor="w"
        ).pack(fill="x", pady=2)

        tk.Label(
            job_box,
            text=f"Location: {location}",
            font=("Arial", 10),
            anchor="w"
        ).pack(fill="x", pady=2)

        tk.Label(
            job_box,
            text=f"Job ID: {job_id}",
            font=("Arial", 9),
            fg="gray",
            anchor="w"
        ).pack(fill="x", pady=2)

        button_frame = tk.Frame(job_box)
        button_frame.pack(anchor="w", pady=(8, 0))

        if job_url:
            apply_link = tk.Label(
                button_frame,
                text="Apply Here",
                fg="red",
                cursor="hand2",
                font=("Arial", 10, "underline")
            )
            apply_link.pack(side="left", padx=(0, 10))
            apply_link.bind(
                "<Button-1>",
                lambda event, url=job_url: webbrowser.open(url)
            )

        tk.Button(
            button_frame,
            text="Add to Dashboard",
            command=lambda j=job: add_job(j)
        ).pack(side="left")

    search_button.config(state="normal")


# ============================================================
# SEARCH ERROR
# ============================================================

def show_search_error(message):
    clear_search_results()
    tk.Label(
        results_container,
        text=message,
        font=("Arial", 10),
        justify="left",
        anchor="w",
        wraplength=650
    ).pack(fill="x", padx=10, pady=10)
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
# OPEN DASHBOARD
# ============================================================

def open_dashboard():

    global search_box, results, search_button

    clear_window()

    header = tk.Frame(
        root,
        bg="#000000",
        height=70
    )
    header.pack(fill="x")

    tk.Label(
        header,
        text="JobTrac Dashboard",
        font=("Arial", 20, "bold"),
        bg="#000000",
        fg="white"
    ).pack(side="left", padx=20, pady=15)

    tk.Button(
        header,
        text="Account",
        command=show_account_info
    ).pack(side="right", padx=5)

    tk.Button(
        header,
        text="Back to Search",
        command=lambda: open_main_app(current_username)
    ).pack(side="right", padx=20)

    tk.Label(
        root,
        text="My Job Dashboard",
        font=("Arial", 18, "bold")
    ).pack(pady=10)

    jobs = load_jobs()

    if not jobs:
        tk.Label(
            root,
            text="No jobs saved yet.",
            font=("Arial", 12)
        ).pack(pady=20)

        return

    container = tk.Frame(root)
    container.pack(fill="both", expand=True, padx=10, pady=5)

    canvas = tk.Canvas(container)
    scrollbar = tk.Scrollbar(
        container,
        orient="vertical",
        command=canvas.yview
    )

    scrollable_frame = tk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda event: canvas.configure(
            scrollregion=canvas.bbox("all")
        )
    )

    canvas.create_window(
        (0, 0),
        window=scrollable_frame,
        anchor="nw"
    )

    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    for job in jobs:

        job_frame = tk.Frame(
            scrollable_frame,
            bd=1,
            relief="solid",
            padx=10,
            pady=10
        )
        job_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(
            job_frame,
            text=job.get("title", "No title"),
            font=("Arial", 12, "bold"),
            wraplength=600
        ).pack(anchor="w")

        tk.Label(
            job_frame,
            text=f"Company: {job.get('company', 'Unknown company')}"
        ).pack(anchor="w")

        tk.Label(
            job_frame,
            text=f"Location: {job.get('location', 'Unknown location')}"
        ).pack(anchor="w")

        tk.Label(
            job_frame,
            text=f"Status: {job.get('status', 'Saved')}",
            font=("Arial", 10, "bold")
        ).pack(anchor="w", pady=3)

        button_frame = tk.Frame(job_frame)
        button_frame.pack(anchor="w", pady=5)

        tk.Button(
            button_frame,
            text="Open Job",
            command=lambda url=job.get("url", ""):
                webbrowser.open(url) if url else messagebox.showwarning(
                    "JobTrac",
                    "No application link is available."
                )
        ).pack(side="left", padx=3)

        for status in ["Applied", "Interviewing", "Offered", "Denied"]:
            tk.Button(
                button_frame,
                text=status,
                command=lambda job_id=str(job.get("id", "")),
                               new_status=status:
                    change_status(job_id, new_status)
            ).pack(side="left", padx=3)

        tk.Button(
            button_frame,
            text="Delete",
            command=lambda job_id=str(job.get("id", "")):
                delete_job(job_id)
        ).pack(side="left", padx=3)


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

    global search_box, results, results_container, search_button
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
        fg="black",
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
