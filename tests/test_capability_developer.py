from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from jarvis.capabilities.developer import DeveloperWorkspace, WorkspaceSecurityError


class FakeDeveloperWorkspace(DeveloperWorkspace):
    def __init__(self, root: Path) -> None:
        super().__init__({"project": root})
        self.calls: list[tuple[tuple[str, ...], Path, float]] = []
        self.timeout = False

    def _run_process(
        self,
        command: tuple[str, ...],
        cwd: Path,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, cwd, timeout))
        if self.timeout:
            raise subprocess.TimeoutExpired(command, timeout, output="partial")
        return subprocess.CompletedProcess(command, 0, "4 passed", "")


def make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "src" / "app.py").write_text("value = 1\nprint(value)\n", encoding="utf-8")
    (root / "README.md").write_text("Proyecto de prueba\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=no-leer\n", encoding="utf-8")
    (root / ".git" / "config").write_text("private\n", encoding="utf-8")
    (root / "private.pem").write_text("private\n", encoding="utf-8")
    return root


def test_list_search_read_and_diff_are_read_only_and_hide_secrets(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    workspace = DeveloperWorkspace({"project": root})

    entries = workspace.list_files("project", recursive=True)
    paths = {entry.path for entry in entries}
    document = workspace.read("project", "src/app.py")
    matches = workspace.search("project", "PRINT")
    diff = workspace.diff("project", "src/app.py", "value = 2\nprint(value)\n")

    assert "src/app.py" in paths
    assert ".env" not in paths
    assert ".git" not in paths
    assert "private.pem" not in paths
    assert document.content.startswith("value = 1")
    assert [(match.path, match.line) for match in matches] == [("src/app.py", 2)]
    assert "-value = 1" in diff and "+value = 2" in diff
    assert (root / "src" / "app.py").read_text(encoding="utf-8").startswith("value = 1")


@pytest.mark.parametrize(
    "path",
    ["../outside.txt", ".env", ".git/config", "private.pem"],
)
def test_workspace_rejects_escape_and_private_paths(tmp_path: Path, path: str) -> None:
    workspace = DeveloperWorkspace({"project": make_workspace(tmp_path)})

    with pytest.raises(WorkspaceSecurityError):
        workspace.read("project", path)


def test_workspace_rejects_symlink_without_following_it(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = root / "src" / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("La cuenta de Windows no permite crear symlinks")
    workspace = DeveloperWorkspace({"project": root})

    with pytest.raises(WorkspaceSecurityError):
        workspace.read("project", "src/link.txt")


def test_run_tests_accepts_only_exact_vectors_and_uses_injected_method(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    workspace = FakeDeveloperWorkspace(root)

    result = workspace.run_tests(
        "project",
        ("python", "-m", "pytest", "-q"),
        relative_cwd="src",
        timeout=30,
    )

    assert result.success is True
    assert result.stdout == "4 passed"
    assert workspace.calls == [
        (
            (str(Path(sys.executable).resolve()), "-m", "pytest", "-q"),
            (root / "src").resolve(),
            30,
        )
    ]

    with pytest.raises(WorkspaceSecurityError):
        workspace.run_tests("project", ("python", "-c", "print('unsafe')"))
    assert len(workspace.calls) == 1


def test_run_tests_never_resolves_python_from_the_workspace(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    fake_python = root / "src" / "python.exe"
    fake_python.write_bytes(b"not an executable")
    workspace = FakeDeveloperWorkspace(root)

    workspace.run_tests(
        "project",
        ("python", "-m", "pytest", "-q"),
        relative_cwd="src",
    )

    assert workspace.calls[0][0][0] == str(Path(sys.executable).resolve())
    assert workspace.calls[0][0][0] != str(fake_python.resolve())


def test_run_tests_reports_timeout_without_running_a_real_process(tmp_path: Path) -> None:
    workspace = FakeDeveloperWorkspace(make_workspace(tmp_path))
    workspace.timeout = True

    result = workspace.run_tests("project", "npm test -- --runInBand", timeout=5)

    assert result.timed_out is True
    assert result.returncode is None
    assert result.stdout == "partial"
