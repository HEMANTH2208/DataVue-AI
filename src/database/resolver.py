"""
LLMSQL Session-Based Database Resolver

Handles registration, validation, switching, path resolution,
and automated cleanup of session-specific user-uploaded databases.
"""

from __future__ import annotations

import contextvars
import os
import shutil
import sqlite3
import time
import zipfile
import csv
import re
from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import BaseModel

# ContextVar for thread/async-safe session ID propagation
active_session_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("active_session_id", default=None)

# Directory inside the workspace for temporary database files
TEMP_DB_DIR = Path("data/temporary_databases").resolve()

# Security limits
MAX_ZIP_SIZE = 20 * 1024 * 1024       # 20MB
MAX_EXTRACTED_SIZE = 100 * 1024 * 1024 # 100MB


class SessionDatabase(BaseModel):
    session_id: str
    database_type: str = "SQLite"
    database_name: str
    database_path: str
    schema_data: Optional[Dict[str, Any]] = None
    created_at: float
    last_activity: float
    source_type: str  # "default" | "uploaded"
    original_uploaded_path: Optional[str] = None  # To retain switch path if uploaded exists


# In-memory session database registry
_session_databases: Dict[str, SessionDatabase] = {}


def get_active_database_path(session_id: Optional[str] = None) -> str:
    """Resolve the file path of the database for the active session.

    Falls back to the default e-commerce database if no session is set
    or if the default database is selected.
    """
    if session_id is None:
        session_id = active_session_id.get()

    if session_id and session_id in _session_databases:
        sess_db = _session_databases[session_id]
        sess_db.last_activity = time.time()  # Keep session alive

        if sess_db.source_type == "uploaded":
            return sess_db.database_path

    # Fallback to default
    from src.config import get_settings
    return get_settings().default_db_path


def get_session_db_info(session_id: str) -> Dict[str, Any]:
    """Retrieve metadata about the database for a session."""
    from src.config import get_settings
    default_db = get_settings().default_db_path
    
    # Trigger periodic cleanup
    cleanup_expired_sessions()

    if session_id in _session_databases:
        sess_db = _session_databases[session_id]
        sess_db.last_activity = time.time()
        return {
            "session_id": sess_db.session_id,
            "database_name": sess_db.database_name,
            "database_type": sess_db.database_type,
            "source_type": sess_db.source_type,
            "created_at": sess_db.created_at,
            "status": "Ready",
        }

    # If session not registered yet, default info
    return {
        "session_id": session_id,
        "database_name": Path(default_db).name,
        "database_type": "SQLite",
        "source_type": "default",
        "created_at": time.time(),
        "status": "Ready",
    }


