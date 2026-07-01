import os
import json
import re
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


USAGE_HELP_COMMANDS = {"格式", "提示", "help", "說明"}


def is_usage_help_command(text):
    return text.strip().lower() in USAGE_HELP_COMMANDS


def format_usage_help():
    return "\n".join([
        "可以用這些格式記帳：",
        "1. 一般記帳：午餐 120",
        "2. 補記帳：補記帳 6/18 午餐 120",
        "3. 查本月：本月花費",
        "4. 查月份：查詢6月總花費",
        "5. 刪除上一筆：刪除上一筆",
        "6. 指定刪除：刪除 6/18 午餐 120",
        "7. 新增分類：新增分類 餐飲 午餐 咖啡",
        "",
        "想再看一次，傳「格式」或「提示」給我。",
    ])


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
    if value is None:
        return None

    normalized = str(value).strip()
    normalized = normalized.replace(",", "")
    normalized = normalized.replace("NT$", "")
    normalized = normalized.replace("nt$", "")
    normalized = normalized.replace("$", "")
    normalized = normalized.replace("元", "")

    try:
        return int(float(normalized))
    except (TypeError, ValueError):
        return None


def parse_expense_message(text):
    parts = text.split()

    if len(parts) < 2:
        return None, None

    price = parse_price(parts[-1])
    if price is None:
        return None, None

    item = " ".join(parts[:-1]).strip()
    if not item:
        return None, None

    return item, price


def parse_backfill_expense_message(text, today=None):
    today = today or datetime.now()
    match = re.fullmatch(r"補記帳\s+(\d{1,2})/(\d{1,2})\s+(\S+)\s+(.+)", text.strip())

    if not match:
        return None

    month_text, day_text, item, price_text = match.groups()
    price = parse_price(price_text)

    if price is None:
        return None

    try:
        expense_date = datetime(today.year, int(month_text), int(day_text))
    except ValueError:
        return None

    return expense_date.strftime("%Y-%m-%d"), item, price


def parse_delete_expense_message(text, today=None):
    today = today or datetime.now()
    match = re.fullmatch(r"刪除\s+(\d{1,2})/(\d{1,2})\s+(.+)\s+(\S+)", text.strip())

    if not match:
        return None

    month_text, day_text, item_text, price_text = match.groups()
    price = parse_price(price_text)

    if price is None:
        return None

    try:
        expense_date = datetime(today.year, int(month_text), int(day_text))
    except ValueError:
        return None

    item_text = item_text.strip()
    if not item_text:
        return None

    return expense_date.strftime("%Y-%m-%d"), item_text, price


def parse_month_query(text, today=None):
    today = today or datetime.now()
    stripped_text = text.strip()
    year_month_match = re.fullmatch(r"查詢\s*(\d{4})-(\d{1,2})", stripped_text)

    if year_month_match:
        year_text, month_text = year_month_match.groups()
        month = int(month_text)
        if 1 <= month <= 12:
            return f"{year_text}-{month:02d}"

        return None

    month_match = re.fullmatch(r"查詢\s*(\d{1,2})月(?:總花費)?", stripped_text)
    if month_match:
        month = int(month_match.group(1))
        if 1 <= month <= 12:
            return f"{today.year}-{month:02d}"

    return None


def parse_add_category_message(text):
    parts = text.split()

    if len(parts) < 3 or parts[0] != "新增分類":
        return None

    category = parts[1]
    keywords = ",".join(parts[2:])

    return category, keywords


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


def format_monthly_summary(target_month):
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


def get_monthly_summary():
    target_month = datetime.now().strftime("%Y-%m")
    return format_monthly_summary(target_month)


