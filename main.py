import tkinter as tk
from tkinter import messagebox

# Create the main window
root = tk.Tk()
root.title("JobTrac")
root.attributes("-fullscreen", True)
root.resizable(True, True)

# Login function
def login():
    username = username_entry.get()
    password = password_entry.get()

    # Example login credentials
    if username == "admin" and password == "1234":
        messagebox.showinfo("Login Successful", "Welcome!")
    else:
        messagebox.showerror("Login Failed", "Incorrect username or password.")


# Title
title_label = tk.Label(
    root,
    text="Login",
    font=("Arial", 24, "bold")
)
title_label.pack(pady=25)


# Username
username_label = tk.Label(
    root,
    text="Username",
    font=("Arial", 12)
)
username_label.pack()

username_entry = tk.Entry(
    root,
    width=30,
    font=("Arial", 12)
)
username_entry.pack(pady=5)


# Password
password_label = tk.Label(
    root,
    text="Password",
    font=("Arial", 12)
)
password_label.pack()

password_entry = tk.Entry(
    root,
    width=30,
    font=("Arial", 12),
    show="*"
)
password_entry.pack(pady=5)


# Login button
login_button = tk.Button(
    root,
    text="Login",
    width=15,
    font=("Arial", 12),
    command=login
)
login_button.pack(pady=20)


# Run the application
root.mainloop()