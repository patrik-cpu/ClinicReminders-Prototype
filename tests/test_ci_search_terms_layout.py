import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SearchTermsLayoutTests(unittest.TestCase):
    def test_add_new_search_term_examples_are_row_aligned(self):
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            self.skipTest(f"Playwright is not installed: {exc}")

        repo_root = Path(__file__).resolve().parents[1]
        port = free_local_port()
        url = f"http://127.0.0.1:{port}/"
        env = {
            **os.environ,
            "CLINIC_REMINDERS_E2E_SEARCH_TERMS_LAYOUT": "1",
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        }

        with tempfile.TemporaryFile(mode="w+t") as output:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    "reminders_app_v3.py",
                    "--server.headless",
                    "true",
                    "--server.port",
                    str(port),
                    "--server.address",
                    "127.0.0.1",
                    "--server.fileWatcherType",
                    "none",
                    "--browser.gatherUsageStats",
                    "false",
                ],
                cwd=repo_root,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                self._wait_for_initial_page(proc, output, url)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(viewport={"width": 1900, "height": 900})
                        page.goto(url, wait_until="networkidle", timeout=30000)
                        page.get_by_text("Add New Search Term").wait_for(timeout=30000)
                        self._assert_example_rows_aligned(page)
                    finally:
                        browser.close()
            except PlaywrightError as exc:
                self.skipTest(f"Playwright browser is not available: {exc}")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

    def _assert_example_rows_aligned(self, page) -> None:
        example_keys = [
            "search-term",
            "category",
            "first-reminder",
            "second-reminder",
            "due-date",
            "overdue",
            "use-qty",
            "message-text",
        ]
        reference_keys = [
            "search-term",
            "first-reminder",
            "second-reminder",
            "due-date",
            "overdue",
            "message-text",
        ]
        for line in ("1", "2"):
            y_positions = {}
            for key in example_keys:
                selector = f'[data-field-examples="{key}"] [data-example-line="{line}"]'
                locator = page.locator(selector)
                locator.wait_for(timeout=10000)
                box = locator.bounding_box()
                self.assertIsNotNone(box, f"No browser box for {selector}")
                y_positions[key] = round(float(box["y"]), 2)

            reference_y = statistics.median(y_positions[key] for key in reference_keys)
            delta = abs(y_positions["use-qty"] - reference_y)
            self.assertLessEqual(
                delta,
                2,
                f"Use Qty example line {line} is misaligned against the row baseline: {y_positions}",
            )

    def _wait_for_initial_page(self, proc, output, url: str) -> str:
        deadline = time.time() + 25
        last_error = None
        while time.time() < deadline:
            if proc.poll() is not None:
                output.seek(0)
                logs = output.read()
                self.fail(f"Streamlit exited before serving {url}.\n{logs[-4000:]}")
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    body = response.read(4096).decode("utf-8", errors="replace")
                    self.assertEqual(response.status, 200)
                    return body
            except Exception as exc:
                last_error = exc
                time.sleep(0.5)

        output.seek(0)
        logs = output.read()
        self.fail(f"Streamlit did not serve {url}: {last_error}\n{logs[-4000:]}")


if __name__ == "__main__":
    unittest.main()
