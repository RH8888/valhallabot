"""Automatic MySQL backup creation and Telegram delivery helpers."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from telegram import Bot

from api.subscription_aggregator import ordered_admin_ids
from services.settings import get_setting_exact, set_setting

log = logging.getLogger(__name__)

BACKUP_ENABLED_KEY = "automatic_backups_enabled"
BACKUP_INTERVAL_KEY = "automatic_backups_interval_hours"
BACKUP_LAST_RUN_KEY = "automatic_backups_last_run_at"
DEFAULT_BACKUP_INTERVAL_HOURS = 24
DEFAULT_BACKUP_DIR = "/app/backups"
MAX_BACKUP_FILES = 30


@dataclass(frozen=True)
class BackupSettings:
    enabled: bool
    interval_hours: int
    backup_dir: Path
    last_run_at: datetime | None


@dataclass(frozen=True)
class BackupResult:
    archive_path: Path
    created_at: datetime
    size_bytes: int
    database: str
    hostname: str


def main_admin_id() -> int | None:
    admins = ordered_admin_ids()
    return int(admins[0]) if admins else None


def is_main_admin(tg_id: int | None) -> bool:
    root = main_admin_id()
    return root is not None and tg_id is not None and int(tg_id) == root


def _setting_owner() -> int | None:
    return main_admin_id()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        log.warning("Invalid %s=%r; using %s", key, raw, default)
        return default


def backup_directory() -> Path:
    return Path(os.getenv("BACKUP_DIR", DEFAULT_BACKUP_DIR)).expanduser()


def get_backup_settings() -> BackupSettings:
    owner = _setting_owner()
    enabled_raw = get_setting_exact(owner, BACKUP_ENABLED_KEY) if owner is not None else None
    interval_raw = get_setting_exact(owner, BACKUP_INTERVAL_KEY) if owner is not None else None
    last_raw = get_setting_exact(owner, BACKUP_LAST_RUN_KEY) if owner is not None else None
    try:
        interval = int(float(interval_raw or DEFAULT_BACKUP_INTERVAL_HOURS))
    except ValueError:
        interval = DEFAULT_BACKUP_INTERVAL_HOURS
    return BackupSettings(
        enabled=(enabled_raw or "0") != "0",
        interval_hours=max(1, interval),
        backup_dir=backup_directory(),
        last_run_at=_parse_dt(last_raw),
    )


def set_backup_enabled(enabled: bool) -> None:
    owner = _setting_owner()
    if owner is None:
        raise RuntimeError("No main admin is configured")
    set_setting(owner, BACKUP_ENABLED_KEY, "1" if enabled else "0")


def set_backup_interval_hours(hours: int) -> None:
    owner = _setting_owner()
    if owner is None:
        raise RuntimeError("No main admin is configured")
    set_setting(owner, BACKUP_INTERVAL_KEY, str(max(1, int(hours))))


def mark_backup_run(when: datetime) -> None:
    owner = _setting_owner()
    if owner is not None:
        set_setting(owner, BACKUP_LAST_RUN_KEY, when.astimezone(timezone.utc).isoformat())


def _mysql_env() -> dict[str, str]:
    load_dotenv()
    env = os.environ.copy()
    password = os.getenv("MYSQL_PASSWORD", "")
    if password:
        env["MYSQL_PWD"] = password
    return env


def _dump_database(output_path: Path) -> str:
    load_dotenv()
    database = os.getenv("MYSQL_DATABASE", "botdb")
    mysqldump_bin = os.getenv("MYSQLDUMP_BIN", "mysqldump")
    if shutil.which(mysqldump_bin) is None:
        raise RuntimeError(
            f"{mysqldump_bin!r} was not found. Install default-mysql-client/mysql-client "
            "or set MYSQLDUMP_BIN to the mysqldump executable path."
        )
    cmd = [
        mysqldump_bin,
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "-h", os.getenv("MYSQL_HOST", "127.0.0.1"),
        "-P", str(_env_int("MYSQL_PORT", 3306)),
        "-u", os.getenv("MYSQL_USER", "root"),
        database,
    ]
    with output_path.open("wb") as fh:
        subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, env=_mysql_env(), check=True)
    return database


def _copy_env_file(output_path: Path) -> None:
    env_path = Path(os.getenv("ENV_FILE_PATH", ".env"))
    if not env_path.is_absolute():
        env_path = Path.cwd() / env_path
    if env_path.exists():
        shutil.copyfile(env_path, output_path)
    else:
        output_path.write_text("", encoding="utf-8")
        log.warning(".env file not found at %s; adding empty .env to backup", env_path)


def _archive_backup(source_dir: Path, archive_path: Path) -> Path:
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(source_dir / "database.sql", "database.sql")
            zf.write(source_dir / ".env", ".env")
        return archive_path
    except Exception:
        log.exception("zip archive creation failed; falling back to tar.gz")
    archive_path = archive_path.with_suffix(".tar.gz")
    with tarfile.open(archive_path, "w:gz") as tf:
        tf.add(source_dir / "database.sql", arcname="database.sql")
        tf.add(source_dir / ".env", arcname=".env")
    return archive_path


def _cleanup_old_backups(backup_dir: Path) -> None:
    files = sorted(
        [p for p in backup_dir.glob("backup_*") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[MAX_BACKUP_FILES:]:
        try:
            old.unlink()
        except OSError:
            log.warning("Failed to delete old backup %s", old, exc_info=True)


def create_backup() -> BackupResult:
    created_at = datetime.now(timezone.utc)
    backup_dir = backup_directory()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = created_at.strftime("%Y-%m-%d_%H-%M")
    archive_path = backup_dir / f"backup_{stamp}.zip"
    with tempfile.TemporaryDirectory(prefix="backup_", dir=str(backup_dir)) as tmp:
        tmpdir = Path(tmp)
        database = _dump_database(tmpdir / "database.sql")
        _copy_env_file(tmpdir / ".env")
        archive_path = _archive_backup(tmpdir, archive_path)
    _cleanup_old_backups(backup_dir)
    result = BackupResult(archive_path, created_at, archive_path.stat().st_size, database, socket.gethostname())
    log.info("Created backup %s (%s bytes)", result.archive_path, result.size_bytes)
    return result


def format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size} B"


def backup_caption(result: BackupResult) -> str:
    return (
        f"🗄️ Database backup\n"
        f"Date/time: {result.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"File size: {format_size(result.size_bytes)}\n"
        f"Database: {result.database}\n"
        f"Hostname: {result.hostname}"
    )


async def create_and_send_backup(bot: Bot, chat_id: int) -> BackupResult:
    log.info("Starting backup attempt for chat_id=%s", chat_id)
    try:
        result = await asyncio.to_thread(create_backup)
        with result.archive_path.open("rb") as fh:
            await bot.send_document(chat_id=chat_id, document=fh, filename=result.archive_path.name, caption=backup_caption(result))
        mark_backup_run(result.created_at)
        log.info("Backup %s sent to chat_id=%s", result.archive_path, chat_id)
        return result
    except Exception as exc:
        log.exception("Backup attempt failed")
        try:
            await bot.send_message(chat_id=chat_id, text=f"❌ Backup failed: {exc}")
        except Exception:
            log.exception("Failed to notify main admin about backup failure")
        raise


async def backup_scheduler_loop(bot: Bot, stop_event: asyncio.Event | None = None) -> None:
    log.info("Automatic backup scheduler started")
    while stop_event is None or not stop_event.is_set():
        try:
            admin_id = main_admin_id()
            settings = get_backup_settings()
            now = datetime.now(timezone.utc)
            due = settings.last_run_at is None or (now - settings.last_run_at).total_seconds() >= settings.interval_hours * 3600
            if admin_id is not None and settings.enabled and due:
                await create_and_send_backup(bot, admin_id)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60) if stop_event else await asyncio.sleep(60)
        except asyncio.TimeoutError:
            pass
