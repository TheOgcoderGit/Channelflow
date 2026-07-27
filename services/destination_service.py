from database.db import get_connection


def add_destination(
    project_id,
    chat_id,
    username,
    title,
    chat_type
):

    conn = get_connection()
    cur = conn.cursor()

    # Duplicate Check
    cur.execute(
        """
        SELECT id
        FROM destinations
        WHERE project_id=?
        AND chat_id=?
        """,
        (project_id, chat_id)
    )

    if cur.fetchone():

        conn.close()

        return False

    cur.execute(
        """
        INSERT INTO destinations
        (
            project_id,
            chat_id,
            username,
            title,
            chat_type
        )
        VALUES
        (
            ?, ?, ?, ?, ?
        )
        """,
        (
            project_id,
            chat_id,
            username,
            title,
            chat_type
        )
    )

    conn.commit()
    conn.close()

    return True


def get_destinations(project_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM destinations
        WHERE project_id=?
        ORDER BY id DESC
        """,
        (project_id,)
    )

    rows = cur.fetchall()

    conn.close()

    return rows


def get_destination(destination_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM destinations
        WHERE id=?
        """,
        (destination_id,)
    )

    row = cur.fetchone()

    conn.close()

    return row


def delete_destination(destination_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        DELETE FROM destinations
        WHERE id=?
        """,
        (destination_id,)
    )

    conn.commit()
    conn.close()


def get_destination_chat_ids(project_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT chat_id
        FROM destinations
        WHERE project_id=?
        """,
        (project_id,)
    )

    rows = [str(row["chat_id"]) for row in cur.fetchall()]

    conn.close()

    return rows


def toggle_destination_enabled(destination_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT enabled FROM destinations WHERE id=?", (destination_id,))
    row = cur.fetchone()

    if row is None:
        conn.close()
        return None

    new_value = 0 if row["enabled"] else 1

    cur.execute(
        "UPDATE destinations SET enabled=? WHERE id=?",
        (new_value, destination_id)
    )

    conn.commit()
    conn.close()

    return new_value


def get_enabled_destination_chat_ids(project_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT chat_id
        FROM destinations
        WHERE project_id=?
        AND enabled=1
        """,
        (project_id,)
    )

    rows = [int(row["chat_id"]) for row in cur.fetchall()]

    conn.close()

    return rows


def count_destinations(project_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*)
        FROM destinations
        WHERE project_id=?
        """,
        (project_id,)
    )

    total = cur.fetchone()[0]

    conn.close()

    return total
