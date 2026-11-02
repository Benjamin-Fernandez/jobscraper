"""Spike S-5b (Q-23b, D-78): keep one headed Edge alive so step scripts can attach.

Usage: python keeper.py <profile_dir> <cdp_port> <stop_file>

Playwright launch defaults (channel msedge, headed, no stealth flags; navigator.webdriver
stays true). The extra --remote-debugging-port only lets the step scripts
(`drive.py`) attach with connect_over_cdp, so the wizard survives between steps.
Stops when <stop_file> exists or the window is closed.
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright


def main() -> int:
    profile, port, stop = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    os.makedirs(profile, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile, channel="msedge", headless=False, no_viewport=True,
            locale="en-SG", timezone_id="Asia/Singapore", accept_downloads=False,
            args=[f"--remote-debugging-port={port}"])
        print(f"keeper up on {port}", flush=True)
        while not os.path.exists(stop):
            try:
                if not ctx.pages:
                    break
                ctx.pages[0].wait_for_timeout(1000)
            except Exception:
                time.sleep(1)
        try:
            ctx.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
