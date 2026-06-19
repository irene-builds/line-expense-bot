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
    def test_parses_month_day_category_and_price(self):
        app = load_app_with_fakes()

        result = app.parse_backfill_expense_message(
            "補記帳 6/18 餐飲 120",
            today=datetime(2026, 6, 19),
        )

        self.assertEqual(result, ("2026-06-18", "餐飲", "補記帳", 120))


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


if __name__ == "__main__":
    unittest.main()
