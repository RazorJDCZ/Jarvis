from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from jarvis.actions.windows import AppController, InstalledApp, WindowController


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _tokens(value: str) -> set[str]:
    ignored = {
        "app",
        "aplicacion",
        "de",
        "del",
        "for",
        "la",
        "los",
        "microsoft",
        "para",
        "the",
        "windows",
    }
    return {
        token
        for token in "".join(
            character if character.isalnum() else " " for character in _normalize(value)
        ).split()
        if len(token) >= 3 and token not in ignored
    }


@dataclass(slots=True)
class LifecycleResult:
    index: int
    name: str
    source: str
    launch_success: bool
    launch_verified: bool
    launch_message: str
    new_windows: list[dict[str, object]]
    closed_windows: list[dict[str, object]]
    residual_windows: list[dict[str, object]]
    new_processes: list[dict[str, object]]
    terminated_processes: list[dict[str, object]]
    residual_processes: list[dict[str, object]]
    status: str
    elapsed_seconds: float


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


@dataclass(frozen=True, slots=True)
class _ProcessInfo:
    name: str
    parent_pid: int


_PROCESS_INFRASTRUCTURE = {
    "applicationframehost.exe",
    "backgroundtaskhost.exe",
    "conhost.exe",
    "dllhost.exe",
    "runtimebroker.exe",
    "searchhost.exe",
    "shellexperiencehost.exe",
    "svchost.exe",
}


def _process_snapshot() -> dict[int, _ProcessInfo]:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry)]
    kernel32.Process32FirstW.restype = ctypes.c_bool
    kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry)]
    kernel32.Process32NextW.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot in {None, invalid_handle}:
        return {}
    entry = _ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    processes: dict[int, _ProcessInfo] = {}
    try:
        available = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while available:
            processes[int(entry.th32ProcessID)] = _ProcessInfo(
                name=entry.szExeFile,
                parent_pid=int(entry.th32ParentProcessID),
            )
            available = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    return processes


def _new_application_processes(
    before: dict[int, _ProcessInfo],
    after: dict[int, _ProcessInfo],
) -> dict[int, _ProcessInfo]:
    current_pid = os.getpid()
    return {
        pid: info
        for pid, info in after.items()
        if pid not in before
        and pid != current_pid
        and info.parent_pid not in before
        and info.name.casefold() not in _PROCESS_INFRASTRUCTURE
    }


def _wait_for_process_exit(
    processes: dict[int, _ProcessInfo],
    timeout: float = 5.0,
) -> dict[int, _ProcessInfo]:
    deadline = time.monotonic() + timeout
    residual = processes
    while residual and time.monotonic() < deadline:
        current = _process_snapshot()
        residual = {
            pid: info
            for pid, info in processes.items()
            if current.get(pid) is not None
            and current[pid].name.casefold() == info.name.casefold()
        }
        if residual:
            time.sleep(0.25)
    return residual


def _window_process_id(handle: int) -> int | None:
    process_id = ctypes.c_ulong()
    if not ctypes.windll.user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id)):
        return None
    return int(process_id.value) or None


def _owned_process_tree(
    before: dict[int, _ProcessInfo],
    after: dict[int, _ProcessInfo],
    roots: set[int],
) -> dict[int, _ProcessInfo]:
    owned = {pid for pid in roots if pid > 0}
    changed = True
    while changed:
        changed = False
        for pid, info in after.items():
            if pid in before or pid in owned or info.parent_pid not in owned:
                continue
            owned.add(pid)
            changed = True
    return {
        pid: info
        for pid, info in after.items()
        if pid not in before and pid in owned
    }


