#!/usr/bin/env python3
"""Копирует живой журнал на GitHub.

Скрипт читает файлы сайта и делает коммит в отдельной копии репозитория.
Сессии входа не копируются: по ним можно войти без пароля.
Запуск на сервере: /usr/local/bin/urokklass-github-backup
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_FILES = (
    "journal.py",
    "server.py",
    "pdf_import.py",
    ".gitignore",
    ".gitattributes",
    "запустить.bat",
)
ROOT_DIRS = ("static", "tools", "seed-banks", "seed-pdfs")
DATA_FILES = ("students.json", "auth.json", "ege-10-raw.txt", "source-10.2.pdf")
DATA_DIRS = ("banks", "uploads")
SKIP_NAMES = {"sessions.json", "known_hosts"}
SKIP_SUFFIXES = (".tmp", ".pyc")
SKIP_RELATIVE = {
    "tools/github-backup.py",
    "tools/test_github_backup.py",
    "tools/urokklass-github-backup",
    "tools/urokklass-github-backup.service",
    "tools/urokklass-github-backup.path",
    "tools/urokklass-github-backup.timer",
}
EXTRA_FILES = (
    ("/etc/nginx/sites-available/urokklass", "deploy/live-server/nginx-urokklass.conf"),
    ("/etc/systemd/system/journal-urokklass.service", "deploy/live-server/journal-urokklass.service"),
)


def _skipped(path: Path) -> bool:
    if path.name in SKIP_NAMES or path.suffix in SKIP_SUFFIXES:
        return True
    return any(part in {"__pycache__", ".venv"} for part in path.parts)


def iter_backup_files(journal_root: Path) -> list[tuple[Path, str]]:
    """Пары (файл на сервере, путь внутри репозитория)."""
    found: list[tuple[Path, str]] = []
    for name in ROOT_FILES:
        source = journal_root / name
        if source.is_file():
            found.append((source, name))
    for name in DATA_FILES:
        source = journal_root / "data" / name
        if source.is_file() and not _skipped(source):
            found.append((source, f"data/{name}"))
    for directory in (*ROOT_DIRS, *(f"data/{name}" for name in DATA_DIRS)):
        source_dir = journal_root / directory
        if not source_dir.is_dir():
            continue
        for source in source_dir.rglob("*"):
            if not source.is_file() or _skipped(source):
                continue
            relative = source.relative_to(journal_root).as_posix()
            if relative in SKIP_RELATIVE:
                continue
            found.append((source, relative))
    return found


def _run(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=check,
    )


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _sync_tree(journal_root: Path, repo: Path) -> None:
    copied: set[str] = set()
    for source, relative in iter_backup_files(journal_root):
        _copy(source, repo / relative)
        copied.add(relative)
    for source_name, relative in EXTRA_FILES:
        source = Path(source_name)
        if source.is_file():
            _copy(source, repo / relative)
            copied.add(relative)
    for directory in DATA_DIRS:
        mirror = repo / "data" / directory
        if not mirror.is_dir():
            continue
        for existing in mirror.rglob("*"):
            if not existing.is_file():
                continue
            relative = existing.relative_to(repo).as_posix()
            if relative not in copied:
                existing.unlink()


def _ensure_identity(repo: Path) -> None:
    email = _run(repo, ["config", "--get", "user.email"], check=False).stdout.strip()
    if not email:
        _run(repo, ["config", "user.email", "backup@urokklass.ru"])
        _run(repo, ["config", "user.name", "urokklass-backup"])


def _commit_if_needed(repo: Path) -> bool:
    paths = [
        path
        for path in ("data", "static", "tools", "seed-banks", "seed-pdfs", "deploy")
        if (repo / path).exists()
    ]
    if paths:
        _run(repo, ["add", "-A", "--", *paths])
    for name in ROOT_FILES:
        if (repo / name).exists():
            _run(repo, ["add", "--", name])
    staged = _run(repo, ["diff", "--cached", "--quiet"], check=False)
    if staged.returncode == 0:
        return False
    _run(
        repo,
        [
            "commit",
            "-m",
            "Сохранить живой журнал: ученики, файлы и правки сайта.",
        ],
    )
    return True


def _push(repo: Path, branch: str) -> None:
    _run(repo, ["fetch", "origin", branch], check=False)
    rebase = _run(repo, ["pull", "--rebase", "origin", branch], check=False)
    if rebase.returncode != 0:
        raise RuntimeError(rebase.stderr.strip() or "не удалось забрать свежие коммиты")
    push = _run(repo, ["push", "origin", f"HEAD:{branch}"])
    if push.returncode != 0:
        raise RuntimeError(push.stderr.strip() or "GitHub не принял сохранение")


def backup_once(journal_root: Path, repo: Path, branch: str, push: bool) -> bool:
    if not (repo / ".git").exists():
        raise RuntimeError(f"нет копии репозитория: {repo}")
    _ensure_identity(repo)
    _sync_tree(journal_root, repo)
    committed = _commit_if_needed(repo)
    if push and (_run(repo, ["status", "--porcelain"], check=False).stdout.strip() or committed or _unpushed(repo, branch)):
        _push(repo, branch)
    return committed


def _unpushed(repo: Path, branch: str) -> bool:
    check = _run(repo, ["rev-parse", "--abbrev-ref", "@{upstream}"], check=False)
    if check.returncode != 0:
        return True
    ahead = _run(repo, ["rev-list", "--count", f"origin/{branch}..HEAD"], check=False)
    return ahead.returncode == 0 and ahead.stdout.strip() not in {"", "0"}


def main() -> int:
    journal_root = Path(os.environ.get("JOURNAL_ROOT", "/var/www/urokklass"))
    repo = Path(os.environ.get("BACKUP_REPO", "/var/backups/urokklass-mirror"))
    branch = os.environ.get("BACKUP_BRANCH", "cursor/live-journal-backup-ea20")
    push = os.environ.get("BACKUP_PUSH", "1") != "0"
    lock_path = Path(os.environ.get("BACKUP_LOCK", "/var/lock/urokklass-github-backup.lock"))
    dirty_flag = Path(os.environ.get("BACKUP_DIRTY", "/var/lock/urokklass-github-backup.dirty"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:
        fcntl = None  # type: ignore[assignment]
    handle = lock_path.open("a", encoding="utf-8")
    try:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                dirty_flag.write_text("1", encoding="utf-8")
                return 0
        while True:
            dirty_flag.unlink(missing_ok=True)
            backup_once(journal_root, repo, branch, push)
            if not dirty_flag.exists():
                break
    finally:
        handle.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # журнал уже записан на диск, GitHub догонит следующим запуском
        print(f"Резервная копия на GitHub не отправилась: {error}", file=sys.stderr)
        sys.exit(1)
