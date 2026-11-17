# -*- coding: utf-8 -*-
"""Registration, migration, and room persistence over the real client transport."""
import json
import secrets
import sqlite3
import threading
import time

import pytest

from account_client import AccountClient
from account_protocol import ACCOUNT_PROTOCOL, AccountError, EMPTY_FARM
from account_saves import FarmSync, legacy_farms
from account_store import AccountStore, OnlineWrite
from farm_core import new_state, save_state
from multiplayer import RoomClient, PROTOCOL
from online_rooms import (RelayError, RelayHost, _abort, _reply, _websocket, connect_guest,
                          search_rooms)
from save_slots import save_slot
from verify_online_rooms import RunningRelay, wait_for
from v8_features import init_v8

PASSWORD = 'テスト用-pass-97'


def register(relay, name):
    return AccountClient(relay.endpoint).sign_in('register', name, PASSWORD)


def farm_with(coins=200, name='アンベラ'):
    state = init_v8(new_state())
    state.update(coins=coins, player_name=name)
    return state


def api(relay, session):
    return AccountClient(relay.endpoint, session)


@pytest.fixture
def server(tmp_path):
    store = AccountStore(sqlite_path=tmp_path/'server.db')
    relay = RunningRelay(store)
    try:
        yield relay, store
    finally:
        relay.close()
        store.close()


def test_login_unique_normalized_name_and_hashed_credentials(server):
    relay, store = server
    first = register(relay, 'まってぃＡ')
    assert first.account.name == 'まってぃA'
    assert first.normal == EMPTY_FARM and not first.has_online
    with pytest.raises(AccountError, match='使用されています'):
        register(relay, 'まってぃa')
    result = AccountClient(relay.endpoint).sign_in('login', 'まってぃａ', PASSWORD)
    assert result.account == first.account and result.token != first.token
    with pytest.raises(AccountError, match='違います'):
        AccountClient(relay.endpoint).sign_in('login', 'まってぃａ', 'incorrect-123')
    with sqlite3.connect(store.path) as db:
        salt, hashed = db.execute('SELECT salt, password_hash FROM accounts').fetchone()
        assert len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(hashed)) == 32
        assert first.token not in {r[0] for r in db.execute('SELECT token_hash FROM sessions')}
    api(relay, result).logout()
    with pytest.raises(AccountError) as expired:
        store.authenticate(result.token)
    assert expired.value.code == 'auth_required'


def test_migration_is_a_single_normal_save_with_originals_retained(server, tmp_path):
    relay, store = server
    root = tmp_path/'windows-profile'
    legacy = farm_with(8765, '以前の牧場')
    legacy['plots'][0] = {'crop': 'kabu', 'planted_at': time.time()}
    legacy['seeds']['kabu'] = 8
    save_state(legacy, root/'save.json')
    save_slot(farm_with(456, '通常の別枠'), 'offline', 2, root/'save_slots')
    save_slot(legacy, 'online', 2, root/'save_slots')
    (root/'room_worlds').mkdir()
    (root/'room_worlds'/'farm_1.json').write_text('old room must not be imported')
    prior = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    options = legacy_farms(root, ('online', 2))
    assert options[0].label == '旧オンライン枠2'
    assert options[0].state['coins'] == 8765
    assert all(x.state and x.label != 'farm_1' for x in options)

    session = register(relay, '継続プレイヤー')
    write = secrets.token_hex(16)
    assert api(relay, session).write_normal(0, write, options[0].state) == 1
    assert api(relay, session).write_normal(0, write, options[0].state) == 1
    with pytest.raises(AccountError) as conflict:
        api(relay, session).write_normal(0, secrets.token_hex(16), farm_with())
    assert conflict.value.code == 'save_conflict'
    assert all(p.read_bytes() == data for p, data in prior.items())
    assert store.existing_online(session.account) == EMPTY_FARM
    # A different install/session sees the entire original farm.
    second_device = AccountClient(relay.endpoint).sign_in('login', '継続プレイヤー', PASSWORD)
    assert second_device.normal.state['plots'] == legacy['plots']
    assert second_device.normal.state['seeds']['kabu'] == 8
    assert second_device.normal.state['coins'] == 8765
    assert register(relay, '別のアカウント').normal == EMPTY_FARM