def get_cached_schema(session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve cached schema for the session's active database."""
    if session_id is None:
        session_id = active_session_id.get()

    if session_id and session_id in _session_databases:
        return _session_databases[session_id].schema_data
    return None


def cache_schema(schema: Dict[str, Any], session_id: Optional[str] = None) -> None:
    """Store the discovered schema in the session's database state."""
    if session_id is None:
        session_id = active_session_id.get()

    if session_id:
        if session_id not in _session_databases:
            # Register a default session entry to cache schema
            from src.config import get_settings
            default_path = get_settings().default_db_path
            _session_databases[session_id] = SessionDatabase(
                session_id=session_id,
                database_name=Path(default_path).name,
                database_path=default_path,
                created_at=time.time(),
                last_activity=time.time(),
                source_type="default",
            )
        _session_databases[session_id].schema_data = schema


def select_database(session_id: str, source_type: str) -> None:
    """Switch the session's active database between 'default' and 'uploaded'."""
    if source_type == "default":
        if session_id in _session_databases:
            sess_db = _session_databases[session_id]
            sess_db.source_type = "default"
            # Invalidate schema cache so the default schema is loaded
            sess_db.schema_data = None
            sess_db.last_activity = time.time()
    elif source_type == "uploaded":
        if session_id in _session_databases:
            sess_db = _session_databases[session_id]
            if sess_db.original_uploaded_path:
                sess_db.database_path = sess_db.original_uploaded_path
                sess_db.source_type = "uploaded"
                sess_db.schema_data = None
                sess_db.last_activity = time.time()
            else:
                raise ValueError("No uploaded database found for this session.")
    else:
        raise ValueError(f"Invalid database source type: {source_type}")


def _normalize_identifier(name: str) -> str:
    """Normalize names to valid lowercase SQLite identifiers."""
    stem = Path(name).stem
    # Replace spaces and special characters with underscores
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", stem.strip())
    clean = clean.lower().strip("_")
    if not clean:
        clean = "table"
    # Ensure it doesn't start with a number
    if clean[0].isdigit():
        clean = "t_" + clean
    return clean


def _detect_delimiter(file_path: Path) -> str:
    """Detect CSV delimiter safely, default to comma."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            sample = f.read(4096)
            if not sample:
                return ","
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(sample, delimiters=",;\t|")
            return dialect.delimiter
    except Exception:
        return ","


def _infer_column_type(values: list[str]) -> str:
    """Infer SQLite datatype from sample values, preserving leading zeros."""
    non_empty = [v.strip() for v in values if v.strip()]
    if not non_empty:
        return "TEXT"

    is_int = True
    is_float = True

    for val in non_empty:
        # Preserve leading zeros for values like "0123"
        if val.startswith("0") and len(val) > 1 and val.isdigit():
            return "TEXT"

        try:
            int(val)
        except ValueError:
            is_int = False

        try:
            float(val)
        except ValueError:
            is_float = False

    if is_int:
        return "INTEGER"
    if is_float:
        return "REAL"

    # Check date formats (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)
    datetime_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}(\s+\d{2}:\d{2}:\d{2})?$")
    if all(datetime_pattern.match(val) for val in non_empty):
        return "DATETIME"

    return "TEXT"


def _detect_column_types(file_path: Path, delimiter: str = ",") -> tuple[list[str], list[str]]:
    """Infers columns and types from the first 500 rows of a CSV file."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f, delimiter=delimiter)
        try:
            headers = next(reader)
        except StopIteration:
            raise ValueError(f"CSV file '{file_path.name}' is empty.")

        # Clean header identifiers
        headers = [_normalize_identifier(h) for h in headers]
        
        # Resolve duplicates
        seen = {}
        for i, h in enumerate(headers):
            if not h:
                h = f"col_{i}"
            if h in seen:
                seen[h] += 1
                headers[i] = f"{h}_{seen[h]}"
            else:
                seen[h] = 0
                headers[i] = h

        rows = []
        for _ in range(500):
            try:
                row = next(reader)
                if row:
                    rows.append(row)
            except StopIteration:
                break

    if not rows:
        return headers, ["TEXT"] * len(headers)

    col_types = []
    for col_idx in range(len(headers)):
        col_values = [row[col_idx] for row in rows if col_idx < len(row)]
        col_types.append(_infer_column_type(col_values))

    return headers, col_types


def _import_csv_to_sqlite(csv_path: Path, conn: sqlite3.Connection, table_name: str) -> None:
    """Import a CSV file into a SQLite database table dynamically."""
    delimiter = _detect_delimiter(csv_path)
    headers, col_types = _detect_column_types(csv_path, delimiter)

    # Create table SQL
    columns_def = ", ".join(f'"{col}" {col_type}' for col, col_type in zip(headers, col_types))
    create_sql = f'CREATE TABLE "{table_name}" ({columns_def});'
    
    try:
        conn.execute(create_sql)
    except Exception as exc:
        raise ValueError(f"Failed to create table '{table_name}': {exc}")

    # Prepare insert statement
    placeholders = ", ".join(["?"] * len(headers))
    insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders});'

    with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f, delimiter=delimiter)
        # Skip header
        try:
            next(reader)
        except StopIteration:
            return

        batch = []
        for line_num, row in enumerate(reader, start=2):
            if not row:
                continue

            # Pad or truncate row to match headers length
            if len(row) < len(headers):
                row = row + [None] * (len(headers) - len(row))
            elif len(row) > len(headers):
                row = row[:len(headers)]

            # Convert types safely
            typed_row = []
            for val, col_type in zip(row, col_types):
                v = val.strip() if val else ""
                if v == "":
                    typed_row.append(None)
                elif col_type == "INTEGER":
                    try:
                        typed_row.append(int(v))
                    except ValueError:
                        typed_row.append(v)
                elif col_type == "REAL":
                    try:
                        typed_row.append(float(v))
                    except ValueError:
                        typed_row.append(v)
                else:
                    typed_row.append(val)
            batch.append(typed_row)

            if len(batch) >= 1000:
                try:
                    conn.executemany(insert_sql, batch)
                except Exception as exc:
                    raise ValueError(f"Failed to insert row in table '{table_name}' batch near row {line_num}: {exc}")
                batch = []

        if batch:
            try:
                conn.executemany(insert_sql, batch)
            except Exception as exc:
                raise ValueError(f"Failed to insert remaining rows in table '{table_name}': {exc}")
        conn.commit()


