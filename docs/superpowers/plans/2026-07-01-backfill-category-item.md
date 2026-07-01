# Backfill Category and Item Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make backfilled expenses use the existing automatic category mapping and store the entered expense description as Item.

**Architecture:** Keep date, item, and price parsing in `parse_backfill_expense_message()`. Reuse the existing `classify(item)` function in the webhook before appending the Google Sheets row.

**Tech Stack:** Python, Flask, unittest, unittest.mock

---

### Task 1: Parse the backfill description as Item

**Files:**
- Modify: `test_app.py:43-55`
- Modify: `app.py:138-156`

- [ ] **Step 1: Write the failing parser test**

Change the expected value for `補記帳 6/18 午餐 120` to:

```python
self.assertEqual(result, ("2026-06-18", "午餐", 120))
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/codex-pycache python3 -m unittest test_app.BackfillExpenseParsingTest -v`

Expected: FAIL because the current parser returns `("2026-06-18", "午餐", "補記帳", 120)`.

- [ ] **Step 3: Implement the minimal parser change**

Treat the text between the date and amount as `item`, then return:

```python
return expense_date.strftime("%Y-%m-%d"), item, price
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/codex-pycache python3 -m unittest test_app.BackfillExpenseParsingTest -v`

Expected: one passing test.

### Task 2: Apply the existing category mapping before saving

**Files:**
- Modify: `test_app.py`
- Modify: `app.py:414-421`

- [ ] **Step 1: Write a failing webhook test**

Post a LINE event containing `補記帳 6/18 午餐 120`, make `classify("午餐")` return `Lunch`, and assert:

```python
app.expense_sheet.append_row.assert_called_once_with(
    ["2026-06-18", "Lunch", "午餐", 120, "補記帳 6/18 午餐 120"]
)
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `PYTHONPYCACHEPREFIX=/tmp/codex-pycache python3 -m unittest test_app.BackfillExpenseWebhookTest -v`

Expected: FAIL because the webhook currently treats the parsed description as Category and stores `補記帳` as Item.

- [ ] **Step 3: Implement the minimal webhook change**

Unpack the parser result as date, item, and price, then classify it:

```python
date, item, price = backfill_expense
category = classify(item)
```

Keep the existing five-column row format and full raw command.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `PYTHONPYCACHEPREFIX=/tmp/codex-pycache python3 -m unittest test_app.BackfillExpenseWebhookTest -v`

Expected: one passing test.

### Task 3: Update help wording and run full verification

**Files:**
- Modify: `app.py:65`
- Modify: `test_app.py:154-166`

- [ ] **Step 1: Update the help example assertion**

Require the help text to contain `補記帳 6/18 午餐 120` so the third field is clearly an Item rather than a Category.

- [ ] **Step 2: Update the centralized help example**

Replace `補記帳 6/18 餐飲 120` with `補記帳 6/18 午餐 120`.

- [ ] **Step 3: Run all tests**

Run: `PYTHONPYCACHEPREFIX=/tmp/codex-pycache python3 -m unittest -v`

Expected: all tests pass with zero failures and zero errors.

- [ ] **Step 4: Check Python syntax and the final diff**

Run: `PYTHONPYCACHEPREFIX=/tmp/codex-pycache python3 -m py_compile app.py test_app.py`

Expected: exit code 0 with no output. Then run `git diff --check` and confirm no whitespace errors.
