import importlib
import os
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import Mock


def load_app_with_fakes():
    os.environ["LINE_ACCESS_TOKEN"] = "test-token"
    os.environ["GOOGLE_CREDENTIALS"] = '{"client_email":"test@example.com","token_uri":"https://example.com","private_key":"-----BEGIN PRIVATE KEY-----\\ntest\\n-----END PRIVATE KEY-----\\n"}'

    fake_gspread = types.ModuleType("gspread")
    fake_gspread.WorksheetNotFound = Exception
    fake_gspread.authorize = Mock()
    fake_spreadsheet = Mock()
    fake_spreadsheet.worksheet.return_value = Mock()
    fake_client = Mock()
    fake_client.open.return_value = fake_spreadsheet
    fake_gspread.authorize.return_value = fake_client

    fake_google = types.ModuleType("google")
    fake_oauth2 = types.ModuleType("google.oauth2")
    fake_service_account = types.ModuleType("google.oauth2.service_account")

    class FakeCredentials:
        @classmethod
        def from_service_account_info(cls, info, scopes):
            return cls()

    fake_service_account.Credentials = FakeCredentials
    fake_oauth2.service_account = fake_service_account
    fake_google.oauth2 = fake_oauth2

    sys.modules["gspread"] = fake_gspread
    sys.modules["google"] = fake_google
    sys.modules["google.oauth2"] = fake_oauth2
    sys.modules["google.oauth2.service_account"] = fake_service_account
    sys.modules.pop("app", None)

    return importlib.import_module("app")


class BackfillExpenseParsingTest(unittest.TestCase):
    def test_parses_month_day_item_and_price(self):
        app = load_app_with_fakes()

        result = app.parse_backfill_expense_message(
            "補記帳 6/18 午餐 120",
            today=datetime(2026, 6, 19),
        )

        self.assertEqual(result, ("2026-06-18", "午餐", 120))


class BackfillExpenseWebhookTest(unittest.TestCase):
    def test_classifies_item_with_existing_rules_before_saving(self):
        app = load_app_with_fakes()
        app.classify = Mock(return_value="Lunch")
        app.update_monthly_summary_sheet = Mock()
        app.reply_message = Mock()

        response = app.app.test_client().post(
            "/webhook",
            json={
                "events": [
                    {
                        "type": "message",
                        "message": {"type": "text", "text": "補記帳 6/18 午餐 120"},
                        "replyToken": "reply-token",
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        app.classify.assert_called_once_with("午餐")
        app.expense_sheet.append_row.assert_called_once_with(
            ["2026-06-18", "Lunch", "午餐", 120, "補記帳 6/18 午餐 120"]
        )

    def test_accepts_full_width_colon_before_backfill_date(self):
        app = load_app_with_fakes()
        app.classify = Mock(return_value="Lunch")
        app.update_monthly_summary_sheet = Mock()
        app.reply_message = Mock()

        response = app.app.test_client().post(
            "/webhook",
            json={
                "events": [
                    {
                        "type": "message",
                        "message": {"type": "text", "text": "補記帳：7/1 中餐 62"},
                        "replyToken": "reply-token",
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        app.classify.assert_called_once_with("中餐")
        app.expense_sheet.append_row.assert_called_once_with(
            ["2026-07-01", "Lunch", "中餐", 62, "補記帳：7/1 中餐 62"]
        )


class MonthQueryParsingTest(unittest.TestCase):
    def test_parses_year_month_query(self):
        app = load_app_with_fakes()

        result = app.parse_month_query(
            "查詢 2026-06",
            today=datetime(2026, 6, 19),
        )

        self.assertEqual(result, "2026-06")

    def test_parses_simple_month_query_with_current_year(self):
        app = load_app_with_fakes()

        result = app.parse_month_query(
            "查詢 6月",
            today=datetime(2026, 6, 19),
        )

        self.assertEqual(result, "2026-06")

    def test_parses_total_spending_month_query_with_current_year(self):
        app = load_app_with_fakes()

        result = app.parse_month_query(
            "查詢6月總花費",
            today=datetime(2026, 6, 19),
        )

        self.assertEqual(result, "2026-06")


class CategoryCommandParsingTest(unittest.TestCase):
    def test_parses_category_and_keywords(self):
        app = load_app_with_fakes()

        result = app.parse_add_category_message("新增分類 餐飲 午餐 咖啡")

        self.assertEqual(result, ("餐飲", "午餐,咖啡"))


class DeleteExpenseParsingTest(unittest.TestCase):
    def test_parses_month_day_item_and_price(self):
        app = load_app_with_fakes()

        result = app.parse_delete_expense_message(
            "刪除 6/18 午餐 120",
            today=datetime(2026, 6, 19),
        )

        self.assertEqual(result, ("2026-06-18", "午餐", 120))


class DeleteExpenseTest(unittest.TestCase):
    def test_deletes_single_matching_expense(self):
        app = load_app_with_fakes()
        app.update_monthly_summary_sheet = Mock()
        app.expense_sheet.get_all_values.return_value = [
            ["Date", "Category", "Item", "Price", "Raw"],
            ["2026-06-18", "餐飲", "早餐", "80", "早餐 80"],
            ["2026-06-18", "餐飲", "午餐", "120", "午餐 120"],
            ["2026-06-19", "餐飲", "午餐", "120", "午餐 120"],
        ]

        result = app.delete_expense_by_match("2026-06-18", "午餐", 120)

        app.expense_sheet.delete_rows.assert_called_once_with(3)
        app.update_monthly_summary_sheet.assert_called_once()
        self.assertEqual(result, "已刪除：2026-06-18｜餐飲｜午餐｜120 元")

    def test_does_not_delete_when_no_expense_matches(self):
        app = load_app_with_fakes()
        app.expense_sheet.get_all_values.return_value = [
            ["Date", "Category", "Item", "Price", "Raw"],
            ["2026-06-18", "餐飲", "早餐", "80", "早餐 80"],
        ]

        result = app.delete_expense_by_match("2026-06-18", "午餐", 120)

        app.expense_sheet.delete_rows.assert_not_called()
        self.assertEqual(result, "找不到這筆資料：2026-06-18｜午餐｜120 元")

    def test_does_not_delete_when_multiple_expenses_match(self):
        app = load_app_with_fakes()
        app.expense_sheet.get_all_values.return_value = [
            ["Date", "Category", "Item", "Price", "Raw"],
            ["2026-06-18", "餐飲", "午餐", "120", "午餐 120"],
            ["2026-06-18", "餐飲", "午餐便當", "120", "午餐便當 120"],
        ]

        result = app.delete_expense_by_match("2026-06-18", "午餐", 120)

        app.expense_sheet.delete_rows.assert_not_called()
        self.assertEqual(result, "找到 2 筆符合資料，請輸入更明確的項目文字，避免誤刪")


class UsageHelpTest(unittest.TestCase):
    def test_includes_every_supported_command_format(self):
        app = load_app_with_fakes()

        help_text = app.format_usage_help()

        self.assertIn("午餐 120", help_text)
        self.assertIn("補記帳 6/18 午餐 120", help_text)
        self.assertIn("本月花費", help_text)
        self.assertIn("查詢6月總花費", help_text)
        self.assertIn("刪除上一筆", help_text)
        self.assertIn("刪除 6/18 午餐 120", help_text)
        self.assertIn("新增分類 餐飲 午餐 咖啡", help_text)

    def test_recognizes_help_commands(self):
        app = load_app_with_fakes()

        for text in ["格式", "提示", "help", "說明"]:
            self.assertTrue(app.is_usage_help_command(text))


if __name__ == "__main__":
    unittest.main()
