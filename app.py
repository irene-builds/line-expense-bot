import os
import json
from datetime import datetime

from flask import Flask, request
import requests
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


def get_or_create_worksheet(title, rows=1000, cols=10):
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


summary_sheet = get_or_create_worksheet("Monthly summary")


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


def parse_price(value):
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def build_monthly_summaries():
    records = expense_sheet.get_all_records()
    monthly_summaries = {}

    for record in records:
        date = str(record.get("Date"))
        month = date[:7]
        category = record.get("Category")
        price = parse_price(record.get("Price"))

        if len(month) != 7 or price is None:
            continue

        monthly_summary = monthly_summaries.setdefault(
            month,
            {"total": 0, "category_totals": {}}
        )

        monthly_summary["total"] += price
        category = category or "Other"
        category_totals = monthly_summary["category_totals"]
        category_totals[category] = category_totals.get(category, 0) + price

    return monthly_summaries


def update_monthly_summary_sheet():
    monthly_summaries = build_monthly_summaries()
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    values = [
        ["Month", "Category", "Amount", "Updated At"],
    ]

    for month in sorted(monthly_summaries):
        monthly_summary = monthly_summaries[month]
        values.append([month, "Total", monthly_summary["total"], updated_at])

        for category, amount in sorted(monthly_summary["category_totals"].items()):
            values.append([month, category, amount, updated_at])

    summary_sheet.clear()
    summary_sheet.update(range_name="A1", values=values)

    return monthly_summaries


def get_monthly_summary():
    target_month = datetime.now().strftime("%Y-%m")
    monthly_summaries = update_monthly_summary_sheet()
    monthly_summary = monthly_summaries.get(
        target_month,
        {"total": 0, "category_totals": {}}
    )
    total = monthly_summary["total"]
    category_totals = monthly_summary["category_totals"]

    if total == 0:
        return f"{target_month} 目前還沒有記帳資料"

    lines = [f"{target_month} 總花費：{total} 元"]

    for category, amount in sorted(category_totals.items()):
        lines.append(f"{category}：{amount} 元")

    lines.append("已更新 Monthly summary 報表")

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
                update_monthly_summary_sheet()

                reply_message(reply_token, f"已記帳：{date}｜{category}｜{item}｜{price} 元")
            else:
                reply_message(reply_token, "請輸入格式：項目 金額，例如：午餐 120")

    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "LINE Bot is running!", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
