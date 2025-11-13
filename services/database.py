"""Database utilities shared across application layers."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from contextlib import AbstractContextManager
from typing import Any, Dict
from urllib.parse import quote_plus

from dotenv import load_dotenv
from mysql.connector import Error as MySQLError
from mysql.connector import errorcode, errors as mysql_errors, pooling

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MongoSettings:
    """Runtime configuration for the MongoDB backend."""

    uri: str
    host: str
    port: int
    username: str | None
    password: str | None
    database: str | None


@dataclass(frozen=True)
class DatabaseSettings:
    """Combined database configuration derived from the environment."""

    backend: str
    mysql: Dict[str, Any] | None = None
    mongo: MongoSettings | None = None


MYSQL_POOL: pooling.MySQLConnectionPool | None = None
DATABASE_SETTINGS: DatabaseSettings | None = None
PoolError = pooling.PoolError


def _int_from_env(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        log.warning("Invalid integer for %s=%s; using default %s", key, value, default)
        return default


def _build_pool_config(overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    default_pool_size = (os.cpu_count() or 1) * 5
    config: Dict[str, Any] = {
        "pool_name": os.getenv("MYSQL_POOL_NAME", "bot_pool"),
        "pool_size": _int_from_env("MYSQL_POOL_SIZE", default_pool_size),
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": _int_from_env("MYSQL_PORT", 3306),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": os.getenv("MYSQL_DATABASE", "botdb"),
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
        "use_pure": True,
    }
    if overrides:
        config.update({k: v for k, v in overrides.items() if v is not None})
    return config


def _normalise_backend(value: str | None) -> str:
    if not value:
        return "mysql"
    value = value.strip().lower()
    if value in {"mongo", "mongodb"}:
        return "mongodb"
    return "mysql"


def _build_mongo_settings() -> MongoSettings:
    host = os.getenv("MONGODB_HOST", "mongodb")
    port = _int_from_env("MONGODB_PORT", 27017)
    username = (os.getenv("MONGO_USER") or "").strip() or None
    password = (os.getenv("MONGO_PASS") or "").strip() or None
    database = (os.getenv("MONGO_DATABASE") or os.getenv("MONGO_DB"))
    if database:
        database = database.strip() or None

    uri = (os.getenv("MONGO_URI") or "").strip()
    if not uri:
        auth = ""
        if username:
            user_enc = quote_plus(username)
            if password:
                auth = f"{user_enc}:{quote_plus(password)}@"
            else:
                auth = f"{user_enc}@"
        uri = f"mongodb://{auth}{host}:{port}"
        if database:
            uri = f"{uri}/{database}"

    return MongoSettings(
        uri=uri,
        host=host,
        port=port,
        username=username,
        password=password,
        database=database,
    )


def load_database_settings(force_refresh: bool = False) -> DatabaseSettings:
    """Load and cache database configuration from environment variables."""

    global DATABASE_SETTINGS
    if DATABASE_SETTINGS is not None and not force_refresh:
        return DATABASE_SETTINGS

    load_dotenv()
    backend = _normalise_backend(os.getenv("DATABASE_BACKEND"))
    if backend == "mysql":
        mysql_config = _build_pool_config()
        DATABASE_SETTINGS = DatabaseSettings(backend="mysql", mysql=mysql_config)
    else:
        mongo_settings = _build_mongo_settings()
        DATABASE_SETTINGS = DatabaseSettings(backend="mongodb", mongo=mongo_settings)

    return DATABASE_SETTINGS


def get_database_backend() -> str:
    """Return the configured database backend."""

    return load_database_settings().backend


def get_mongo_settings() -> MongoSettings:
    """Return MongoDB configuration, raising if MongoDB is not selected."""

    settings = load_database_settings()
    if settings.backend != "mongodb" or settings.mongo is None:
        raise RuntimeError("MongoDB backend is not configured")
    return settings.mongo


def init_mysql_pool(**overrides: Any) -> None:
    """Initialise the global MySQL connection pool if needed."""
    settings = load_database_settings()
    if settings.backend != "mysql":
        log.info("Skipping MySQL pool initialisation for backend=%s", settings.backend)
        return
    global MYSQL_POOL
    if MYSQL_POOL is not None:
        return
    load_dotenv()
    config = _build_pool_config(overrides)
    MYSQL_POOL = pooling.MySQLConnectionPool(**config)


def get_mysql_pool() -> pooling.MySQLConnectionPool:
    """Return the active MySQL connection pool, initialising it on demand."""
    global MYSQL_POOL
    if MYSQL_POOL is None:
        init_mysql_pool()
    if MYSQL_POOL is None:
        raise RuntimeError("MySQL backend is not configured; cannot provide a connection pool")
    return MYSQL_POOL


class _CursorContext(AbstractContextManager):
    def __init__(self, dict_: bool = True) -> None:
        self.dict_ = dict_
        self.conn: Any = None
        self.cur: Any = None

    def __enter__(self):
        pool = get_mysql_pool()
        try:
            self.conn = pool.get_connection()
        except PoolError:
            log.error(
                "MySQL connection pool exhausted; consider increasing MYSQL_POOL_SIZE"
            )
            raise
        self.cur = self.conn.cursor(dictionary=self.dict_)
        return self.cur

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            if self.cur is not None:
                self.cur.close()
            if self.conn is not None:
                self.conn.close()
        return False


def with_mysql_cursor(dict_: bool = True):
    """Return a context manager yielding a MySQL cursor."""
    return _CursorContext(dict_=dict_)


def ensure_schema() -> None:
    """Create database tables required by the application if they do not exist."""
    settings = load_database_settings()
    if settings.backend != "mysql":
        log.info("Skipping schema creation for backend=%s", settings.backend)
        return

    with with_mysql_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admins(
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                api_token VARCHAR(128) NOT NULL UNIQUE,
                api_token_encrypted TEXT,
                api_token_raw VARCHAR(128) NULL,
                is_super TINYINT(1) NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        try:
            cur.execute("ALTER TABLE admins ADD COLUMN api_token_encrypted TEXT")
        except MySQLError:
            pass
        try:
            cur.execute("ALTER TABLE admins ADD COLUMN api_token_raw VARCHAR(128) NULL")
        except MySQLError:
            pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS panels(
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                telegram_user_id BIGINT NOT NULL,
                panel_url VARCHAR(255) NOT NULL,
                name VARCHAR(128) NOT NULL,
                panel_type VARCHAR(32) NOT NULL DEFAULT 'marzneshin',
                admin_username VARCHAR(64) NOT NULL,
                access_token VARCHAR(2048) NOT NULL,
                template_username VARCHAR(64) NULL,
                sub_url VARCHAR(2048) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_user_url (telegram_user_id, panel_url)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        try:
            cur.execute(
                "ALTER TABLE panels ADD COLUMN panel_type VARCHAR(32) NOT NULL DEFAULT 'marzneshin' AFTER name"
            )
        except MySQLError:
            pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_users(
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                telegram_user_id BIGINT NOT NULL,
                username VARCHAR(64) NOT NULL,
                app_key VARCHAR(64) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_owner_username (telegram_user_id, username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS local_users(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                username VARCHAR(64) NOT NULL,
                plan_limit_bytes BIGINT NOT NULL,
                used_bytes BIGINT NOT NULL DEFAULT 0,
                expire_at DATETIME NULL,
                note VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                disabled_pushed TINYINT(1) NOT NULL DEFAULT 0,
                disabled_pushed_at DATETIME NULL,
                UNIQUE KEY uq_local(owner_id, username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS local_user_keys(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                local_user_id BIGINT NOT NULL,
                access_key VARCHAR(64) NOT NULL,
                expires_at DATETIME NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_local_user(local_user_id),
                UNIQUE KEY uq_access_key(access_key),
                FOREIGN KEY (local_user_id) REFERENCES local_users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS local_user_panel_links(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                local_username VARCHAR(64) NOT NULL,
                panel_id BIGINT NOT NULL,
                remote_username VARCHAR(128) NOT NULL,
                last_used_traffic BIGINT NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_link(owner_id, local_username, panel_id),
                FOREIGN KEY (panel_id) REFERENCES panels(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS panel_disabled_configs(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                telegram_user_id BIGINT NOT NULL,
                panel_id BIGINT NOT NULL,
                config_name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_panel_cfg(panel_id, config_name),
                INDEX idx_panel(panel_id),
                FOREIGN KEY (panel_id) REFERENCES panels(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS panel_disabled_numbers(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                telegram_user_id BIGINT NOT NULL,
                panel_id BIGINT NOT NULL,
                config_index INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_panel_idx(panel_id, config_index),
                INDEX idx_panel(panel_id),
                FOREIGN KEY (panel_id) REFERENCES panels(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agents(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                telegram_user_id BIGINT NOT NULL UNIQUE,
                name VARCHAR(128) NOT NULL,
                plan_limit_bytes BIGINT NOT NULL DEFAULT 0,
                expire_at DATETIME NULL,
                active TINYINT(1) NOT NULL DEFAULT 1,
                user_limit BIGINT NOT NULL DEFAULT 0,
                max_user_bytes BIGINT NOT NULL DEFAULT 0,
                total_used_bytes BIGINT NOT NULL DEFAULT 0,
                api_token CHAR(64) UNIQUE,
                api_token_encrypted TEXT,
                disabled_pushed TINYINT(1) NOT NULL DEFAULT 0,
                disabled_pushed_at DATETIME NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        try:
            cur.execute("ALTER TABLE agents ADD COLUMN user_limit BIGINT NOT NULL DEFAULT 0")
        except MySQLError:
            pass
        try:
            cur.execute("ALTER TABLE agents ADD COLUMN max_user_bytes BIGINT NOT NULL DEFAULT 0")
        except MySQLError:
            pass
        added_total = False
        try:
            cur.execute("ALTER TABLE agents ADD COLUMN total_used_bytes BIGINT NOT NULL DEFAULT 0")
            added_total = True
        except MySQLError:
            pass
        try:
            cur.execute("ALTER TABLE agents ADD COLUMN api_token CHAR(64) UNIQUE")
        except MySQLError:
            pass
        try:
            cur.execute("ALTER TABLE agents ADD COLUMN api_token_encrypted TEXT")
        except MySQLError:
            pass
        if added_total:
            cur.execute(
                """
                UPDATE agents a
                SET total_used_bytes = (
                    SELECT COALESCE(SUM(used_bytes),0) FROM local_users WHERE owner_id=a.telegram_user_id
                )
                """
            )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_panels(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                agent_tg_id BIGINT NOT NULL,
                panel_id BIGINT NOT NULL,
                UNIQUE KEY uq_agent_panel(agent_tg_id, panel_id),
                FOREIGN KEY (panel_id) REFERENCES panels(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS services(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS service_panels(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                service_id BIGINT NOT NULL,
                panel_id BIGINT NOT NULL,
                UNIQUE KEY uq_service_panel(service_id, panel_id),
                FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE,
                FOREIGN KEY (panel_id) REFERENCES panels(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                `key` VARCHAR(128) NOT NULL,
                `value` TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_owner_key (owner_id, `key`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        try:
            cur.execute("ALTER TABLE agents ADD COLUMN service_id BIGINT NULL")
        except MySQLError:
            pass
        try:
            cur.execute("ALTER TABLE local_users ADD COLUMN service_id BIGINT NULL")
        except MySQLError:
            pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS account_presets(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                telegram_user_id BIGINT NOT NULL,
                limit_bytes BIGINT NOT NULL,
                duration_days INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_access_tokens(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                agent_id BIGINT NOT NULL,
                token_hash CHAR(64) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_agent_token(agent_id, token_hash)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)


__all__ = [
    "init_mysql_pool",
    "get_mysql_pool",
    "with_mysql_cursor",
    "ensure_schema",
    "load_database_settings",
    "get_database_backend",
    "get_mongo_settings",
    "DatabaseSettings",
    "MongoSettings",
    "MYSQL_POOL",
    "MySQLError",
    "mysql_errors",
    "PoolError",
    "errorcode",
]
