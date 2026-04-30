# 🔐 Secure Messenger

<p align="center">
  <strong>Private • Decentralized • Encrypted</strong>
</p>

<p align="center">
  A secure messaging application that puts your privacy first.
</p>

---

## ⚠️ Security Notice

> This application handles sensitive cryptographic material. Please read the [Security Guidelines](#-security-guidelines) before use.

---

## ✨ Overview

Secure Messenger enables private communication through:

- **End-to-end encryption** — Messages are encrypted on your device and can only be read by the intended recipient
- **Decentralized architecture** — No central server stores your messages in readable form
- **Wallet-based identity** — Your identity is derived from a cryptographic mnemonic phrase you control
- **Local-first design** — Sensitive data stays on your device

---

## 🚀 Getting Started

### Requirements
- Python 3.8+
- Modern web browser (Chrome, Firefox, Edge, Safari)
- Internet connection for peer communication

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd secure-messenger

# Install dependencies
pip install -r requirements.txt

# Start the application
python app.py
```

Visit `http://localhost:5000` in your browser.

### First-Time Setup

1. **Create or import your wallet**
   - New users: Click "Create Wallet" and **securely save** your mnemonic phrase
   - Returning users: Click "Login" and enter your mnemonic phrase

2. **Add contacts**
   - Share your address (64-character hex string) with contacts
   - Add contacts manually or via QR code scan

3. **Start messaging**
   - Select a contact and begin encrypted communication

---

## 🔐 Security Guidelines

### 🛡️ Protect Your Mnemonic

Your mnemonic phrase is the **master key** to your identity and messages.

✅ **DO:**
- Write it down and store in a secure, offline location
- Use a reputable password manager for digital storage
- Verify the full phrase before saving

❌ **NEVER:**
- Share your mnemonic with anyone
- Enter it on websites you don't fully trust
- Store it in plain text files, emails, or cloud notes
- Take screenshots or photos of it

> ⚠️ **If your mnemonic is compromised, your identity and messages can be accessed by others. There is no "password reset" — your mnemonic is irreplaceable.**

### 🔒 Session Security

- Sessions expire after a configurable period of inactivity
- Always click **Logout** when using shared or public devices
- Clear your browser cache after sensitive sessions

### 📱 Device Security

- Keep your operating system and browser updated
- Use device encryption (BitLocker, FileVault, etc.)
- Avoid using the application on rooted/jailbroken devices
- Be cautious of browser extensions that can read page content

### 🌐 Network Security

- Use HTTPS in production deployments
- Avoid public Wi-Fi for sensitive communications
- Consider using a trusted VPN for additional privacy

---

## 📱 Features

### Messaging
- Send encrypted text messages
- Share images with automatic encryption
- View message history with local decryption
- Delete your own messages locally

### Contacts
- Manage your address book securely
- Scan QR codes for easy contact addition
- Verify contact identities via public key fingerprint

### Groups
- Create encrypted group conversations
- Add/remove members with cryptographic access control
- Group messages are encrypted individually per member

### Privacy Tools
- Export your mnemonic securely (with confirmation)
- Clear conversation history locally
- View your public address for sharing

---

## ⚙️ Configuration (For Administrators)

Basic configuration via environment variables:

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Session encryption (generate securely) |
| `FLASK_ENV` | Set to `production` for production settings |
| `DATABASE_PATH` | Location of the local database file |
| `UPLOAD_FOLDER` | Directory for temporary file handling |

> 🔐 **Never commit `.env` files or secrets to version control.**

See `config.example` for a template with safe defaults.

---

## 🆘 Support

### Common Issues

| Issue | Solution |
|-------|----------|
| "Invalid mnemonic" on login | Verify all 24 words are entered correctly, in order, with single spaces |
| Messages not sending | Check internet connection; ensure recipient address is valid (64 hex chars) |
| Camera not working for QR | Allow camera permissions in browser; try HTTPS if on remote server |
| Session expires frequently | Increase `SESSION_LIFETIME` in configuration (balance with security) |

### Getting Help

- Review the [Security Guidelines](#-security-guidelines) first
- Check browser console for error messages (F12 → Console)
- Ensure you're running the latest version
- For technical issues: open an issue with **no sensitive information**

---

## 🤝 Contributing

We welcome responsible contributions.

### Before Contributing

1. Read our [Security Policy](SECURITY.md)
2. Never include real keys, mnemonics, or user data in PRs
3. Test changes in an isolated environment first

### Contribution Guidelines

- Follow existing code style and security patterns
- Add tests for new functionality
- Document user-facing changes
- Security fixes: coordinate privately first (see SECURITY.md)

---

## 📜 License

This project is licensed under the MIT License. See the LICENSE file for details.

---

## 🔗 Resources

- [Understanding Mnemonic Phrases](https://bitcoin.org/en/developer-guide#mnemonic-code)
- [Browser Security Best Practices](https://developer.mozilla.org/en-US/docs/Web/Security)
- [HTTPS Configuration Guide](https://https.cio.gov/)

---

<p align="center">
  <sub>🔐 Your keys, your messages, your responsibility.</sub>
</p>

> ℹ️ This README intentionally omits implementation details to protect user security. For architectural documentation, please contact the maintainers directly.