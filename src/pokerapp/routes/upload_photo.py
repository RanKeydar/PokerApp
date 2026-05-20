"""
routes/upload_photo.py  -- הזנת תוצאות פוקר מצילום
GET  /upload-photo                -> עמוד העלאה
POST /upload-photo/preprocess     -> Pillow + CLAHE -> base64 preview
POST /upload-photo/analyze        -> Claude Vision (few-shot) -> JSON numbers
POST /upload-photo/save           -> שמירת תוצאות ל-DB
POST /upload-photo/save-example   -> שמירת דוגמה לאימון
GET  /upload-photo/examples       -> רשימת דוגמאות
DELETE /upload-photo/examples/<n> -> מחיקת דוגמה
"""
import base64
import json
import os
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request

from pokerapp.db.connection import get_db_connection, log_activity
from pokerapp.services.auth import get_current_user, login_required, role_required

bp_upload = Blueprint("upload_photo", __name__)

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_BYTES    = 20 * 1024 * 1024
EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "vision_examples"
MAX_FEW_SHOT = 5

# חלון זמן לשחקנים "פעילים" — ימים
ACTIVE_DAYS = 180


# ── Anthropic client ──────────────────────────────────────────────────────────

def _get_anthropic_client():
    try:
        import anthropic
    except ImportError:
        return None, "anthropic package not installed"
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).resolve().parents[3] / ".env",
                        override=True, encoding="utf-8-sig")
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        except Exception:
            pass
    if not api_key:
        return None, "ANTHROPIC_API_KEY not set"
    current_app.logger.info("Anthropic key len=%d prefix=%s", len(api_key), api_key[:12])
    return anthropic.Anthropic(api_key=api_key), None


# ── image helpers ─────────────────────────────────────────────────────────────

def _preprocess_image(raw: bytes, mime: str) -> tuple:
    """EXIF + CLAHE preview."""
    try:
        import io, numpy as np, cv2
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        bgr  = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        clahe    = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        denoised = cv2.fastNlMeansDenoising(enhanced, None, h=7,
                                             templateWindowSize=7, searchWindowSize=21)
        rgb = cv2.cvtColor(denoised, cv2.COLOR_GRAY2BGR)
        _, buf = cv2.imencode(".jpg", rgb, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return bytes(buf), "image/jpeg"
    except Exception as exc:
        current_app.logger.warning("Preprocess skipped: %s", exc)
        return raw, mime


def _rotate_only(raw: bytes, mime: str) -> tuple:
    """EXIF correction only."""
    try:
        import io
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=92)
        return buf.getvalue(), "image/jpeg"
    except Exception as exc:
        current_app.logger.warning("Rotate skipped: %s", exc)
        return raw, mime


def _parse_json_response(text: str):
    """Parse Claude response -> Python list, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(
            ln for ln in text.splitlines() if not ln.startswith("```")
        ).strip()
    import re
    m = re.search(r'\[[\s\S]*\]', text)
    if m:
        text = m.group(0)
    obj, _ = json.JSONDecoder().raw_decode(text)
    return obj if isinstance(obj, list) else []


# ── few-shot example storage ──────────────────────────────────────────────────

def _load_examples() -> list:
    """Load saved training examples (image + result)."""
    EXAMPLES_DIR.mkdir(exist_ok=True)
    examples = []
    for img_path in sorted(EXAMPLES_DIR.glob("*_image.jpg")):
        res_path = img_path.with_name(
            img_path.stem.replace("_image", "_result") + ".json"
        )
        if not res_path.exists():
            continue
        try:
            b64    = base64.standard_b64encode(img_path.read_bytes()).decode()
            result = json.loads(res_path.read_text(encoding="utf-8"))
            examples.append({"image_b64": b64, "mime": "image/jpeg", "result": result})
        except Exception:
            continue
    return examples


def _next_example_index() -> int:
    EXAMPLES_DIR.mkdir(exist_ok=True)
    nums = []
    for p in EXAMPLES_DIR.glob("*_image.jpg"):
        try:
            nums.append(int(p.stem.split("_")[0]))
        except ValueError:
            pass
    return max(nums) + 1 if nums else 1


# ── Claude Vision ─────────────────────────────────────────────────────────────

NUMBERS_PROMPT = """\
You are reading a handwritten Hebrew poker cash-game result sheet.

The sheet has multiple player COLUMNS side by side.
Each column contains:
  1. A player name at the TOP (Hebrew text -- ignore, do not read it)
  2. One or more BUY-IN numbers below the name (above a separator line or gap)
  3. A SEPARATOR (horizontal line or blank space)
  4. A single CASH-OUT number below the separator

YOUR TASK -- extract ONLY the numbers, column by column:
  * Count every visible player column
  * For each column: sum ALL numbers above the separator = buyin
  * For each column: read the single number below the separator = cashout
  * Use 0 for any value you cannot read

