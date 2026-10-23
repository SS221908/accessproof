"""Reproduce this keyboard task. Run: python reproducer.py

Optional: ACCESSPROOF_TEST_URL=http://127.0.0.1:8000/demo/working python reproducer.py
Install Playwright first: python -m pip install playwright; python -m playwright install chromium
A failed success assertion deliberately preserves an unsuccessful recorded task.
"""
import asyncio
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

DEFAULT_URL = 'https://accessproof-demo.onrender.com/demo/working'
ACTIONS = [{'action': 'press', 'key': 'Tab'}, {'action': 'type', 'text': 'Alex Rivera'}, {'action': 'press', 'key': 'Tab'}, {'action': 'type', 'text': 'alex@example.com'}, {'action': 'press', 'key': 'Tab'}, {'action': 'type', 'text': 'Calculus'}, {'action': 'press', 'key': 'Tab'}, {'action': 'press', 'key': 'Enter'}]
EXPECTED_TEXT = 'Alex Rivera · alex@example.com · Calculus'

def browser_executable():
    explicit = os.environ.get("ACCESSPROOF_BROWSER_EXECUTABLE")
    if explicit:
        return explicit
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return str(chrome) if sys.platform == "darwin" and chrome.is_file() else None

async def main():
    url = os.environ.get("ACCESSPROOF_TEST_URL", DEFAULT_URL)
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.username or parts.password:
        raise ValueError("Use an HTTP(S) URL without embedded credentials.")
    def origin(value):
        p = urlsplit(value)
        return (p.scheme, p.hostname, p.port or (443 if p.scheme == "https" else 80))
    allowed = origin(url)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, executable_path=browser_executable(),
        )
        context = await browser.new_context(service_workers="block", accept_downloads=False)
        async def route_request(route):
            if origin(route.request.url) != allowed:
                await route.abort("blockedbyclient")
            else:
                await route.continue_()
        await context.route("**/*", route_request)
        page = await context.new_page()
        async def close_popup(popup):
            await popup.close()
        page.on("popup", close_popup)
        async def cancel_download(download):
            await download.cancel()
        page.on("download", cancel_download)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=10000)
            for action in ACTIONS:
                if action["action"] == "press":
                    await page.keyboard.press(action["key"])
                else:
                    await page.keyboard.type(action["text"], delay=50)
                await page.wait_for_timeout(80)
            if not urlsplit(url).path.startswith("/demo/"):
                raise AssertionError("Success markers are trusted only for AccessProof owned /demo/ fixtures.")
            await page.wait_for_function("""() => [...document.querySelectorAll('[data-ap-success="true"]')].some(el => {
                const s = getComputedStyle(el);
                return el.getClientRects().length > 0 && s.visibility !== 'hidden' && s.display !== 'none' && el.innerText.trim().length > 0;
            })""", timeout=5000)
            observed = await page.evaluate("""() => [...document.querySelectorAll('[data-ap-success="true"]')]
              .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
              .map(el => el.innerText).join(' ')""")
            if EXPECTED_TEXT is not None:
                normalized = lambda value: " ".join(value.casefold().split())
                assert normalized(EXPECTED_TEXT) in normalized(observed), "Confirmation did not match the expected task details."
            print("PASS: independent task confirmation is visible.")
        finally:
            await context.close()
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
