import subprocess

from paxen import workers


def test_training_oom_does_not_kill_the_worker(monkeypatch, caplog):
    """An out-of-memory kill of the training child is logged; the caller (the worker) carries on."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, -9))
    assert workers.train_isolated() == {"exit": -9}
    assert "out of memory" in caplog.text


def test_training_success(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0))
    assert workers.train_isolated() == {"exit": 0}
