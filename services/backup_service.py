"""Automatic Database Backup service for Valhalla Bot."""
from __future__ import annotations

import gzip
import io
import logging
import os
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple, Union

import requests
from dotenv import load_dotenv

from services.database import with_mysql_cursor
from services.settings import get_setting, set_setting

log = logging.getLogger("valhalla.backup")

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_DIR = "/app/backups"
MAX_BACKUP_FILES = 30

_scheduler_running = False
_scheduler_thread: Optional[threading.Thread] = None
_scheduler_lock = threading.Lock()


def get_backup_dir() -> Path:
    """Return the configured or default backup directory, ensuring it exists."""
    configured = (os.getenv("BACKUP_DIR") or DEFAULT_BACKUP_DIR).strip()
    target_path = Path(configured)
    try:
        target_path.mkdir(parents=True, exist_ok=True)
        return target_path
    except (PermissionError, OSError) as exc:
        log.warning("Could not use backup directory '%s': %s. Falling back to project backups dir.", target_path, exc)
        fallback = BASE_DIR / "backups"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _get_main_admin_id() -> Optional[int]:
    raw_ids = (os.getenv("ADMIN_IDS") or "").strip()
    if not raw_ids:
        return None
    for raw in raw_ids.split(","):
        raw = raw.strip()
        if raw.isdigit():
            return int(raw)
    return None


def get_backup_settings() -> dict:
    """Return current automatic backup settings."""
    main_admin_id = _get_main_admin_id()
    owner_id = main_admin_id or 0

    raw_enabled = get_setting(owner_id, "auto_backup_enabled")
    enabled = raw_enabled == "1" if raw_enabled is not None else False

    raw_interval = get_setting(owner_id, "backup_interval_hours")
    try:
        interval_hours = max(1, int(raw_interval)) if raw_interval else 24
    except ValueError:
        interval_hours = 24

    last_backup = get_setting(owner_id, "last_backup_timestamp") or None

    return {
        "enabled": enabled,
        "interval_hours": interval_hours,
        "last_backup": last_backup,
    }


def set_backup_settings(enabled: bool, interval_hours: int) -> dict:
    """Update and persist automatic backup settings."""
    main_admin_id = _get_main_admin_id()
    owner_id = main_admin_id or 0

    interval_hours = max(1, int(interval_hours))
    enabled_str = "1" if enabled else "0"

    set_setting(owner_id, "auto_backup_enabled", enabled_str)
    set_setting(owner_id, "backup_interval_hours", str(interval_hours))

    return get_backup_settings()


def _update_last_backup_timestamp() -> None:
    main_admin_id = _get_main_admin_id()
    owner_id = main_admin_id or 0
    now_str = datetime.now(timezone.utc).isoformat()
    set_setting(owner_id, "last_backup_timestamp", now_str)


def format_bytes(size_bytes: int) -> str:
    """Format bytes into human-readable string."""
    units = ["B", "KB", "MB", "GB"]
    size = float(size_bytes)
    idx = 0
    while size >= 1024.0 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    return f"{size:.2f} {units[idx]}"


