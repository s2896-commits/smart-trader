import sqlite3
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "trades.db")

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        asset_type TEXT,
        entry_price REAL,
        exit_price REAL,
        entry_time TEXT,
        exit_time TEXT,
        reason TEXT,
        status TEXT,
        pnl REAL DEFAULT 0.0,
        lesson TEXT
    )''')
    conn.commit()
    conn.close()

def log_trade(symbol, asset_type, price, reason):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO trades (symbol, asset_type, entry_price, entry_time, reason, status) VALUES (?, ?, ?, ?, ?, 'OPEN')",
              (symbol, asset_type, round(price, 4), now, reason))
    conn.commit()
    conn.close()

def update_open_trades(current_prices):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE status = 'OPEN'")
    open_trades = [dict(r) for r in c.fetchall()]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for t in open_trades:
        sym = t['symbol']
        if sym in current_prices:
            curr = current_prices[sym]
            entry = t['entry_price']
            change_pct = ((curr - entry) / entry) * 100
            live_pnl = round((curr - entry) * 10, 2)

            if change_pct >= 1.5:
                lesson = "دخول موفق: السيولة العالية دعمت استمرار الصعود للهدف (+1.5%)."
                c.execute("UPDATE trades SET exit_price=?, exit_time=?, status='WON', pnl=?, lesson=? WHERE id=?",
                          (round(curr, 4), now, live_pnl, lesson, t['id']))
            elif change_pct <= -1.0:
                lesson = "تفعيل وقف الخسارة (-1%): حماية المحفظة من تراجع السعر."
                c.execute("UPDATE trades SET exit_price=?, exit_time=?, status='LOST', pnl=?, lesson=? WHERE id=?",
                          (round(curr, 4), now, live_pnl, lesson, t['id']))
            else:
                lesson = f"السعر الحالي: {round(curr, 4)}$ ({change_pct:+.2f}%) | الهدف: +1.5%"
                c.execute("UPDATE trades SET pnl=?, lesson=? WHERE id=?",
                          (live_pnl, lesson, t['id']))
    conn.commit()
    conn.close()

def get_all_trades():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trades ORDER BY id DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

init_db()
