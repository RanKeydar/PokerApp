from pokerapp import create_app
from pokerapp.db.connection import get_db_connection
from pokerapp.routes.main import import_csv_year_to_db, HARBO_IMPORT_YEARS

app = create_app()

with app.app_context():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    DELETE FROM game_results
    WHERE game_id IN (SELECT id FROM games WHERE game_type='harbo');
    """)
    cur.execute("DELETE FROM games WHERE game_type='harbo';")
    conn.commit()
    conn.close()

    for y in HARBO_IMPORT_YEARS:
        print(import_csv_year_to_db("harbo", y))
