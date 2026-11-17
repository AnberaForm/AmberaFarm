"""Prevent shipping the mandatory login screen before its server is reachable."""
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from account_protocol import SERVER_ENDPOINT
from online_ui import wait_for_relay


if __name__ == '__main__':
    wait_for_relay(SERVER_ENDPOINT, threading.Event(), print, require_accounts=True)
    print('Published account service is accepting connections.')
