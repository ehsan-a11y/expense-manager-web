from flask import Flask, request, jsonify, render_template
import sqlite3
import os
import pandas as pd
from werkzeug.utils import secure_filename

app = Flask(__name__)

if os.environ.get("VERCEL"):
    DB_PATH = "/tmp/expenses.db"
    UPLOAD_FOLDER = "/tmp/uploads"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "expenses.db")
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PRESET_COLORS = ["#6c63ff","#00d4aa","#ff6b6b","#ffa94d","#51cf66",
                 "#339af0","#f06595","#cc5de8","#20c997","#fd7e14"]

# ---------------------------
# DATABASE INITIALIZATION
# ---------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT, type TEXT, amount REAL,
        category TEXT, account TEXT, note TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        color TEXT DEFAULT '#6c63ff'
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        type TEXT DEFAULT 'Cash',
        icon TEXT DEFAULT '💳'
    )""")

    # Seed categories/accounts from existing expense data if tables empty
    c.execute("SELECT COUNT(*) FROM categories")
    if c.fetchone()[0] == 0:
        c.execute("SELECT DISTINCT category FROM expenses WHERE category IS NOT NULL AND category != ''")
        for i, (cat,) in enumerate(c.fetchall()):
            c.execute("INSERT OR IGNORE INTO categories (name, color) VALUES (?, ?)",
                      (cat, PRESET_COLORS[i % len(PRESET_COLORS)]))

    c.execute("SELECT COUNT(*) FROM accounts")
    if c.fetchone()[0] == 0:
        c.execute("SELECT DISTINCT account FROM expenses WHERE account IS NOT NULL AND account != ''")
        for (acc,) in c.fetchall():
            c.execute("INSERT OR IGNORE INTO accounts (name) VALUES (?)", (acc,))

    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------------------
# MAIN PAGE
# ---------------------------
@app.route("/")
def index():
    return render_template("index.html")

# ---------------------------
# RECORDS
# ---------------------------
@app.route("/api/records", methods=["GET"])
def get_records():
    date_from  = request.args.get("date_from", "All")
    date_to    = request.args.get("date_to",   "All")
    categories = request.args.getlist("categories")

    query  = "SELECT time, type, amount, category, account, note FROM expenses WHERE 1=1"
    params = []

    if date_from != "All" and date_to != "All":
        query += " AND DATE(time) BETWEEN DATE(?) AND DATE(?)"
        params.extend([date_from, date_to])
    if categories:
        query += f" AND category IN ({','.join('?'*len(categories))})"
        params.extend(categories)

    query += " ORDER BY time DESC"
    conn = get_db()
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    return jsonify(rows)

@app.route("/api/filters", methods=["GET"])
def get_filters():
    conn = get_db()
    cats  = [r[0] for r in conn.execute("SELECT DISTINCT category FROM expenses ORDER BY category").fetchall()]
    dates = [r[0] for r in conn.execute("SELECT DISTINCT DATE(time) FROM expenses ORDER BY time DESC").fetchall()]
    conn.close()
    return jsonify({"categories": cats, "dates": dates})

@app.route("/api/record", methods=["POST"])
def add_record():
    data = request.json
    for f in ["time", "type", "amount", "category", "account"]:
        if not str(data.get(f, "")).strip():
            return jsonify({"success": False, "error": f"'{f}' is required"}), 400
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO expenses (time,type,amount,category,account,note) VALUES (?,?,?,?,?,?)",
            (data["time"], data["type"], float(data["amount"]),
             data["category"], data["account"], data.get("note", ""))
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/record", methods=["DELETE"])
def delete_record():
    d = request.json
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM expenses WHERE time=? AND type=? AND amount=? AND category=? AND account=? AND note=?",
        (d["time"], d["type"], d["amount"], d["category"], d["account"], d["note"])
    )
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return jsonify({"success": bool(deleted)}) if deleted else (jsonify({"success": False, "error": "Not found"}), 404)

# ---------------------------
# IMPORT (xlsx / xls / csv)
# ---------------------------
@app.route("/api/import", methods=["POST"])
def import_file():
    if "file" not in request.files or request.files["file"].filename == "":
        return jsonify({"success": False, "error": "No file provided"}), 400

    file     = request.files["file"]
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    try:
        ext = filename.rsplit(".", 1)[-1].lower()
        df  = pd.read_csv(filepath) if ext == "csv" else pd.read_excel(filepath)

        required = ["Time", "Type", "Amount", "Category", "Account", "Note"]
        missing  = [c for c in required if c not in df.columns]
        if missing:
            return jsonify({"success": False, "error": f"Missing columns: {', '.join(missing)}"}), 400

        conn  = get_db()
        count = 0
        for _, row in df.iterrows():
            conn.execute(
                "INSERT INTO expenses (time,type,amount,category,account,note) VALUES (?,?,?,?,?,?)",
                (str(row["Time"]), str(row["Type"]), float(row["Amount"]),
                 str(row["Category"]), str(row["Account"]), str(row.get("Note", "")))
            )
            count += 1
        conn.commit()
        conn.close()
        return jsonify({"success": True, "imported": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

# ---------------------------
# CATEGORIES
# ---------------------------
@app.route("/api/categories", methods=["GET"])
def get_categories():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT id,name,color FROM categories ORDER BY name").fetchall()]
    conn.close()
    return jsonify(rows)

@app.route("/api/categories", methods=["POST"])
def add_category():
    data  = request.json
    name  = data.get("name", "").strip()
    color = data.get("color", "#6c63ff")
    if not name:
        return jsonify({"success": False, "error": "Name required"}), 400
    try:
        conn = get_db()
        cur  = conn.execute("INSERT INTO categories (name,color) VALUES (?,?)", (name, color))
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return jsonify({"success": True, "id": new_id})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "Category already exists"}), 400

@app.route("/api/categories/<int:cat_id>", methods=["DELETE"])
def delete_category(cat_id):
    conn = get_db()
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ---------------------------
# ACCOUNTS
# ---------------------------
@app.route("/api/accounts", methods=["GET"])
def get_accounts():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT id,name,type,icon FROM accounts ORDER BY name").fetchall()]
    conn.close()
    return jsonify(rows)

@app.route("/api/accounts", methods=["POST"])
def add_account():
    data = request.json
    name = data.get("name", "").strip()
    atype = data.get("type", "Cash")
    icon  = data.get("icon", "💳")
    if not name:
        return jsonify({"success": False, "error": "Name required"}), 400
    try:
        conn   = get_db()
        cur    = conn.execute("INSERT INTO accounts (name,type,icon) VALUES (?,?,?)", (name, atype, icon))
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return jsonify({"success": True, "id": new_id})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "Account already exists"}), 400

@app.route("/api/accounts/<int:acc_id>", methods=["DELETE"])
def delete_account(acc_id):
    conn = get_db()
    conn.execute("DELETE FROM accounts WHERE id=?", (acc_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