def process_zip_upload(zip_file_path: Path, session_id: str) -> SessionDatabase:
    """Validate, extract, and initialize a temporary SQLite database from uploaded CSV files in a ZIP archive.

    Performs Zip Slip validation, detects CSV files recursively, converts them to database tables,
    and returns database metadata.
    """
    if not zipfile.is_zipfile(zip_file_path):
        raise ValueError("The uploaded file is not a valid ZIP archive.")

    if zip_file_path.stat().st_size > MAX_ZIP_SIZE:
        raise ValueError(f"Uploaded ZIP exceeds maximum size limit of {MAX_ZIP_SIZE // (1024*1024)}MB.")

    # Create session-specific temporary directory with unique upload subfolder to prevent locks
    session_dir = TEMP_DB_DIR / f"session_{session_id}" / f"up_{int(time.time() * 1000)}"
    session_dir.mkdir(parents=True, exist_ok=True)

    extracted_size = 0

    # 2. Secure extraction with path traversal checks
    with zipfile.ZipFile(zip_file_path, "r") as zref:
        corrupted = zref.testzip()
        if corrupted:
            raise ValueError(f"Corrupted file found inside ZIP: {corrupted}")

        for member in zref.infolist():
            extracted_size += member.file_size
            if extracted_size > MAX_EXTRACTED_SIZE:
                raise ValueError("Extracted contents exceed size limit (possible zip bomb detected).")

            target_path = Path(os.path.abspath(session_dir / member.filename))
            if not target_path.resolve().as_posix().startswith(session_dir.resolve().as_posix()):
                raise ValueError(f"Security violation: path traversal attempt detected in ZIP ({member.filename}).")

            if not member.is_dir():
                parts = Path(member.filename).parts
                if any(p.startswith(".") or p.startswith("__MACOSX") for p in parts):
                    continue

                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zref.open(member) as source, open(target_path, "wb") as target:
                    shutil.copyfileobj(source, target)

    # 3. Recursively find CSV files inside the extracted directory (including subdirectories)
    csv_files: list[Path] = []
    for root, _, files in os.walk(session_dir):
        for file in files:
            if file.lower().endswith(".csv"):
                csv_files.append(Path(root) / file)

    if not csv_files:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise ValueError("No CSV files were found in the uploaded ZIP. Please upload a ZIP containing one or more CSV files.")

    # 4. Create temporary SQLite database and import all CSV files
    sqlite_db_path = session_dir / "user_dataset.db"
    conn = sqlite3.connect(sqlite_db_path)
    try:
        table_names_seen = {}
        for csv_path in csv_files:
            base_name = _normalize_identifier(csv_path.name)
            if base_name in table_names_seen:
                table_names_seen[base_name] += 1
                table_name = f"{base_name}_{table_names_seen[base_name]}"
            else:
                table_names_seen[base_name] = 0
                table_name = base_name
            
            _import_csv_to_sqlite(csv_path, conn, table_name)
    except Exception as exc:
        conn.close()
        shutil.rmtree(session_dir, ignore_errors=True)
        raise ValueError(f"CSV import failed: {exc}") from exc
    finally:
        conn.close()

    # 5. Validate SQLite database integrity
    if not _validate_sqlite_integrity(sqlite_db_path):
        shutil.rmtree(session_dir, ignore_errors=True)
        raise ValueError("SQLite database integrity validation failed.")

    # Register the successful session database
    now = time.time()
    sess_db = SessionDatabase(
        session_id=session_id,
        database_name=sqlite_db_path.name,
        database_path=str(sqlite_db_path),
        created_at=now,
        last_activity=now,
        source_type="uploaded",
        original_uploaded_path=str(sqlite_db_path),
    )
    _session_databases[session_id] = sess_db

    # Clean up the original uploaded ZIP file
    if zip_file_path.exists() and zip_file_path.parent != session_dir:
        try:
            zip_file_path.unlink()
        except Exception:
            pass

    return sess_db


def _validate_sqlite_integrity(db_path: Path) -> bool:
    """Safely runs PRAGMA integrity_check against a SQLite database."""
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            cursor.fetchall()
            cursor = conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            return result == "ok"
        finally:
            conn.close()
    except Exception as e:
        print(f"[SQLite Integrity Check Error] DB: {db_path} | Exception: {e}")
        return False


def cleanup_session(session_id: str) -> None:
    """Close connections and delete all temporary files for a session."""
    if session_id in _session_databases:
        _session_databases.pop(session_id)
    
    session_dir = TEMP_DB_DIR / f"session_{session_id}"
    if session_dir.exists():
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
            print(f"[Cleanup] Cleaned up directory for session: {session_id}")
        except Exception as e:
            print(f"[Cleanup Error] Failed to delete temporary directory {session_dir}: {e}")


def cleanup_expired_sessions(inactivity_timeout_seconds: float = 1800.0) -> None:
    """Identifies and purges session databases that have been inactive."""
    now = time.time()
    expired_ids = []
    
    for sid, sess_db in list(_session_databases.items()):
        if sess_db.source_type == "uploaded":
            if now - sess_db.last_activity > inactivity_timeout_seconds:
                expired_ids.append(sid)
                
    for sid in expired_ids:
        print(f"[Cleanup] Session {sid} has expired due to inactivity. Purging database.")
        cleanup_session(sid)
