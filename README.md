# Jos_mag📰 The Chronicle Bot — Telegram Breaking News Bot

A production-ready Python bot that delivers breaking world news
from BBC, Reuters, and Al Jazeera to your Telegram chat every hour.

---

## 🗂 Project Structure
chronicle-bot/
├── main.py           # Main bot logic
├── requirements.txt  # Python dependencies
└── README.md         # This file
---

## ⚙️ Step 1 — Create Your Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **API token** you receive (looks like `123456:ABC-DEF...`)
4. To get your **Chat ID**:
   - Start a chat with your bot
   - Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Find the `"id"` field inside `"chat"` in the JSON response
   - 