def _terminate_owned_processes(
    processes: dict[int, _ProcessInfo],
) -> list[dict[str, object]]:
    if not processes:
        return []
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.TerminateProcess.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool

    def depth(pid: int) -> int:
        seen: set[int] = set()
        current = pid
        value = 0
        while current in processes and current not in seen:
            seen.add(current)
            current = processes[current].parent_pid
            value += 1
        return value

    terminated: list[dict[str, object]] = []
    for pid in sorted(processes, key=depth, reverse=True):
        expected = processes[pid]
        current = _process_snapshot().get(pid)
        if current is None:
            terminated.append({"pid": pid, "name": expected.name, "already_gone": True})
            continue
        if current.name.casefold() != expected.name.casefold():
            terminated.append(
                {"pid": pid, "name": current.name, "identity_changed": True, "success": False}
            )
            continue
        handle = kernel32.OpenProcess(0x0001, False, pid)
        success = bool(handle and kernel32.TerminateProcess(handle, 0))
        if handle:
            kernel32.CloseHandle(handle)
        terminated.append({"pid": pid, "name": expected.name, "success": success})
    return terminated


def _foreground_handle(windows: WindowController) -> int | None:
    result = windows.current()
    if not result.success:
        return None
    handle = result.details.get("handle")
    return handle if isinstance(handle, int) and not isinstance(handle, bool) else None


def _candidate_windows(
    *,
    label: str,
    before: dict[int, str],
    after: dict[int, str],
    foreground: int | None,
    include_foreground: bool = True,
) -> dict[int, str]:
    appeared = {handle: title for handle, title in after.items() if handle not in before}
    if not appeared:
        return {}
    label_tokens = _tokens(label)
    matching = {
        handle: title
        for handle, title in appeared.items()
        if label_tokens and label_tokens.intersection(_tokens(title))
    }
    if include_foreground and foreground in appeared:
        matching[foreground] = appeared[foreground]
    # A single newly visible top-level window immediately after InvokeVerb is a
    # stronger identity signal than its localized or document-derived title.
    if not matching and len(appeared) == 1:
        return appeared
    return matching


def _wait_for_candidates(
    windows: WindowController,
    *,
    label: str,
    before: dict[int, str],
    timeout: float,
) -> tuple[dict[int, str], dict[int, str]]:
    deadline = time.monotonic() + timeout
    latest = before
    candidates: dict[int, str] = {}
    last_change = time.monotonic()
    while time.monotonic() < deadline:
        latest = windows.visible_window_snapshot()
        foreground = _foreground_handle(windows)
        current = _candidate_windows(
            label=label,
            before=before,
            after=latest,
            foreground=foreground,
        )
        if current != candidates:
            candidates = current
            last_change = time.monotonic()
        if candidates and time.monotonic() - last_change >= 0.8:
            break
        time.sleep(0.2)
    return candidates, latest


