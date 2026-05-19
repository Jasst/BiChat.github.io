```markdown
# 🔐 Dark Messenger

**Private • Decentralized • Encrypted — with built‑in rewards**

A secure messaging application that protects your privacy and lets you earn cryptocurrency just by chatting.

---

## ✨ Overview

- **End‑to‑end encryption** – only you and the recipient can read messages
- **Decentralized** – no central server stores your data in plain text
- **Proof of Writing** – send messages and earn COIN through a fair lottery
- **Built‑in wallet** – send, receive and hold COIN inside the app
- **Identity from mnemonic** – you control your keys, no registration

---

## 🚀 Quick Start

### Requirements
- Python 3.8+
- Modern browser

### Installation

```bash
git clone <repo-url>
cd dark-messenger
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000` and either create a new wallet or login with your existing 24‑word mnemonic.

---

## 📱 Features

### 💬 Encrypted Messaging
- Text messages and images encrypted with hybrid ECDH + AES‑GCM
- Group chats with per‑member encryption
- Delete your own messages anytime

### 💰 Wallet & Proof of Writing
- **Earn COIN** – every message you send gives you a lottery ticket
- Every 30 minutes one random sender wins the current reward
- Reward halves periodically (every ~1000 payouts)
- **Send COIN** to any address (manual input or QR scan)
- **Receive COIN** by showing your address or QR code
- Transfers include a **0.01 COIN fee** to prevent spam

### 👥 Contacts & Groups
- Add contacts manually or by scanning a QR code
- Create encrypted group conversations
- Manage group members (creator controls)

### 🔐 Profile & Security
- View your public address and QR code
- Export your mnemonic phrase (with double confirmation)
- Session management and logout

---

## 🛡️ Security Guidelines

- **Your mnemonic phrase is your master key** – write it down, never share it
- **No password reset** – if you lose your mnemonic, your identity and funds are lost
- Always **logout** on shared devices
- Use HTTPS in production

---

## 🪙 Wallet Details

- **Unit**: 1 COIN = 1 000 000 minimal units
- **Earning**: send any message (group or private) to enter the lottery
- **Sending**: enter recipient’s 64‑hex address or scan their QR; a fixed **0.01 COIN fee** is deducted
- **Receiving**: share your address or QR – no action needed
- **History**: view all rewards and transfers in the Wallet tab

---

## ⚙️ Configuration (Admins)

Basic environment variables (`.env` or system):

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Session encryption (generate a strong random key) |
| `FLASK_ENV` | Set to `production` for production settings |
| `DATABASE_PATH` | Location of the SQLite database |
| `UPLOAD_FOLDER` | Temporary file storage |
| `COIN` | Minimal units per coin (default `1000000`) |
| `TRANSFER_FEE` | Fee per transfer in minimal units (default `10000`) |
| `POW_DIFFICULTY` | Proof‑of‑work difficulty for block mining |

> 🔐 Never commit secrets to version control.

---

## 🆘 Support

- Check browser console (F12) for errors
- Make sure your mnemonic is entered correctly (24 words, single spaces)
- For camera issues, allow browser permissions or use HTTPS
- Ensure the recipient address is exactly 64 hex characters

---

## 📜 License

MIT License. See `LICENSE` for details.

---

<p align="center">
  <sub>🔐 Your keys, your messages, your coins. Stay safe.</sub>
</p>
