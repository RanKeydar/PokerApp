import csv
import io
import re
from datetime import datetime

import pandas as pd


def _norm_name(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value.lower()


def _read_csv_hebrew(path: str) -> pd.DataFrame:
    with open(path, "rb") as f:
        raw = f.read()

    for encoding in ("utf-8-sig", "utf-8", "cp1255", "cp1252", "latin1"):
        try:
            text = raw.decode(encoding)
            break
        except Exception:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    try:
        return pd.read_csv(io.StringIO(text))
    except Exception:
        return pd.read_csv(io.StringIO(text), engine="python")


def _parse_date_to_iso(value: str) -> str | None:
    s = str(value or "").strip()
    if not s or s.lower() == "nan":
        return None

    formats = [
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d/%m/%y",
        "%d.%m.%y",
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass

    try:
        dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.date().isoformat()
    except Exception:
        return None