"""
JobTrac - job search and application tracker.

Desktop app built with Tkinter + SQLite. Searches Adzuna, The Muse and USAJOBS,
tracks applications on a dashboard and schedules interviews on a calendar.

Theme: red / black / white.

Run:      python3 jobtrac.py
API keys: edit api_config.json (created next to this file on first run).
          Never commit that file to GitHub.
"""

import tkinter as tk
from email_assistant import draft_email
from tkinter import messagebox, filedialog, ttk
import sqlite3
import json
import webbrowser
import threading
import queue
import os
import sys
import subprocess
import shutil
import calendar
import math
import re
import hashlib
import hmac
import secrets
import uuid
from pathlib import Path
from datetime import date, datetime

from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError


# ============================================================
# CONFIGURATION
# ============================================================

RESULTS_PER_SOURCE = 10

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "users.db"
JOBS_FILE = BASE_DIR / "jobs.json"
RESUME_DIR = BASE_DIR / "resumes"
CONFIG_FILE = BASE_DIR / "api_config.json"
RESUME_DIR.mkdir(exist_ok=True)

API_CONFIG_TEMPLATE = {
    "adzuna_app_id": "PASTE_ADZUNA_APP_ID_HERE",
    "adzuna_app_key": "PASTE_ADZUNA_APP_KEY_HERE",
    "muse_api_key": "",
    "usajobs_email": "PASTE_USAJOBS_EMAIL_HERE",
    "usajobs_key": "PASTE_USAJOBS_KEY_HERE",
}

STATUSES = ["Saved", "Applied", "Interviewing", "Offered", "Denied"]


def ensure_api_config():
    """Create a template api_config.json the first time the app runs."""
    if not CONFIG_FILE.exists():
        try:
            CONFIG_FILE.write_text(json.dumps(API_CONFIG_TEMPLATE, indent=4), encoding="utf-8")
        except OSError:
            pass


def load_api_config():
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid api_config.json: " + str(exc)) from exc


def request_json(url, headers=None):
    request = Request(url, headers=headers or {"User-Agent": "JobTrac-Capstone/1.0"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


ensure_api_config()


# ============================================================
# PASSWORD HASHING (PBKDF2). Legacy plain-text passwords are
# accepted once and upgraded to a hash on the next login.
# ============================================================

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000
    ).hex()
    return f"pbkdf2${salt}${digest}"


def verify_password(password, stored):
    stored = stored or ""
    if stored.startswith("pbkdf2$"):
        try:
            _, salt, _digest = stored.split("$")
        except ValueError:
            return False
        return hmac.compare_digest(hash_password(password, salt), stored)
    return hmac.compare_digest(password.encode("utf-8"), stored.encode("utf-8"))


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

existing_columns = [col[1] for col in cursor.execute("PRAGMA table_info(users)").fetchall()]
for col_name, col_type in [
    ("first_name", "TEXT"), ("last_name", "TEXT"), ("email", "TEXT"),
    ("phone", "TEXT"), ("location", "TEXT"), ("resume_path", "TEXT"),
]:
    if col_name not in existing_columns:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass


# ============================================================
# JOB STORAGE (jobs.json). Every job belongs to one user.
# ============================================================

current_username = ""


def read_all_jobs():
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError):
        try:  # keep the unreadable file instead of overwriting it
            shutil.copy(JOBS_FILE, JOBS_FILE.with_suffix(".json.bak"))
        except OSError:
            pass
        return []


def write_all_jobs(jobs):
    tmp = JOBS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(jobs, file, indent=4)
    os.replace(tmp, JOBS_FILE)


def my_jobs():
    return [j for j in read_all_jobs() if j.get("owner") == current_username]


def claim_legacy_jobs(username):
    """Jobs saved by the old single-user version have no owner; give them to this user."""
    jobs = read_all_jobs()
    changed = False
    for job in jobs:
        if not job.get("owner"):
            job["owner"] = username
            changed = True
    if changed:
        write_all_jobs(jobs)


def update_job(job_id, **changes):
    """Update fields on one of the current user's jobs. A value of None removes the field."""
    jobs = read_all_jobs()
    for job in jobs:
        if str(job.get("id")) == str(job_id) and job.get("owner") == current_username:
            for key, value in changes.items():
                if value is None:
                    job.pop(key, None)
                else:
                    job[key] = value
            break
    write_all_jobs(jobs)


def remove_job(job_id):
    jobs = [j for j in read_all_jobs()
            if not (str(j.get("id")) == str(job_id) and j.get("owner") == current_username)]
    write_all_jobs(jobs)


def _text(value, key="display_name", default=""):
    """Search results nest names in dicts; saved jobs store plain strings."""
    if isinstance(value, dict):
        return value.get(key) or default
    return value or default


def add_job(job):
    """Save a search result for the current user. Returns False if it was already saved."""
    jobs = read_all_jobs()
    job_id = str(job.get("id", "")).strip()
    if not job_id:
        job_id = f"{job.get('title', 'job')}|{job.get('redirect_url', '')}"
    for saved in jobs:
        if saved.get("owner") == current_username and str(saved.get("id", "")) == job_id:
            return False
    jobs.append({
        "id": job_id,
        "owner": current_username,
        "title": job.get("title", "No title"),
        "company": _text(job.get("company"), default="Unknown company"),
        "location": _text(job.get("location"), default="Unknown location"),
        "url": job.get("redirect_url", ""),
        "status": "Saved",
        "source": job.get("source", "Adzuna"),
        "notes": job.get("notes", ""),
        "added": date.today().isoformat(),
    })
    write_all_jobs(jobs)
    return True


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


# ============================================================
# THEME: RED / BLACK / WHITE
# ============================================================

BLACK = "#0B0B0B"
CHARCOAL = "#2A2A2A"
RED = "#D90429"
DARK_RED = "#9D0208"
WHITE = "#FFFFFF"
SNOW = "#F4F4F4"
LINE = "#D9D9D9"
MUTED = "#6B6B6B"

# status -> (background, text colour, border colour)
STATUS_STYLE = {
    "Saved": (SNOW, BLACK, LINE),
    "Applied": (BLACK, WHITE, BLACK),
    "Interviewing": (WHITE, RED, RED),
    "Offered": (RED, WHITE, RED),
    "Denied": (MUTED, WHITE, MUTED),
}

root = tk.Tk()
root.title("JobTrac")
root.geometry("1000x760")
root.minsize(900, 680)
root.configure(bg=BLACK)


def setup_styles():
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TCombobox", fieldbackground=WHITE, background=WHITE, foreground=BLACK,
                    bordercolor=LINE, lightcolor=WHITE, darkcolor=WHITE, arrowcolor=RED,
                    padding=5)
    style.map("TCombobox",
              fieldbackground=[("readonly", WHITE)],
              foreground=[("readonly", BLACK)],
              selectbackground=[("readonly", WHITE)],
              selectforeground=[("readonly", BLACK)],
              bordercolor=[("focus", RED)],
              arrowcolor=[("active", DARK_RED)])
    style.configure("Vertical.TScrollbar", background=BLACK, troughcolor=SNOW,
                    bordercolor=SNOW, arrowcolor=WHITE, lightcolor=BLACK, darkcolor=BLACK)
    style.map("Vertical.TScrollbar", background=[("active", RED)])
    root.option_add("*TCombobox*Listbox.background", WHITE)
    root.option_add("*TCombobox*Listbox.foreground", BLACK)
    root.option_add("*TCombobox*Listbox.selectBackground", RED)
    root.option_add("*TCombobox*Listbox.selectForeground", WHITE)
    root.option_add("*TCombobox*Listbox.font", ("Arial", 11))


setup_styles()


# ============================================================
# THEMED WIDGET HELPERS
# ============================================================

