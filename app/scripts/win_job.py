"""Windows Job Object process containment (stdlib ``ctypes`` only — no pywin32).

Why this exists
---------------
The UnboundBot supervisor (``supervise.py``) launches its workers (monitor,
learner, and the three order executors) in their OWN process group via
``CREATE_NEW_PROCESS_GROUP`` so that Ctrl+C typed at the supervisor console does
not instantly propagate to every child. That isolation is deliberate and is
kept. The side effect — documented in ``docs/Audit_2026-10-22.md`` §11.3 — was a
real orphan-process bug: if the supervisor process is *force-terminated* (Task
Manager, ``Stop-Process -Force``, a crashed host shell) its ``finally`` drain
never runs, so every child (and, because ``run_paper.py`` itself shells out to
``freqtrade.exe``, the whole executor *grandchild* tree too) keeps running with
nobody owning it.

A Windows **Job Object** with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` is the only
OS-level guarantee that removes this class of bug: the kernel terminates *every*
process assigned to the job the moment the last handle to the job closes — and
that handle lives in the supervisor, so if the supervisor dies for ANY reason
(handle closed by the OS on process exit), the entire contained tree dies with
it. This is enforced by the operating system, not by cooperative signal handling,
which is why it is the primary defence rather than a signal/heartbeat best-effort.

Atomic containment (no escape race)
------------------------------------
A child must enter the job *before* it can spawn descendants. ``subprocess.
Popen`` starts the process immediately and gives no hook, and assigning after
start leaves a window where a fast child could spawn a grandchild outside the
job. So we create the process ourselves with ``CREATE_SUSPENDED``, assign the
suspended process to the job, and only then ``ResumeThread``. Grandchildren
created later inherit the job automatically (children cannot break away: we never
pass ``CREATE_BREAKAWAY_FROM_JOB`` and never enable breakaway limits on the job),
and the job handle is created non-inheritable and passed with
``bInheritHandles=FALSE`` so no child can acquire it.

Fail-closed
-----------
If the job cannot be created, or a process cannot be assigned to it (an outer
job on the supervisor disallows nesting, restrictive policy, handle error), we
raise :class:`ContainmentError`. Callers MUST treat that as "do not launch this
process" rather than launching it unprotected. A supervisor that cannot
guarantee containment cannot honour its no-orphan safety contract.

This module is Windows-only; import it only behind an ``os.name == "nt"`` guard.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes

# ----------------------------------------------------------------- constants
CREATE_SUSPENDED = 0x00000004
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000  # deliberately never used

_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102

_STILL_ACTIVE = 259

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

_CTRL_C_EVENT = 0
_CTRL_BREAK_EVENT = 1

_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)


class ContainmentError(RuntimeError):
    """Job creation or process assignment failed. Callers must fail closed."""


# ----------------------------------------------------------------- structs
class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


# ------------------------------------------------------------- kernel32 signatures
_KERNEL32.CreateJobObjectW.restype = wintypes.HANDLE
_KERNEL32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
_KERNEL32.SetInformationJobObject.restype = wintypes.BOOL
_KERNEL32.SetInformationJobObject.argtypes = [
    wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
]
_KERNEL32.AssignProcessToJobObject.restype = wintypes.BOOL
_KERNEL32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_KERNEL32.TerminateJobObject.restype = wintypes.BOOL
_KERNEL32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
_KERNEL32.CreateProcessW.restype = wintypes.BOOL
_KERNEL32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID,
    wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION),
]
_KERNEL32.ResumeThread.restype = wintypes.DWORD
_KERNEL32.ResumeThread.argtypes = [wintypes.HANDLE]
_KERNEL32.GetExitCodeProcess.restype = wintypes.BOOL
_KERNEL32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_KERNEL32.WaitForSingleObject.restype = wintypes.DWORD
_KERNEL32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_KERNEL32.TerminateProcess.restype = wintypes.BOOL
_KERNEL32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_KERNEL32.CloseHandle.restype = wintypes.BOOL
_KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
_KERNEL32.GenerateConsoleCtrlEvent.restype = wintypes.BOOL
_KERNEL32.GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD, wintypes.DWORD]


def _last_err() -> int:
    return ctypes.get_last_error()


def supported() -> bool:
    """Job Object containment is available on this interpreter (Windows only)."""
    return sys.platform == "win32"


# ----------------------------------------------------------------- Job
class JobObject:
    """A kill-on-close Windows Job Object. Owns exactly one kernel handle."""

    def __init__(self, name: str | None = None):
        self._name = name
        self._handle = _KERNEL32.CreateJobObjectW(None, name)
        if not self._handle:
            raise ContainmentError(
                f"CreateJobObjectW failed (WinError {_last_err()})"
            )
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _KERNEL32.SetInformationJobObject(
            self._handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            err = _last_err()
            self.close()
            raise ContainmentError(
                f"SetInformationJobObject(KILL_ON_JOB_CLOSE) failed (WinError {err})"
            )

    @property
    def handle(self):
        return self._handle

    def assign(self, process_handle) -> None:
        """Bind an already-created process handle to this job. Fail-closed."""
        if not self._handle:
            raise ContainmentError("job already closed")
        if not _KERNEL32.AssignProcessToJobObject(self._handle, process_handle):
            raise ContainmentError(
                f"AssignProcessToJobObject failed (WinError {_last_err()}) — "
                "the process could not be contained; refusing to launch unprotected. "
                "An outer Windows job may disallow nesting."
            )

    def terminate(self, exit_code: int = 0) -> None:
        if self._handle:
            _KERNEL32.TerminateJobObject(self._handle, exit_code)

    def close(self) -> None:
        # Closing the last handle is what triggers the OS to kill contained procs.
        if self._handle:
            _KERNEL32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> "JobObject":
        return self

    def __exit__(self, *_exc) -> bool:
        self.close()
        return False


# ----------------------------------------------------------------- managed process
class ManagedProcess:
    """A minimal subprocess.Popen-shaped handle over a job-contained process.

    Exposes the same surface ``supervise.Managed`` relies on: ``pid``,
    ``poll()``, ``wait(timeout)``, ``send_signal()``, ``terminate()``,
    ``kill()``, plus a deterministic ``close()`` that releases the process
    handle (job cleanup does the killing on supervisor death).
    """

    def __init__(self, process_handle, pid: int, argv: list[str]):
        self._handle = process_handle
        self.pid = pid
        self._argv = list(argv)
        self._returncode: int | None = None

    @property
    def handle(self):
        return self._handle

    @property
    def returncode(self) -> int | None:
        return self._returncode

    def poll(self) -> int | None:
        if self._returncode is not None:
            return self._returncode
        code = wintypes.DWORD(0)
        if not _KERNEL32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            # Handle invalid -> process is gone.
            self._returncode = -1
            return self._returncode
        if code.value == _STILL_ACTIVE:
            return None
        self._returncode = code.value
        return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        ms = _INFINITE if timeout is None else max(0, int(timeout * 1000))
        r = _KERNEL32.WaitForSingleObject(self._handle, ms)
        if r == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(self._argv, timeout)
        code = self.poll()
        return code if code is not None else -1

    def send_signal(self, sig: int) -> None:
        """Ctrl-C / Ctrl-Break to this process's own group (graceful). Anything
        else is a hard terminate. The target shares our console and was created
        with CREATE_NEW_PROCESS_GROUP, so its group id == its pid."""
        if sig in (_CTRL_C_EVENT, _CTRL_BREAK_EVENT):
            ok = _KERNEL32.GenerateConsoleCtrlEvent(sig, self.pid)
            if not ok:
                # Not attached / already gone: escalate rather than silently no-op.
                self.terminate()

    def terminate(self) -> None:
        # Graceful-ish stop request for a non-console-signalled child.
        self.kill()

    def kill(self) -> None:
        if self._returncode is None:
            _KERNEL32.TerminateProcess(self._handle, 1)
            self.poll()

    def close(self) -> None:
        if self._handle:
            _KERNEL32.CloseHandle(self._handle)
            self._handle = None

    def __repr__(self) -> str:  # diagnostics: pid + argv + state are legible
        state = "alive" if self.poll() is None else f"exit={self._returncode}"
        return f"<ManagedProcess pid={self.pid} {state} argv={self._argv!r}>"


# ----------------------------------------------------------------- spawn
def spawn(argv: list[str], *, cwd: str | None, job: JobObject) -> ManagedProcess:
    """Atomically create a suspended, new-process-group child, bind it to the
    job, then resume it. Fail-closed: any containment problem terminates the
    half-created child and raises :class:`ContainmentError`."""
    if not argv:
        raise ValueError("argv must be non-empty")
    cmdline = subprocess.list2cmdline([str(a) for a in argv])
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    pi = PROCESS_INFORMATION()
    flags = CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP
    ok = _KERNEL32.CreateProcessW(
        None,                # application name (use cmdline[0])
        cmdline,            # command line
        None, None,         # default process/thread security
        False,              # bInheritHandles — FALSE so the job handle is NOT passed
        flags,
        None,               # inherit parent environment
        str(cwd) if cwd else None,
        ctypes.byref(si), ctypes.byref(pi),
    )
    if not ok:
        raise ContainmentError(f"CreateProcessW failed (WinError {_last_err()})")

    try:
        # Contain BEFORE resuming — a suspended process cannot spawn descendants.
        job.assign(pi.hProcess)
    except ContainmentError:
        _KERNEL32.TerminateProcess(pi.hProcess, 1)
        _KERNEL32.CloseHandle(pi.hThread)
        _KERNEL32.CloseHandle(pi.hProcess)
        raise

    # Resume: the process now runs, already inside the job.
    if _KERNEL32.ResumeThread(pi.hThread) == 0xFFFFFFFF:  # (DWORD)-1 == failure
        err = _last_err()
        _KERNEL32.TerminateProcess(pi.hProcess, 1)
        _KERNEL32.CloseHandle(pi.hThread)
        _KERNEL32.CloseHandle(pi.hProcess)
        raise ContainmentError(f"ResumeThread failed (WinError {err})")
    _KERNEL32.CloseHandle(pi.hThread)  # thread handle not needed after resume
    return ManagedProcess(pi.hProcess, pi.dwProcessId, argv)
