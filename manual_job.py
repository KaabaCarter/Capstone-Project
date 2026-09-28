
import tkinter as tk
from tkinter import messagebox


def open_manual_job_window():

    # Create the manual job window
    window = tk.Toplevel()
    window.title("Add Job Manually")
    window.geometry("450x500")

    # Page title
    title_label = tk.Label(
        window,
        text="Add a Job",
        font=("Arial", 20, "bold")
    )
    title_label.pack(pady=20)

    # Job Title
    tk.Label(window, text="Job Title").pack()

    job_title_entry = tk.Entry(window, width=40)
    job_title_entry.pack(pady=5)

    # Company
    tk.Label(window, text="Company").pack()

    company_entry = tk.Entry(window, width=40)
    company_entry.pack(pady=5)

    # Location
    tk.Label(window, text="Location").pack()

    location_entry = tk.Entry(window, width=40)
    location_entry.pack(pady=5)

    # Job URL
    tk.Label(window, text="Job URL").pack()

    url_entry = tk.Entry(window, width=40)
    url_entry.pack(pady=5)

    # Save button
    save_button = tk.Button(
        window,
        text="Save Job"
    )
    save_button.pack(pady=25)
