import tkinter as tk
from tkinter import ttk, messagebox
import requests
from ttkthemes import ThemedStyle
import tkinter as tk

# URL вашего сервера
BASE_URL = 'https://jasstme.pythonanywhere.com'

# Глобальные переменные для виджетов
mnemonic_entry = None
recipient_entry = None
content_text = None
messages_list = None


# Функции для взаимодействия с сервером Flask
def create_wallet():
    response = requests.post(f'{BASE_URL}/create_wallet')
    if response.status_code == 200:
        data = response.json()
        mnemonic_phrase = data['mnemonic_phrase']
        address = data['address']
        address_var.set(address)
        mnemonic_var.set(mnemonic_phrase)
        messagebox.showinfo("Wallet Created", f"Mnemonic Phrase: {mnemonic_phrase}\nAddress: {address}")
        show_message_menu()
    else:
        messagebox.showerror("Error", "Failed to create wallet")


def login_wallet(event=None):
    mnemonic_phrase = mnemonic_entry.get()
    response = requests.post(f'{BASE_URL}/login_wallet', json={'mnemonic_phrase': mnemonic_phrase})
    if response.status_code == 200:
        data = response.json()
        address = data['address']
        address_var.set(address)
        messagebox.showinfo("Wallet Logged In", f"Address: {address}")
        show_message_menu()
    else:
        messagebox.showerror("Error", "Failed to login to wallet")


def send_message(event=None):
    address = address_var.get()
    recipient = recipient_entry.get()
    content = content_text.get("1.0", tk.END).strip()

    if not address or not recipient or not content:
        messagebox.showerror("Error", "All fields are required")
        return

    response = requests.post(f'{BASE_URL}/send_message', json={
        'mnemonic_phrase': mnemonic_var.get(),
        'recipient': recipient,
        'content': content,
        'image': None
    })

    if response.status_code == 201:
        messagebox.showinfo("Success", "Message sent")
        content_text.delete("1.0", tk.END)
    else:
        messagebox.showerror("Error", "Failed to send message")


def copy_to_clipboard(content):
    root.clipboard_clear()
    root.clipboard_append(content)
    messagebox.showinfo("Copied", "Copied to clipboard")


def paste_from_clipboard(entry):
    entry.insert(tk.END, root.clipboard_get())


def show_message_menu():
    for widget in root.winfo_children():
        widget.destroy()
    create_message_menu()


def create_message_menu():
    global recipient_entry, content_text, messages_list

    title_label = ttk.Label(root, text="Blockchain Messenger", font=("Helvetica", 18, "bold"))
    title_label.pack(pady=10)

    address_label = ttk.Label(root, text="Wallet Address:")
    address_label.pack(pady=5)

    address_frame = ttk.Frame(root)
    address_frame.pack(pady=5)

    address_display = ttk.Label(address_frame, textvariable=address_var, font=("Helvetica", 12, "bold"))
    address_display.pack(side=tk.LEFT, padx=5)

    copy_address_button = ttk.Button(address_frame, text="Copy", command=lambda: copy_to_clipboard(address_var.get()))
    copy_address_button.pack(side=tk.LEFT)

    recipient_label = ttk.Label(root, text="Recipient Address:")
    recipient_label.pack(pady=5)
    recipient_entry = ttk.Entry(root, width=50)
    recipient_entry.pack(pady=5)

    copy_recipient_button = ttk.Button(root, text="Copy", command=lambda: copy_to_clipboard(recipient_entry.get()))
    copy_recipient_button.pack(pady=5)

    paste_recipient_button = ttk.Button(root, text="Paste", command=lambda: paste_from_clipboard(recipient_entry))
    paste_recipient_button.pack(pady=5)

    content_label = ttk.Label(root, text="Message Content:")
    content_label.pack(pady=5)
    content_text = tk.Text(root, height=10, width=50)
    content_text.pack(pady=5)

    copy_content_button = ttk.Button(root, text="Copy",
                                     command=lambda: copy_to_clipboard(content_text.get("1.0", tk.END)))
    copy_content_button.pack(pady=5)

    paste_content_button = ttk.Button(root, text="Paste", command=lambda: paste_from_clipboard(content_text))
    paste_content_button.pack(pady=5)

    send_message_button = ttk.Button(root, text="Send Message", command=send_message)
    send_message_button.pack(pady=10)

    messages_frame = ttk.LabelFrame(root, text="Incoming Messages", padding=10)
    messages_frame.pack(padx=10, pady=10, fill="both", expand=True)

    messages_list = tk.Listbox(messages_frame)
    messages_list.pack(fill="both", expand=True)

    root.after(10000, check_incoming_messages)


def check_incoming_messages():
    address = address_var.get()
    if not address:
        return

    try:
        response = requests.post(f'{BASE_URL}/get_messages', json={'mnemonic_phrase': mnemonic_var.get()})
        if response.status_code == 200:
            data = response.json()
            messages = data['messages']
            messages_list.delete(0, tk.END)
            for message in messages:
                messages_list.insert(tk.END, f"From: {message['sender']} - {message['content']}")
    except Exception as e:
        print(f"Failed to fetch messages: {str(e)}")

    root.after(10000, check_incoming_messages)


def show_initial_menu():
    global mnemonic_entry

    for widget in root.winfo_children():
        widget.destroy()

    title_label = ttk.Label(root, text="Blockchain Messenger", font=("Helvetica", 18, "bold"))
    title_label.pack(pady=10)

    create_wallet_button = ttk.Button(root, text="Create Wallet", command=create_wallet)
    create_wallet_button.pack(pady=10)

    mnemonic_label = ttk.Label(root, text="Mnemonic Phrase:")
    mnemonic_label.pack(pady=5)
    mnemonic_entry = ttk.Entry(root, textvariable=mnemonic_var, width=50)
    mnemonic_entry.pack(pady=5)

    copy_mnemonic_button = ttk.Button(root, text="Copy", command=lambda: copy_to_clipboard(mnemonic_var.get()))
    copy_mnemonic_button.pack(pady=5)

    paste_mnemonic_button = ttk.Button(root, text="Paste", command=lambda: paste_from_clipboard(mnemonic_entry))
    paste_mnemonic_button.pack(pady=5)

    login_wallet_button = ttk.Button(root, text="Login Wallet", command=login_wallet)
    login_wallet_button.pack(pady=10)


# Создание графического интерфейса
root = tk.Tk()
root.title("Blockchain Messenger")
root.geometry("600x700")

# Используем тему оформления для добавления анимаций
style = ThemedStyle(root)
style.set_theme("plastik")

address_var = tk.StringVar()
mnemonic_var = tk.StringVar()

show_initial_menu()
root.mainloop()
