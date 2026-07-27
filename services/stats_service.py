"""
Per-project running counters: forwarded / failed / retried / filtered.
A row is created lazily on first increment, same pattern as
project_settings.
"""

from database.db import get_connection


def _ensure_row(cur, project_id):

    cur.execute(
        "INSERT OR IGNORE INTO stats(project_id) VALUES(?)",
        (project_id,)
    )


def get_stats(project_id):

    conn = get_connection()
    cur = conn.cursor()

    _ensure_row(cur, project_id)
    conn.commit()

    cur.execute("SELECT * FROM stats WHERE project_id=?", (project_id,))

    row = cur.fetchone()

    conn.close()

    return row


def increment(project_id, field, amount=1):

    if field not in ("forwarded", "failed", "retried", "filtered"):
        raise ValueError(f"Unknown stats field: {field}")

    conn = get_connection()
    cur = conn.cursor()

    _ensure_row(cur, project_id)

    if field == "forwarded":

        cur.execute(
            f"""
            UPDATE stats
            SET {field} = {field} + ?, last_forward_at = CURRENT_TIMESTAMP
            WHERE project_id=?
            """,
            (amount, project_id)
        )

    else:

        cur.execute(
            f"UPDATE stats SET {field} = {field} + ? WHERE project_id=?",
            (amount, project_id)
        )

    conn.commit()
    conn.close()


def global_stats(user_id, project_ids):
    """Aggregates stats across a set of project ids (used for the Status screen)."""

    if not project_ids:
        return {"forwarded": 0, "failed": 0, "retried": 0, "filtered": 0}

    conn = get_connection()
    cur = conn.cursor()

    placeholders = ",".join("?" for _ in project_ids)

    cur.execute(
        f"""
        SELECT
            COALESCE(SUM(forwarded), 0) AS forwarded,
            COALESCE(SUM(failed), 0) AS failed,
            COALESCE(SUM(retried), 0) AS retried,
            COALESCE(SUM(filtered), 0) AS filtered
        FROM stats
        WHERE project_id IN ({placeholders})
        """,
        project_ids
    )

    row = cur.fetchone()

    conn.close()

    return dict(row)
