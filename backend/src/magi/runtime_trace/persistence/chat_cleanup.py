"""SQLite owner of trace and notification deletion requested by chat."""

from pathlib import Path

from ...core.logger import get_logger
from ...core.sqlite import connect_sqlite

logger = get_logger(__name__)


class SqliteTraceContentRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def delete_session(self, *, user_id: str, session_id: str) -> None:
        if not self._db_path.exists():
            return
        conn = connect_sqlite(self._db_path, profile="hot_write")
        try:
            conn.execute("PRAGMA secure_delete=ON")
            existing_tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "trace_turns" in existing_tables:
                for table in (
                    "trace_llm_calls",
                    "trace_tools",
                    "trace_spans",
                ):
                    if table in existing_tables:
                        conn.execute(
                            f"""
                            DELETE FROM {table}
                            WHERE turn_id IN (
                                SELECT turn_id FROM trace_turns
                                WHERE user_id = ? AND session_id = ?
                            )
                            """,
                            (user_id, session_id),
                        )
                conn.execute(
                    "DELETE FROM trace_turns WHERE user_id = ? AND session_id = ?",
                    (user_id, session_id),
                )
            if "agent_run_manifests" in existing_tables:
                if "run_plans" in existing_tables:
                    conn.execute(
                        "DELETE FROM run_plans WHERE session_id = ?",
                        (session_id,),
                    )
                if "agent_run_events" in existing_tables:
                    conn.execute(
                        """
                        DELETE FROM agent_run_events
                        WHERE run_id IN (
                            SELECT run_id FROM agent_run_manifests
                            WHERE user_id = ? AND session_id = ?
                        )
                        """,
                        (user_id, session_id),
                    )
                conn.execute(
                    "DELETE FROM agent_run_manifests WHERE user_id = ? AND session_id = ?",
                    (user_id, session_id),
                )
            if "runtime_notifications" in existing_tables:
                conn.execute(
                    """
                    DELETE FROM runtime_notifications
                    WHERE user_id = ? AND session_id = ?
                    """,
                    (user_id, session_id),
                )
            if "trace_read_revisions" in existing_tables:
                conn.execute(
                    "DELETE FROM trace_read_revisions WHERE user_id = ? AND session_id = ?",
                    (user_id, session_id),
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            logger.exception("Failed to delete runtime trace rows")
            raise
        finally:
            conn.close()

    def delete_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> None:
        """Strictly delete every runtime-trace copy owned by one chat turn."""
        if not self._db_path.exists():
            return
        conn = connect_sqlite(self._db_path, profile="hot_write")
        try:
            conn.execute("PRAGMA secure_delete=ON")
            existing_tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            owns_turn = False
            if "trace_turns" in existing_tables:
                owns_turn = (
                    conn.execute(
                        """
                        SELECT 1 FROM trace_turns
                        WHERE user_id = ? AND session_id = ? AND turn_id = ?
                        LIMIT 1
                        """,
                        (user_id, session_id, turn_id),
                    ).fetchone()
                    is not None
                )
            if owns_turn:
                for table in (
                    "trace_llm_calls",
                    "trace_tools",
                    "trace_spans",
                ):
                    if table in existing_tables:
                        conn.execute(f"DELETE FROM {table} WHERE turn_id = ?", (turn_id,))
                conn.execute(
                    """
                    DELETE FROM trace_turns
                    WHERE user_id = ? AND session_id = ? AND turn_id = ?
                    """,
                    (user_id, session_id, turn_id),
                )
            if "agent_run_manifests" in existing_tables:
                if "run_plans" in existing_tables:
                    conn.execute(
                        """
                        DELETE FROM run_plans
                        WHERE run_id IN (
                            SELECT run_id FROM agent_run_manifests
                            WHERE user_id = ? AND session_id = ? AND turn_id = ?
                        )
                        """,
                        (user_id, session_id, turn_id),
                    )
                if "agent_run_events" in existing_tables:
                    conn.execute(
                        """
                        DELETE FROM agent_run_events
                        WHERE run_id IN (
                            SELECT run_id FROM agent_run_manifests
                            WHERE user_id = ? AND session_id = ? AND turn_id = ?
                        )
                        """,
                        (user_id, session_id, turn_id),
                    )
                conn.execute(
                    """
                    DELETE FROM agent_run_manifests
                    WHERE user_id = ? AND session_id = ? AND turn_id = ?
                    """,
                    (user_id, session_id, turn_id),
                )
            if "runtime_notifications" in existing_tables:
                conn.execute(
                    """
                    DELETE FROM runtime_notifications
                    WHERE user_id = ? AND session_id = ? AND turn_id = ?
                    """,
                    (user_id, session_id, turn_id),
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            logger.exception("Failed to delete runtime trace turn rows")
            raise
        finally:
            conn.close()

    def clear_all(self) -> None:
        """Delete execution traces and every persisted user-facing notification."""
        if not self._db_path.exists():
            return
        conn = connect_sqlite(self._db_path, profile="hot_write")
        try:
            existing_tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            for table in (
                "run_plans",
                "agent_run_events",
                "agent_run_manifests",
                "trace_llm_calls",
                "trace_tools",
                "trace_spans",
                "trace_turns",
                "trace_read_revisions",
            ):
                if table in existing_tables:
                    conn.execute(f"DELETE FROM {table}")
            if "runtime_notifications" in existing_tables:
                conn.execute("DELETE FROM runtime_notifications")
            if "user_notifications" in existing_tables:
                conn.execute("DELETE FROM user_notifications")
            if "plugin_rpc_receipts" in existing_tables:
                conn.execute("UPDATE plugin_rpc_receipts SET result_json=NULL,http_status=NULL,state='uncertain'")
            conn.commit()
            conn.execute("VACUUM")
            checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint is not None and int(checkpoint[0] or 0) != 0:
                raise RuntimeError("Runtime trace WAL could not be truncated after clear")
        except Exception:
            conn.rollback()
            logger.exception("Failed to clear runtime trace rows")
            raise
        finally:
            conn.close()
