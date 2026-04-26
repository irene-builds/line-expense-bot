from flask import Flask, request
import requests
import os
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# ✅ 先直接寫死（之後再改 env）
LINE_ACCESS_TOKEN = os.getenv("rSved7PHDjfPgW9GB+ZE0Ho0y0kZoMlxcHqIs+iqqfqx81gl+rH9vQOuKwTI2A/HCy1erWswXz0viuWf/dcY4NmPBdkNSdUhlXwJH+ceMLXtyxNWkI08HFFpXfPP/Y+QZKl4Nae0SeGXFnJzv1ofLwdB04t89/1O/w1cDnyilFU="
)
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


def reply_message(reply_token, text):
    headers = {
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    body = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=body)
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

            # 🔥 新增分類功能
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