from pokerapp.db.connection import get_db_connection

def get_top_players(game_type: str, limit: int = 5, year="all"):
    conn = get_db_connection()
    cur = conn.cursor()

    params = [game_type]
    year_filter = ""

    if year is not None and str(year) != "all":
        year_filter = "AND substr(g.date, 1, 4) = ?"
        params.append(str(year))

    sql = f"""
    SELECT
        p.id AS player_id,
        p.name AS player_name,
        ROUND(COALESCE(SUM(gr.profit), 0), 2) AS total_profit,

        COUNT(DISTINCT gr.game_id) AS games_played,
        ROUND(
            COALESCE(SUM(gr.profit), 0) * 1.0 / NULLIF(COUNT(DISTINCT gr.game_id), 0),
            2
        ) AS avg_profit_per_game,
        COUNT(DISTINCT substr(g.date, 1, 4)) AS years_played

    FROM players p
    JOIN game_results gr ON gr.player_id = p.id
    JOIN games g ON g.id = gr.game_id
    WHERE g.game_type = ?
    {year_filter}
    GROUP BY p.id, p.name
    ORDER BY total_profit DESC
    LIMIT ?;
    """

    params.append(limit)
    cur.execute(sql, params)

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
              (substr(date,9,2) || '.' || substr(date,6,2) || '.' || substr(date,3,2)) AS date_il,
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
              (substr(date,9,2) || '.' || substr(date,6,2) || '.' || substr(date,3,2)) AS date_il,
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

def get_complete_top_players(limit: int = 5, year="all"):
    conn = get_db_connection()
    cur = conn.cursor()

    params = []
    year_filter = ""

    if year is not None and str(year) != "all":
        year_filter = "AND substr(g.date, 1, 4) = ?"
        params.append(str(year))

    sql = f"""
    SELECT
        p.id AS player_id,
        p.name AS player_name,
        ROUND(COALESCE(SUM(gr.profit), 0), 2) AS total_profit,

        COUNT(DISTINCT gr.game_id) AS games_played,
        ROUND(
            COALESCE(SUM(gr.profit), 0) * 1.0 / NULLIF(COUNT(DISTINCT gr.game_id), 0),
            2
        ) AS avg_profit_per_game,
        COUNT(DISTINCT substr(g.date, 1, 4)) AS years_played

    FROM players p
    JOIN game_results gr ON gr.player_id = p.id
    JOIN games g ON g.id = gr.game_id
    WHERE g.game_type IN ('cash', 'harbo')
    {year_filter}
    GROUP BY p.id, p.name
    ORDER BY total_profit DESC
    """

    # אם limit הוא None => "הצג הכל" => לא מוסיפים LIMIT בכלל
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows

def get_complete_recent_games(limit: int = 5, year="all"):
    conn = get_db_connection()
    cur = conn.cursor()

    params = []
    year_filter = ""

    if year is not None and str(year) != "all":
        year_filter = "AND substr(date, 1, 4) = ?"
        params.append(str(year))

    sql = f"""
    SELECT
      id,
      date,
      (substr(date,9,2) || '.' || substr(date,6,2) || '.' || substr(date,3,2)) AS date_il,
      location,
      game_type,
      CASE
        WHEN game_type = 'cash' THEN 'קאש'
        WHEN game_type = 'harbo' THEN 'חרבו'
        ELSE game_type
      END AS game_type_label
    FROM games
    WHERE game_type IN ('cash', 'harbo')
    {year_filter}
    ORDER BY date DESC, id DESC
    LIMIT ?;
    """

    params.append(int(limit))
    cur.execute(sql, params)

    rows = cur.fetchall()
    conn.close()
    return rows
