from __future__ import annotations

import os
import sqlite3
import tempfile
from csv import DictReader
from pathlib import Path
from typing import Any


DATA_DIR = Path("data")
CSV_PATH = DATA_DIR / "business_metrics.csv"
DB_PATH = Path(tempfile.gettempdir()) / "voice_sql_agent.db" if os.getenv("VERCEL") else DATA_DIR / "voice_sql_agent.db"
TABLE_NAME = os.getenv("ANALYTICS_TABLE", "business_metrics").strip() or "business_metrics"


def get_database_config() -> dict[str, Any]:
    backend = os.getenv("DB_BACKEND", "").strip().lower()
    if backend == "mysql":
        return {
            "backend": "mysql",
            "host": os.getenv("MYSQL_HOST", "").strip(),
            "port": int(os.getenv("MYSQL_PORT", "3306").strip() or "3306"),
            "user": os.getenv("MYSQL_USER", "").strip(),
            "password": os.getenv("MYSQL_PASSWORD", ""),
            "database": os.getenv("MYSQL_DATABASE", "").strip(),
            "seed_sample": os.getenv("DB_SEED_SAMPLE", "false").strip().lower() == "true",
        }
    return {"backend": "sqlite", "path": DB_PATH}


def initialize_database() -> dict[str, Any]:
    config = get_database_config()
    if config["backend"] == "mysql":
        _initialize_mysql_database(config)
    else:
        _initialize_sqlite_database(config["path"])
    return config


def _load_sample_rows() -> list[tuple[Any, ...]]:
    with CSV_PATH.open("r", encoding="utf-8", newline="") as csv_file:
        reader = DictReader(csv_file)
        rows = []
        for row in reader:
            rows.append(
                (
                    row["month"],
                    row["region"],
                    row["product_line"],
                    float(row["revenue"]),
                    float(row["cost"]),
                    int(row["units_sold"]),
                    float(row["customer_churn"]),
                    float(row["csat"]),
                    int(row["incident_count"]),
                )
            )
        return rows


def _initialize_sqlite_database(db_path: Path) -> None:
    rows = _load_sample_rows()
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
        connection.execute(
            f"""
            CREATE TABLE {TABLE_NAME} (
                month TEXT NOT NULL,
                region TEXT NOT NULL,
                product_line TEXT NOT NULL,
                revenue REAL NOT NULL,
                cost REAL NOT NULL,
                units_sold INTEGER NOT NULL,
                customer_churn REAL NOT NULL,
                csat REAL NOT NULL,
                incident_count INTEGER NOT NULL
            )
            """
        )
        connection.executemany(
            f"""
            INSERT INTO {TABLE_NAME}
            (month, region, product_line, revenue, cost, units_sold, customer_churn, csat, incident_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_month
            ON {TABLE_NAME} (month)
            """
        )
        connection.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_region
            ON {TABLE_NAME} (region)
            """
        )
        connection.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_product
            ON {TABLE_NAME} (product_line)
            """
        )


def _initialize_mysql_database(config: dict[str, Any]) -> None:
    required = ["host", "user", "database"]
    missing = [field for field in required if not config.get(field)]
    if missing:
        raise ValueError("Missing MySQL configuration: " + ", ".join(missing))

    with pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        database=config["database"],
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    month DATE NOT NULL,
                    region VARCHAR(32) NOT NULL,
                    product_line VARCHAR(32) NOT NULL,
                    revenue DECIMAL(12, 2) NOT NULL,
                    cost DECIMAL(12, 2) NOT NULL,
                    units_sold INT NOT NULL,
                    customer_churn DECIMAL(6, 2) NOT NULL,
                    csat DECIMAL(6, 2) NOT NULL,
                    incident_count INT NOT NULL
                )
                """
            )
            cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
            row_count = int(cursor.fetchone()[0])
            if row_count == 0 and config.get("seed_sample"):
                rows = _load_sample_rows()
                insert_sql = f"""
                    INSERT INTO {TABLE_NAME}
                    (month, region, product_line, revenue, cost, units_sold, customer_churn, csat, incident_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.executemany(insert_sql, rows)
            if row_count == 0 and not config.get("seed_sample"):
                raise ValueError(
                    "MySQL table is empty. Set DB_SEED_SAMPLE=true to load demo data, "
                    "or populate the client table before starting the app."
                )
            _ensure_mysql_index(cursor, f"idx_{TABLE_NAME}_month", "month")
            _ensure_mysql_index(cursor, f"idx_{TABLE_NAME}_region", "region")
            _ensure_mysql_index(cursor, f"idx_{TABLE_NAME}_product", "product_line")


def _ensure_mysql_index(cursor: Any, index_name: str, column_name: str) -> None:
    cursor.execute(f"SHOW INDEX FROM {TABLE_NAME} WHERE Key_name = %s", (index_name,))
    if cursor.fetchone() is None:
        cursor.execute(f"CREATE INDEX {index_name} ON {TABLE_NAME} ({column_name})")


def open_connection(config: dict[str, Any]):
    if config["backend"] == "mysql":
        return pymysql.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["database"],
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
    return sqlite3.connect(config["path"])


def describe_database(config: dict[str, Any]) -> str:
    if config["backend"] == "mysql":
        return f"mysql://{config['host']}:{config['port']}/{config['database']}"
    return str(config["path"])


def parameter_placeholder(config: dict[str, Any]) -> str:
    return "%s" if config["backend"] == "mysql" else "?"
