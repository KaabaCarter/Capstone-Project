
import tkinter as tk
import json
import webbrowser
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

APP_ID = "7757f192"
APP_KEY = "8a25186bd7572c44b87a3819322588d3"


def search_jobs():
    description = search_box.get().strip()

    if not description:
        results.delete("1.0", tk.END)
        results.insert(tk.END, "Please enter a job description.")
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
    results.insert(tk.END, "Searching...\n\n")

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

    results.delete("1.0", tk.END)

    jobs = data.get("results", [])

    if not jobs:
        results.insert(
            tk.END,
            "No jobs found for that search."
        )
        return

    for job in jobs:

        title = job.get("title", "No title")

        company = job.get(
            "company", {}
        ).get(
            "display_name",
            "Unknown company"
        )

        location = job.get(
            "location", {}
        ).get(
            "display_name",
            "Unknown location"
        )

        job_url = job.get("redirect_url")

        # -------------------------
        # Job information
        # -------------------------

        results.insert(
            tk.END,
            f"{title}\n"
            f"Company: {company}\n"
            f"Location: {location}\n"
        )

        # -------------------------
        # Clickable links
        # -------------------------

        if job_url:

            # Apply Here link
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

            # Actual URL
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
            "-" * 50 + "\n\n"
        )


# -------------------------
# Window
# -------------------------

root = tk.Tk()

root.title("Job Search")

root.geometry("700x600")


# -------------------------
# Search question
# -------------------------

tk.Label(
    root,
    text="What type of job are you looking for?",
    font=("Arial", 12)
).pack(pady=10)


# -------------------------
# Search box
# -------------------------

search_box = tk.Entry(
    root,
    width=60
)

search_box.pack()


# -------------------------
# Search button
# -------------------------

tk.Button(
    root,
    text="Search Jobs",
    command=search_jobs
).pack(pady=10)


# -------------------------
# Results box
# -------------------------

results = tk.Text(
    root,
    width=80,
    height=25
)

results.pack(pady=10)


root.mainloop()

