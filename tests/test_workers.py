"""Per-backend workers: coalescing, one job at a time, results via the dispatcher."""

import threading
import time

from settings_hub.workers import Worker, Workers


def direct(fn):
    fn()


def test_coalesces_jobs_queued_while_one_runs():
    w = Worker("t", direct)
    gate = threading.Event()
    ran = []
    w.submit(lambda: (gate.wait(2), ran.append(0)))
    time.sleep(0.05)  # the first job is now running and blocked
    for i in (1, 2, 3):
        w.submit(lambda i=i: ran.append(i))
    assert w.pending() == 1
    gate.set()
    assert w.wait_idle(2)
    assert ran == [0, 3]
    w.stop(1)


def test_different_keys_all_run_in_order_of_latest_submit():
    w = Worker("t", direct)
    gate = threading.Event()
    ran = []
    w.submit(gate.wait, key="block")
    time.sleep(0.05)
    w.submit(lambda: ran.append("a1"), key="a")
    w.submit(lambda: ran.append("b"), key="b")
    w.submit(lambda: ran.append("a2"), key="a")
    gate.set()
    assert w.wait_idle(2)
    assert ran == ["b", "a2"]
    w.stop(1)


def test_never_two_jobs_at_once():
    w = Worker("t", direct)
    lock = threading.Lock()
    state = {"now": 0, "max": 0, "done": 0}

    def job():
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.005)
        with lock:
            state["now"] -= 1
            state["done"] += 1

    threads = [threading.Thread(target=lambda k=k: [w.submit(job, key=(k, j))
                                                    for j in range(10)]) for k in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert w.wait_idle(5)
    assert state["max"] == 1
    assert state["done"] == 50
    w.stop(1)


def test_result_and_error_go_through_the_dispatcher():
    calls = []
    dispatched = []

    def dispatch(fn):
        dispatched.append(threading.current_thread().name)
        fn()

    w = Worker("night", dispatch)
    w.submit(lambda: 42, on_done=lambda r, e: calls.append((r, e)))
    w.submit(lambda: 1 / 0, on_done=lambda r, e: calls.append((r, type(e))), key="x")
    assert w.wait_idle(2)
    assert calls == [(42, None), (None, ZeroDivisionError)]
    assert dispatched == ["apply-night", "apply-night"]
    w.stop(1)


def test_busy_while_queued_or_running():
    w = Worker("t", direct)
    gate = threading.Event()
    assert not w.busy()
    w.submit(gate.wait)
    assert w.busy()
    gate.set()
    assert w.wait_idle(2)
    assert not w.busy()
    w.stop(1)


def test_workers_one_thread_per_backend():
    ws = Workers(direct)
    assert ws.get("screen-sleep") is ws.get("screen-sleep")
    assert ws.get("screen-sleep") is not ws.get("night")
    done = threading.Event()
    ws.submit("night", lambda: None, on_done=lambda r, e: done.set())
    assert done.wait(2)
    ws.stop_all(1)