class FlatButton(tk.Label):
    """Label-based button so colours look identical on Windows, macOS and Linux."""

    STYLES = {
        "primary": dict(bg=RED, fg=WHITE, hover=DARK_RED, hfg=WHITE, border=RED),
        "dark": dict(bg=BLACK, fg=WHITE, hover=CHARCOAL, hfg=WHITE, border=BLACK),
        "outline": dict(bg=WHITE, fg=BLACK, hover=BLACK, hfg=WHITE, border=BLACK),
        "danger": dict(bg=WHITE, fg=RED, hover=RED, hfg=WHITE, border=RED),
        "nav": dict(bg=BLACK, fg=WHITE, hover=CHARCOAL, hfg=WHITE, border=BLACK),
    }

    def __init__(self, parent, text, command=None, style="primary", size=10, padx=14, pady=6, **kw):
        self._s = self.STYLES[style]
        self.command = command
        self.enabled = True
        super().__init__(
            parent, text=text, bg=self._s["bg"], fg=self._s["fg"],
            font=("Arial", size, "bold"), padx=padx, pady=pady, cursor="hand2",
            highlightthickness=1, highlightbackground=self._s["border"],
            highlightcolor=self._s["border"], **kw)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)

    def _enter(self, _event=None):
        if self.enabled:
            self.config(bg=self._s["hover"], fg=self._s["hfg"])

    def _leave(self, _event=None):
        if self.enabled:
            self.config(bg=self._s["bg"], fg=self._s["fg"])

    def _click(self, _event=None):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        if enabled:
            self.config(bg=self._s["bg"], fg=self._s["fg"], cursor="hand2",
                        highlightbackground=self._s["border"])
        else:
            self.config(bg="#BDBDBD", fg=WHITE, cursor="arrow", highlightbackground="#BDBDBD")


def make_entry(parent, width=30, show=None, value=""):
    entry = tk.Entry(
        parent, width=width, show=show or "", font=("Arial", 11), bg=WHITE, fg=BLACK,
        insertbackground=RED, relief="flat", highlightthickness=1,
        highlightbackground=LINE, highlightcolor=RED,
        selectbackground=RED, selectforeground=WHITE)
    if value:
        entry.insert(0, value)
    return entry


def field(parent, text, value="", show=None, width=30):
    """Label + entry in one frame. Returns (frame, entry); the caller places the frame."""
    bg = parent["bg"]
    frame = tk.Frame(parent, bg=bg)
    tk.Label(frame, text=text, font=("Arial", 10, "bold"), bg=bg, fg=BLACK).pack(anchor="w")
    entry = make_entry(frame, width=width, show=show, value=value)
    entry.pack(fill="x", ipady=5, pady=(3, 0))
    return frame, entry


def label(parent, text, size=11, bold=False, fg=BLACK, **kw):
    return tk.Label(parent, text=text, font=("Arial", size, "bold" if bold else "normal"),
                    bg=parent["bg"], fg=fg, **kw)


def pill(parent, text, status=None):
    bg, fg, border = STATUS_STYLE.get(status or text, (BLACK, WHITE, BLACK))
    return tk.Label(parent, text=text, font=("Arial", 9, "bold"), bg=bg, fg=fg,
                    padx=9, pady=2, highlightthickness=1, highlightbackground=border)


