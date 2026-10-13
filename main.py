import tkinter as tk
from tkinter import messagebox, filedialog
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
selected_resume_path = None
resume_label = None

search_box = None
results = None
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
            INSERT INTO users (username, password, first_name, last_name, email, phone, resume_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
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

    cursor.execute(
        """
        SELECT username, first_name, last_name, email, phone, resume_path
        FROM users WHERE username = ?
        """,
        (current_username,)
    )
    user_info = cursor.fetchone()

    if not user_info:
        messagebox.showerror("Error", "User details not found.")
        open_main_app(current_username)
        return

    username, first_name, last_name, email, phone, resume_path = user_info

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

    description = search_box.get().strip()

    if not description:

        results.delete(
            "1.0",
            tk.END
        )

        results.insert(
            tk.END,
            "Please enter a job description."
        )

        return

    search_button.config(
        state="disabled"
    )

    results.delete(
        "1.0",
        tk.END
    )

    results.insert(
        tk.END,
        "Searching for jobs...\n\n"
    )

    thread = threading.Thread(
        target=search_jobs_api,
        args=(description,),
        daemon=True
    )

    thread.start()


# ============================================================
# ADZUNA API SEARCH
# ============================================================

def search_jobs_api(description):

    api_url = (
        "https://api.adzuna.com/v1/api/jobs/us/search/1"
    )

    params = {

        "app_id": APP_ID,

        "app_key": APP_KEY,

        "what": description,

        "results_per_page": 5
    }

    request_url = (
        f"{api_url}?{urlencode(params)}"
    )

    try:

        with urlopen(
            request_url,
            timeout=8
        ) as response:

            data = json.load(response)

        root.after(
            0,
            lambda: display_search_results(data)
        )

    except HTTPError as e:

        root.after(
            0,
            lambda: show_search_error(
                f"API Error: {e.code}"
            )
        )

    except URLError as e:

        root.after(
            0,
            lambda: show_search_error(
                f"Connection Error:\n\n{e.reason}"
            )
        )

    except Exception as e:

        root.after(
            0,
            lambda: show_search_error(
                f"Unexpected Error:\n\n{e}"
            )
        )


# ============================================================
# DISPLAY SEARCH RESULTS
# ============================================================

def display_search_results(data):

    results.delete(
        "1.0",
        tk.END
    )

    jobs = data.get(
        "results",
        []
    )

    if not jobs:

        results.insert(
            tk.END,
            "No jobs found for that search."
        )

        search_button.config(
            state="normal"
        )

        return

    for job in jobs:

        title = job.get(
            "title",
            "No title"
        )

        company = job.get(
            "company",
            {}
        ).get(
            "display_name",
            "Unknown company"
        )

        location = job.get(
            "location",
            {}
        ).get(
            "display_name",
            "Unknown location"
        )

        job_url = job.get(
            "redirect_url"
        )

        results.insert(
            tk.END,
            f"{title}\n"
            f"Company: {company}\n"
            f"Location: {location}\n"
        )

        if job_url:

            apply_start = results.index(
                tk.END
            )

            results.insert(
                tk.END,
                "Apply Here\n"
            )

            apply_end = results.index(
                tk.END
            )

            apply_tag = (
                f"apply_{job.get('id', title)}"
            )

            results.tag_add(
                apply_tag,
                apply_start,
                apply_end
            )

            results.tag_config(
                apply_tag,
                foreground="blue",
                underline=True
            )

            results.tag_bind(
                apply_tag,
                "<Button-1>",
                lambda event, url=job_url:
                    webbrowser.open(url)
            )

        results.insert(
            tk.END,
            f"Job ID: {job.get('id', 'N/A')}\n"
        )

        results.insert(
            tk.END,
            "-" * 60 + "\n\n"
        )

    search_button.config(
        state="normal"
    )

    show_add_job_buttons(jobs)


# ============================================================
# ADD JOB BUTTONS
# ============================================================

def show_add_job_buttons(jobs):

    clear_window()
    root.title("Add Jobs to Dashboard")
    
    header = tk.Frame(root)
    header.pack(fill="x", padx=10, pady=(10, 0))

    tk.Button(
        header,
        text="Back to Search",
        command=lambda: open_main_app(current_username)
    ).pack(side="left")

    tk.Label(
        root,
        text="Add Jobs to Dashboard",
        font=("Arial", 16, "bold")
    ).pack(pady=10)

    if not jobs:
        tk.Label(root, text="No jobs to display.").pack(pady=10)
        return

    container = tk.Frame(root)
    container.pack(fill="both", expand=True, padx=10, pady=5)

    canvas = tk.Canvas(container)
    scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda event: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    for job in jobs:
        frame = tk.Frame(
            scrollable_frame,
            bd=1,
            relief="solid",
            padx=10,
            pady=8
        )
        frame.pack(fill="x", padx=5, pady=4)

        title = job.get("title", "No title")
        company = job.get("company", {}).get("display_name", "Unknown company")

        tk.Label(
            frame,
            text=f"{title}\n{company}",
            font=("Arial", 11, "bold"),
            wraplength=400,
            justify="left"
        ).pack(side="left", fill="x", expand=True)

        tk.Button(
            frame,
            text="Add",
            command=lambda j=job: add_job(j)
        ).pack(side="right", padx=(8, 0))
        
        
# ============================================================
# SEARCH ERROR
# ============================================================

def show_search_error(message):

    results.delete(
        "1.0",
        tk.END
    )

    results.insert(
        tk.END,
        message
    )

    search_button.config(
        state="normal"
    )


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
# MAIN JOBTRAC APPLICATION
# ============================================================

def open_main_app(username):

    global search_box, results, search_button
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

    tk.Button(
        header,
        text="Account",
        command=show_account_info
    ).pack(
        side="right",
        padx=5
    )

    tk.Button(
        header,
        text="Dashboard",
        command=open_dashboard
    ).pack(
        side="right",
        padx=5
    )

    tk.Button(
        header,
        text="Logout",
        command=logout
    ).pack(
        side="right",
        padx=20
    )

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

    results_frame = tk.Frame(
        root
    )

    results_frame.pack(
        fill="both",
        expand=True,
        padx=20,
        pady=10
    )

    scrollbar = tk.Scrollbar(
        results_frame
    )

    scrollbar.pack(
        side="right",
        fill="y"
    )

    results = tk.Text(
        results_frame,
        width=90,
        height=20,
        wrap="word",
        yscrollcommand=scrollbar.set
    )

    results.pack(
        side="left",
        fill="both",
        expand=True
    )

    scrollbar.config(
        command=results.yview
    )


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