def delete_last_expense():
    values = expense_sheet.get_all_values()

    if len(values) <= 1:
        return "目前沒有可刪除的記帳資料"

    last_row_index = None
    last_row_values = None

    for row_index in range(len(values), 1, -1):
        row_values = values[row_index - 1]
        if any(str(cell).strip() for cell in row_values):
            last_row_index = row_index
            last_row_values = row_values
            break

    if last_row_index is None or last_row_values is None:
        return "目前沒有可刪除的記帳資料"

    expense_sheet.delete_rows(last_row_index)
    update_monthly_summary_sheet()

    date = last_row_values[0] if len(last_row_values) > 0 else ""
    category = last_row_values[1] if len(last_row_values) > 1 else "Other"
    item = last_row_values[2] if len(last_row_values) > 2 else ""
    price = last_row_values[3] if len(last_row_values) > 3 else ""

    return f"已刪除上一筆：{date}｜{category}｜{item}｜{price} 元"


def delete_expense_by_match(target_date, item_text, target_price):
    values = expense_sheet.get_all_values()
    matches = []

    for row_index, row_values in enumerate(values[1:], start=2):
        date = str(row_values[0]).strip() if len(row_values) > 0 else ""
        category = str(row_values[1]).strip() if len(row_values) > 1 else ""
        item = str(row_values[2]).strip() if len(row_values) > 2 else ""
        price = parse_price(row_values[3] if len(row_values) > 3 else None)
        raw_message = str(row_values[4]).strip() if len(row_values) > 4 else ""

        searchable_text = " ".join([category, item, raw_message])
        if date == target_date and price == target_price and item_text in searchable_text:
            matches.append((row_index, row_values))

    if not matches:
        return f"找不到這筆資料：{target_date}｜{item_text}｜{target_price} 元"

    if len(matches) > 1:
        return f"找到 {len(matches)} 筆符合資料，請輸入更明確的項目文字，避免誤刪"

    row_index, row_values = matches[0]
    expense_sheet.delete_rows(row_index)
    update_monthly_summary_sheet()

    category = row_values[1] if len(row_values) > 1 else "Other"
    item = row_values[2] if len(row_values) > 2 else ""
    price = row_values[3] if len(row_values) > 3 else target_price

    return f"已刪除：{target_date}｜{category}｜{item}｜{price} 元"


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

            if is_usage_help_command(msg):
                reply_message(reply_token, format_usage_help())
                continue

            # 🔥 本月花費查詢
            if msg == "本月花費":
                summary = get_monthly_summary()
                reply_message(reply_token, summary)
                continue

            month_query = parse_month_query(msg)
            if month_query:
                summary = format_monthly_summary(month_query)
                reply_message(reply_token, summary)
                continue

            if msg in ["刪除上一筆", "取消上一筆"]:
                result = delete_last_expense()
                reply_message(reply_token, result)
                continue

            delete_expense = parse_delete_expense_message(msg)
            if delete_expense:
                target_date, item_text, price = delete_expense
                result = delete_expense_by_match(target_date, item_text, price)
                reply_message(reply_token, result)
                continue

            backfill_expense = parse_backfill_expense_message(msg)
            if backfill_expense:
                date, item, price = backfill_expense
                category = classify(item)

                expense_sheet.append_row([date, category, item, price, msg])
                update_monthly_summary_sheet()

                reply_message(reply_token, f"已補記帳：{date}｜{category}｜{price} 元")
                continue

            # 🔥 分類功能
            if msg.startswith("新增分類"):
                add_category = parse_add_category_message(msg)

                if add_category:
                    category, keywords = add_category
                    category_sheet.append_row([category, keywords])

                    reply_message(reply_token, f"已新增分類：{category}｜關鍵字：{keywords}")
                else:
                    reply_message(reply_token, format_usage_help())

                continue

            # 🔥 記帳功能
            item, price = parse_expense_message(msg)

            if item and price is not None:
                category = classify(item)
                date = datetime.now().strftime("%Y-%m-%d")

                expense_sheet.append_row([date, category, item, price, msg])
                update_monthly_summary_sheet()

                reply_message(reply_token, f"已記帳：{date}｜{category}｜{item}｜{price} 元")
            else:
                reply_message(reply_token, format_usage_help())

    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "LINE Bot is running!", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