def test_normal_outbox_replays_and_protects_conflict(server, tmp_path):
    relay, _ = server
    first = register(relay, '一つのセーブ')
    folder = tmp_path/'local-data'
    initial = FarmSync(api(relay, first), folder)
    original = farm_with(2180)
    initial.stage(original)
    initial.close()  # durable pending write remains, even with no connection
    second = AccountClient(relay.endpoint).sign_in('login', '一つのセーブ', PASSWORD)
    sync = FarmSync(api(relay, second), folder)
    try:
        assert sync.recovered and sync.state['coins'] == 2180
        sync.start()
        assert sync.flush(timeout=5)
        assert not sync.path.exists()
        # Competing device writes, stale local changes are kept rather than uploaded.
        assert api(relay, second).write_normal(1, secrets.token_hex(16), farm_with(2310)) == 2
        sync.stage(farm_with(9090))
        assert wait_for(lambda: sync.status == 'save_conflict')
        assert sync.path.exists()
    finally:
        sync.close()
    newest = AccountClient(relay.endpoint).sign_in('login', '一つのセーブ', PASSWORD)
    assert newest.normal.state['coins'] == 2310
    recovered = FarmSync(api(relay, newest), folder)
    assert not recovered.recovered and recovered.recovery_warning
    assert len(list(recovered.path.parent.glob('normal_recovery_*'))) == 1


def test_lost_save_reply_does_not_replay_a_second_write(server, tmp_path):
    relay, store = server
    session = register(relay, '通信途切れ')
    real = api(relay, session)
    interrupted = threading.Event()

    class LoseReply(AccountClient):
        def write_normal(self, *args):
            super().write_normal(*args)
            interrupted.set()
            raise AccountError('account_unavailable')

    sync = FarmSync(LoseReply(relay.endpoint, session), tmp_path)
    sync.stage(farm_with(555))
    sync.start()
    assert interrupted.wait(5)
    sync.close()
    sync.thread.join(4)
    assert sync.path.exists()
    signed_in = AccountClient(relay.endpoint).sign_in('login', session.account.name, PASSWORD)
    recovered = FarmSync(api(relay, signed_in), tmp_path)
    assert recovered.state['coins'] == 555 and recovered.base == 1 and not recovered.path.exists()
    assert store.normal_info(session.account).revision == 1


def connect(relay, host, session, approval=None):
    transport = connect_guest(relay.endpoint, host.code, host.pin, ACCOUNT_PROTOCOL,
                              approval=approval, session=session.token)
    return RoomClient('relay', host.pin, connection=transport, relay_authenticated=True)


def managed_host(relay, session, public=True):
    host = RelayHost(relay.endpoint, None, '134679', ACCOUNT_PROTOCOL, title='牧場 v9.7',
                     name='No spoofing', public=public, session=session.token)
    return host


def snapshot(client, predicate=lambda state: True, timeout=5):
    packets = []
    def received():
        packets.extend(p['state'] for p in client.poll()
                       if p.get('type') in ('snapshot','result') and predicate(p['state']))
        return bool(packets)
    assert wait_for(received, timeout)
    return packets[-1]


def ask_to_join(relay, host, session):
    ws = _websocket(relay.endpoint)
    try:
        ws.send(json.dumps({'op': 'request', 'version': 1, 'protocol': ACCOUNT_PROTOCOL, 'code': host.code,
                            'name': 'Spoof', 'session': session.token}))
        pending = _reply(ws)
        assert pending['type'] == 'pending'
        assert wait_for(lambda: host.pending_requests())
        assert host.pending_requests()[0]['name'] == session.account.name
        assert host.decide(pending['id'], True)
        return _reply(ws)['approval']
    finally:
        _abort(ws)


