from flask import Flask, request
import requests
import os
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
print("TOKEN exists:", LINE_ACCESS_TOKEN is not None)
print("TOKEN length:", len(LINE_ACCESS_TOKEN) if LINE_ACCESS_TOKEN else 0)
print("TOKEN prefix:", LINE_ACCESS_TOKEN[:5] if LINE_ACCESS_TOKEN else "None")
print("TOKEN suffix:", LINE_ACCESS_TOKEN[-5:] if LINE_ACCESS_TOKEN else "None")

# Google Sheets 設定
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

import os
import json

google_credentials_str = os.getenv("GOOGLE_CREDENTIALS")

if not google_credentials_str:
    raise ValueError("GOOGLE_CREDENTIALS not set")

google_credentials = json.loads(google_credentials_str)

creds = Credentials.from_service_account_info(
    google_credentials,
    scopes=SCOPES
)

client = gspread.authorize(creds)

spreadsheet = client.open("Expense record")
expense_sheet = spreadsheet.worksheet("Record list")
category_sheet = spreadsheet.worksheet("Category setting")


# 讀分類
def load_category_keywords():
    records = category_sheet.get_all_records()
    category_keywords = {}

    for record in records:
        category = record.get("Category")
        keywords = record.get("Keyword")

        if category and keywords:
            keyword_list = [k.strip() for k in keywords.split(",")]
            category_keywords[category] = keyword_list

    return category_keywords


def classify(text):
    category_keywords = load_category_keywords()
    text_lower = text.lower()

    for category, keywords in category_keywords.items():
        for keyword in keywords:
            if keyword.lower() in text_lower:
                return category

    return "Other"

def get_monthly_summary():
    records = expense_sheet.get_all_records()
    current_month = datetime.now().strftime("%Y-%m")

    total = 0
    category_totals = {}

    for record in records:
        date = str(record.get("Date"))
        category = record.get("Category")
        price = record.get("Price")

        if date.startswith(current_month):
            try:
                price = int(price)
            except:
                continue

            total += price
            category_totals[category] = category_totals.get(category, 0) + price

    if total == 0:
        return "本月目前還沒有記帳資料"

    lines = [f"本月總花費：{total} 元"]

    for category, amount in category_totals.items():
        lines.append(f"{category}：{amount} 元")

    return "\n".join(lines)

def reply_message(reply_token, text):
    headers = {
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    body = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }

    response = requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers=headers,
        json=body
    )

    print("LINE reply status:", response.status_code)
    print("LINE reply response:", response.text)


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if not data:
        return "OK", 200

    for event in data.get("events", []):
        if event.get("type") == "message":
            msg = event["message"]["text"]
            reply_token = event["replyToken"]

           # 🔥 本月花費查詢
            if msg == "本月花費":
                summary = get_monthly_summary()
                reply_message(reply_token, summary)
                continue

            # 🔥 分類功能
            if msg.startswith("新增分類"):
                parts = msg.split()

                if len(parts) >= 3:
                    category = parts[1]
                    keywords = ",".join(parts[2:])

                    category_sheet.append_row([category, keywords])

                    reply_message(reply_token, f"已新增分類：{category}｜關鍵字：{keywords}")
                else:
                    reply_message(reply_token, "請輸入格式：新增分類 類別 關鍵字1 關鍵字2")

                continue

            # 🔥 記帳功能
            parts = msg.split()

            if len(parts) >= 2 and parts[-1].isdigit():
                price = parts[-1]
                item = " ".join(parts[:-1])
                category = classify(item)
                date = datetime.now().strftime("%Y-%m-%d")

                expense_sheet.append_row([date, category, item, price, msg])

                reply_message(reply_token, f"已記帳：{date}｜{category}｜{item}｜{price} 元")
            else:
                reply_message(reply_token, "請輸入格式：項目 金額，例如：午餐 120")

    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "LINE Bot is running!", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))