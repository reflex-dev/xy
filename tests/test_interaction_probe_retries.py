"""The interaction probe's retry-and-headroom policy (CI reliability).

Headless-Chromium probes on shared runners have environmental failure modes
(virtual-time/wall-clock budget exhaustion, GPU init hiccups) that a fresh
launch resolves; a genuine client regression fails every attempt. These tests
pin that policy without launching a browser.
"""

from __future__ import annotations

from benchmarks import bench_interaction


def test_probe_relaunches_until_ok_and_reports_each_retry(monkeypatch, capsys):
    calls: list[dict] = []

    def fake_probe(html, *, marker, chromium, virtual_time_ms, timeout_s):
        calls.append({"virtual_time_ms": virtual_time_ms, "timeout_s": timeout_s})
        if len(calls) >= 3:
            return {"status": "ok"}
        return {"status": "failed(timeout)"}

    monkeypatch.setattr(bench_interaction, "run_json_probe", fake_probe)

    result = bench_interaction._probe_with_retries(
        "<html/>", chromium=None, scenario="density_scatter_interaction", retries=2
    )

    assert result["status"] == "ok"
    assert len(calls) == 3
    # Retries are recorded, never silent.
    err = capsys.readouterr().err
    assert "retry 1/2 for density_scatter_interaction" in err
    assert "failed(timeout)" in err
    # Every attempt gets the shared-runner headroom, not the library defaults.
    for call in calls:
        assert call["virtual_time_ms"] == bench_interaction.PROBE_VIRTUAL_TIME_MS
        assert call["timeout_s"] == bench_interaction.PROBE_TIMEOUT_S


def test_zero_retries_keeps_first_failure(monkeypatch):
    calls: list[int] = []

    def fake_probe(html, **kwargs):
        calls.append(1)
        return {"status": "failed(timeout)"}

    monkeypatch.setattr(bench_interaction, "run_json_probe", fake_probe)

    result = bench_interaction._probe_with_retries(
        "<html/>", chromium=None, scenario="s", retries=0
    )

    assert result["status"] == "failed(timeout)"
    assert len(calls) == 1


def test_persistent_failure_exhausts_retries_and_keeps_last_status(monkeypatch):
    calls: list[int] = []

    def fake_probe(html, **kwargs):
        calls.append(1)
        return {"status": "failed(no probe title)"}

    monkeypatch.setattr(bench_interaction, "run_json_probe", fake_probe)

    result = bench_interaction._probe_with_retries(
        "<html/>", chromium=None, scenario="s", retries=2
    )

    assert result["status"] == "failed(no probe title)"
    assert len(calls) == 3  # 1 + 2 retries, then the real regression surfaces


def test_probe_headroom_exceeds_library_defaults():
    """The budgets exist to out-wait slow shared runners; they must dominate
    the run_json_probe defaults or the constants silently stop mattering."""
    import inspect

    from benchmarks import _fastcharts_browser

    sig = inspect.signature(_fastcharts_browser.run_json_probe)
    assert sig.parameters["virtual_time_ms"].default < bench_interaction.PROBE_VIRTUAL_TIME_MS
    assert sig.parameters["timeout_s"].default < bench_interaction.PROBE_TIMEOUT_S
