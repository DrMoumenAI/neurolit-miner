import os
import sys

# Ensure src is importable as module path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Import the Flask app object from src/app.py
from app import app

if __name__ == "__main__":
    # Run development server
    app.run(host="127.0.0.1", port=5000, debug=True)
