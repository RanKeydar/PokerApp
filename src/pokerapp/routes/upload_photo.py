"""
routes/upload_photo.py  — הזנת תוצאות פוקר מצילום
POST /upload-photo/analyze  → Claude Vision → JSON
POST /upload-photo/save     → שמירת תוצאות ל-DB
GET  /upload-photo          → עמוד העלאה
"""
import base64
import json
import os

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from pokerapp.db.connection import get_db_connection
from pokerapp.services.auth import get_current_user, login_required, role_required

bp_upload = Blueprint("upload_photo", __name__)

# ─────────────────────────────────────────
# helpers
# ─────────────────────────────────────────

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_BYTES = 20 * 1024 * 1024  # 20 MB


def _get_anthropic_client():
    """Lazy import so startup doesn't fail if package missing."""
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        return None, "חבילת anthropic לא מותקנת בסביבה"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "ANTHROPIC_API_KEY לא מוגדר בסביבה"

    return anthropic.Anthropic(api_key=api_key), None


VISION_PROMPT = """You are analyzing a poker game result sheet (may be handwritten or printed, in Hebrew or English).

Extract all player names and their financial results.

Return ONLY a valid JSON array — no explanation, no markdown fences.
Each element must have exactly these keys:
  "name"    — player name as written
  "buyin"   — total buy-in amount (number, 0 if unknown)
  "cashout" — cash-out amount (number, 0 if unknown)

If the sheet shows only profit/loss (no separate buyin/cashout columns):
  set buyin = 0 and cashout = profit_value  (negative profit → negative cashout)

If a cell is blank / illegible, use 0.

Example output:
[
  {"name": "יוסי", "buyin": 200, "cashout": 350},
  {"name": "דני",  "buyin": 200, "cashout": 80}
]
"""


# ─────────────────────────────────────────
# GET  /upload-photo
# ─────────────────────────────────────────

@bp_upload.route("/upload-photo", methods=["GET"])
@login_required
@role_required("admin", "magician")
def upload_photo():
    conn = get_db_connection()
    cur = conn.cursor()

    # רשימת שחקנים לטבלת האישור
    cur.execute("""
        SELECT DISTINCT p.id, p.name
        FROM players p
        JOIN game_results gr ON gr.player_id = p.id
        ORDER BY p.name COLLATE NOCASE;
    """)
    players = [dict(r) for r in cur.fetchall()]
    conn.close()

    from datetime import date as _date
    today = _date.today().isoformat()

    return render_template(
        "upload_photo.html",
        players=players,
        today=today,
        current_user=get_current_user(),
    )


# ─────────────────────────────────────────
# POST /upload-photo/analyze  (AJAX → JSON)
# ─────────────────────────────────────────

@bp_upload.route("/upload-photo/analyze", methods=["POST"])
@login_required
@role_required("admin", "magician")
def analyze_photo():
    """מקבל תמונה, שולח ל-Claude Vision, מחזיר JSON עם שמות וסכומים."""
    file = request.files.get("photo")
    if not file or file.filename == "":
        return jsonify({"error": "לא נשלחה תמונה"}), 400

    mime = file.content_type or "image/jpeg"
    if mime not in ALLOWED_MIME:
        return jsonify({"error": f"סוג קובץ לא נתמך: {mime}"}), 400

    raw = file.read()
    if len(raw) > MAX_BYTES:
        return jsonify({"error": "הקובץ גדול מדי (מקסימום 20MB)"}), 400

    client, err = _get_anthropic_client()
    if err:
        return jsonify({"error": err}), 503

    b64 = base64.standard_b64encode(raw).decode()

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": VISION_PROMPT},
                    ],
                }
            ],
        )
    except Exception as exc:
        current_app.logger.error("Claude Vision error: %s", exc)
        return jsonify({"error": f"שגיאה בשליחה ל-Claude API: {exc}"}), 502

    raw_text = response.content[0].text.strip()

    # נקה markdown fences אם יש
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        raw_text = "\n".join(
            ln for ln in lines if not ln.startswith("```")
        ).strip()

    try:
        players = json.loads(raw_text)
        if not isinstance(players, list):
            raise ValueError("not a list")
    except (json.JSONDecodeError, ValueError) as exc:
        current_app.logger.error("JSON parse error: %s\nraw: %s", exc, raw_text)
        return jsonify({"error": "Claude החזיר תשובה שלא ניתן לפרסר", "raw": raw_text}), 422

    # נרמל שדות
    result = []
    for p in players:
        result.append(
            {
                "name": str(p.get("name", "")).strip(),
                "buyin": float(p.get("buyin", 0) or 0),
                "cashout": float(p.get("cashout", 0) or 0),
            }
        )

    return jsonify({"players": result})


# ─────────────────────────────────────────
# POST /upload-photo/save
# ─────────────────────────────────────────

@bp_upload.route("/upload-photo/save", methods=["POST"])
@login_required
@role_required("admin", "magician")
def save_photo_results():
    """שומר תוצאות מאושרות ל-DB ומפנה לעמוד המשחק."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "גוף הבקשה ריק"}), 400

    game_date  = data.get("date", "").strip()
    location   = data.get("location", "").strip() or None
    game_type  = data.get("game_type", "cash")
    game_id    = data.get("game_id")          # None → צור משחק חדש
    entries    = data.get("entries", [])       # [{name, buyin, cashout}]

    if not game_date:
        return jsonify({"error": "תאריך חסר"}), 400
    if not entries:
        return jsonify({"error": "אין תוצאות לשמור"}), 400

    conn = get_db_connection()
    cur  = conn.cursor()

    try:
        # ── 1. צור משחק חדש אם צריך ──────────────────────────────────
        if not game_id:
            cur.execute(
                "INSERT INTO games (date, location, game_type) VALUES (?, ?, ?)",
                (game_date, location, game_type),
            )
            conn.commit()
            game_id = cur.lastrowid

        # ── 2. התאם/צור שחקנים ─────────────────────────────────────
        for entry in entries:
            name    = entry.get("name", "").strip()
            buyin   = float(entry.get("buyin",   0) or 0)
            cashout = float(entry.get("cashout", 0) or 0)
            profit  = cashout - buyin

            if not name:
                continue

            # חפש שחקן לפי שם (case-insensitive)
            cur.execute(
                "SELECT id FROM players WHERE name = ? COLLATE NOCASE LIMIT 1",
                (name,),
            )
            row = cur.fetchone()

            if row:
                player_id = row["id"]
            else:
                # צור שחקן חדש
                cur.execute(
                    "INSERT INTO players (name) VALUES (?)",
                    (name,),
                )
                conn.commit()
                player_id = cur.lastrowid

            # הוסף / עדכן תוצאה (upsert)
            cur.execute(
                """
                INSERT INTO game_results (game_id, player_id, buyin, cashout, profit)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(game_id, player_id)
                DO UPDATE SET buyin=excluded.buyin,
                              cashout=excluded.cashout,
                              profit=excluded.profit
                """,
                (game_id, player_id, buyin, cashout, profit),
            )

        conn.commit()
    except Exception as exc:
        conn.rollback()
        current_app.logger.error("save_photo_results error: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        conn.close()

    return jsonify({"ok": True, "game_id": game_id})
