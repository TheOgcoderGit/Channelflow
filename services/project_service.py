from database.db import get_connection


def create_project(user_id, name):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO projects
        (
            user_id,
            name,
            status
        )
        VALUES
        (
            ?, ?, 0
        )
    """, (user_id, name))

    conn.commit()

    project_id = cur.lastrowid

    conn.close()

    return project_id


def get_projects(user_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            name,
            status,
            created_at
        FROM projects
        WHERE user_id=?
        ORDER BY id DESC
    """, (user_id,))

    rows = cur.fetchall()

    conn.close()

    return rows


def get_project(project_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM projects
        WHERE id=?
    """, (project_id,))

    row = cur.fetchone()

    conn.close()

    return row


def rename_project(project_id, new_name):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE projects
        SET name=?
        WHERE id=?
    """, (new_name, project_id))

    conn.commit()
    conn.close()


def update_status(project_id, status):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE projects
        SET status=?
        WHERE id=?
    """, (status, project_id))

    conn.commit()
    conn.close()


def delete_project(project_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM projects WHERE id=?",
        (project_id,)
    )

    conn.commit()
    conn.close()


def count_projects(user_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM projects WHERE user_id=?",
        (user_id,)
    )

    total = cur.fetchone()[0]

    conn.close()

    return total


def project_exists(project_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM projects WHERE id=?",
        (project_id,)
    )

    exists = cur.fetchone() is not None

    conn.close()

    return exists