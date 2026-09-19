import tkinter as tk
from tkinter import messagebox
import sqlite3

# ---------------- DATABASE ----------------

conn = sqlite3.connect("users.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password TEXT NOT NULL
)
""")

conn.commit()


# ---------------- REGISTER ----------------

def register():
    username = username_entry.get()
    password = password_entry.get()

    if username == "" or password == "":
        messagebox.showerror("Error", "Please enter a username and password.")
        return

    try:
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, password)
        )

        conn.commit()

        messagebox.showinfo("Success", "Account created!")

        username_entry.delete(0, tk.END)
        password_entry.delete(0, tk.END)

    except sqlite3.IntegrityError:
        messagebox.showerror("Error", "Username already exists.")


# ---------------- LOGIN ----------------

def login():
    username = username_entry.get()
    password = password_entry.get()

    cursor.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?",
        (username, password)
    )

    user = cursor.fetchone()

    if user:
        messagebox.showinfo("Success", "Login successful!")
        open_main_app()
    else:
        messagebox.showerror("Error", "Invalid username or password.")


# ---------------- MAIN APP ----------------

def open_main_app():
    login_window.destroy()

    app = tk.Tk()
    app.title("JobTrac")
    app.geometry("800x600")

    tk.Label(
        app,
        text="Welcome to JobTrac!",
        font=("Arial", 24)
    ).pack(pady=100)

    app.mainloop()


# ---------------- LOGIN WINDOW ----------------

login_window = tk.Tk()
login_window.title("Login")
login_window.geometry("400x300")

tk.Label(
    login_window,
    text="Login",
    font=("Arial", 24)
).pack(pady=20)

tk.Label(login_window, text="Username").pack()

username_entry = tk.Entry(login_window)
username_entry.pack(pady=5)

tk.Label(login_window, text="Password").pack()

password_entry = tk.Entry(login_window, show="*")
password_entry.pack(pady=5)

tk.Button(
    login_window,
    text="Login",
    command=login
).pack(pady=10)

tk.Button(
    login_window,
    text="Register",
    command=register
).pack()

login_window.mainloop()


# Run the application
root.mainloop()
