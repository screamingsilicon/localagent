"""Prototype: timing-based stream vs buffer decision for shell output."""
from __future__ import annotations
import time


BURST_GAP_MS = 200


def classify_output(lines_with_times):
    if len(lines_with_times) <= 1:
        return {
            "mode": "burst", "total_lines": len(lines_with_times),
            "total_duration_ms": 0, "switch_at_line": None,
            "burst_lines": len(lines_with_times), "stream_lines": 0,
        }

    burst_count = 0
    stream_count = 0
    switch_at = None
    threshold_s = BURST_GAP_MS / 1000.0

    for i in range(1, len(lines_with_times)):
        gap = lines_with_times[i][1] - lines_with_times[i - 1][1]
        if gap <= threshold_s:
            burst_count += 1
        else:
            stream_count += 1
            if switch_at is None:
                switch_at = i

    total = len(lines_with_times)
    if burst_count == total - 1:
        mode = "burst"
    elif stream_count == 0:
        mode = "burst"
    elif burst_count == 0:
        mode = "stream"
    else:
        mode = "mixed"

    duration_ms = (lines_with_times[-1][1] - lines_with_times[0][1]) * 1000

    return {
        "mode": mode, "total_lines": total,
        "total_duration_ms": round(duration_ms, 1),
        "switch_at_line": switch_at,
        "burst_lines": burst_count + 1,
        "stream_lines": stream_count,
    }


def gen_burst(n, gap_ms=0.5):
    t0 = time.monotonic()
    return [(f"line_{i}", t0 + i * gap_ms / 1000) for i in range(n)]


def gen_trickle(n, gap_ms=500):
    t0 = time.monotonic()
    return [(f"line_{i}", t0 + i * gap_ms / 1000) for i in range(n)]


def gen_mixed(burst_n, burst_gap_ms, trickle_n, trickle_gap_ms):
    t0 = time.monotonic()
    lines = [(f"line_{i}", t0 + i * burst_gap_ms / 1000) for i in range(burst_n)]
    base_t = t0 + burst_n * burst_gap_ms / 1000
    lines += [(f"line_{burst_n + i}", base_t + i * trickle_gap_ms / 1000) for i in range(trickle_n)]
    return lines


def simulate_display(lines_with_times, label):
    result = classify_output(lines_with_times)
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Mode: {result['mode']} | Lines: {result['total_lines']} | Duration: {result['total_duration_ms']}ms")
    print(f"  Burst: {result['burst_lines']} lines | Stream: {result['stream_lines']} lines")
    if result["switch_at_line"] is not None:
        print(f"  -> Switched burst->stream at line {result['switch_at_line']}")

    mode = result["mode"]
    lines = [l[0] for l in lines_with_times]

    if mode == "burst":
        print(f"\n  [Screen: NOTHING during execution, truncated result at exit]")
    elif mode == "stream":
        print(f"\n  [Screen: ALL lines streamed live]")
    else:
        sw = result["switch_at_line"]
        print(f"\n  [Lines 0-{sw-1} buffered (burst)]")
        print(f"  [Lines {sw}-{len(lines)-1} streamed live]")


def test_live_command(cmd, label):
    import subprocess, shutil

    print(f"\n{'='*60}")
    print(f"  LIVE: {label}")
    print(f"  $ {cmd}")

    shell_bin = shutil.which("bash") or "/bin/sh"
    p = subprocess.Popen(
        cmd, shell=True, executable=shell_bin,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    lines_with_times = []
    t_start = time.monotonic()
    for line in p.stdout:
        elapsed = time.monotonic() - t_start
        lines_with_times.append((line.rstrip(), elapsed))
    p.wait()

    result = classify_output(lines_with_times)
    print(f"  Mode: {result['mode']} | Lines: {result['total_lines']} | Duration: {result['total_duration_ms']}ms")
    print(f"  Burst: {result['burst_lines']} | Stream: {result['stream_lines']}")
    if result["switch_at_line"] is not None:
        print(f"  -> Switched at line {result['switch_at_line']}")

    if len(lines_with_times) >= 2:
        print(f"\n  First 10 inter-line gaps (ms):")
        for i in range(1, min(11, len(lines_with_times))):
            gap = (lines_with_times[i][1] - lines_with_times[i-1][1]) * 1000
            marker = " <- burst" if gap <= BURST_GAP_MS else " -> stream"
            print(f"    line {i}: {gap:6.1f}ms{marker}")


def main():
    print(f"BURST_GAP_MS = {BURST_GAP_MS}")

    # Simulated scenarios
    simulate_display(gen_burst(5000, gap_ms=0.3),     "SIM: cat large file (5000 lines in ~1.5s)")
    simulate_display(gen_burst(200, gap_ms=1.0),       "SIM: grep with 200 matches (~0.2s)")
    simulate_display(gen_trickle(50, gap_ms=400),      "SIM: build progress (50 lines over 20s)")
    simulate_display(gen_trickle(30, gap_ms=1000),     "SIM: apt install (30 lines over 30s)")
    simulate_display(gen_mixed(500, 0.5, 20, 600),     "SIM: grep on huge file (burst then trickle)")
    simulate_display(gen_burst(10, gap_ms=0.1),        "SIM: ls -R small dir")
    simulate_display(gen_mixed(3, 1000, 5, 0.5),       "SIM: slow start then burst (edge case)")

    # Live commands
    test_live_command("echo line1; echo line2; echo line3",                     "Quick echo")
    test_live_command("ls /usr/bin | head -100",                                "ls /usr/bin | head")
    test_live_command("find /workspace -name '*.py' -type f 2>/dev/null",       "find .py files in /workspace")
    test_live_command("seq 1 5000",                                              "seq 1 5000 (burst)")
    test_live_command("for i in $(seq 1 10); do echo $i; sleep 0.3; done",      "Loop with 300ms delay")

    print(f"\n{'='*60}")
    print("  Done. Adjust BURST_GAP_MS at top of file and re-run.")


if __name__ == "__main__":
    main()