def test_room_admission_profile_separation_and_shared_plot_isolation(server):
    relay, store = server
    a, b, c = [register(relay, name) for name in ('部屋主', '参加者', '別の部屋主')]
    a_normal = farm_with(8000)
    a_normal['plots'][0] = {'crop': 'kabu', 'planted_at': time.time()}
    api(relay, a).write_normal(0, secrets.token_hex(16), a_normal)
    api(relay, b).write_normal(0, secrets.token_hex(16), farm_with(6100))
    with pytest.raises(RelayError) as anonymous:
        search_rooms(relay.endpoint, '', ACCOUNT_PROTOCOL)
    assert anonymous.value.code == 'auth_required'
    with pytest.raises(AccountError) as denied:
        api(relay, b)._call('write_online', state=farm_with(999))
    assert denied.value.code == 'denied'
    host = managed_host(relay, a)
    other_host = managed_host(relay, c, public=False)
    clients = []
    try:
        assert [r['host'] for r in search_rooms(relay.endpoint, '', ACCOUNT_PROTOCOL, b.token)] == ['部屋主']
        assert search_rooms(relay.endpoint, '', PROTOCOL) == []
        player = connect(relay, host, a); clients.append(player)
        initial = snapshot(player)
        assert initial['coins'] == 200 and initial['plots'][0] is None and initial['player_uid'] == a.account.id
        with pytest.raises(RelayError) as denied_second_room:
            connect(relay, other_host, a)
        assert denied_second_room.value.code == 'already_playing'
        with pytest.raises(RelayError) as denied_entry:
            connect(relay, host, b)
        assert denied_entry.value.code == 'approval_required'
        approved = ask_to_join(relay, host, b)
        d = register(relay, '承認されていない人')
        with pytest.raises(RelayError) as not_owner_of_approval:
            connect(relay, host, d, approval=approved)
        assert not_owner_of_approval.value.code == 'approval_required'
        assert store.existing_online(d.account) == EMPTY_FARM
        guest = connect(relay, host, b, approval=approved); clients.append(guest)
        assert snapshot(guest)['coins'] == 200

        # Planting uses the shared host field. Both the plot and the seed
        # expenditure must remain after leaving, without replacing guest land.
        game = relay.relay.rooms[host.code].game
        from world_map import plot_world
        with game.lock:
            game.players[guest.id]['x'], game.players[guest.id]['y'] = plot_world(0)
        guest.action('plot', {'index': 0, 'crop': 'kaiware'})
        planted = snapshot(guest, lambda s: s['plots'][0] is not None)
        assert planted['seeds']['kaiware'] == 3
        guest.close()
        assert wait_for(lambda: b.account.id not in relay.relay.active_players)
        assert store.existing_online(b.account).state['plots'][0] is None
        assert store.existing_online(a.account).state['plots'][0]['crop'] == 'kaiware'

        guest_again = connect(relay, other_host, b); clients.append(guest_again)
        next_room = snapshot(guest_again)
        assert next_room['seeds']['kaiware'] == 3 and next_room['plots'][0] is None
        assert next_room['player_uid'] == b.account.id
        assert store.normal_info(b.account).state['coins'] == 6100
        assert store.normal_info(a.account).state['plots'][0]['crop'] == 'kabu'
    finally:
        for client in clients:
            client.close()
        for control in (host, other_host):
            control.close()
    assert wait_for(lambda: not relay.relay.active_players)