def _close_created_windows(
    windows: WindowController,
    created: dict[int, str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    closed: list[dict[str, object]] = []
    for handle in reversed(tuple(created)):
        current_title = windows.visible_window_snapshot().get(handle)
        if current_title is None:
            closed.append({"handle": handle, "title": created[handle], "already_gone": True})
            continue
        normalized_title = _normalize(current_title)
        if (
            current_title.lstrip().startswith("*")
            or "recuperado" in normalized_title
            or "recovered" in normalized_title
        ):
            closed.append(
                {
                    "handle": handle,
                    "title": current_title,
                    "success": False,
                    "verified": False,
                    "message": (
                        "No cerré una ventana que parece contener trabajo "
                        "recuperado o sin guardar."
                    ),
                }
            )
            continue
        result = windows.close_handle(handle, current_title)
        closed.append(
            {
                "handle": handle,
                "title": current_title,
                "success": result.success,
                "verified": result.details.get("verified", False),
                "message": result.message,
            }
        )
    # Office and a few launchers acknowledge WM_CLOSE immediately but finish their
    # shutdown several seconds later. Waiting avoids a false residual and, more
    # importantly, prevents the next application from overlapping with it.
    deadline = time.monotonic() + 8.0
    residual: dict[int, str] = {}
    while time.monotonic() < deadline:
        snapshot = windows.visible_window_snapshot()
        residual = {handle: snapshot[handle] for handle in created if handle in snapshot}
        if not residual:
            break
        time.sleep(0.2)
    # Some apps reuse a splash/installer handle for their main window. Revalidate
    # the new title and make one more graceful close request instead of carrying the
    # fully started application into the next test.
    transitioned = {
        handle: title
        for handle, title in residual.items()
        if title != created.get(handle)
        and not title.lstrip().startswith("*")
        and "recuperado" not in _normalize(title)
        and "recovered" not in _normalize(title)
    }
    for handle, title in transitioned.items():
        result = windows.close_handle(handle, title)
        closed.append(
            {
                "handle": handle,
                "title": title,
                "success": result.success,
                "verified": result.details.get("verified", False),
                "message": result.message,
                "transitioned": True,
            }
        )
    if transitioned:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            snapshot = windows.visible_window_snapshot()
            residual = {handle: snapshot[handle] for handle in created if handle in snapshot}
            if not residual:
                break
            time.sleep(0.2)
    return closed, [
        {"handle": handle, "title": title} for handle, title in residual.items()
    ]


def _close_successor_windows(
    windows: WindowController,
    *,
    label: str,
    before: dict[int, str],
    already_seen: dict[int, str],
    grace: float = 10.0,
) -> tuple[dict[int, str], list[dict[str, object]], list[dict[str, object]]]:
    """Close a main window that replaces a splash, prompt, or launcher later."""
    discovered: dict[int, str] = {}
    closed: list[dict[str, object]] = []
    residual: list[dict[str, object]] = []
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        snapshot = windows.visible_window_snapshot()
        foreground = _foreground_handle(windows)
        candidates = _candidate_windows(
            label=label,
            before=before,
            after=snapshot,
            foreground=foreground,
            include_foreground=False,
        )
        candidates = {
            handle: title
            for handle, title in candidates.items()
            if handle not in already_seen and handle not in discovered
        }
        if not candidates:
            time.sleep(0.25)
            continue
        discovered.update(candidates)
        successor_closed, successor_residual = _close_created_windows(windows, candidates)
        closed.extend(successor_closed)
        residual.extend(successor_residual)
        if successor_residual:
            break
        # A splash may be followed by a prompt and then the main window. Give each
        # verified successor its own complete grace period before advancing.
        deadline = time.monotonic() + grace
    return discovered, closed, residual


def _test_one(
    *,
    windows: WindowController,
    apps: AppController,
    index: int,
    name: str,
    source: str,
    timeout: float,
    installed: InstalledApp | None = None,
) -> LifecycleResult:
    before = windows.visible_window_snapshot()
    processes_before = _process_snapshot()
    started = time.monotonic()
    if installed is None:
        launch = apps.open(name)
    else:
        launch = apps.open(
            name,
            app_id=installed.app_id,
            display_name=installed.name,
            target_path=installed.target_path,
        )
    observation_timeout = 1.5 if launch.details.get("verified") else timeout
    candidates, _latest = _wait_for_candidates(
        windows,
        label=installed.name if installed is not None else apps.APPS[name].display_name,
        before=before,
        timeout=observation_timeout,
    )
    if not candidates and launch.success and not launch.details.get("verified"):
        # Launchers such as Battle.net can return before their first window exists.
        # Do not start another application while that delayed window is pending.
        candidates, _latest = _wait_for_candidates(
            windows,
            label=installed.name if installed is not None else apps.APPS[name].display_name,
            before=before,
            timeout=min(8.0, timeout),
        )
    owned_roots = {
        process_id
        for process_id in (_window_process_id(handle) for handle in candidates)
        if process_id is not None
    }
    for detail_key in ("pid", "launcher_pid"):
        process_id = launch.details.get(detail_key)
        if isinstance(process_id, int) and not isinstance(process_id, bool):
            owned_roots.add(process_id)
    closed, residual = _close_created_windows(windows, candidates)
    label = installed.name if installed is not None else apps.APPS[name].display_name
    if candidates and not residual:
        successors, successor_closed, successor_residual = _close_successor_windows(
            windows,
            label=label,
            before=before,
            already_seen=candidates,
        )
        candidates.update(successors)
        closed.extend(successor_closed)
        residual.extend(successor_residual)
    launch_success = bool(launch.success)
    launch_verified = bool(launch.details.get("verified"))
    processes_after = _process_snapshot()
    created_processes = _new_application_processes(processes_before, processes_after)
    visible_process_ids = {
        process_id
        for process_id in (
            _window_process_id(handle) for handle in windows.visible_window_snapshot()
        )
        if process_id is not None
    }
    if installed is not None:
        # explorer.exe can act as a short-lived AppsFolder broker whose reported
        # parent is the preexisting shell rather than the Popen PID. A newly created,
        # windowless Explorer instance is therefore part of this isolated launch.
        owned_roots.update(
            pid
            for pid, info in processes_after.items()
            if pid not in processes_before
            and info.name.casefold() == "explorer.exe"
            and pid not in visible_process_ids
        )
    owned_processes = _owned_process_tree(
        processes_before,
        processes_after,
        owned_roots,
    )
    created_processes.update(
        {
            pid: info
            for pid, info in owned_processes.items()
            if info.name.casefold() not in _PROCESS_INFRASTRUCTURE
        }
    )
    residual_processes = _wait_for_process_exit(created_processes)
    terminated_processes: list[dict[str, object]] = []
    if residual_processes and not residual:
        owned_residual = {
            pid: info for pid, info in residual_processes.items() if pid in owned_processes
        }
        terminated_processes = _terminate_owned_processes(owned_residual)
        residual_processes = _wait_for_process_exit(residual_processes, timeout=3.0)
    if residual:
        status = "residual_window_stop"
    elif residual_processes:
        status = "residual_process_stop"
    elif candidates:
        status = "opened_and_closed"
    elif launch.details.get("already_open"):
        status = "preexisting_untouched"
    elif launch_success:
        status = "launched_without_new_window"
    else:
        status = "launch_failed"
    return LifecycleResult(
        index=index,
        name=installed.name if installed is not None else apps.APPS[name].display_name,
        source=source,
        launch_success=launch_success,
        launch_verified=launch_verified,
        launch_message=launch.message,
        new_windows=[{"handle": handle, "title": title} for handle, title in candidates.items()],
        closed_windows=closed,
        residual_windows=residual,
        new_processes=[
            {"pid": pid, "name": info.name, "parent_pid": info.parent_pid}
            for pid, info in created_processes.items()
        ],
        terminated_processes=terminated_processes,
        residual_processes=[
            {"pid": pid, "name": info.name, "parent_pid": info.parent_pid}
            for pid, info in residual_processes.items()
        ],
        status=status,
        elapsed_seconds=round(time.monotonic() - started, 3),
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open and safely close permitted apps one by one.")
    parser.add_argument("--mode", choices=("static", "installed"), default="static")
    parser.add_argument("--start", type=int, default=1, help="One-based inventory position.")
    parser.add_argument("--limit", type=int, default=0, help="0 means all remaining entries.")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--include-steam", action="store_true")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = _arguments()
    windows = WindowController()
    apps = AppController(windows)
    if args.mode == "static":
        entries: list[tuple[int, str, InstalledApp | None]] = [
            (index, name, None) for index, name in enumerate(apps.APPS, 1)
        ]
    else:
        inventory = apps.installed_apps()
        entries = [
            (index, app.name, app)
            for index, app in enumerate(inventory, 1)
            if args.include_steam or not app.target_path.casefold().startswith("steam:")
        ]
    entries = [entry for entry in entries if entry[0] >= max(1, args.start)]
    if args.limit > 0:
        entries = entries[: args.limit]
    report_dir = Path(".data") / "qa"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"app-lifecycle-{args.mode}-{stamp}.jsonl"
    print(
        json.dumps(
            {
                "event": "start",
                "mode": args.mode,
                "entries": len(entries),
                "report": str(report_path),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    completed = 0
    with report_path.open("w", encoding="utf-8") as report:
        for index, name, installed in entries:
            result = _test_one(
                windows=windows,
                apps=apps,
                index=index,
                name=name,
                source=args.mode,
                timeout=max(1.0, min(args.timeout, 30.0)),
                installed=installed,
            )
            payload = asdict(result)
            line = json.dumps(payload, ensure_ascii=False)
            report.write(line + "\n")
            report.flush()
            print(line, flush=True)
            completed += 1
            if result.residual_windows or result.residual_processes:
                print(
                    json.dumps(
                        {
                            "event": "stopped",
                            "reason": (
                                "residual_window"
                                if result.residual_windows
                                else "residual_process"
                            ),
                            "index": index,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                return 2
    print(json.dumps({"event": "complete", "completed": completed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
