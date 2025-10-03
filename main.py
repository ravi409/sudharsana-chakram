import os
import asyncio
import time
from datetime import datetime
import requests
from playwright.async_api import async_playwright

# ----------------------
# Environment Variables
# ----------------------
URL = os.getenv("APP_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
USER_ID = os.getenv("USER_ID")
USER_PIN = os.getenv("USER_PIN")
ALLOWED_LOCS = os.getenv("ALLOWED_LOCS", "")
ALLOWED_CLS = os.getenv("ALLOWED_CLS", "")

# Convert CSV strings to lists
allowed_locations = [loc.strip() for loc in ALLOWED_LOCS.split(",") if loc.strip()]
allowed_classifications = [cls.strip() for cls in ALLOWED_CLS.split(",") if cls.strip()]

# ----------------------
# Helper Functions
# ----------------------
def send_notification(message: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("[WARN] Telegram credentials missing.", flush=True)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": CHAT_ID, "text": message})
        if resp.status_code != 200:
            print(f"[ERROR] Telegram API failed: {resp.text}", flush=True)
    except Exception as e:
        print(f"[ERROR] Failed to send notification: {e}", flush=True)


def format_notification(row):
    """Formats row data into notification string and calculates duration in hours."""
    try:
        short_loc = " ".join(row["location"].split()[:2])
        classification = row["classification"].strip()
        date_lines = row["date"].split()
        date_str = date_lines[-1] if date_lines else ""
        diff_hours = 7

        time_parts = row["time"].split()
        if len(time_parts) >= 4:
            start_str = f"{time_parts[0]} {time_parts[1]}"
            end_str = f"{time_parts[2]} {time_parts[3]}"
            try:
                start_dt = datetime.strptime(start_str, "%I:%M %p")
                end_dt = datetime.strptime(end_str, "%I:%M %p")
                diff_hours = (end_dt - start_dt).seconds / 3600
            except Exception:
                pass

        message = f"{short_loc} - {classification} - {date_str} - {diff_hours:.1f} hrs"
        return message, short_loc, diff_hours
    except Exception as e:
        return f"[ERROR] Could not format notification: {e}", "", 0


async def safe_click(locator, force=False, scroll=True, retries=5):
    """Attempts to click a locator safely with retries and scrolling."""
    for _ in range(retries):
        try:
            if scroll:
                await locator.scroll_into_view_if_needed()
            await locator.click(force=force)
            return True
        except Exception:
            await asyncio.sleep(0.2)
    return False


async def expand_date_filter(page):
    """Expand date filter section and set date range."""
    try:
        toggle_date = page.get_by_role("button", name="Toggle Date Filter")
        await toggle_date.wait_for(state="visible", timeout=10000)
        await safe_click(toggle_date)

        # Select Date Range radio button
        date_range_label = page.locator("label[for='date-type-range-option-0']")
        await date_range_label.wait_for(state="visible", timeout=10000)
        await safe_click(date_range_label, force=True)

        # Fill dates
        today_str = datetime.today().strftime("%m/%d/%Y")
        await page.fill("#start-date-filter-input", today_str)
        await page.fill("#end-date-filter-input", "06/15/2026")

        # Collapse date section
        await safe_click(toggle_date, force=True)
        await asyncio.sleep(0.5)
        print("[INFO] Date filter set successfully", flush=True)
    except Exception as e:
        print(f"[WARN] Could not set date range filter: {e}", flush=True)


async def set_location_filter(page):
    """Expand location filter and select ELEMENTARY checkbox."""
    try:
        toggle_location = page.get_by_role("button", name="Toggle Location Filter")
        await safe_click(toggle_location, force=True)
        await asyncio.sleep(1)

        # Find the first checkbox with label ELEMENTARY
        elementary_label = page.locator("ul >> li >> label", has_text="ELEMENTARY").first
        elementary_checkbox = elementary_label.locator("input[type=checkbox]")

        # Scroll container until visible
        container = page.locator("section:has(button[name='Toggle Location Filter']) ul")
        for _ in range(5):
            if await elementary_checkbox.is_visible():
                break
            await container.evaluate("el => el.scrollBy(0, 200)")
            await asyncio.sleep(0.2)

        await safe_click(elementary_checkbox, force=True)
        print("[INFO] ✅ Selected ELEMENTARY checkbox", flush=True)
    except Exception as e:
        print(f"[WARN] Could not set location filters: {e}", flush=True)


async def process_rows(page):
    """Extract rows and send notifications based on allowed locations/classifications."""
    try:
        await page.wait_for_selector("#apply-filter")
        await page.click("#apply-filter")
        await page.wait_for_timeout(2000)

        # rows = await page.query_selector_all("tr[id^='desktop-row-']")
        await page.wait_for_selector("tr[id^='desktop-row-']", timeout=2000)  # Wait up to 10 seconds
        rows = await page.query_selector_all("tr[id^='desktop-row-']")
        row_data_list = []

        for row in rows:
            try:
                row_obj = {
                    "date": (await (await row.query_selector("td[id^='desktop-row-data-startenddate']")).inner_text()).strip() if await row.query_selector("td[id^='desktop-row-data-startenddate']") else "",
                    "time": (await (await row.query_selector("td[id^='desktop-row-data-startendtime']")).inner_text()).strip() if await row.query_selector("td[id^='desktop-row-data-startendtime']") else "",
                    "classification": (await (await row.query_selector("td[id^='desktop-row-data-classification']")).inner_text()).strip() if await row.query_selector("td[id^='desktop-row-data-classification']") else "",
                    "location": (await (await row.query_selector("td[id^='desktop-row-data-location']")).inner_text()).strip() if await row.query_selector("td[id^='desktop-row-data-location']") else "",
                }
                row_data_list.append(row_obj)
            except Exception as e:
                print(f"[ERROR] Failed to process row: {e}", flush=True)

        print(f"[INFO] Found {len(row_data_list)} rows", flush=True)
        for row in row_data_list:
            message, _, diff_hours = format_notification(row)
            print(message, flush=True)
            location_upper = row["location"].upper().strip()
            classification = row["classification"].upper().strip()

            if any(allowed in classification for allowed in allowed_classifications) and \
               any(keyword in location_upper for keyword in allowed_locations) and \
               diff_hours > 6:
                send_notification(message)
            
            # send_notification(message)
    except Exception as e:
        print(f"[ERROR] Processing rows failed: {e}", flush=True)


async def main_loop(page, duration_seconds=3600, interval_seconds=30):
    """Run main loop to repeatedly apply filters and process rows."""
    start_time = time.time()
    while time.time() - start_time < duration_seconds:
        await process_rows(page)
        await asyncio.sleep(interval_seconds)


# ----------------------
# Main Entry
# ----------------------
async def main():
    print("Allowed classifications:", allowed_classifications, flush=True)
    print("Allowed locations:", allowed_locations, flush=True)

    async with async_playwright() as p:
        # browser = await p.chromium.launch(headless=True)
        browser = await p.chromium.launch(headless=True, args=["--window-size=1920,1080"])
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        # context = await browser.new_context()
        page = await context.new_page()

        # Login
        await page.goto(URL)
        await page.fill("#userId", USER_ID)
        await page.fill("#userPin", USER_PIN)
        await page.click("#submitBtn")

        await page.wait_for_selector("#available-tab-link")
        await page.click("#available-tab-link")

        # Set filters
        await expand_date_filter(page)
        # await set_location_filter(page)

        # Run main loop
        await main_loop(page)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