Return ONLY a JSON array (one entry per column, ordered right-to-left):
[{"buyin": 0, "cashout": 0}, ...]

Rules:
- Do NOT include player names
- Return EXACTLY one entry per visible column
- buyin and cashout are positive integers (Israeli shekels)
- Do NOT skip any column
"""

NUMBERS_PROMPT_FOLLOWUP = "Same task -- extract numbers only from this poker sheet."


def _analyze_full_image(raw: bytes) -> list:
    """
    Send full image to Claude with few-shot examples -> extract numbers per column.
    Accuracy improves automatically as saved examples accumulate.
    """
    client, err = _get_anthropic_client()
    if err:
        raise RuntimeError(err)

    # Build few-shot conversation from saved examples
    # Saved results have names; strip them -> numbers only for assistant turns
    examples = _load_examples()[-MAX_FEW_SHOT:]
    messages = []
    for ex in examples:
        numbers_only = [
            {"buyin": e.get("buyin", 0), "cashout": e.get("cashout", 0)}
            for e in ex["result"]
        ]
        prompt_text = NUMBERS_PROMPT if not messages else NUMBERS_PROMPT_FOLLOWUP
        messages.append({"role": "user", "content": [
            {"type": "image", "source": {
                "type": "base64",
                "media_type": ex["mime"],
                "data": ex["image_b64"],
            }},
            {"type": "text", "text": prompt_text},
        ]})
        messages.append({
            "role": "assistant",
            "content": json.dumps(numbers_only, ensure_ascii=False),
        })

    # Actual image
    b64 = base64.standard_b64encode(raw).decode()
    prompt_text = NUMBERS_PROMPT if not examples else NUMBERS_PROMPT_FOLLOWUP
    messages.append({"role": "user", "content": [
        {"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg", "data": b64,
        }},
        {"type": "text", "text": prompt_text},
    ]})

    current_app.logger.info(
        "Sending to Claude with %d few-shot example(s)", len(examples)
    )

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=messages,
    )

    raw_r = resp.content[0].text
    current_app.logger.info("Claude raw (first 400): %s", raw_r[:400])
    return _parse_json_response(raw_r)


# ── DB helper: active players ─────────────────────────────────────────────────

def _active_player_names() -> list:
    """Players who played in the last ACTIVE_DAYS days."""
    try:
        c = get_db_connection()
        cur = c.cursor()
        cur.execute("""
            SELECT DISTINCT p.name FROM players p
            JOIN game_results gr ON gr.player_id = p.id
            JOIN games g ON g.id = gr.game_id
            WHERE g.date >= date('now', ? )
            ORDER BY p.name COLLATE NOCASE
        """, (f"-{ACTIVE_DAYS} days",))
        names = [r["name"] for r in cur.fetchall()]
        c.close()
        return names
    except Exception:
        return []


# ── routes ────────────────────────────────────────────────────────────────────

@bp_upload.route("/upload-photo", methods=["GET"])
@login_required
@role_required("admin", "magician")
def upload_photo():
    players = [{"name": n} for n in _active_player_names()]
    from datetime import date as _date
    example_count = (
        len(list(EXAMPLES_DIR.glob("*_image.jpg"))) if EXAMPLES_DIR.exists() else 0
    )
    return render_template(
        "upload_photo.html",
        players=players,
        today=_date.today().isoformat(),
        current_user=get_current_user(),
        example_count=example_count,
    )


@bp_upload.route("/upload-photo/preprocess", methods=["POST"])
@login_required
@role_required("admin", "magician")
def preprocess_photo():
    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify({"error": "no image"}), 400
    mime = file.content_type or "image/jpeg"
    if mime not in ALLOWED_MIME:
        return jsonify({"error": f"unsupported type: {mime}"}), 400
    raw = file.read()
    if len(raw) > MAX_BYTES:
        return jsonify({"error": "file too large"}), 400
    processed, new_mime = _preprocess_image(raw, mime)
    b64 = base64.standard_b64encode(processed).decode()
    return jsonify({"image_data": f"data:{new_mime};base64,{b64}"})


@bp_upload.route("/upload-photo/analyze", methods=["POST"])
@login_required
@role_required("admin", "magician")
def analyze_photo():
    """Full image -> Claude (with few-shot) -> numbers per column."""
    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify({"error": "no image"}), 400
    mime = file.content_type or "image/jpeg"
    if mime not in ALLOWED_MIME:
        return jsonify({"error": f"unsupported type: {mime}"}), 400
    raw = file.read()
    if len(raw) > MAX_BYTES:
        return jsonify({"error": "file too large (max 20MB)"}), 400

    known_names = _active_player_names()

    rotated_raw, _ = _rotate_only(raw, mime)

    try:
        rows = _analyze_full_image(rotated_raw)
    except Exception as exc:
        current_app.logger.error("Claude Vision error: %s", exc)
        return jsonify({"error": str(exc)}), 500

    if not rows:
        return jsonify({"error": "Claude did not detect columns"}), 422

    players = [
        {
            "name":    "",
            "buyin":   float(r.get("buyin",   0) or 0),
            "cashout": float(r.get("cashout", 0) or 0),
        }
        for r in rows
    ]

    current_app.logger.info("Returning %d rows (examples: %d)", len(players), len(_load_examples()))
    return jsonify({"players": players, "known_names": known_names})


@bp_upload.route("/upload-photo/save-example", methods=["POST"])
@login_required
@role_required("admin", "magician")
def save_example():
    file    = request.files.get("photo")
    entries = request.form.get("entries")
    if not file or not file.filename:
        return jsonify({"error": "no image"}), 400
    if not entries:
        return jsonify({"error": "no entries"}), 400
    try:
        entries_list = json.loads(entries)
    except Exception:
        return jsonify({"error": "invalid entries"}), 400
    mime = file.content_type or "image/jpeg"
    raw  = file.read()
    if len(raw) > MAX_BYTES:
        return jsonify({"error": "file too large"}), 400
    processed, _ = _preprocess_image(raw, mime)
    EXAMPLES_DIR.mkdir(exist_ok=True)
    idx      = _next_example_index()
    img_path = EXAMPLES_DIR / f"{idx:03d}_image.jpg"
    res_path = EXAMPLES_DIR / f"{idx:03d}_result.json"
    img_path.write_bytes(processed)
    res_path.write_text(
        json.dumps(entries_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = len(list(EXAMPLES_DIR.glob("*_image.jpg")))
    current_app.logger.info("Saved example #%d (total=%d)", idx, total)
    return jsonify({"ok": True, "index": idx, "total": total})


@bp_upload.route("/upload-photo/examples", methods=["GET"])
@login_required
@role_required("admin", "magician")
def list_examples():
    EXAMPLES_DIR.mkdir(exist_ok=True)
    examples = []
    for img_path in sorted(EXAMPLES_DIR.glob("*_image.jpg")):
        res_path = img_path.with_name(
            img_path.stem.replace("_image", "_result") + ".json"
        )
        try:
            idx    = int(img_path.stem.split("_")[0])
            result = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else []
            examples.append({"index": idx, "players": len(result)})
        except Exception:
            continue
    return jsonify({"examples": examples})


@bp_upload.route("/upload-photo/examples/<int:idx>", methods=["DELETE"])
@login_required
@role_required("admin", "magician")
def delete_example(idx):
    for p in (
        EXAMPLES_DIR / f"{idx:03d}_image.jpg",
        EXAMPLES_DIR / f"{idx:03d}_result.json",
    ):
        if p.exists():
            p.unlink()
    return jsonify({"ok": True})


@bp_upload.route("/upload-photo/save", methods=["POST"])
@login_required
@role_required("admin", "magician")
def save_photo_results():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "empty body"}), 400
    game_date = data.get("date", "").strip()
    location  = data.get("location", "").strip() or None
    game_type = data.get("game_type", "cash")
    game_id   = data.get("game_id")
    entries   = data.get("entries", [])
    if not game_date:
        return jsonify({"error": "missing date"}), 400
    if not entries:
        return jsonify({"error": "no entries"}), 400

    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        if not game_id:
            cur.execute(
                "INSERT INTO games (date, location, game_type) VALUES (?, ?, ?)",
                (game_date, location, game_type),
            )
            conn.commit()
            game_id = cur.lastrowid

        for entry in entries:
            name    = entry.get("name", "").strip()
            buyin   = float(entry.get("buyin",   0) or 0)
            cashout = float(entry.get("cashout", 0) or 0)
            profit  = cashout - buyin
            if not name:
                continue
            cur.execute(
                "SELECT id FROM players WHERE name = ? COLLATE NOCASE LIMIT 1", (name,)
            )
            row = cur.fetchone()
            if row:
                player_id = row["id"]
            else:
                cur.execute("INSERT INTO players (name) VALUES (?)", (name,))
                conn.commit()
                player_id = cur.lastrowid
            cur.execute(
                """INSERT INTO game_results (game_id, player_id, buyin, cashout, profit)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(game_id, player_id)
                   DO UPDATE SET buyin=excluded.buyin,
                                 cashout=excluded.cashout,
                                 profit=excluded.profit""",
                (game_id, player_id, buyin, cashout, profit),
            )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        current_app.logger.error("save error: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        conn.close()

    log_activity("save_from_photo", f"משחק {game_id}")
    return jsonify({"ok": True, "game_id": game_id})
