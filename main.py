import tkinter as tk
from tkinter import messagebox
import sqlite3
import json
import webbrowser
import threading
from pathlib import Path

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


# ============================================================
# DATABASE
# ============================================================

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password TEXT NOT NULL
)
""")

conn.commit()


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
# REGISTER
# ============================================================

def register():

    username = username_entry.get().strip()
    password = password_entry.get()

    if username == "" or password == "":

        messagebox.showerror(
            "Error",
            "Please enter a username and password."
        )

        return

    try:

        cursor.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, password)
        )

        conn.commit()

        messagebox.showinfo(
            "Success",
            "Account created successfully!"
        )

        username_entry.delete(0, tk.END)
        password_entry.delete(0, tk.END)

    except sqlite3.IntegrityError:

        messagebox.showerror(
            "Error",
            "Username already exists."
        )


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
        # Fall back to the application URL/title when an API result has no ID.
        job_id = f"{job.get("title", "job")}|{job.get("redirect_url", "")}"

    # Prevent duplicate jobs
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

    # Disable search button
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

    # Run API request in background
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

        # Send results back to Tkinter
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

        # Job information

        results.insert(
            tk.END,
            f"{title}\n"
            f"Company: {company}\n"
            f"Location: {location}\n"
        )

        # Apply link

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

        # Add job button can't be placed inside Text,
        # so we use a keyboard-friendly ID below.

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

    # Show add-job window
    show_add_job_buttons(jobs)


# ============================================================
# ADD JOB BUTTONS
# ============================================================

def show_add_job_buttons(jobs):

    # Create a window containing Add buttons

    add_window = tk.Toplevel(root)

    add_window.title(
        "Add Jobs to Dashboard"
    )

    add_window.geometry(
        "600x500"
    )

    tk.Label(
        add_window,
        text="Add Jobs to Dashboard",
        font=("Arial", 16, "bold")
    ).pack(
        pady=10
    )

    for job in jobs:

        frame = tk.Frame(
            add_window,
            bd=1,
            relief="solid",
            padx=10,
            pady=8
        )

        frame.pack(
            fill="x",
            padx=10,
            pady=4
        )

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

        tk.Label(
            frame,
            text=title,
            font=("Arial", 11, "bold"),
            wraplength=400
        ).pack(
            side="left"
        )

        tk.Button(
            frame,
            text="Add",
            command=lambda j=job:
                add_job(j)
        ).pack(
            side="right"
        )


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

    # Refresh dashboard in the same window
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

    # Refresh dashboard in the same window
    open_dashboard()


# ============================================================
# OPEN DASHBOARD
# ============================================================



def open_dashboard():

    global search_box, results, search_button

    # Clear the current screen instead of opening a new window
    clear_window()

    # Header
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

    # Back button
    tk.Button(
        header,
        text="Back to Search",
        command=lambda: open_main_app(current_username)
    ).pack(side="right", padx=20)

    # Dashboard title
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

    # Scrollable area
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

    # Display saved jobs
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

    # Header

    header = tk.Frame(
        root,
        bg="#000000",
        height=70
    )

    header.pack(
        fill="x"
    )

    # JobTrac Logo
    # Put your logo PNG in the same folder as this Python file
    # and name it "logo.png".
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

        # Keep a reference so Tkinter does not remove the image
        logo_label.image = logo_image

        logo_label.pack(
            side="left",
            padx=20,
            pady=10
        )

    except tk.TclError:
        # If logo.png is missing, use text instead
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

    # Welcome

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

    # Search question

    tk.Label(
        root,
        text="What type of job are you looking for?",
        font=("Arial", 12)
    ).pack(
        pady=5
    )

    # Search box

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

    # Search button

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

    # Results area

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

    # Title

    tk.Label(
        root,
        text="JobTrac",
        font=("Arial", 30, "bold"),
        fg="#1f4e79"
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

    # Username

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

    # Password

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

    # Login

    tk.Button(
        login_frame,
        text="Login",
        command=login,
        width=20,
        bg="#1f4e79",
        fg="white",
        font=("Arial", 11, "bold")
    ).pack(
        pady=(15, 5)
    )

    # Register

    tk.Button(
        login_frame,
        text="Register",
        command=register,
        width=20,
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


# Run the application
root.mainloop()
