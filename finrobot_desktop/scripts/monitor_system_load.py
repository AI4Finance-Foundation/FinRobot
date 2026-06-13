#!/usr/bin/env python3
"""System load / heat monitor for the autonomous optimization session.

Watches CPU load-per-core, temperature & fan (best-effort, NO sudo) and the
count of session worker processes, so the orchestrator can back off launching
new parallel agents when the machine is straining (overheating / fans pinned).

Design constraints (this script must never become the bug it guards against):
- NEVER invoke sudo (e.g. ``sudo powermetrics``) — it would block forever on a
  password prompt. Temperature/fan come from optional third-party CLIs only.
- Every external call is timeout-bounded and failure-tolerant; a missing tool
  degrades to "n/a", never an exception.
- The loop sleeps between samples and is itself near-zero load.

Usage::

    python scripts/monitor_system_load.py            # loop, 15s interval -> /tmp/finrobot_monitor.log
    python scripts/monitor_system_load.py --once     # single sample to stdout
    python scripts/monitor_system_load.py --interval 30
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

LOG_PATH = "/tmp/finrobot_monitor.log"
STATE_PATH = "/tmp/finrobot_load_state.json"

# load1/ncpu thresholds: 1.0 == cores fully booked. Headroom-aware bands.
WARN_PER_CORE = 1.5
CRIT_PER_CORE = 2.5
WARN_TEMP_C = 85.0
CRIT_TEMP_C = 95.0

WORKER_PATTERNS = ("claude", "node", "mypy", "pytest", "ruff")


@dataclass
class Sample:
    ts: str
    cores: int
    load1: float
    load5: float
    load15: float
    load_per_core: float
    temp_c: float | None
    fan_rpm: float | None
    workers: int
    python_procs: int
    level: str
    recommendation: str


def _run(cmd: list[str], timeout: float = 5.0) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout if out.returncode == 0 else None


def _load_avg() -> tuple[float, float, float]:
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        return (0.0, 0.0, 0.0)


def _cpu_temp_c() -> float | None:
    """Best-effort CPU temp via optional CLIs. No sudo, ever."""
    if shutil.which("osx-cpu-temp"):
        out = _run(["osx-cpu-temp"])
        if out:
            try:
                return float(out.strip().rstrip("C").rstrip("°").strip())
            except ValueError:
                return None
    if shutil.which("istats"):
        out = _run(["istats", "cpu", "temp", "--value-only"])
        if out:
            try:
                return float(out.strip())
            except ValueError:
                return None
    return None


def _fan_rpm() -> float | None:
    """Best-effort max fan RPM via istats, if installed."""
    if not shutil.which("istats"):
        return None
    out = _run(["istats", "fan", "speed", "--value-only"])
    if not out:
        return None
    vals: list[float] = []
    for tok in out.split():
        try:
            vals.append(float(tok))
        except ValueError:
            continue
    return max(vals) if vals else None


def _proc_counts() -> tuple[int, int]:
    """(worker_count, python_proc_count) from a single ps snapshot."""
    out = _run(["ps", "-A", "-o", "comm="])
    if not out:
        return (0, 0)
    workers = 0
    pythons = 0
    for line in out.splitlines():
        low = line.lower()
        if any(p in low for p in WORKER_PATTERNS):
            workers += 1
        if "python" in low:
            pythons += 1
    return (workers, pythons)


def _classify(per_core: float, temp: float | None) -> tuple[str, str]:
    if per_core >= CRIT_PER_CORE or (temp is not None and temp >= CRIT_TEMP_C):
        return (
            "critical",
            "STOP launching new agents; let running ones drain or kill non-essential background work",
        )
    if per_core >= WARN_PER_CORE or (temp is not None and temp >= WARN_TEMP_C):
        return ("warn", "hold new agent launches until this clears")
    return ("ok", "fan-out freely")


def take_sample() -> Sample:
    cores = os.cpu_count() or 1
    l1, l5, l15 = _load_avg()
    per_core = l1 / cores
    temp = _cpu_temp_c()
    workers, pythons = _proc_counts()
    level, rec = _classify(per_core, temp)
    return Sample(
        ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        cores=cores,
        load1=round(l1, 2),
        load5=round(l5, 2),
        load15=round(l15, 2),
        load_per_core=round(per_core, 2),
        temp_c=temp,
        fan_rpm=_fan_rpm(),
        workers=workers,
        python_procs=pythons,
        level=level,
        recommendation=rec,
    )


def fmt(s: Sample) -> str:
    icon = {"ok": "OK ", "warn": "WARN", "critical": "CRIT"}[s.level]
    temp = f"{s.temp_c:.0f}C" if s.temp_c is not None else "temp n/a"
    fan = f"{s.fan_rpm:.0f}rpm" if s.fan_rpm is not None else "fan n/a"
    return (
        f"[{icon}] {s.ts}  load {s.load1}/{s.load5}/{s.load15} on {s.cores}c "
        f"= {s.load_per_core}/core  {temp}  {fan}  "
        f"py={s.python_procs} workers={s.workers}  -> {s.recommendation}"
    )


def write_state(s: Sample) -> None:
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(s), f)
    except OSError:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="one sample to stdout, then exit")
    ap.add_argument("--interval", type=float, default=15.0, help="seconds between samples")
    args = ap.parse_args()

    if args.once:
        s = take_sample()
        print(fmt(s))
        write_state(s)
        return

    interval = max(5.0, args.interval)
    while True:
        s = take_sample()
        line = fmt(s)
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        write_state(s)
        time.sleep(interval)


if __name__ == "__main__":
    main()
