# PokerApp — תיעוד למחלון הבא

## פרויקט
אפליקציית Flask לניהול משחקי פוקר קאש, RTL עברית, SQLite, Fly.io.

## מצב נכון להיום (16.5.2026)

### Git
- **HEAD מקומי + GitHub**: `d58850d1f16680f6d0c7566f3b8b965150438ca7`
- **פרומוד ב-Fly.io**: עדיין ב-`b8736532` (צריך `fly deploy`)
- **שלב ג' בתהליך** — יש uncommitted changes (upload-photo feature)

### בעיה ידועה בגיט
- `.git/index` פגום (bad signature) — לא ניתן להריץ `git add/commit` ישירות
- עקיפה: `GIT_INDEX_FILE=/tmp/newidx` + `git read-tree HEAD` + `git update-index --add FILE` + `git write-tree` + `git commit-tree` + כתיבה ידנית ל-`.git/refs/heads/main`
- `.git/index.lock` ו-`.git/HEAD.lock` נעולים ולא ניתן למחוק מהסנדבוקס

### בעיה ידועה בסנדבוקס
- `Write` tool כותב דרך Windows mount — לפעמים ה-mtime לא מתעדכן ו-Python טוען `.pyc` ישן
- עקיפה: לכתוב קבצי Python קריטיים דרך bash (`cat > file.py << 'EOF'`)
- לאחר שינוי ב-`app.py`: חובה לקמפל מחדש: `python3 -c "import py_compile; py_compile.compile('src/pokerapp/app.py', cfile='src/pokerapp/__pycache__/app.cpython-310.pyc', doraise=True)"`

### Stack
- Python 3.12 (Fly.io) / 3.10 (sandbox — עקיפה: `datetime.UTC = datetime.timezone.utc`)
- Flask 3.1.2, Flask-WTF, gunicorn
- Volume Fly.io מ-mount ב-`/data` — DB_PATH חייב להצביע שם בפרודקשן
- `PYTHONPATH=/code/src` ב-Dockerfile

## קבצים קריטיים

| קובץ | מה יש בו |
|------|-----------|
| `src/pokerapp/app.py` | create_app(), filters, error handler — **נוטה להתקצר בגיט!** |
| `src/pokerapp/routes/main.py` | ~1967 שורות, 25 routes כולל /calculator |
| `src/pokerapp/routes/auth.py` | login, logout, change_password |
| `src/pokerapp/routes/upload_photo.py` | **חדש!** blueprint עם 3 routes: GET /upload-photo, POST /upload-photo/analyze, POST /upload-photo/save |
| `src/pokerapp/db/init_db.py` | init_db() + _run_migrations() (מיגרציה רצה רק אם קובץ קיים) |
| `src/pokerapp/db/connection.py` | get_db_connection(), log_admin_action(), ensure_admin_audit_log_table() |
| `src/pokerapp/db/schema.sql` | כולל `private_stats INTEGER NOT NULL DEFAULT 0` בטבלת users |
| `src/pokerapp/templates/stats.html` | 657 שורות, עיצוב חדש |
| `src/pokerapp/templates/calculator.html` | עמוד מחשבון סיכויים (Monte Carlo) |
| `src/pokerapp/templates/upload_photo.html` | **חדש!** עמוד העלאת תמונה + עריכה + שמירה |

## שלבי פיתוח

### שלב א' — בסיס
משחקים, שחקנים, auth, DB

### שלב ב' (commit 526af3b) ✅
סטטיסטיקות, תשתית multi-table, game_results, admin

### שלב ג' (commit d58850d → בתהליך) 
- ✅ עמוד מחשבון פוקר (`/calculator`, Monte Carlo simulation)
- ✅ עיצוב מחדש של עמוד סטטיסטיקות (`stats.html` 657 שורות)
- ✅ שיפורי UI שונים
- ✅ תמיכה בפרטיות סטטיסטיקות (`private_stats`)
- ✅ admin_audit_log table
- ✅ **הזנת תוצאות מצילום** (`/upload-photo`) — Claude Vision API, עריכה לפני שמירה
- ⏳ **`fly deploy` עדיין לא בוצע** — צריך commit + push + deploy

## תמרורי אזהרה
- `app.py` קוצר פעמים רבות בגיט — לאחר כל קומיט לבדוק: `tail -5 src/pokerapp/app.py` חייב להסתיים ב-`return app`
- `requirements.txt` מקודד UTF-16 — בסדר, pip תומך. הוספנו `anthropic>=0.40.0`
- `scripts/migrate_phase_b.py` לא בגיט → לא רץ בפרודקשן (בכוונה)
- `connection.py` משתמש ב-`datetime.UTC` — Python 3.11+ בלבד (בסדר ב-Fly.io)
- ב-Fly.io צריך להגדיר `ANTHROPIC_API_KEY` כ-secret: `fly secrets set ANTHROPIC_API_KEY=sk-ant-...`

## פקודות שימושיות

```bash
# בדיקת startup מקומית (sandbox)
python3 -c "
import sys, datetime, os, tempfile
sys.path.insert(0, 'src')
datetime.UTC = datetime.timezone.utc
tf = __import__('tempfile').NamedTemporaryFile(suffix='.db', delete=False)
tf.close()
os.environ['DB_PATH'] = tf.name
from pokerapp.app import create_app
app = create_app()
print('OK - routes:', len(list(app.url_map.iter_rules())))
"

# recompile app.py pyc אחרי כל שינוי (בגלל mtime issue)
python3 -c "import py_compile; py_compile.compile('src/pokerapp/app.py', cfile='src/pokerapp/__pycache__/app.cpython-310.pyc', doraise=True)"

# קומיט עם GIT_INDEX_FILE (עקיפת index פגום)
TMPIDX=/tmp/cidx_$(date +%s%N)
export GIT_INDEX_FILE=$TMPIDX
git read-tree HEAD 2>/dev/null
git update-index --add PATH/TO/FILE 2>/dev/null
TREE=$(git write-tree 2>/dev/null)
PARENT=$(cat .git/refs/heads/main)
COMMIT=$(GIT_AUTHOR_NAME="Ran Keydar" GIT_AUTHOR_EMAIL="bentuvim@gmail.com" \
  GIT_COMMITTER_NAME="Ran Keydar" GIT_COMMITTER_EMAIL="bentuvim@gmail.com" \
  git commit-tree "$TREE" -p "$PARENT" -m "MESSAGE" 2>/dev/null)
echo "$COMMIT" > .git/refs/heads/main
# לאחר מכן: git push origin main (מהטרמינל של Windows)
```

## הגדרת ANTHROPIC_API_KEY בפרודקשן
```bash
fly secrets set ANTHROPIC_API_KEY=sk-ant-YOUR-KEY-HERE
```

## מה נשאר לשלב ג'
- [ ] פתקים/הערות פרטיות לשחקן במשחק (player_notes table)
- [ ] תובנות AI לשחקן (Claude API + cache)
- [ ] אנדרואיד / iOS (שלב עתידי)
