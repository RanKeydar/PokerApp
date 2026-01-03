import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from pokerapp.app import create_app

app = create_app()

# תיקון cache - העלה גרסה
app.config['STATIC_VER'] = 2

if __name__ == "__main__":
    app.run(debug=True)
