import tkinter as tk
from tkinter import messagebox
import sqlite3
import json
import webbrowser
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError, URLError


# ============================================================
# CONFIGURATION
# ============================================================

APP_ID = "7757f192"
APP_KEY = "8a25186bd7572c44b87a3819322588d3"


# ============================================================
# DATABASE
# ============================================================

conn = sqlite3.connect("users.db")
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
# CLEAR WINDOW
# ============================================================

def clear_window():
    """Remove everything from the current window."""
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
            "Please enter your username and password."
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
        messagebox.showinfo(
            "Success",
            "Login successful!"
        )

        open_main_app(username)

    else:
        messagebox.showerror(
            "Error",
            "Invalid username or password."
        )


# ============================================================
# JOB SEARCH
# ============================================================

def search_jobs():
    description = search_box.get().strip()

    if not description:
        results.delete("1.0", tk.END)
        results.insert(
            tk.END,
            "Please enter a job description."
        )
        return

    api_url = "https://api.adzuna.com/v1/api/jobs/us/search/1"

    params = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
        "what": description,
        "results_per_page": 10
    }

    request_url = f"{api_url}?{urlencode(params)}"

    results.delete("1.0", tk.END)
    results.insert(
        tk.END,
        "Searching...\n\n"
    )

    try:
        with urlopen(request_url, timeout=15) as response:
            data = json.load(response)

    except HTTPError as e:
        results.delete("1.0", tk.END)

        if e.code == 401:
            results.insert(
                tk.END,
                "401 Unauthorized\n\n"
                "Your Adzuna APP_ID or APP_KEY is invalid."
            )

        elif e.code == 503:
            results.insert(
                tk.END,
                "503 Service Unavailable\n\n"
                "Adzuna's server is temporarily unavailable.\n"
                "Please try again in a few seconds."
            )

        else:
            results.insert(
                tk.END,
                f"API Error: {e.code}\n\n"
                "Please try again later."
            )

        return

    except URLError as e:
        results.delete("1.0", tk.END)

        results.insert(
            tk.END,
            f"Connection Error:\n\n{e.reason}"
        )

        return

    except Exception as e:
        results.delete("1.0", tk.END)

        results.insert(
            tk.END,
            f"Unexpected Error:\n\n{e}"
        )

        return

    results.delete("1.0", tk.END)

    jobs = data.get("results", [])

    if not jobs:
        results.insert(
            tk.END,
            "No jobs found for that search."
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

        # ----------------------------------------------------
        # Job information
        # ----------------------------------------------------

        results.insert(
            tk.END,
            f"{title}\n"
            f"Company: {company}\n"
            f"Location: {location}\n"
        )

        # ----------------------------------------------------
        # Apply Here link
        # ----------------------------------------------------

        if job_url:

            apply_start = results.index(tk.END)

            results.insert(
                tk.END,
                "Apply Here\n"
            )

            apply_end = results.index(tk.END)

            apply_tag = f"apply_{job.get('id', title)}"

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

            # ------------------------------------------------
            # Actual URL
            # ------------------------------------------------

            url_start = results.index(tk.END)

            results.insert(
                tk.END,
                f"{job_url}\n"
            )

            url_end = results.index(tk.END)

            url_tag = f"url_{job.get('id', title)}"

            results.tag_add(
                url_tag,
                url_start,
                url_end
            )

            results.tag_config(
                url_tag,
                foreground="blue",
                underline=True
            )

            results.tag_bind(
                url_tag,
                "<Button-1>",
                lambda event, url=job_url:
                    webbrowser.open(url)
            )

        results.insert(
            tk.END,
            "-" * 60 + "\n\n"
        )


# ============================================================
# LOGOUT
# ============================================================

def logout():
    global username_entry
    global password_entry

    show_login_screen()


# ============================================================
# MAIN JOBTRAC APPLICATION
# ============================================================

def open_main_app(username):

    global search_box
    global results

    clear_window()

    # --------------------------------------------------------
    # Header
    # --------------------------------------------------------

    header = tk.Frame(
        root,
        bg="#1f4e79",
        height=70
    )

    header.pack(
        fill="x"
    )

    tk.Label(
        header,
        text="JobTrac",
        font=("Arial", 26, "bold"),
        bg="#1f4e79",
        fg="white"
    ).pack(
        side="left",
        padx=20,
        pady=15
    )

    tk.Button(
        header,
        text="Logout",
        command=logout
    ).pack(
        side="right",
        padx=20
    )

    # --------------------------------------------------------
    # Welcome message
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Search question
    # --------------------------------------------------------

    tk.Label(
        root,
        text="What type of job are you looking for?",
        font=("Arial", 12)
    ).pack(
        pady=5
    )

    # --------------------------------------------------------
    # Search box
    # --------------------------------------------------------

    search_box = tk.Entry(
        root,
        width=60,
        font=("Arial", 12)
    )

    search_box.pack(
        pady=5
    )

    # Allow Enter key to search
    search_box.bind(
        "<Return>",
        lambda event: search_jobs()
    )

    # --------------------------------------------------------
    # Search button
    # --------------------------------------------------------

    tk.Button(
        root,
        text="Search Jobs",
        command=search_jobs,
        font=("Arial", 11, "bold"),
        bg="#1f4e79",
        fg="white",
        padx=20,
        pady=5
    ).pack(
        pady=10
    )

    # --------------------------------------------------------
    # Results frame
    # --------------------------------------------------------

    results_frame = tk.Frame(root)

    results_frame.pack(
        fill="both",
        expand=True,
        padx=20,
        pady=10
    )

    # --------------------------------------------------------
    # Scrollbar
    # --------------------------------------------------------

    scrollbar = tk.Scrollbar(
        results_frame
    )

    scrollbar.pack(
        side="right",
        fill="y"
    )

    # --------------------------------------------------------
    # Results box
    # --------------------------------------------------------

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
# LOGIN SCREEN
# ============================================================

def show_login_screen():

    global username_entry
    global password_entry

    clear_window()

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Login frame
    # --------------------------------------------------------

    login_frame = tk.Frame(root)

    login_frame.pack()

    # --------------------------------------------------------
    # Username
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Password
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Login button
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Register button
    # --------------------------------------------------------

    tk.Button(
        login_frame,
        text="Register",
        command=register,
        width=20,
        font=("Arial", 11)
    ).pack(
        pady=5
    )

    # Press Enter to login
    password_entry.bind(
        "<Return>",
        lambda event: login()
    )

    username_entry.focus()


# ============================================================
# CLOSE DATABASE WHEN APP CLOSES
# ============================================================

def close_app():
    conn.close()
    root.destroy()


root.protocol(
    "WM_DELETE_WINDOW",
    close_app
)


# ============================================================
# START APPLICATION
# ============================================================

show_login_screen()

root.mainloop()


