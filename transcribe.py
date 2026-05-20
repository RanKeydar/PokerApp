"""
הרצה מהטרמינל:
  set OPENAI_API_KEY=sk-...
  python transcribe.py "נתיב\לקובץ\האודיו.mp4"

התוצאה תישמר ב-transcription.txt באותה תיקייה.
"""
import sys
import os

def main():
    if len(sys.argv) < 2:
        print("שימוש: python transcribe.py <נתיב לקובץ אודיו>")
        sys.exit(1)

    audio_path = sys.argv[1]
    if not os.path.exists(audio_path):
        print(f"קובץ לא נמצא: {audio_path}")
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("שגיאה: OPENAI_API_KEY לא מוגדר.")
        print("הרץ:  set OPENAI_API_KEY=sk-...")
        sys.exit(1)

    try:
        from openai import OpenAI
    except ImportError:
        print("מתקין openai...")
        os.system(f"{sys.executable} -m pip install openai -q")
        from openai import OpenAI

    client = OpenAI(api_key=api_key)

    print(f"שולח ל-Whisper: {os.path.basename(audio_path)}")
    print("ממתין לתמלול (בדרך כלל 30-60 שניות)...")

    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="he",
            response_format="verbose_json",   # כולל timestamps
            timestamp_granularities=["segment"]
        )

    # שמירה לקובץ טקסט
    out_path = os.path.splitext(audio_path)[0] + "_transcription.txt"

    with open(out_path, "w", encoding="utf-8") as out:
        out.write(f"קובץ מקור: {os.path.basename(audio_path)}\n")
        out.write(f"שפה: {getattr(response, 'language', 'he')}\n")
        out.write(f"משך: {getattr(response, 'duration', '?')} שניות\n")
        out.write("=" * 60 + "\n\n")

        # פלט עם timestamps לכל segment
        for seg in response.segments:
            start = int(seg.start)
            m, s = divmod(start, 60)
            h, m = divmod(m, 60)
            ts = f"[{h:02d}:{m:02d}:{s:02d}]"
            out.write(f"{ts} {seg.text.strip()}\n")

        out.write("\n" + "=" * 60 + "\n")
        out.write("טקסט מלא:\n\n")
        out.write(response.text)

    print(f"\n✅ הושלם! הקובץ נשמר ב:\n   {out_path}")
    print(f"\nתצוגה מקדימה (10 שורות ראשונות):")
    print("-" * 40)
    with open(out_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 13: break
            print(line, end="")

if __name__ == "__main__":
    main()
