# -*- coding: utf-8 -*-
"""Authoritative profiles and the single home farm for an authenticated room."""
import copy
from dataclasses import dataclass, field
import logging
import secrets
import threading
import time

from account_protocol import Account, AccountError, SavedFarm, encode_state
from account_store import OnlineWrite

LOG = logging.getLogger(__name__)
CHECKPOINT_INTERVAL = 2.0


@dataclass
class Seat:
    account: Account
    saved: SavedFarm
    ticket: str = field(repr=False)
    done: threading.Event = field(default_factory=threading.Event, repr=False)
    accepted: bool = False
    stored: bool = False


class ManagedFarm:
    """Methods are called with the game's room lock held."""
    def __init__(self, store, owner, farm):
        self.store = store
        self.owner = owner
        self.profiles = {owner.id: copy.deepcopy(farm.state)}
        self.committed = {owner.id: farm}
        self.tickets = {}
        self.departed = set()
        self.dirty = False
        self.next_checkpoint = 0.
        self.problem = ''
        self.pending = []

    def authorize(self, account, saved):
        if account.id in self.departed:
            raise AccountError('account_unavailable')
        ticket = secrets.token_hex(24)
        seat = Seat(account, saved, ticket)
        self.tickets[ticket] = seat
        return seat

    def enter(self, ticket):
        # The relay issues the hello on a loopback socket, never the client.
        seat = self.tickets.pop(ticket, None) if isinstance(ticket, str) else None
        if seat is None:
            return None
        if seat.account.id not in self.profiles:
            self.committed[seat.account.id] = seat.saved
            self.profiles[seat.account.id] = copy.deepcopy(seat.saved.state)
        return seat

    def _writes(self, plots, preparation):
        writes = []
        for ident, profile in self.profiles.items():
            if ident == self.owner.id:
                profile = dict(profile, plots=plots, plot_preparation=preparation)
            clean, _ = encode_state(copy.deepcopy(profile))
            previous = self.committed[ident]
            if clean != previous.state:
                writes.append(OnlineWrite(ident, previous.revision, secrets.token_hex(16), clean))
        return writes

    def checkpoint(self, plots, preparation, force=False):
        now = time.monotonic()
        if self.problem == 'save_conflict':
            return False
        if not force and (not self.dirty or now < self.next_checkpoint):
            return not self.problem
        self.next_checkpoint = now + CHECKPOINT_INTERVAL
        try:
            # Reuse write IDs after transient failures, including a lost commit
            # acknowledgement. Always take a fresh snapshot after a retry.
            if self.pending:
                self.committed.update(self.store.write_online_batch(self.pending))
                self.pending = []
            self.pending = self._writes(plots, preparation)
            if self.pending:
                self.committed.update(self.store.write_online_batch(self.pending))
                self.pending = []
            self.dirty = False
            self.problem = ''
            for ident in self.departed:
                if ident != self.owner.id:
                    self.profiles.pop(ident, None)
                    self.committed.pop(ident, None)
            self.departed.clear()
            return True
        except AccountError as error:
            self.problem = error.code
            self.dirty = True
            LOG.warning('Online room checkpoint deferred: %s', error.code)
            return False

    def depart(self, seat, plots, preparation):
        self.departed.add(seat.account.id)
        seat.stored = self.checkpoint(plots, preparation, force=True)
        seat.done.set()

    def discard_ticket(self, seat):
        self.tickets.pop(seat.ticket, None)
        if not seat.accepted:
            seat.stored = True
            seat.done.set()