def _format_sql_value(v: Any) -> str:
    """Format a Python value into a safe SQL literal for dump output."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (bytes, bytearray)):
        return f"0x{bytes(v).hex()}"
    escaped = (
        str(v)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\0", "\\0")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f"'{escaped}'"


def _dump_mysql_cli(target: Optional[Union[str, Path, io.TextIOBase]] = None) -> Optional[str]:
    """Try dumping MySQL database using mysqldump CLI binary."""
    load_dotenv()
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    db_name = os.getenv("MYSQL_DATABASE", "botdb")

    cmd = [
        "mysqldump",
        "-h", host,
        "-P", str(port),
        "-u", user,
        "--single-transaction",
        "--quick",
        "--skip-lock-tables",
        db_name,
    ]
    env = os.environ.copy()
    if password:
        env["MYSQL_PWD"] = password

    try:
        if target is None:
            res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
            return res.stdout
        elif isinstance(target, (str, Path)):
            target_path = Path(target)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                subprocess.run(cmd, env=env, stdout=f, check=True)
            return None
        elif hasattr(target, "write"):
            proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, text=True)
            if proc.stdout:
                for chunk in iter(lambda: proc.stdout.read(65536), ""):
                    target.write(chunk)
            proc.wait()
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, cmd)
            return None
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        log.warning("mysqldump CLI execution failed or unavailable: %s. Using Python fallback dump.", exc)
        return None


def _write_dump_stream(cur: Any, out: io.TextIOBase, batch_size: int = 100) -> None:
    """Stream dump statements directly into an open text stream in batches."""
    db_name = os.getenv("MYSQL_DATABASE", "botdb")
    hostname = socket.gethostname()

    out.write(
        f"-- Valhalla MySQL Backup Dump\n"
        f"-- Database: {db_name}\n"
        f"-- Hostname: {hostname}\n"
        f"-- Generated at: {datetime.now(timezone.utc).isoformat()}\n"
        "SET FOREIGN_KEY_CHECKS=0;\n"
        "SET SQL_MODE = 'NO_AUTO_VALUE_ON_ZERO';\n\n"
    )

    # Use transaction-consistent snapshot without acquiring global table locks
    try:
        cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
    except Exception as tx_exc:
        log.warning("Could not start transaction with consistent snapshot: %s. Falling back to START TRANSACTION.", tx_exc)
        try:
            cur.execute("START TRANSACTION")
        except Exception:
            pass

    try:
        cur.execute("SHOW TABLES")
        tables = [row[0] for row in cur.fetchall()]

        for table in tables:
            out.write(f"-- Table structure for table `{table}`\n")
            out.write(f"DROP TABLE IF EXISTS `{table}`;\n")
            cur.execute(f"SHOW CREATE TABLE `{table}`")
            create_row = cur.fetchone()
            if create_row and len(create_row) > 1:
                out.write(f"{create_row[1]};\n")
            out.write("\n")

            cur.execute(f"SHOW COLUMNS FROM `{table}`")
            cols_rows = cur.fetchall()
            cols = [col[0] for col in cols_rows] if cols_rows else []
            if not cols and cur.description:
                cols = [desc[0] for desc in cur.description]
            col_names = ", ".join([f"`{c}`" for c in cols])
            col_clause = f" ({col_names})" if col_names else ""

            cur.execute(f"SELECT * FROM `{table}`")
            first_batch = cur.fetchmany(batch_size)
            if first_batch:
                out.write(f"-- Dumping data for table `{table}`\n")
                batch = first_batch
                while batch:
                    val_strs = [
                        f"({', '.join(_format_sql_value(v) for v in row)})"
                        for row in batch
                    ]
                    out.write(f"INSERT INTO `{table}`{col_clause} VALUES\n" + ",\n".join(val_strs) + ";\n")
                    batch = cur.fetchmany(batch_size)
                out.write("\n")
    finally:
        try:
            cur.execute("COMMIT")
        except Exception:
            pass

    out.write("SET FOREIGN_KEY_CHECKS=1;\n")


def _dump_mysql_python(
    target: Optional[Union[str, Path, io.TextIOBase]] = None,
    use_gzip: bool = False,
    batch_size: int = 100,
) -> Optional[Union[str, bytes]]:
    """Fallback Python-native dump generator for MySQL tables and rows.

    Streams database rows in batches without loading entire tables into memory.
    Uses transaction-consistent snapshot without global table write locks.
    Can write directly to target file/stream, optionally compressed with gzip.
    """
    load_dotenv()
    with with_mysql_cursor(dict_=False) as cur:
        if isinstance(target, (str, Path)):
            target_path = Path(target)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if use_gzip or target_path.suffix == ".gz" or str(target).endswith(".gz"):
                with gzip.open(target_path, "wt", encoding="utf-8") as gz_f:
                    _write_dump_stream(cur, gz_f, batch_size=batch_size)
            else:
                with open(target_path, "w", encoding="utf-8") as f:
                    _write_dump_stream(cur, f, batch_size=batch_size)
            return None
        elif target is not None and hasattr(target, "write"):
            _write_dump_stream(cur, target, batch_size=batch_size)
            return None
        elif use_gzip:
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb") as gz_raw:
                with io.TextIOWrapper(gz_raw, encoding="utf-8") as gz_text:
                    _write_dump_stream(cur, gz_text, batch_size=batch_size)
            return buf.getvalue()
        else:
            buf = io.StringIO()
            _write_dump_stream(cur, buf, batch_size=batch_size)
            return buf.getvalue()


def generate_sql_dump(
    target: Optional[Union[str, Path, io.TextIOBase]] = None,
    use_gzip: bool = False,
    batch_size: int = 100,
) -> Optional[Union[str, bytes]]:
    """Generate MySQL SQL dump using CLI or fallback to Python generator."""
    if target is None and not use_gzip:
        cli_dump = _dump_mysql_cli()
        if cli_dump is not None:
            return cli_dump
        return _dump_mysql_python(batch_size=batch_size)

    if not use_gzip and isinstance(target, (str, Path)) and not str(target).endswith(".gz"):
        cli_res = _dump_mysql_cli(target=target)
        if cli_res is None and Path(target).exists() and Path(target).stat().st_size > 0:
            return None
        if Path(target).exists():
            Path(target).unlink(missing_ok=True)

    return _dump_mysql_python(target=target, use_gzip=use_gzip, batch_size=batch_size)


def cleanup_old_backups(backup_dir: Path, keep: int = MAX_BACKUP_FILES) -> int:
    """Delete old backup archives keeping only the latest `keep` files."""
    deleted_count = 0
    try:
        files = sorted(
            [f for f in backup_dir.iterdir() if f.is_file() and f.name.startswith("backup_")],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if len(files) > keep:
            for old_file in files[keep:]:
                try:
                    old_file.unlink()
                    deleted_count += 1
                    log.info("Deleted old backup archive: %s", old_file.name)
                except Exception as exc:
                    log.warning("Failed to delete old backup %s: %s", old_file.name, exc)
    except Exception as exc:
        log.warning("Error during backup directory cleanup: %s", exc)
    return deleted_count


def create_backup_archive() -> Tuple[Path, str, int]:
    """Create a backup archive (.zip or .tar.gz) containing database.sql and .env.

    Returns:
        (archive_path, filename, size_bytes)
    """
    backup_dir = get_backup_dir()
    timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    zip_filename = f"backup_{timestamp_str}.zip"
    zip_filepath = backup_dir / zip_filename

    env_filepath = BASE_DIR / ".env"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        sql_filepath = temp_dir_path / "database.sql"

        # Stream directly to sql_filepath without keeping the entire dump in memory
        dump_res = generate_sql_dump(target=sql_filepath)
        if not sql_filepath.exists() and isinstance(dump_res, (str, bytes)):
            if isinstance(dump_res, bytes):
                sql_filepath.write_bytes(dump_res)
            else:
                sql_filepath.write_text(dump_res, encoding="utf-8")

        temp_env_filepath = temp_dir_path / ".env"
        if env_filepath.exists():
            shutil.copy2(env_filepath, temp_env_filepath)
        else:
            temp_env_filepath.write_text("# Environment configuration dump\n", encoding="utf-8")

        try:
            with zipfile.ZipFile(zip_filepath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(sql_filepath, arcname="database.sql")
                zf.write(temp_env_filepath, arcname=".env")
        except Exception as zip_exc:
            log.warning("zipfile creation failed (%s); falling back to tar.gz archive", zip_exc)
            tar_filename = f"backup_{timestamp_str}.tar.gz"
            tar_filepath = backup_dir / tar_filename
            with tarfile.open(tar_filepath, "w:gz") as tar:
                tar.add(sql_filepath, arcname="database.sql")
                tar.add(temp_env_filepath, arcname=".env")
            zip_filepath = tar_filepath
            zip_filename = tar_filename

    size_bytes = zip_filepath.stat().st_size
    cleanup_old_backups(backup_dir)
    return zip_filepath, zip_filename, size_bytes


def send_backup_to_telegram(file_path: Path, trigger_type: str = "auto") -> None:
    """Send backup document to the primary super-admin on Telegram."""
    bot_token = (os.getenv("BOT_TOKEN") or "").strip()
    if not bot_token:
        raise ValueError("BOT_TOKEN environment variable is not configured")

    main_admin_id = _get_main_admin_id()
    if not main_admin_id:
        raise ValueError("No main admin (ADMIN_IDS) configured to receive Telegram backup")

    size_bytes = file_path.stat().st_size
    db_name = os.getenv("MYSQL_DATABASE", "botdb")
    hostname = socket.gethostname()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    trigger_label = "⚡ Manual" if trigger_type.lower() == "manual" else "⏰ Automatic"
    caption = (
        f"📦 **Database Backup** ({trigger_label})\n\n"
        f"📅 **Date/Time**: `{date_str}`\n"
        f"💾 **File Size**: `{format_bytes(size_bytes)}`\n"
        f"🗄️ **Database**: `{db_name}`\n"
        f"🖥️ **Server Hostname**: `{hostname}`"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    with open(file_path, "rb") as f:
        files = {"document": (file_path.name, f, "application/zip")}
        data = {"chat_id": main_admin_id, "caption": caption, "parse_mode": "Markdown"}
        resp = requests.post(url, data=data, files=files, timeout=120)

    if resp.status_code != 200:
        raise RuntimeError(f"Telegram API sendDocument returned HTTP {resp.status_code}: {resp.text}")


def notify_admin_error(error_message: str, trigger_type: str = "auto") -> None:
    """Send error notification message to the main admin on Telegram."""
    bot_token = (os.getenv("BOT_TOKEN") or "").strip()
    main_admin_id = _get_main_admin_id()

    if not bot_token or not main_admin_id:
        log.warning("Cannot send Telegram error notification: BOT_TOKEN or main admin ID missing.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    trigger_label = "Manual" if trigger_type.lower() == "manual" else "Automatic"
    text = f"❌ **{trigger_label} Backup Failed**\n\n⚠️ Error details:\n`{error_message}`"

    try:
        requests.post(url, json={"chat_id": main_admin_id, "text": text, "parse_mode": "Markdown"}, timeout=15)
    except Exception as exc:
        log.warning("Failed to send Telegram error notification: %s", exc)


def perform_backup(trigger_type: str = "auto") -> Tuple[Path, str, int]:
    """Perform a complete backup cycle: generate dump & archive, send via Telegram, update timestamp."""
    log.info("Starting %s database backup cycle...", trigger_type)
    try:
        file_path, filename, size_bytes = create_backup_archive()
        send_backup_to_telegram(file_path, trigger_type=trigger_type)
        _update_last_backup_timestamp()
        log.info("Successfully completed %s backup: %s (%s)", trigger_type, filename, format_bytes(size_bytes))
        return file_path, filename, size_bytes
    except Exception as exc:
        log.exception("Backup execution failed (%s): %s", trigger_type, exc)
        notify_admin_error(str(exc), trigger_type=trigger_type)
        raise


def check_and_run_scheduled_backup() -> bool:
    """Check if an automatic backup is due and execute if needed."""
    settings = get_backup_settings()
    if not settings["enabled"]:
        return False

    interval_hours = settings["interval_hours"]
    last_backup_str = settings["last_backup"]

    if last_backup_str:
        try:
            last_backup_dt = datetime.fromisoformat(last_backup_str)
            now = datetime.now(timezone.utc)
            elapsed_seconds = (now - last_backup_dt).total_seconds()
            if elapsed_seconds < (interval_hours * 3600 - 30):
                return False
        except Exception as exc:
            log.warning("Failed to parse last backup timestamp '%s': %s", last_backup_str, exc)

    try:
        perform_backup(trigger_type="auto")
        return True
    except Exception as exc:
        log.warning("Scheduled backup failed: %s", exc)
        return False


def _scheduler_loop() -> None:
    log.info("Backup scheduler daemon loop active.")
    while _scheduler_running:
        try:
            check_and_run_scheduled_backup()
        except Exception as exc:
            log.exception("Unexpected error in backup scheduler loop: %s", exc)

        for _ in range(60):
            if not _scheduler_running:
                break
            time.sleep(1)


def start_backup_scheduler() -> None:
    """Start background backup scheduler thread if not already running."""
    global _scheduler_running, _scheduler_thread
    with _scheduler_lock:
        if _scheduler_running:
            return
        _scheduler_running = True
        _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="BackupSchedulerThread")
        _scheduler_thread.start()
        log.info("Backup scheduler background thread launched successfully.")


def stop_backup_scheduler() -> None:
    """Stop the background backup scheduler thread."""
    global _scheduler_running
    with _scheduler_lock:
        _scheduler_running = False


__all__ = [
    "_dump_mysql_python",
    "cleanup_old_backups",
    "create_backup_archive",
    "format_bytes",
    "generate_sql_dump",
    "get_backup_dir",
    "get_backup_settings",
    "notify_admin_error",
    "perform_backup",
    "send_backup_to_telegram",
    "set_backup_settings",
    "start_backup_scheduler",
    "stop_backup_scheduler",
]
