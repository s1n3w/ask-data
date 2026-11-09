"""Start Ollama, run the interactive question prompt, and stop Ollama on exit.

Run:  python -m askdata.launcher       (or double-click "Ask Data.bat")

Ollama is started hidden inside a Windows job object set to kill everything in it when the
job's last handle closes. The handle belongs to this process, so Ollama and its model runner
stop however the launcher ends: typing a blank line, Ctrl+C, or closing the console window.
If Ollama was already running before launch, it is left alone.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import requests

from . import llm
from .ask import main as ask_main

OLLAMA_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
STARTUP_TIMEOUT_S = 30

JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _kill_on_close_job(process: subprocess.Popen):
    """Put the process in a job that Windows kills when this launcher exits. Returns the job handle."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(wintypes.HANDLE(job), JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                          ctypes.byref(limits), ctypes.sizeof(limits))
    ok = ok and kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(process._handle))
    if not ok:
        raise OSError(ctypes.get_last_error(), "Couldn't attach Ollama to a job object")
    return job  # must stay referenced (and open) for the life of the launcher


def ollama_running() -> bool:
    try:
        return requests.get(f"{llm.OLLAMA_URL}/api/version", timeout=1).ok
    except requests.RequestException:
        return False


def start_ollama():
    exe = OLLAMA_EXE if OLLAMA_EXE.exists() else shutil.which("ollama")
    if not exe:
        raise SystemExit("Ollama isn't installed (expected it at " + str(OLLAMA_EXE) + ").")
    process = subprocess.Popen([str(exe), "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    job = _kill_on_close_job(process)
    deadline = time.time() + STARTUP_TIMEOUT_S
    while not ollama_running():
        if process.poll() is not None or time.time() > deadline:
            process.kill()
            raise SystemExit("Ollama didn't start. Try running it once from the Start menu to see the error.")
        time.sleep(0.3)
    return process, job


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    process = job = None
    if ollama_running():
        print("Ollama is already running; it will be left running when you quit.")
    else:
        print("Starting Ollama...", flush=True)
        process, job = start_ollama()
    try:
        print("Loading the model onto the GPU (first time takes a few seconds)...", flush=True)
        llm.chat([{"role": "user", "content": "Reply OK."}])
        sys.argv = sys.argv[:1]  # interactive mode
        ask_main()
    except KeyboardInterrupt:
        pass
    finally:
        if process:
            print("Stopping Ollama...")
            process.terminate()  # the runner child dies with the job when this process exits


if __name__ == "__main__":
    main()
