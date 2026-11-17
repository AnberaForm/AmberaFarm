# -*- coding: utf-8 -*-
"""Local-only preview, isolated from the player's installed game and saves."""
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from account_store import AccountStore
from farm_core import new_state, save_state
from verify_online_rooms import RunningRelay
from v8_features import init_v8


def main():
    preview = ROOT / '.account_preview'
    sample = preview / 'profile' / 'AmberaFarm' / 'save_slots' / 'offline_1.json'
    if not sample.exists():
        old = init_v8(new_state())
        old['player_name'] = '体験版の牧場'
        old['coins'] = 4250
        old['seeds']['kabu'] = 8
        old['plots'][0] = {'crop': 'kabu', 'planted_at': time.time()}
        save_state(old, sample)
    store = AccountStore(sqlite_path=preview / 'preview_accounts.db')
    relay = RunningRelay(store)
    environment = dict(os.environ, APPDATA=str(preview / 'profile'),
                       AMBERA_TEST_RELAY_URL=relay.endpoint, PYTHONUTF8='1')
    try:
        return subprocess.call([sys.executable, str(ROOT / 'ambera_farm.py')],
                               cwd=ROOT, env=environment)
    finally:
        relay.close()
        store.close()


if __name__ == '__main__':
    raise SystemExit(main())
