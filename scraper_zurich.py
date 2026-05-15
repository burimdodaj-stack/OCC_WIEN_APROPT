"""
PandaParken Zürich – Occupancy Scraper (Aktueller + Nächster Monat)
====================================================================
Standort  : https://admin.pandaparken.ch/capacity
Sheet     : 1Xq1GG4f_2pjZn2-H0qZsGwMCbdgdDyQrPyrBcTeSmv0
Tab       : SpezoällOCCZur
"""

import os
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup

# ── Konfiguration ──────────────────────────────────────────────────────────────
ADMIN_URL  = "https://admin.pandaparken.ch/capacity"
USERNAME   = os.environ["PANDA_USER"]
PASSWORD   = os.environ["PANDA_PASS"]

SHEET_ID   = "1Xq1GG4f_2pjZn2-H0qZsGwMCbdgdDyQrPyrBcTeSmv0"
SHEET_NAME = "SpezoällOCCZur"

SERVICE_ACCOUNT_FILE = "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

PANDA_SECTIONS = ["Panda 1", "Panda 2", "Panda 3", "Panda 4", "Panda 5", "Panda 6"]

CAPACITY_IDS = {
    "Panda 1": "capacity_1",
    "Panda 2": "capacity_2",
    "Panda 3": "capacity_3",
    "Panda 4": "capacity_4",
    "Panda 5": "capacity_5",
    "Panda 6": "capacity_6",
}

SECTION_START_ROWS_CURRENT = {
    "Panda 1": 1,
    "Panda 2": 40,
    "Panda 3": 79,
    "Panda 4": 118,
    "Panda 5": 157,
    "Panda 6": 196,
}

SECTION_START_ROWS_NEXT = {
    "Panda 1": 235,
    "Panda 2": 274,
    "Panda 3": 313,
    "Panda 4": 352,
    "Panda 5": 391,
    "Panda 6": 430,
}
# ──────────────────────────────────────────────────────────────────────────────


def login(page):
    print("▶ Öffne Login-Seite ...")
    page.goto(ADMIN_URL, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    try:
        page.fill('input[placeholder="Username"]', USERNAME, timeout=5000)
        page.fill('input[placeholder="Password"]', PASSWORD)
        page.click('button:has-text("Login")')
        page.wait_for_load_state("networkidle", timeout=20000)
        time.sleep(2)
        print("  ✓ Eingeloggt")
    except Exception:
        print("  ✓ Kein Login-Formular gefunden, bereits eingeloggt oder direkte URL")


def navigate_to_capacity(page):
    print("▶ Navigiere zu Parking Capacity ...")
    current_url = page.url
    if "/capacity" not in current_url:
        try:
            page.click("text=Parking", timeout=5000)
            time.sleep(1)
            page.click("text=Parking Capacity", timeout=5000)
        except Exception:
            page.goto(ADMIN_URL, wait_until="networkidle", timeout=30000)

    page.wait_for_load_state("networkidle", timeout=20000)
    time.sleep(4)
    print("  ✓ Capacity-Seite geladen")


def click_next_month(page):
    print("▶ Klicke auf 'Next Month' ...")
    old_html = page.content()

    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(2)

    try:
        next_month_link = page.locator("text=Next Month").first
        next_month_link.wait_for(timeout=10000)
        next_month_link.scroll_into_view_if_needed()
        time.sleep(1)
        next_month_link.click()
    except Exception:
        next_month_link = page.locator("text=Nächster Monat").first
        next_month_link.wait_for(timeout=10000)
        next_month_link.click()

    time.sleep(2)

    try:
        page.wait_for_function(
            """(oldHtml) => document.body.innerHTML !== oldHtml""",
            arg=old_html,
            timeout=15000
        )
    except PlaywrightTimeoutError:
        print("  ! Inhalt hat sich nicht eindeutig geändert, warte trotzdem ...")

    page.wait_for_load_state("networkidle", timeout=20000)
    time.sleep(4)
    print("  ✓ Nächster Monat geladen")


def parse_tbody_by_id(html: str, tbody_id: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    tbody = soup.find("tbody", {"id": tbody_id})
    if not tbody:
        print(f"  ✗ <tbody id='{tbody_id}'> nicht gefunden!")
        return []

    table = tbody.find_parent("table")
    rows = []

    if table:
        thead = table.find("thead")
        if thead:
            header_cells = thead.find_all(["th", "td"])
            rows.append([c.get_text(strip=True) for c in header_cells])

    for tr in tbody.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        row = [c.get_text(strip=True) for c in cells]
        if any(cell != "" for cell in row):
            rows.append(row)

    return rows


def extract_all_data(page) -> dict:
    html = page.content()
    result = {}
    for name in PANDA_SECTIONS:
        print(f"  ▶ Lese {name} ...")
        tbody_id = CAPACITY_IDS[name]
        rows = parse_tbody_by_id(html, tbody_id)
        print(f"    ✓ {len(rows)} Zeilen gefunden")
        result[name] = {"rows": rows}
    return result


def column_number_to_letter(n):
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def write_to_sheet(worksheet, section_name: str, data: dict, start_row: int):
    rows = data.get("rows", [])
    if not rows:
        print(f"  ✗ Keine Daten für {section_name}, überspringe")
        return

    header_row = rows[0]
    data_rows = rows[1:]

    to_write = [[section_name], header_row, *data_rows]

    end_row = start_row + len(to_write) - 1
    max_cols = max((len(r) for r in to_write), default=25)
    end_col = column_number_to_letter(max_cols)
    cell_range = f"A{start_row}:{end_col}{end_row}"

    worksheet.update(
        range_name=cell_range,
        values=to_write,
        value_input_option="USER_ENTERED"
    )
    print(f"    ✓ {section_name} → {len(data_rows)} Datenzeilen → {cell_range}")


def main():
    print("▶ Verbinde mit Google Sheets ...")
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.worksheet(SHEET_NAME)
    print(f"  ✓ Sheet '{SHEET_NAME}' geöffnet")
    worksheet.clear()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        print("\n════════════════════════════════════")
        print("  AKTUELLER MONAT")
        print("════════════════════════════════════")
        login(page)
        navigate_to_capacity(page)

        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
        current_data = extract_all_data(page)

        print("\n▶ Schreibe aktuellen Monat in Google Sheets ...")
        for name in PANDA_SECTIONS:
            if name in current_data:
                write_to_sheet(worksheet, name, current_data[name], SECTION_START_ROWS_CURRENT[name])

        print("\n════════════════════════════════════")
        print("  NÄCHSTER MONAT")
        print("════════════════════════════════════")
        click_next_month(page)
        next_data = extract_all_data(page)
        browser.close()

    print("\n▶ Schreibe nächsten Monat in Google Sheets ...")
    for name in PANDA_SECTIONS:
        if name in next_data:
            write_to_sheet(worksheet, name, next_data[name], SECTION_START_ROWS_NEXT[name])

    print("\n✅ Fertig!")
    print(f"   → https://docs.google.com/spreadsheets/d/{SHEET_ID}")


if __name__ == "__main__":
    main()
