import subprocess
import threading
import time
import shutil

def test_watchdog_behavior():
    """Test if the watchdog pattern works correctly."""
    
    p = subprocess.Popen(
        ['sleep', 10],
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    
    lines = []
    killed_by_watchdog = threading.Event()
    
    def _watchdog():
        print(f"[Watchdog] Sleeping for 2 seconds...")
        time.sleep(2)
        print(f"[Watchdog] Checking if process {p.pid} is still alive: {p.poll()}")
        if p.poll() is None:
            print(f"[Watchdog] Killing process group {os.getpgid(p.pid)}")
            import os, signal
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError) as e:
                print(f"[Watchdog] Error killing: {e}")
            killed_by_watchdog.set()
            print(f"[Watchdog] Set killed_by_watchdog event")
        else:
            print(f"[Watchdog] Process already exited with code {p.returncode}")
    
    wd = threading.Thread(target=_watchdog, daemon=True)
    wd.start()
    
    try:
        for line in p.stdout:
            lines.append(line.rstrip('\n'))
        p.wait()
    except KeyboardInterrupt:
        pass
    
    timed_out = killed_by_watchdog.is_set() or (p.returncode is not None and p.returncode < 0)
    return_code = 124 if timed_out else p.returncode
    
    print(f"\n[Main] Process returncode: {p.returncode}")
    print(f"[Main] killed_by_watchdog: {killed_by_watchdog.is_set()}")
    print(f"[Main] timed_out: {timed_out}")
    print(f"[Main] final return_code: {return_code}")

if __name__ == "__main__":
    test_watchdog_behavior()