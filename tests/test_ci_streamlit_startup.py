import os
import socket
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


class StreamlitStartupSmokeTests(unittest.TestCase):
    def test_streamlit_app_serves_initial_page(self):
        repo_root = Path(__file__).resolve().parents[1]
        port = free_local_port()
        url = f"http://127.0.0.1:{port}/"
        env = {
            **os.environ,
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
                body = self._wait_for_initial_page(proc, output, url)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

        self.assertIn("Streamlit", body)

    def _wait_for_initial_page(self, proc, output, url: str) -> str:
        deadline = time.time() + 20
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
