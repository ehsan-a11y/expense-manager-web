from flask import Flask, request, jsonify, render_template
import sqlite3
import os
import pandas as pd
from werkzeug.utils import secure_filename

app = Flask(__name__)

# On Vercel, only /tmp is writable; locally use the project directory
if os.environ.get("VERCEL"):
    DB_PATH = "/tmp/expenses.db"
    UPLOAD_FOLDER = "/tmp/uploads"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "expenses.db")
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------------------
# DATABASE INITIALIZATION
# ---------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT,
            type TEXT,
            amount REAL,
            category TEXT,
            account TEXT,
            note TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------------------
# ROUTES
# ---------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/records", methods=["GET"])
def get_records():
    date_from = request.args.get("date_from", "All")
    date_to = request.args.get("date_to", "All")
    categories = request.args.getlist("categories")

    query = "SELECT time, type, amount, category, account, note FROM expenses WHERE 1=1"
    params = []

    if date_from != "All" and date_to != "All":
        query += " AND DATE(time) BETWEEN DATE(?) AND DATE(?)"
        params.extend([date_from, date_to])
    if categories:
        placeholders = ",".join("?" * len(categories))
        query += f" AND category IN ({placeholders})"
        params.extend(categories)

    query += " ORDER BY time DESC"

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route("/api/filters", methods=["GET"])
def get_filters():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT category FROM expenses ORDER BY category")
    categories = [r[0] for r in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT DATE(time) FROM expenses ORDER BY time DESC")
    dates = [r[0] for r in cursor.fetchall()]

    conn.close()
    return jsonify({"categories": categories, "dates": dates})

@app.route("/api/record", methods=["POST"])
def add_record():
    data = request.json
    required = ["time", "type", "amount", "category", "account", "note"]
    missing = [f for f in required if not str(data.get(f, "")).strip()]
    if missing:
        return jsonify({"success": False, "error": f"Missing fields: {', '.join(missing)}"}), 400
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO expenses (time, type, amount, category, account, note)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (data["time"], data["type"], float(data["amount"]),
              data["category"], data["account"], data["note"]))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/record", methods=["DELETE"])
def delete_record():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM expenses
        WHERE time=? AND type=? AND amount=? AND category=? AND account=? AND note=?
    """, (data["time"], data["type"], data["amount"], data["category"], data["account"], data["note"]))
    conn.commit()
    deleted = cursor.rowcount
    conn.close()
    if deleted:
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Record not found"}), 404

@app.route("/api/import", methods=["POST"])
def import_excel():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    try:
        df = pd.read_excel(filepath)
        required_cols = ["Time", "Type", "Amount", "Category", "Account", "Note"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            return jsonify({"success": False, "error": f"Missing columns: {', '.join(missing)}"}), 400

        conn = get_db()
        cursor = conn.cursor()
        count = 0
        for _, row in df.iterrows():
            cursor.execute("""
                INSERT INTO expenses (time, type, amount, category, account, note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(row["Time"]), str(row["Type"]), float(row["Amount"]),
                  str(row["Category"]), str(row["Account"]), str(row["Note"])))
            count += 1
        conn.commit()
        conn.close()
        return jsonify({"success": True, "imported": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        os.remove(filepath)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
