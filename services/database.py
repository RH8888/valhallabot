"""Database utilities shared across application layers."""
from __future__ import annotations

import os
from contextlib import AbstractContextManager
from typing import Any

from dotenv import load_dotenv
from mysql.connector import pooling, Error as MySQLError


MYSQL_POOL: pooling.MySQLConnectionPool | None = None


def init_mysql_pool() -> None:
    """Initialise the global MySQL connection pool if needed."""
    global MYSQL_POOL
    if MYSQL_POOL is not None:
        return
    load_dotenv()
    MYSQL_POOL = pooling.MySQLConnectionPool(
        pool_name="bot_pool",
        pool_size=5,
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "botdb"),
        charset="utf8mb4",
        use_pure=True,
    )


class _CursorContext(AbstractContextManager):
    def __init__(self, dict_: bool = True) -> None:
        self.dict_ = dict_
        self.conn: Any = None
        self.cur: Any = None

    def __enter__(self):
        global MYSQL_POOL
        if MYSQL_POOL is None:
            init_mysql_pool()
        self.conn = MYSQL_POOL.get_connection()
        self.cur = self.conn.cursor(dictionary=self.dict_)
        return self.cur

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.cur.close()
            self.conn.close()
        return False


def with_mysql_cursor(dict_: bool = True):
    """Return a context manager yielding a MySQL cursor."""
    return _CursorContext(dict_=dict_)


def ensure_schema() -> None:
    """Create database tables required by the application if they do not exist."""
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


__all__ = ["init_mysql_pool", "with_mysql_cursor", "ensure_schema", "MYSQL_POOL"]
