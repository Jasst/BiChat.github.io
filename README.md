# 🔐 Dark Messenger

**Decentralized, end‑to‑end encrypted messenger with built‑in cryptocurrency wallet, WebRTC calls, and self‑improving AI assistant.**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-blueviolet) ![License](https://img.shields.io/badge/License-MIT-orange)

---

## ✨ Features

- **🔒 End‑to‑end encryption** – ECDH + AES‑GCM, perfect forward secrecy.
- **💬 Private & group chats** – with read receipts, delivery status, and message history.
- **📞 WebRTC calls** – audio/video with TURN/STUN fallback, call history, and mini‑widget.
- **💰 Built‑in cryptocurrency wallet** – send/receive `BlockCoin`, stake, and mine blocks (PoW).
- **🧠 AI assistant** – self‑improving, with long‑term memory, web search, image generation, and reasoning mode.
- **🌐 Decentralised by design** – no central server stores your private keys or message content.
- **📱 Progressive Web App** – install on your phone, get push notifications.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Client (PWA)                        │
│   ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌────────────┐  │
│   │   Chat  │  │  Calls  │  │  Wallet  │  │  AI Chat   │  │
│   └────┬────┘  └────┬────┘  └────┬─────┘  └─────┬──────┘  │
│        │            │            │               │         │
│        └────────────┼────────────┼───────────────┘         │
│                     │            │                         │
│              ┌──────▼────────────▼───────┐                 │
│              │    Service Worker (Push)   │                 │
│              └────────────┬───────────────┘                 │
└───────────────────────────┼─────────────────────────────────┘
                            │ (WebSocket / HTTPS)
┌───────────────────────────▼─────────────────────────────────┐
│                        FastAPI Server                        │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌──────────┐ │
│  │   Auth    │  │ Messages  │  │   Calls   │  │   AI     │ │
│  │  & Users  │  │  & Groups │  │  WebRTC   │  │Assistant │ │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └────┬─────┘ │
│        │              │              │             │       │
│        └──────────────┼──────────────┼─────────────┘       │
│                       │              │                     │
│                ┌──────▼──────────────▼──────┐              │
│                │    PostgreSQL + asyncpg      │              │
│                │  (blocks, txs, contacts,    │              │
│                │   groups, push subscriptions)│              │
│                └──────────────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
          ┌───▼───┐     ┌───▼───┐    ┌────▼────┐
          │ Nginx │     │ Coturn│    │ LM Studio│
          │(static│     │(TURN) │    │(LLM API)│
          │ & TLS)│     │       │    │         │
          └───────┘     └───────┘    └─────────┘
```

---

## 🧩 Technology Stack

| Component          | Technology                                                                 |
|--------------------|----------------------------------------------------------------------------|
| **Backend**        | Python 3.10+, FastAPI, Uvicorn, asyncio                                   |
| **Database**       | PostgreSQL 15+ (with asyncpg)                                             |
| **Crypto**         | Web Crypto API (client), cryptography (server)                            |
| **WebRTC**         | Coturn (TURN/STUN), native `RTCPeerConnection`                            |
| **AI**             | LM Studio (local LLM), PyTorch (embeddings, LoRA), DuckDuckGo search     |
| **Push**           | Web Push API + VAPID, Service Worker                                      |
| **Frontend**       | Vanilla JS, PWA, i18next, Marked, Highlight.js, QRCode.js                |
| **Container**      | Docker + docker-compose (Nginx, Coturn)                                  |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL 15+
- Docker & docker-compose (optional, for TURN/STUN)
- LM Studio (if you want AI features)
- Node.js (for frontend tooling, optional)

### Quick Start (production)

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/dark-messenger.git
cd dark-messenger

# 2. Set up environment
cp .env.example .env
# Edit .env with your database URL, secret keys, etc.

# 3. Install dependencies
python -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# 4. Initialize the database
python -c "from database import init_db; import asyncio; asyncio.run(init_db())"

# 5. Start the server
python run.py
```

The server will be available at `http://localhost:8000`.

### Using Docker (recommended for TURN)

```bash
# Start Nginx and Coturn
docker-compose up -d

# Run the FastAPI server (as above)
python run.py
```

---

## 🧠 AI Assistant Setup

1. Download and install [LM Studio](https://lmstudio.ai/)
2. Load a compatible model (e.g., `Qwen/Qwen2.5-14B-Instruct-GGUF`)
3. Start the local inference server (port `1234` by default)
4. Configure `config_ai.py`:
   ```python
   LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
   ```
5. Restart the server – AI features will be available.

---

## 🔐 Security Model

- **Keys**: Your mnemonic phrase never leaves your browser. It is encrypted with PBKDF2 and stored locally.
- **Messages**: Encrypted with ECDH + AES‑GCM per recipient, including group chats.
- **Files**: Uploaded files are encrypted on the client before being stored on the server.
- **WebSocket**: Authenticated via signature challenge using the user’s private key.
- **Push**: End‑to‑end encryption is still respected – push payloads are just notifications.

---

## 📁 Project Structure (highlights)

```
dark-messenger/
├── static/                 # Frontend assets
│   ├── css/
│   ├── js/                 # All client-side logic
│   ├── locales/            # i18n translations
│   └── sw.js               # Service Worker
├── routes/                 # FastAPI route handlers
│   ├── auth.py
│   ├── messages.py
│   ├── calls.py
│   ├── wallet.py
│   └── ws.py               # WebSocket manager
├── services/               # Business logic
│   ├── messaging.py
│   ├── wallet.py
│   ├── notifier.py
│   ├── push.py
│   └── contacts.py
├── templates/              # Jinja2 HTML templates
├── config.py               # Core configuration
├── config_ai.py            # AI-specific config
├── database.py             # PostgreSQL + blockchain logic
├── main.py                 # FastAPI application factory
├── run.py                  # Uvicorn launcher
└── docker-compose.yml      # Nginx + Coturn
```

---

## 🤝 Contributing

Contributions are welcome! Please open an issue or pull request.

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Commit your changes (`git commit -am 'Add my feature'`)
4. Push to the branch (`git push origin feat/my-feature`)
5. Open a PR

---

## 📄 License

MIT © 2025 – see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

- [FastAPI](https://fastapi.tiangolo.com/)
- [PostgreSQL](https://www.postgresql.org/)
- [LM Studio](https://lmstudio.ai/)
- [Coturn](https://coturn.org/)
- [i18next](https://www.i18next.com/)

---

**Made with ❤️ by the Dark Messenger team.**
