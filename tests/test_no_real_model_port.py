"""Safety guard (Q-126 design §6 rule 7, D-214): no test may touch the real Ollama port 11434.

Since Q-126 the queue worker's precheck calls `backends.ensure_model_running` for a real
`OllamaBackend` (the always-flow tests build one over a mock transport). With no injected
`model_ensurer` that call opens a REAL socket to 127.0.0.1:11434 (the owner's live model, and
with autostart on, it may even start a process). `tests/always_flow_support.run_q` therefore
injects a scripted ensurer. These pins fail if that comes back:

  * the trap itself works (the unguarded service call is seen and refused), so the next pin
    is not green by accident;
  * driving `run_q` (the always-flow support path, default ensurer) makes no connection to
    port 11434, and a not-ready ensurer passed through `run_q` pauses the queue.

The trap refuses the connection (nothing leaves the process) and records the attempt.
Verify: python tests/run_tests.py -k no_real_model_port
"""
from __future__ import annotations

import contextlib
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import always_flow_support as S  # noqa: E402
from always_flow_support import Net, backend, make, nav_class, run_q  # noqa: E402

from jobscraper import backends  # noqa: E402

PORT = 11434


def _port_of(address) -> object:
    try:
        return address[1]
    except (TypeError, IndexError, KeyError):
        return None


@contextlib.contextmanager
def port_trap():
    """Every socket connect to port 11434 is recorded and refused (ConnectionRefusedError, which
    httpx reports as a ConnectError); other ports pass through untouched."""
    seen: list[object] = []
    real_cc = socket.create_connection
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def refuse(address):
        seen.append(address)
        raise ConnectionRefusedError(f"test trap: no connection to port {PORT}")

    def create_connection(address, *a, **k):
        if _port_of(address) == PORT:
            refuse(address)
        return real_cc(address, *a, **k)

    def connect(self, address):
        if _port_of(address) == PORT:
            refuse(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        if _port_of(address) == PORT:
            seen.append(address)
            return 10061                      # WSAECONNREFUSED / ECONNREFUSED-like: just "failed"
        return real_connect_ex(self, address)

    socket.create_connection = create_connection
    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
    try:
        yield seen
    finally:
        socket.create_connection = real_cc
        socket.socket.connect, socket.socket.connect_ex = real_connect, real_connect_ex


def test_the_trap_sees_an_unguarded_service_call():
    """Canary: the real `ensure_model_running` over a real httpx client IS caught by the trap."""
    be = backend(Net())
    with port_trap() as seen:
        r = backends.ensure_model_running({}, autostart=False, backend=be, sleep=lambda s: None)
    assert seen, "the trap did not see the probe: the guard below would pass for the wrong reason"
    assert r.code == "not_running", r.code           # refused three times, autostart off: nothing started
    assert all(_port_of(a) == PORT for a in seen)


def _model_on(w):
    """The test world's budget has the model switched off, and then the precheck answers "off"
    without pinging. Switch it on (Ollama, the default URL) so an un-injected service WOULD ping."""
    w.cfg.budget.update(enable_llm=True, backend="ollama")


def test_the_always_flow_support_path_makes_no_connection_to_port_11434():
    w, cid, jobs = make(1)
    try:
        _model_on(w)
        net = Net(chat=S.answering())
        with port_trap() as seen:
            run_q(w, cid, jobs, nav_class()(), backend(net), S.real_page(S.req_numbers("q", 1), "one"),
                  fill_policy="always")
        assert seen == [], f"a test reached the real model port: {seen}"
        assert w.attempt_rows(), "the worker took the role (the guard drove a real run)"
    finally:
        w.close()


def test_run_q_passes_a_not_ready_ensurer_through_and_still_touches_no_port():
    w, cid, jobs = make(1)
    try:
        _model_on(w)
        calls: list[dict] = []
        with port_trap() as seen:
            run_q(w, cid, jobs, nav_class()(), backend(Net()), ensurer=S.ready_ensurer("not_running", calls=calls))
        assert seen == [], seen
        assert calls and calls[0]["autostart"] is False   # library default: never start
        assert w.attempt_rows() == [], "a not-ready model takes no role"
        st = w.store.queue_pause_state()
        assert (st or {}).get("reason") == "model_unavailable", st
    finally:
        w.close()