def card(parent):
    """White card with a red accent bar. Pack the returned outer frame; fill the inner one."""
    outer = tk.Frame(parent, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
    tk.Frame(outer, bg=RED, width=5).pack(side="left", fill="y")
    inner = tk.Frame(outer, bg=WHITE, padx=14, pady=10)
    inner.pack(side="left", fill="both", expand=True)
    return outer, inner


def page_title(parent, title, subtitle=None):
    box = tk.Frame(parent, bg=WHITE)
    box.pack(fill="x", pady=(0, 12))
    tk.Label(box, text=title, font=("Arial", 22, "bold"), bg=WHITE, fg=BLACK).pack(anchor="w")
    tk.Frame(box, bg=RED, width=56, height=4).pack(anchor="w", pady=(4, 6))
    if subtitle:
        tk.Label(box, text=subtitle, font=("Arial", 11), bg=WHITE, fg=MUTED).pack(anchor="w")


def themed_combobox(parent, values, width=18, value=None):
    box = ttk.Combobox(parent, values=values, state="readonly", width=width, font=("Arial", 10))
    if value is not None:
        box.set(value)
    return box


class ScrollFrame(tk.Frame):
    """Vertically scrollable frame. Put content in `.inner`."""

    def __init__(self, parent, bg=WHITE):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner.bind("<Configure>",
                        lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")

    def scroll(self, event):
        if self.canvas.yview() == (0.0, 1.0):
            return
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            self.canvas.yview_scroll(-2, "units")
        else:
            self.canvas.yview_scroll(2, "units")


def _on_wheel(event):
    """One global handler: scroll whichever ScrollFrame is under the mouse."""
    try:
        widget = root.winfo_containing(event.x_root, event.y_root)
    except (KeyError, tk.TclError):
        return
    while widget is not None:
        if isinstance(widget, ScrollFrame):
            widget.scroll(event)
            return
        widget = widget.master


for _sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
    root.bind_all(_sequence, _on_wheel)


def clear_window():
    for widget in root.winfo_children():
        widget.destroy()


def themed_dialog(title, width, height):
    dialog = tk.Toplevel(root)
    dialog.title(title)
    dialog.configure(bg=WHITE)
    dialog.geometry(f"{width}x{height}")
    dialog.resizable(False, False)
    dialog.transient(root)
    tk.Frame(dialog, bg=RED, height=5).pack(fill="x")
    body = tk.Frame(dialog, bg=WHITE, padx=24, pady=18)
    body.pack(fill="both", expand=True)
    try:
        dialog.wait_visibility()
        dialog.grab_set()
    except tk.TclError:
        pass
    return dialog, body


def pretty_time(value):
    try:
        return datetime.strptime(value, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        return value or ""


def pretty_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%b %d, %Y").replace(" 0", " ")
    except (TypeError, ValueError):
        return value or ""


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
    except Exception as exc:
        messagebox.showerror("Error", f"Failed to open file: {exc}")


# ============================================================
# SHELLS: logged-out card layout and logged-in app layout
# ============================================================


def brand(parent, size=24, bg=BLACK):
    """Display the JobTrac logo or fallback wordmark."""
    holder = tk.Frame(parent, bg=bg)

    try:
        image = tk.PhotoImage(file=str(BASE_DIR / "logo.png"))

        # Resize logo to approximately 180 pixels wide
        target_width = 180

        if image.width() > target_width:
            factor = max(1, image.width() // target_width)
            image = image.subsample(factor, factor)

        elif image.width() < target_width:
            factor = max(1, round(target_width / image.width()))
            image = image.zoom(factor, factor)

        logo = tk.Label(holder, image=image, bg=bg)
        logo.image = image
        logo.pack()

    except (tk.TclError, OSError):
        tk.Label(
            holder, text="Job",
            font=("Arial", size, "bold"),
            fg=WHITE, bg=bg
        ).pack(side="left")

        tk.Label(
            holder, text="Trac",
            font=("Arial", size, "bold"),
            fg=RED, bg=bg
        ).pack(side="left")

    return holder



def auth_shell(title, subtitle, min_width=420):
    """Black screen, centred white card. Returns the card's inner frame."""
    clear_window()
    root.configure(bg=BLACK)
    wrap = tk.Frame(root, bg=BLACK)
    wrap.place(relx=0.5, rely=0.5, anchor="center")
    brand(wrap, size=36).pack(pady=(0, 4))
    tk.Label(wrap, text="Search. Apply. Track. Win.", font=("Arial", 11), fg="#BBBBBB",
             bg=BLACK).pack(pady=(0, 14))
    outer = tk.Frame(wrap, bg=WHITE)
    outer.pack()
    tk.Frame(outer, bg=RED, height=6).pack(fill="x")
    inner = tk.Frame(outer, bg=WHITE, padx=36, pady=26)
    inner.pack()
    tk.Frame(inner, bg=WHITE, width=min_width, height=1).pack()
    tk.Label(inner, text=title, font=("Arial", 20, "bold"), bg=WHITE, fg=BLACK).pack(anchor="w")
    tk.Label(inner, text=subtitle, font=("Arial", 11), bg=WHITE, fg=MUTED).pack(anchor="w", pady=(2, 14))
    return inner


NAV_ITEMS = [
    ("search", "Search", lambda: open_main_app(current_username)),
    ("dashboard", "Dashboard", lambda: open_dashboard()),
    ("calendar", "Calendar", lambda: open_calendar()),
    ("add", "Add Job", lambda: manual_job_entry()),
    ("account", "Account", lambda: show_account_info()),
    ("logout", "Logout", lambda: logout()),
]


def build_shell(active):
    """Black header with navigation + red rule + white body. Returns the body frame."""
    clear_window()
    root.configure(bg=WHITE)
    header = tk.Frame(root, bg=BLACK)
    header.pack(fill="x")
    brand(header).pack(side="left", padx=20, pady=10)
    nav = tk.Frame(header, bg=BLACK)
    nav.pack(side="right", padx=14)
    for key, text, command in NAV_ITEMS:
        FlatButton(nav, text, command, "primary" if key == active else "nav").pack(
            side="left", padx=2, pady=14)
    tk.Frame(root, bg=RED, height=4).pack(fill="x")
    body = tk.Frame(root, bg=WHITE)
    body.pack(fill="both", expand=True, padx=30, pady=18)
    return body


# ============================================================
# LOGIN / REGISTER / LOGOUT
# ============================================================

username_entry = None
password_entry = None
reg = {}
selected_resume = {"path": None, "label": None}

search_box = None
search_zip_entry = None
zip_mode_var = None
results_container = None
search_button = None
LAST_SEARCH = None  # remembers the last query so the search page survives navigation


def show_login_screen():
    global username_entry, password_entry, current_username, LAST_SEARCH
    current_username = ""
    LAST_SEARCH = None
    root.title("JobTrac")
    card_frame = auth_shell("Welcome back", "Sign in to track your job search")

    frame, username_entry = field(card_frame, "Username", width=34)
    frame.pack(fill="x", pady=6)
    frame, password_entry = field(card_frame, "Password", show="•", width=34)
    frame.pack(fill="x", pady=6)

    FlatButton(card_frame, "Sign In", login, "primary", size=11, pady=9).pack(fill="x", pady=(16, 8))
    tk.Label(card_frame, text="New to JobTrac?", font=("Arial", 10), bg=WHITE, fg=MUTED).pack()
    FlatButton(card_frame, "Create Account", show_register_screen, "outline", size=11,
               pady=9).pack(fill="x", pady=(6, 0))

    username_entry.bind("<Return>", lambda _e: password_entry.focus())
    password_entry.bind("<Return>", lambda _e: login())
    username_entry.focus()


def login():
    username = username_entry.get().strip()
    password = password_entry.get()
    if not username or not password:
        messagebox.showerror("Error", "Please enter a username and password.")
        return
    cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    if not row or not verify_password(password, row[0]):
        messagebox.showerror("Error", "Invalid username or password.")
        return
    if not (row[0] or "").startswith("pbkdf2$"):  # upgrade legacy plain-text password
        cursor.execute("UPDATE users SET password = ? WHERE username = ?",
                       (hash_password(password), username))
        conn.commit()
    claim_legacy_jobs(username)
    open_main_app(username)


def logout():
    show_login_screen()


def browse_resume(target_label, store):
    file_path = filedialog.askopenfilename(
        title="Select Resume",
        filetypes=[("PDF Documents", "*.pdf"), ("Word Documents", "*.docx"), ("All Files", "*.*")])
    if file_path:
        store["path"] = file_path
        target_label.config(text=Path(file_path).name, fg=RED)


def save_resume_copy(source, username):
    """Copy a resume into the app's resumes folder and return the stored path."""
    safe_user = re.sub(r"[^\w.-]", "_", username)
    destination = RESUME_DIR / f"{safe_user}_{Path(source).name}"
    shutil.copy2(source, destination)
    return str(destination)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def show_register_screen():
    clear_window()
    selected_resume["path"] = None
    card_frame = auth_shell("Create your account", "Fields marked * are required", min_width=560)

    grid = tk.Frame(card_frame, bg=WHITE)
    grid.pack(fill="x")
    grid.columnconfigure(0, weight=1, uniform="col")
    grid.columnconfigure(1, weight=1, uniform="col")

    def place(key, text, row, col, span=1, **kw):
        frame, entry = field(grid, text, width=24, **kw)
        frame.grid(row=row, column=col, columnspan=span, sticky="ew", padx=6, pady=5)
        reg[key] = entry

    place("first", "First Name", 0, 0)
    place("last", "Last Name", 0, 1)
    place("email", "Email Address", 1, 0)
    place("phone", "Phone Number", 1, 1)
    place("location", "Location (City, State, Country)", 2, 0, span=2)
    place("username", "Username *", 3, 0)
    place("password", "Password * (min. 6 characters)", 3, 1, show="•")

    resume_row = tk.Frame(card_frame, bg=WHITE)
    resume_row.pack(fill="x", pady=(10, 0), padx=6)
    tk.Label(resume_row, text="Resume (PDF / DOCX)", font=("Arial", 10, "bold"), bg=WHITE,
             fg=BLACK).pack(anchor="w")
    pick_row = tk.Frame(resume_row, bg=WHITE)
    pick_row.pack(anchor="w", pady=(4, 0))
    resume_label = tk.Label(pick_row, text="No file selected", font=("Arial", 10), bg=WHITE, fg=MUTED)
    FlatButton(pick_row, "Browse...", lambda: browse_resume(resume_label, selected_resume),
               "outline").pack(side="left")
    resume_label.pack(side="left", padx=10)

    buttons = tk.Frame(card_frame, bg=WHITE)
    buttons.pack(fill="x", pady=(18, 0), padx=6)
    FlatButton(buttons, "Register Account", register_user, "primary", size=11, pady=9).pack(
        side="left", fill="x", expand=True, padx=(0, 6))
    FlatButton(buttons, "Back to Login", show_login_screen, "outline", size=11, pady=9).pack(
        side="left", fill="x", expand=True, padx=(6, 0))

    reg["first"].focus()


def register_user():
    values = {k: reg[k].get().strip() for k in ("first", "last", "email", "phone", "location", "username")}
    password = reg["password"].get()

    if not values["username"] or not password:
        messagebox.showerror("Error", "Username and password are required.")
        return
    if len(password) < 6:
        messagebox.showerror("Error", "Password must be at least 6 characters.")
        return
    if values["email"] and not EMAIL_RE.match(values["email"]):
        messagebox.showerror("Error", "Please enter a valid email address.")
        return
    cursor.execute("SELECT 1 FROM users WHERE username = ?", (values["username"],))
    if cursor.fetchone():
        messagebox.showerror("Error", "Username already exists.")
        return

    stored_resume = ""
    source = selected_resume["path"]
    if source and Path(source).exists():
        try:
            stored_resume = save_resume_copy(source, values["username"])
        except OSError as exc:
            messagebox.showwarning("Warning", f"Could not save resume file: {exc}")

    try:
        cursor.execute(
            """INSERT INTO users (username, password, first_name, last_name, email, phone,
                                  location, resume_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (values["username"], hash_password(password), values["first"], values["last"],
             values["email"], values["phone"], values["location"], stored_resume))
        conn.commit()
    except sqlite3.IntegrityError:
        messagebox.showerror("Error", "Username already exists.")
        return
    except sqlite3.Error as exc:
        messagebox.showerror("Registration error", str(exc))
        return

    messagebox.showinfo("Success", "Account created successfully! You can sign in now.")
    show_login_screen()


# ============================================================
# ACCOUNT
# ============================================================

def get_user(username):
    cursor.execute(
        """SELECT username, password, first_name, last_name, email, phone, location, resume_path
           FROM users WHERE username = ?""", (username,))
    return cursor.fetchone()


def show_account_info():
    user = get_user(current_username)
    if not user:
        messagebox.showerror("Error", "User details not found.")
        show_login_screen()
        return
    _, _, first, last, email, phone, location, resume_path = user

    body = build_shell("account")
    page_title(body, "Account Profile", "Your details are used to localise job searches.")

    outer, inner = card(body)
    outer.pack(fill="x")
    inner.columnconfigure(1, weight=1)

    rows = [
        ("Username", current_username),
        ("First name", first or "N/A"),
        ("Last name", last or "N/A"),
        ("Email", email or "N/A"),
        ("Phone", phone or "N/A"),
        ("Location", location or "N/A"),
    ]
    for index, (name, value) in enumerate(rows):
        tk.Label(inner, text=name, font=("Arial", 11, "bold"), bg=WHITE, fg=MUTED, width=12,
                 anchor="w").grid(row=index, column=0, sticky="w", pady=6)
        tk.Label(inner, text=value, font=("Arial", 12), bg=WHITE, fg=BLACK, anchor="w").grid(
            row=index, column=1, sticky="w", padx=14, pady=6)

    resume_row = len(rows)
    tk.Label(inner, text="Resume", font=("Arial", 11, "bold"), bg=WHITE, fg=MUTED, width=12,
             anchor="w").grid(row=resume_row, column=0, sticky="w", pady=8)
    holder = tk.Frame(inner, bg=WHITE)
    holder.grid(row=resume_row, column=1, sticky="w", padx=14, pady=8)
    if resume_path and Path(resume_path).exists():
        tk.Label(holder, text=Path(resume_path).name, font=("Arial", 12), bg=WHITE, fg=RED).pack(side="left")
        FlatButton(holder, "Open Resume", lambda p=resume_path: open_file_externally(p),
                   "outline").pack(side="left", padx=12)
    else:
        tk.Label(holder, text="No resume uploaded", font=("Arial", 12), bg=WHITE, fg=MUTED).pack(side="left")

    actions = tk.Frame(body, bg=WHITE)
    actions.pack(anchor="w", pady=18)
    FlatButton(actions, "Edit Account", lambda: edit_account_info(), "primary", size=11,
               pady=8).pack(side="left", padx=(0, 10))
    FlatButton(actions, "Delete Account", delete_account, "danger", size=11, pady=8).pack(side="left")


def edit_account_info():
    global current_username
    user = get_user(current_username)
    if not user:
        messagebox.showerror("Error", "User details not found.")
        return
    old_username, old_password, first, last, email, phone, location, resume_path = user

    body = build_shell("account")
    page_title(body, "Edit Account", "Update your details. Leave the password blank to keep it.")

    outer, inner = card(body)
    outer.pack(fill="x")
    grid = tk.Frame(inner, bg=WHITE)
    grid.pack(fill="x")
    grid.columnconfigure(0, weight=1, uniform="col")
    grid.columnconfigure(1, weight=1, uniform="col")

    entries = {}

    def place(key, text, value, row, col, span=1, **kw):
        frame, entry = field(grid, text, value=value or "", width=26, **kw)
        frame.grid(row=row, column=col, columnspan=span, sticky="ew", padx=6, pady=5)
        entries[key] = entry

    place("username", "Username *", old_username, 0, 0)
    place("password", "New Password", "", 0, 1, show="•")
    place("first", "First Name", first, 1, 0)
    place("last", "Last Name", last, 1, 1)
    place("email", "Email Address", email, 2, 0)
    place("phone", "Phone Number", phone, 2, 1)
    place("location", "Location (City, State, Country)", location, 3, 0, span=2)

    new_resume = {"path": None}
    has_resume = bool(resume_path and Path(resume_path).exists())
    resume_row = tk.Frame(inner, bg=WHITE)
    resume_row.pack(fill="x", padx=6, pady=(10, 0))
    tk.Label(resume_row, text="Resume", font=("Arial", 10, "bold"), bg=WHITE, fg=BLACK).pack(anchor="w")
    pick = tk.Frame(resume_row, bg=WHITE)
    pick.pack(anchor="w", pady=(4, 0))
    resume_label = tk.Label(pick, text=Path(resume_path).name if has_resume else "No resume uploaded",
                            font=("Arial", 10), bg=WHITE, fg=RED if has_resume else MUTED)
    FlatButton(pick, "Upload New Resume", lambda: browse_resume(resume_label, new_resume),
               "outline").pack(side="left")
    resume_label.pack(side="left", padx=10)

    def save():
        global current_username
        new_username = entries["username"].get().strip()
        new_password = entries["password"].get()
        new_email = entries["email"].get().strip()
        if not new_username:
            messagebox.showerror("Error", "Username is required.")
            return
        if new_password and len(new_password) < 6:
            messagebox.showerror("Error", "Password must be at least 6 characters.")
            return
        if new_email and not EMAIL_RE.match(new_email):
            messagebox.showerror("Error", "Please enter a valid email address.")
            return
        if new_username != old_username:
            cursor.execute("SELECT 1 FROM users WHERE username = ?", (new_username,))
            if cursor.fetchone():
                messagebox.showerror("Error", "That username is already taken.")
                return

        stored_password = hash_password(new_password) if new_password else old_password
        stored_resume = resume_path or ""
        if new_resume["path"]:
            try:
                stored_resume = save_resume_copy(new_resume["path"], new_username)
            except OSError as exc:
                messagebox.showerror("Resume Error", f"Could not save the new resume:\n{exc}")
                return

        try:
            cursor.execute(
                """UPDATE users SET username = ?, password = ?, first_name = ?, last_name = ?,
                          email = ?, phone = ?, location = ?, resume_path = ?
                   WHERE username = ?""",
                (new_username, stored_password, entries["first"].get().strip(),
                 entries["last"].get().strip(), new_email, entries["phone"].get().strip(),
                 entries["location"].get().strip(), stored_resume, old_username))
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            messagebox.showerror("Database Error", f"Could not update your account:\n{exc}")
            return

        if new_username != old_username:  # keep the user's saved jobs attached to them
            jobs = read_all_jobs()
            for job in jobs:
                if job.get("owner") == old_username:
                    job["owner"] = new_username
            write_all_jobs(jobs)
        current_username = new_username
        messagebox.showinfo("Success", "Your account information has been updated!")
        show_account_info()

    actions = tk.Frame(inner, bg=WHITE)
    actions.pack(anchor="w", padx=6, pady=(18, 4))
    FlatButton(actions, "Save Changes", save, "primary", size=11, pady=8).pack(side="left", padx=(0, 10))
    FlatButton(actions, "Cancel", show_account_info, "outline", size=11, pady=8).pack(side="left")


def delete_account():
    if not messagebox.askyesno(
            "Delete Account",
            "This permanently deletes your account, resume and all saved jobs.\n\nContinue?",
            icon="warning"):
        return
    user = get_user(current_username)
    if user and user[7] and Path(user[7]).exists():
        try:
            Path(user[7]).unlink()
        except OSError:
            pass
    cursor.execute("DELETE FROM users WHERE username = ?", (current_username,))
    conn.commit()
    write_all_jobs([j for j in read_all_jobs() if j.get("owner") != current_username])
    messagebox.showinfo("JobTrac", "Your account has been deleted.")
    show_login_screen()


# ============================================================
# SEARCH PAGE
# ============================================================

SEARCH_QUEUE = queue.Queue()
search_state = {"token": 0, "polling": False}


def open_main_app(username):
    global search_box, search_zip_entry, zip_mode_var, results_container, search_button
    global current_username
    current_username = username
    root.title("JobTrac")

    body = build_shell("search")
    user = get_user(username)
    name = (user[2] if user and user[2] else username)
    page_title(body, f"Welcome, {name}!", "Find your next job with JobTrac.")

    outer, inner = card(body)
    outer.pack(fill="x")

    tk.Label(inner, text="What type of job are you looking for?", font=("Arial", 11, "bold"),
             bg=WHITE, fg=BLACK).pack(anchor="w")
    row = tk.Frame(inner, bg=WHITE)
    row.pack(fill="x", pady=(6, 0))

    search_box = make_entry(row, width=34)
    search_box.pack(side="left", fill="x", expand=True, ipady=6)

    tk.Label(row, text="ZIP", font=("Arial", 10, "bold"), bg=WHITE, fg=BLACK).pack(side="left", padx=(14, 4))
    search_zip_entry = make_entry(row, width=8)
    search_zip_entry.pack(side="left", ipady=6)

    zip_mode_var = tk.StringVar(value="Exact ZIP")
    mode_box = themed_combobox(row, ["Exact ZIP", "Within 5 miles"], width=14)
    mode_box.configure(textvariable=zip_mode_var)
    mode_box.pack(side="left", padx=(8, 0), ipady=3)

    search_button = FlatButton(row, "Search Jobs", search_jobs, "primary", size=11, pady=7)
    search_button.pack(side="left", padx=(14, 0))

    search_box.bind("<Return>", lambda _e: search_jobs())
    search_zip_entry.bind("<Return>", lambda _e: search_jobs())

    scroll = ScrollFrame(body)
    scroll.pack(fill="both", expand=True, pady=(14, 0))
    results_container = scroll.inner

    if LAST_SEARCH:
        search_box.insert(0, LAST_SEARCH["query"])
        search_zip_entry.insert(0, LAST_SEARCH["zip"])
        zip_mode_var.set(LAST_SEARCH["mode"])
        display_search_results(LAST_SEARCH["data"])
    else:
        tk.Label(results_container,
                 text="Enter a job title or keyword to search Adzuna, The Muse and USAJOBS at once.",
                 font=("Arial", 11), bg=WHITE, fg=MUTED).pack(anchor="w", padx=4, pady=8)
    search_box.focus()


def widget_alive(widget):
    try:
        return widget is not None and bool(widget.winfo_exists())
    except tk.TclError:
        return False


def clear_search_results():
    if widget_alive(results_container):
        for child in results_container.winfo_children():
            child.destroy()


def show_search_message(message, fg=MUTED):
    clear_search_results()
    if widget_alive(results_container):
        tk.Label(results_container, text=message, font=("Arial", 11), bg=WHITE, fg=fg,
                 wraplength=800, justify="left").pack(anchor="w", padx=4, pady=8)
    if widget_alive(search_button):
        search_button.set_enabled(True)


def show_search_error(message):
    show_search_message(message, fg=RED)


def search_jobs():
    description = search_box.get().strip()
    zipcode = search_zip_entry.get().strip()
    mode = zip_mode_var.get()
    if not description:
        show_search_error("Please enter a job title or keyword.")
        return
    if zipcode and not re.fullmatch(r"\d{5}", zipcode):
        show_search_error("ZIP code must be exactly 5 digits, such as 77030.")
        return
    user = get_user(current_username)
    user_location = ((user[6] or "").strip() if user else "")

    search_button.set_enabled(False)
    info = f"Searching jobs near {zipcode} ({mode})..." if zipcode else "Searching all 3 job sources..."
    show_search_message(info)
    search_button.set_enabled(False)

    search_state["token"] += 1
    token = search_state["token"]
    threading.Thread(target=search_jobs_api,
                     args=(token, description, user_location, zipcode, mode), daemon=True).start()
    if not search_state["polling"]:
        search_state["polling"] = True
        root.after(100, poll_search)


def search_jobs_api(token, description, location="", zipcode="", mode="Exact ZIP"):
    """Runs in a worker thread; never touches Tk. Results go back through SEARCH_QUEUE."""
    jobs, errors, center = [], [], None
    if zipcode and mode == "Within 5 miles":
        try:
            center = zip_center(zipcode)
        except ValueError as exc:
            SEARCH_QUEUE.put((token, {"results": [], "errors": [str(exc)], "zipcode": zipcode,
                                      "mode": mode, "query": description}))
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
        except Exception as exc:  # one failing source must not stop the others
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    SEARCH_QUEUE.put((token, {"results": jobs, "errors": errors, "zipcode": zipcode,
                              "mode": mode, "query": description}))


def poll_search():
    global LAST_SEARCH
    try:
        while True:
            token, data = SEARCH_QUEUE.get_nowait()
            if token != search_state["token"]:
                continue  # stale result from an older search
            search_state["polling"] = False
            LAST_SEARCH = {"query": data.get("query", ""), "zip": data.get("zipcode", ""),
                           "mode": data.get("mode", "Exact ZIP"), "data": data}
            if widget_alive(results_container):
                display_search_results(data)
            return
    except queue.Empty:
        pass
    root.after(100, poll_search)


def display_search_results(data):
    clear_search_results()
    if not widget_alive(results_container):
        return
    jobs = data.get("results", [])
    errors = data.get("errors", [])
    zipcode = data.get("zipcode", "")
    mode = data.get("mode", "Exact ZIP")
    saved_ids = {str(j.get("id")) for j in my_jobs()}

    if zipcode:
        tk.Label(results_container,
                 text=(f"Location filter: {mode} - {zipcode}. Listings without a verifiable ZIP or "
                       "nearby coordinate are hidden, so exact ZIP may return few results because "
                       "job APIs often omit postal codes."),
                 wraplength=800, justify="left", anchor="w", font=("Arial", 10), bg=WHITE,
                 fg=MUTED).pack(fill="x", padx=4, pady=(0, 6))
    if jobs:
        tk.Label(results_container, text=f"Found {len(jobs)} jobs", font=("Arial", 13, "bold"),
                 bg=WHITE, fg=BLACK).pack(anchor="w", padx=4, pady=(0, 6))
    else:
        tk.Label(results_container, text="No jobs returned. Try another search term.",
                 font=("Arial", 11), bg=WHITE, fg=MUTED).pack(anchor="w", padx=4, pady=8)
    if errors:
        tk.Label(results_container, text="Notes: " + "  |  ".join(errors), wraplength=800,
                 justify="left", anchor="w", font=("Arial", 10), bg=WHITE, fg=DARK_RED).pack(
                     fill="x", padx=4, pady=(0, 8))

    for job in jobs:
        outer, inner = card(results_container)
        outer.pack(fill="x", padx=4, pady=5)

        top = tk.Frame(inner, bg=WHITE)
        top.pack(fill="x")
        tk.Label(top, text=job.get("title", "Untitled job"), font=("Arial", 13, "bold"), bg=WHITE,
                 fg=BLACK, wraplength=680, justify="left", anchor="w").pack(side="left")
        pill(top, job.get("source", ""), status="Applied").pack(side="right")

        company = _text(job.get("company"), default="")
        place = _text(job.get("location"), default="")
        tk.Label(inner, text=f"{company}   •   {place}", font=("Arial", 11), bg=WHITE, fg=MUTED,
                 anchor="w").pack(fill="x", pady=(2, 8))

        controls = tk.Frame(inner, bg=WHITE)
        controls.pack(anchor="w")
        link = job.get("redirect_url") or ""
        if link:
            apply_link = tk.Label(controls, text="Apply Here", fg=RED, bg=WHITE, cursor="hand2",
                                  font=("Arial", 10, "bold underline"))
            apply_link.pack(side="left", padx=(0, 14))
            apply_link.bind("<Button-1>", lambda _e, u=link: webbrowser.open(u))
        add_btn = FlatButton(controls, "Add to Dashboard", None, "dark")
        add_btn.pack(side="left")

        def do_add(j=job, b=add_btn):
            if add_job(j):
                b.config(text="✓ Added")
                b.set_enabled(False)
            else:
                b.config(text="✓ Already saved")
                b.set_enabled(False)

        add_btn.command = do_add
        if str(job.get("id", "")) in saved_ids:
            add_btn.config(text="✓ Already saved")
            add_btn.set_enabled(False)

    if widget_alive(search_button):
        search_button.set_enabled(True)


# ============================================================
# DASHBOARD
# ============================================================

def change_status(job_id, status, status_filter):
    update_job(job_id, status=status)
    open_dashboard(status_filter)


def delete_job(job_id, status_filter):
    if not messagebox.askyesno("Delete Job", "Are you sure you want to delete this job?"):
        return
    remove_job(job_id)
    open_dashboard(status_filter)


def open_notes_editor(job, status_filter):
    dialog, body = themed_dialog("Job Notes", 520, 360)
    tk.Label(body, text="Notes", font=("Arial", 16, "bold"), bg=WHITE, fg=BLACK).pack(anchor="w")
    tk.Label(body, text=f"{job.get('title', '')} - {job.get('company', '')}", font=("Arial", 10),
             bg=WHITE, fg=MUTED).pack(anchor="w", pady=(0, 8))
    text = tk.Text(body, height=9, font=("Arial", 11), wrap="word", relief="flat",
                   highlightthickness=1, highlightbackground=LINE, highlightcolor=RED,
                   insertbackground=RED, selectbackground=RED, selectforeground=WHITE)
    text.pack(fill="both", expand=True)
    text.insert("1.0", job.get("notes", ""))

    def save():
        update_job(job["id"], notes=text.get("1.0", "end").strip())
        dialog.destroy()
        open_dashboard(status_filter)

    row = tk.Frame(body, bg=WHITE)
    row.pack(anchor="w", pady=(12, 0))
    FlatButton(row, "Save Notes", save, "primary").pack(side="left", padx=(0, 8))
    FlatButton(row, "Cancel", dialog.destroy, "outline").pack(side="left")
    text.focus()


def open_email_drafter(job):
    dialog, body = themed_dialog("AI Email Assistant", 650, 600)

    tk.Label(
        body,
        text="AI Email Assistant",
        font=("Arial", 18, "bold"),
        bg=WHITE,
        fg=BLACK
    ).pack(anchor="w", pady=(0, 8))

    tk.Label(
        body,
        text=f"{job.get('title', 'Job')} - {job.get('company', 'Company')}",
        font=("Arial", 11),
        bg=WHITE,
        fg=MUTED
    ).pack(anchor="w", pady=(0, 15))

    tk.Label(
        body,
        text="Choose Email Type:",
        font=("Arial", 11, "bold"),
        bg=WHITE,
        fg=BLACK
    ).pack(anchor="w")

    email_type = tk.StringVar(value="interest")

    tk.Radiobutton(
        body, text="Interest Email",
        variable=email_type, value="interest",
        bg=WHITE, fg=BLACK,
        activebackground=WHITE
    ).pack(anchor="w")

    tk.Radiobutton(
        body, text="Follow-up Email",
        variable=email_type, value="followup",
        bg=WHITE, fg=BLACK,
        activebackground=WHITE
    ).pack(anchor="w")

    email_text = tk.Text(
        body, height=14, wrap="word",
        font=("Arial", 11),
        relief="solid", bd=1
    )
    email_text.pack(fill="both", expand=True, pady=12)

    def generate():
        email_text.delete("1.0", "end")
        email_text.insert("1.0", "Generating email...")
        dialog.update_idletasks()

        def worker():
            try:
                result = draft_email(
                    job.get("title", ""),
                    job.get("company", ""),
                    email_type.get()
                )
            except Exception as exc:
                error = str(exc)
                dialog.after(0, lambda: show_error(error))
            else:
                dialog.after(0, lambda: show_result(result))

        threading.Thread(target=worker, daemon=True).start()

    def show_result(result):
        if not dialog.winfo_exists():
            return
        email_text.delete("1.0", "end")
        email_text.insert("1.0", result)

    def show_error(error):
        if not dialog.winfo_exists():
            return
        email_text.delete("1.0", "end")
        messagebox.showerror("AI Email Error", error)

    def copy_email():
        content = email_text.get("1.0", "end").strip()
        if not content or content == "Generating email...":
            return
        dialog.clipboard_clear()
        dialog.clipboard_append(content)
        messagebox.showinfo("JobTrac", "Email copied!")

    actions = tk.Frame(body, bg=WHITE)
    actions.pack(fill="x", pady=(5, 0))

    FlatButton(
        actions, "Generate Email", generate, "primary"
    ).pack(side="left", padx=(0, 8))

    FlatButton(
        actions, "Copy Email", copy_email, "outline"
    ).pack(side="left", padx=4)

    FlatButton(
        actions, "Close", dialog.destroy, "outline"
    ).pack(side="left", padx=4)

def dashboard_job_card(parent, job, status_filter):
    outer, inner = card(parent)
    outer.pack(fill="x", padx=4, pady=5)
    job_id = str(job.get("id", ""))
    status = job.get("status", "Saved")

    top = tk.Frame(inner, bg=WHITE)
    top.pack(fill="x")
    tk.Label(top, text=job.get("title", "No title"), font=("Arial", 13, "bold"), bg=WHITE, fg=BLACK,
             wraplength=640, justify="left", anchor="w").pack(side="left")
    pill(top, status.upper(), status=status).pack(side="right")

    tk.Label(inner, text=f"{_text(job.get('company'), default='Unknown company')}   •   "
                         f"{_text(job.get('location'), default='Not specified')}",
             font=("Arial", 11), bg=WHITE, fg=MUTED, anchor="w").pack(fill="x", pady=(2, 0))
    added = f"   •   Added {pretty_date(job['added'])}" if job.get("added") else ""
    tk.Label(inner, text=f"Source: {job.get('source', 'Manual')}{added}", font=("Arial", 9),
             bg=WHITE, fg=MUTED, anchor="w").pack(fill="x")
    if job.get("interview_date"):
        tk.Label(inner, text=f"Interview: {pretty_date(job['interview_date'])} at "
                             f"{pretty_time(job.get('interview_time', ''))}",
                 font=("Arial", 10, "bold"), bg=WHITE, fg=RED, anchor="w").pack(fill="x", pady=(4, 0))
    if job.get("notes"):
        tk.Label(inner, text=f"Notes: {job['notes']}", font=("Arial", 10, "italic"), bg=WHITE,
                 fg=CHARCOAL, wraplength=760, justify="left", anchor="w").pack(fill="x", pady=(4, 0))

    buttons = tk.Frame(inner, bg=WHITE)
    buttons.pack(anchor="w", pady=(10, 0))
    url = job.get("url", "")
    FlatButton(buttons, "Open Job",
               lambda u=url: webbrowser.open(u) if u else messagebox.showwarning(
                   "JobTrac", "No link available for this job."), "dark").pack(side="left", padx=(0, 6))
    FlatButton(buttons, "Interview", lambda jid=job_id: open_interview_editor(jid),
               "outline").pack(side="left", padx=3)
    FlatButton(buttons, "Notes", lambda j=job: open_notes_editor(j, status_filter),
               "outline").pack(side="left", padx=3)

    FlatButton(
        buttons,
        "Draft Email",
        lambda j=job: open_email_drafter(j),
        "primary"
    ).pack(side="left", padx=3)


    status_box = themed_combobox(buttons, STATUSES, width=12, value=status)
    status_box.pack(side="left", padx=(10, 3), ipady=2)
    status_box.bind("<<ComboboxSelected>>",
                    lambda _e, jid=job_id, box=status_box: change_status(jid, box.get(), status_filter))

    FlatButton(buttons, "Delete", lambda jid=job_id: delete_job(jid, status_filter),
               "danger").pack(side="left", padx=(10, 0))


def open_dashboard(status_filter="All"):
    body = build_shell("dashboard")
    page_title(body, "My Dashboard", "Follow every application from saved to offer.")

    jobs = my_jobs()
    counts = {s: 0 for s in STATUSES}
    for job in jobs:
        counts[job.get("status", "Saved")] = counts.get(job.get("status", "Saved"), 0) + 1

    tiles = tk.Frame(body, bg=WHITE)
    tiles.pack(fill="x", pady=(0, 10))
    for index, (name, caption) in enumerate([("All", "Total")] + [(s, s) for s in STATUSES]):
        count = len(jobs) if name == "All" else counts.get(name, 0)
        selected = status_filter == name
        tile = tk.Frame(tiles, bg=BLACK if selected else WHITE, cursor="hand2", padx=12, pady=8,
                        highlightthickness=1, highlightbackground=RED if selected else LINE)
        tile.grid(row=0, column=index, sticky="ew", padx=4)
        tiles.columnconfigure(index, weight=1, uniform="tile")
        number = tk.Label(tile, text=str(count), font=("Arial", 22, "bold"),
                          bg=tile["bg"], fg=RED if selected else BLACK)
        number.pack()
        words = tk.Label(tile, text=caption, font=("Arial", 10), bg=tile["bg"],
                         fg=WHITE if selected else MUTED)
        words.pack()
        for widget in (tile, number, words):
            widget.bind("<Button-1>", lambda _e, n=name: open_dashboard(n))

    shown = [j for j in jobs if status_filter == "All" or j.get("status", "Saved") == status_filter]
    shown.reverse()  # newest first

    if not shown:
        message = ("No jobs saved yet. Use Search or Add Job to get started." if not jobs
                   else f"No jobs with status '{status_filter}'.")
        tk.Label(body, text=message, font=("Arial", 12), bg=WHITE, fg=MUTED).pack(pady=30)
        return

    scroll = ScrollFrame(body)
    scroll.pack(fill="both", expand=True)
    for job in shown:
        dashboard_job_card(scroll.inner, job, status_filter)


# ============================================================
# INTERVIEW CALENDAR
# ============================================================

def open_interview_editor(job_id=None, initial_date=None):
    """Show the schedule form inline on the calendar page (no pop-up window)."""
    jobs = my_jobs()
    if not jobs:
        messagebox.showinfo("JobTrac", "Save a job before scheduling an interview.")
        return
    day = None
    for candidate in (initial_date,
                      next((j.get("interview_date") for j in jobs
                            if str(j.get("id")) == str(job_id)), None)):
        try:
            day = datetime.strptime(candidate, "%Y-%m-%d").date()
            break
        except (TypeError, ValueError):
            continue
    day = day or date.today()
    open_calendar(day.year, day.month, day.day, editor={"job_id": job_id})


def build_interview_form(parent, editor, selected_iso, year, month, day):
    """Inline schedule/edit form shown in the calendar's right-hand panel."""
    jobs = my_jobs()
    labels = [f"{i + 1}. {j.get('title', 'Job')} — {_text(j.get('company'))}"[:46]
              for i, j in enumerate(jobs)]
    selected = 0
    for index, job in enumerate(jobs):
        if str(job.get("id")) == str(editor.get("job_id")):
            selected = index
            break

    outer, inner = card(parent)
    outer.pack(fill="x")
    tk.Label(inner, text="Schedule interview", font=("Arial", 14, "bold"), bg=WHITE,
             fg=BLACK).pack(anchor="w", pady=(0, 6))
    tk.Label(inner, text="Saved job", font=("Arial", 10, "bold"), bg=WHITE, fg=BLACK).pack(anchor="w")
    chosen = tk.StringVar(value=labels[selected])
    selector = ttk.Combobox(inner, values=labels, textvariable=chosen, state="readonly",
                            width=30, font=("Arial", 10))
    selector.pack(fill="x", pady=(3, 6), ipady=3)

    frame, date_entry = field(inner, "Date (YYYY-MM-DD)", width=24)
    frame.pack(fill="x", pady=3)
    frame, time_entry = field(inner, "Time (24-hour HH:MM)", width=24)
    frame.pack(fill="x", pady=3)
    frame, note_entry = field(inner, "Notes (optional)", width=24)
    frame.pack(fill="x", pady=3)

    def fill_fields(_event=None):
        job = jobs[labels.index(chosen.get())]
        for entry, value in ((date_entry, job.get("interview_date") or selected_iso),
                             (time_entry, job.get("interview_time") or "10:00"),
                             (note_entry, job.get("interview_notes") or "")):
            entry.delete(0, "end")
            entry.insert(0, value)

    selector.bind("<<ComboboxSelected>>", fill_fields)
    fill_fields()
    date_entry.delete(0, "end")  # the day you clicked wins for the initially chosen job
    date_entry.insert(0, selected_iso)

    def save():
        try:
            job = jobs[labels.index(chosen.get())]
            picked = datetime.strptime(date_entry.get().strip(), "%Y-%m-%d").date()
            time_value = datetime.strptime(time_entry.get().strip(), "%H:%M").strftime("%H:%M")
        except ValueError:
            messagebox.showerror("Invalid interview",
                                 "Use YYYY-MM-DD for the date and HH:MM for the time.")
            return
        changes = {"interview_date": picked.isoformat(), "interview_time": time_value,
                   "interview_notes": note_entry.get().strip()}
        if job.get("status", "Saved") in ("Saved", "Applied"):
            changes["status"] = "Interviewing"
        update_job(job["id"], **changes)
        open_calendar(picked.year, picked.month, picked.day)

    def remove():
        job = jobs[labels.index(chosen.get())]
        update_job(job["id"], interview_date=None, interview_time=None, interview_notes=None)
        open_calendar(year, month, day)

    FlatButton(inner, "Save Interview", save, "primary", pady=7).pack(fill="x", pady=(10, 4))
    row = tk.Frame(inner, bg=WHITE)
    row.pack(fill="x")
    FlatButton(row, "Remove", remove, "danger", pady=5).pack(side="left", fill="x", expand=True, padx=(0, 3))
    FlatButton(row, "Cancel", lambda: open_calendar(year, month, day), "outline", pady=5).pack(
        side="left", fill="x", expand=True, padx=(3, 0))


def open_calendar(year=None, month=None, selected_day=None, editor=None):
    today = date.today()
    year = year or today.year
    month = month or today.month
    if selected_day is None:
        selected_day = today.day if (year, month) == (today.year, today.month) else 1
    selected_day = min(selected_day, calendar.monthrange(year, month)[1])

    body = build_shell("calendar")
    page_title(body, "Interview Calendar", "Red days have interviews scheduled.")

    jobs = my_jobs()
    by_date = {}
    for job in jobs:
        if job.get("interview_date"):
            by_date.setdefault(job["interview_date"], []).append(job)

    layout = tk.Frame(body, bg=WHITE)
    layout.pack(fill="both", expand=True)
    left = tk.Frame(layout, bg=WHITE)
    left.pack(side="left", fill="both", expand=True)
    right = tk.Frame(layout, bg=WHITE, width=300)
    right.pack(side="left", fill="y", padx=(20, 0))
    right.pack_propagate(False)

    # --- month navigation
    previous_month = date(year - 1, 12, 1) if month == 1 else date(year, month - 1, 1)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    nav = tk.Frame(left, bg=WHITE)
    nav.pack(fill="x", pady=(0, 8))
    FlatButton(nav, "‹ Prev", lambda: open_calendar(previous_month.year, previous_month.month, 1),
               "outline").pack(side="left")
    tk.Label(nav, text=f"{calendar.month_name[month]} {year}", font=("Arial", 17, "bold"),
             bg=WHITE, fg=BLACK).pack(side="left", expand=True)
    FlatButton(nav, "Today", lambda: open_calendar(), "dark").pack(side="right", padx=(6, 0))
    FlatButton(nav, "Next ›", lambda: open_calendar(next_month.year, next_month.month, 1),
               "outline").pack(side="right")

    # --- month grid
    grid = tk.Frame(left, bg=WHITE)
    grid.pack(fill="both", expand=True)
    for col, weekday in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
        grid.columnconfigure(col, weight=1, uniform="day")
        tk.Label(grid, text=weekday, font=("Arial", 10, "bold"), bg=BLACK, fg=WHITE,
                 pady=5).grid(row=0, column=col, sticky="nsew", padx=1, pady=(0, 2))
    for row, week in enumerate(calendar.monthcalendar(year, month), start=1):
        grid.rowconfigure(row, weight=1)
        for col, day in enumerate(week):
            if day == 0:
                tk.Label(grid, text="", bg=WHITE).grid(row=row, column=col, sticky="nsew")
                continue
            key = date(year, month, day).isoformat()
            events = len(by_date.get(key, []))
            is_selected = day == selected_day
            is_today = key == today.isoformat()
            if is_selected:
                bg, fg, border = BLACK, WHITE, BLACK
            elif events:
                bg, fg, border = RED, WHITE, RED
            else:
                bg, fg, border = WHITE, BLACK, RED if is_today else LINE
            text = f"{day}\n{'●' * min(events, 3)}" if events else f"{day}\n "
            cell = tk.Label(grid, text=text, font=("Arial", 11, "bold" if (events or is_today) else "normal"),
                            bg=bg, fg=RED if (is_selected and events) else fg, cursor="hand2",
                            highlightthickness=2 if is_today else 1, highlightbackground=border,
                            pady=6)
            cell.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
            cell.bind("<Button-1>", lambda _e, d=day: open_calendar(year, month, d, editor=editor))

    # --- selected-day details
    selected_date = date(year, month, selected_day)
    tk.Label(right, text=selected_date.strftime("%A"), font=("Arial", 10), bg=WHITE,
             fg=MUTED).pack(anchor="w")
    tk.Label(right, text=pretty_date(selected_date.isoformat()), font=("Arial", 16, "bold"),
             bg=WHITE, fg=BLACK).pack(anchor="w")
    tk.Frame(right, bg=RED, width=40, height=3).pack(anchor="w", pady=(3, 8))

    if editor is not None:
        build_interview_form(right, editor, selected_date.isoformat(), year, month, selected_day)
        tk.Frame(right, bg=WHITE, height=14).pack()
    else:
        events = sorted(by_date.get(selected_date.isoformat(), []), key=lambda j: j.get("interview_time", ""))
        if not events:
            tk.Label(right, text="No interviews scheduled.", font=("Arial", 11), bg=WHITE,
                     fg=MUTED).pack(anchor="w")
        for event in events:
            outer, inner = card(right)
            outer.pack(fill="x", pady=3)
            tk.Label(inner, text=pretty_time(event.get("interview_time", "")), font=("Arial", 11, "bold"),
                     bg=WHITE, fg=RED).pack(anchor="w")
            tk.Label(inner, text=f"{event.get('title', 'Job')}\n{_text(event.get('company'))}",
                     font=("Arial", 10), bg=WHITE, fg=BLACK, wraplength=220, justify="left").pack(anchor="w")
            if event.get("interview_notes"):
                tk.Label(inner, text=event["interview_notes"], font=("Arial", 9, "italic"), bg=WHITE,
                         fg=MUTED, wraplength=220, justify="left").pack(anchor="w")
            FlatButton(inner, "Edit", lambda jid=str(event.get("id")), d=selected_date.isoformat():
                       open_interview_editor(jid, d), "outline", size=9, pady=3).pack(anchor="w", pady=(6, 0))

        FlatButton(right, "+ Schedule Interview",
                   lambda d=selected_date.isoformat(): open_interview_editor(initial_date=d),
                   "primary", size=10, pady=8).pack(fill="x", pady=(10, 14))


    tk.Label(right, text="Upcoming", font=("Arial", 12, "bold"), bg=WHITE, fg=BLACK).pack(anchor="w")
    upcoming = sorted(
        ((k, j) for k, items in by_date.items() if k >= today.isoformat() for j in items),
        key=lambda pair: (pair[0], pair[1].get("interview_time", "")))[:5]
    if not upcoming:
        tk.Label(right, text="Nothing coming up.", font=("Arial", 10), bg=WHITE, fg=MUTED).pack(anchor="w")
    for key, job in upcoming:
        link = tk.Label(right, text=f"{pretty_date(key)} {pretty_time(job.get('interview_time', ''))}  "
                                    f"{job.get('title', 'Job')}",
                        font=("Arial", 10), bg=WHITE, fg=RED, cursor="hand2", anchor="w",
                        wraplength=270, justify="left")
        link.pack(anchor="w", pady=2)
        target = datetime.strptime(key, "%Y-%m-%d").date()
        link.bind("<Button-1>", lambda _e, t=target: open_calendar(t.year, t.month, t.day))


# ============================================================
# MANUAL JOB ENTRY
# ============================================================

def manual_job_entry():
    body = build_shell("add")
    page_title(body, "Add a Job", "Track a role you found anywhere else.")

    outer, inner = card(body)
    outer.pack(fill="x")
    entries = {}
    for key, text in (("title", "Job Title *"), ("company", "Company *"), ("location", "Location"),
                      ("url", "Application URL (https://...)"), ("notes", "Notes (optional)")):
        frame, entries[key] = field(inner, text, width=60)
        frame.pack(fill="x", pady=5)

    def save():
        title = entries["title"].get().strip()
        company = entries["company"].get().strip()
        location = entries["location"].get().strip()
        url = entries["url"].get().strip()
        notes = entries["notes"].get().strip()
        if not title or not company:
            messagebox.showerror("Missing Information", "Please enter both a job title and company.")
            return
        if url and not url.startswith(("http://", "https://")):
            messagebox.showerror("Invalid URL", "The application URL must start with http:// or https://.")
            return
        for job in my_jobs():
            if (str(job.get("title", "")).strip().lower() == title.lower()
                    and str(_text(job.get("company"))).strip().lower() == company.lower()):
                messagebox.showwarning("Duplicate Job", "This job already exists in your dashboard.")
                return
        try:
            jobs = read_all_jobs()
            jobs.append({
                "id": f"manual_{uuid.uuid4().hex}", "owner": current_username, "title": title,
                "company": company, "location": location or "Not specified", "url": url,
                "notes": notes, "status": "Saved", "source": "Manual",
                "added": date.today().isoformat()})
            write_all_jobs(jobs)
        except (OSError, TypeError, ValueError) as exc:
            messagebox.showerror("Save Error", f"Could not save the job:\n{exc}")
            return
        messagebox.showinfo("Success", f"{title} at {company} was added to your dashboard!")
        open_dashboard()

    actions = tk.Frame(inner, bg=WHITE)
    actions.pack(anchor="w", pady=(14, 4))
    FlatButton(actions, "Save Job", save, "primary", size=11, pady=8).pack(side="left", padx=(0, 10))
    FlatButton(actions, "Cancel", lambda: open_main_app(current_username), "outline", size=11,
               pady=8).pack(side="left")
    entries["title"].focus()


# ============================================================
# START
# ============================================================

def close_app():
    try:
        conn.close()
    finally:
        root.destroy()


root.protocol("WM_DELETE_WINDOW", close_app)

if __name__ == "__main__":
    show_login_screen()
    root.mainloop()