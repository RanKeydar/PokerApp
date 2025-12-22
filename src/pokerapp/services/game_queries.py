from pokerapp.db.connection import get_db_connection

def get_top_players(game_type: str, limit: int = 5, year="all"):
    conn = get_db_connection()
    cur = conn.cursor()

    if year is None or str(year) == "all":
        cur.execute(
            """
            SELECT
                p.id AS player_id,
                p.name AS player_name,
                COALESCE(SUM(gr.profit), 0) AS total_profit,
                COUNT(gr.id) AS rows_count
            FROM players p
            JOIN game_results gr ON gr.player_id = p.id
            JOIN games g ON g.id = gr.game_id
            WHERE g.game_type = ?
            GROUP BY p.id, p.name
            ORDER BY total_profit DESC
            LIMIT ?;
            """,
            (game_type, limit),
        )
    else:
        y = str(year)
        cur.execute(
            """
            SELECT
                p.id AS player_id,
                p.name AS player_name,
                COALESCE(SUM(gr.profit), 0) AS total_profit,
                COUNT(gr.id) AS rows_count
            FROM players p
            JOIN game_results gr ON gr.player_id = p.id
            JOIN games g ON g.id = gr.game_id
            WHERE g.game_type = ?
              AND substr(g.date, 1, 4) = ?
            GROUP BY p.id, p.name
            ORDER BY total_profit DESC
            LIMIT ?;
            """,
            (game_type, y, limit),
        )

    rows = cur.fetchall()
    conn.close()
    return rows


def get_recent_games(game_type: str, limit: int = 5, year="all"):
    conn = get_db_connection()
    cur = conn.cursor()

    # year יכול להיות "all" או 2025/2024/...
    if year is None or str(year) == "all":
        cur.execute(
            """
            SELECT
              id,
              date,
              strftime('%d/%m/%Y', date) AS date_il,
              location
            FROM games
            WHERE game_type = ?
            ORDER BY date DESC, id DESC
            LIMIT ?;
            """,
            (game_type, limit),
        )
    else:
        y = str(year)
        cur.execute(
            """
            SELECT
              id,
              date,
              strftime('%d/%m/%Y', date) AS date_il,
              location
            FROM games
            WHERE game_type = ?
              AND substr(date, 1, 4) = ?
            ORDER BY date DESC, id DESC
            LIMIT ?;
            """,
            (game_type, y, limit),
        )

    rows = cur.fetchall()
    conn.close()
    return rows


    rows = cur.fetchall()
    conn.close()
    return rows

