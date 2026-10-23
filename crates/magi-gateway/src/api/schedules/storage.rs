use crate::db;

pub(super) fn open_scheduler_db() -> Option<db::GuardedConnection> {
    db::open_readonly(&db::scheduler_db_path())
}
