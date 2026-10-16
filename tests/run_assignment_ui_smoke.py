"""Start synthetic A/O, run DOM/API checks, and stop the server."""
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    server = subprocess.Popen([sys.executable, str(root / 'tests/web_demo_server.py')],
                              cwd=root, env={**os.environ, 'AO_TEST_MANAGEMENT': '1'},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError('Synthetic A/O server failed to start (check port 18650)')
            try:
                with urllib.request.urlopen('http://127.0.0.1:18650', timeout=1):
                    break
            except OSError:
                time.sleep(.05)
        else:
            raise RuntimeError('Synthetic A/O server did not become ready')
        result = subprocess.run(['node', str(root / 'tests/assignment_ui_smoke.cjs')], cwd=root, timeout=60)
        raise SystemExit(result.returncode)
    finally:
        server.terminate()
        server.wait(timeout=10)