def test_profile_remains_after_restart_and_online_batch_is_atomic(tmp_path):
    db = tmp_path/'account.db'
    first = AccountStore(sqlite_path=db)
    a, token = first.register('データ保持A', PASSWORD)
    b, _ = first.register('データ保持B', PASSWORD)
    a_save = first.get_online(a)
    b_save = first.get_online(b)
    a_state = dict(a_save.state, coins=301)
    b_state = dict(b_save.state, coins=402)
    with pytest.raises(AccountError):
        first.write_online_batch([OnlineWrite(a.id, a_save.revision, secrets.token_hex(16), a_state),
                                  OnlineWrite(b.id, b_save.revision+1, secrets.token_hex(16), b_state)])
    assert first.existing_online(a).state['coins'] == 200
    first.write_online_batch([OnlineWrite(a.id, a_save.revision, secrets.token_hex(16), a_state),
                              OnlineWrite(b.id, b_save.revision, secrets.token_hex(16), b_state)])
    first.close()
    second = AccountStore(sqlite_path=db)
    assert second.authenticate(token) == a
    assert second.get_online(a).state['coins'] == 301
    assert second.get_online(b).state['coins'] == 402
    assert second.normal_info(a) == EMPTY_FARM


def test_pygame_migration_and_return_from_online(server, tmp_path, monkeypatch):
    relay, store = server
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER', 'dummy')
    monkeypatch.setenv('APPDATA', str(tmp_path/'win_profile'))
    monkeypatch.setenv('AMBERA_TEST_RELAY_URL', relay.endpoint)
    from ambera_farm import Game, pygame
    from farm_core import state_path
    monkeypatch.setattr(Game, 'fetch_mails', lambda self: None)
    monkeypatch.setattr(Game, 'refresh_notices', lambda self, force=False: None)
    original = farm_with(7520)
    save_state(original)
    original_bytes = state_path().read_bytes()
    game = Game()
    try:
        game.render()
        assert not any(action == 'begin' for action, *_ in game.buttons)
        game.open_account('register')
        game.account_fields.update(name='新しい牧場主', password=PASSWORD, confirm=PASSWORD)
        game.render()
        game.submit_account()
        assert not game.account_fields['password'] and not game.account_fields['confirm']
        def pump(condition, timeout=7):
            def tick():
                game.update_gameplay(.01)
                return condition()
            assert wait_for(tick, timeout)
        pump(lambda: game.modal == 'migration')
        game.render()
        assert game.migration_options[0].state['coins'] == 7520
        game.submit_first_farm(game.migration_options[0])
        game.render()
        assert game.normal_sync.flush(timeout=5)
        assert game.state['coins'] == 7520
        assert state_path().read_bytes() == original_bytes
        game.open_online_dialog('host')
        game.render()
        game.begin_internet_connection()
        assert game.modal == 'online_connect'
        pump(lambda: game.online_profile_received)
        assert game.state['coins'] == 200
        game.modal = 'pause'
        game.render()
        account = game.account_session.account
        game.do_action('return_title', None)
        assert game.scene == 'title' and game.state['coins'] == 7520
        assert store.normal_info(account).state['coins'] == 7520
        assert store.existing_online(account).state['coins'] == 200
        game.begin_logout()
        pump(lambda: game.account_session is None)
        assert game.state['coins'] == 200
        assert state_path().read_bytes() == original_bytes
    finally:
        if game.online_job:game.online_job.cancel()
        if game.online_client:game.stop_online()
        game.close_normal_on_exit()
        pygame.quit()


def test_pygame_cancelled_room_job_never_leaves_a_room_open(server, monkeypatch):
    from online_ui import ConnectionJob
    relay, _ = server
    session = register(relay, '取り消しテスト')
    started, proceed = threading.Event(), threading.Event()
    def delay(*args, **kwargs):
        started.set()
        proceed.wait(5)
        return RelayHost(*args, **kwargs)
    monkeypatch.setattr('online_ui.RelayHost', delay)
    job = ConnectionJob('host', {}, relay.endpoint, session)
    assert started.wait(5)
    job.cancel()
    proceed.set()
    job.thread.join(5)
    assert not job.thread.is_alive() and job.take() is None
    assert wait_for(lambda: not relay.relay.rooms and not relay.relay.active_players)
