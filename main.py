from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sqlite3
import random
from datetime import datetime

app = FastAPI()
DB = "app.db"

# =========================
# DB
# =========================

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init():
    c = db()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        user_id TEXT PRIMARY KEY,
        points INTEGER DEFAULT 0,
        exp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS works(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        creator_id TEXT,
        image_url TEXT,
        rarity TEXT,
        hp INTEGER,
        atk INTEGER,
        def INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ownership(
        work_id INTEGER PRIMARY KEY,
        owner_id TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS offers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id INTEGER,
        from_user TEXT,
        to_user TEXT,
        points INTEGER,
        status TEXT DEFAULT 'pending'
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS market(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id INTEGER,
        seller TEXT,
        price INTEGER
    )
    """)

    c.commit()
    c.close()

init()

# =========================
# Models
# =========================

class Offer(BaseModel):
    from_user_id: str
    to_user_id: str
    work_id: int
    offer_points: int

class MarketList(BaseModel):
    user_id: str
    work_id: int
    price_points: int

class Buy(BaseModel):
    buyer_user_id: str
    listing_id: int

# =========================
# ユーザー
# =========================

@app.post("/user/create/{user_id}")
def create(user_id: str):
    c = db()
    cur = c.cursor()
    cur.execute("INSERT OR IGNORE INTO users(user_id,points) VALUES(?,100)", (user_id,))
    c.commit()
    return {"ok": True}

@app.get("/users/{user_id}")
def get_user(user_id: str):
    cur = db().cursor()
    u = cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return dict(u)

# =========================
# ガチャ
# =========================

@app.post("/gacha/{user_id}")
def gacha(user_id: str):
    c = db()
    cur = c.cursor()

    work = cur.execute("SELECT * FROM works ORDER BY RANDOM() LIMIT 1").fetchone()

    own = cur.execute("SELECT * FROM ownership WHERE work_id=?", (work["id"],)).fetchone()

    if not own:
        cur.execute("INSERT INTO ownership VALUES(?,?)", (work["id"], user_id))
        exp = 20
        is_new = True
    else:
        exp = 5
        is_new = False

    cur.execute("UPDATE users SET exp = exp + ? WHERE user_id=?", (exp, user_id))
    c.commit()

    return {
        "result": dict(work),
        "info": {
            "is_new_owner": is_new,
            "exp_gained": exp,
            "owner_user_id": own["owner_id"] if own else user_id
        }
    }

# =========================
# オファー
# =========================

@app.post("/offers")
def send_offer(o: Offer):
    c = db()
    cur = c.cursor()

    cur.execute("""
    INSERT INTO offers(work_id,from_user,to_user,points)
    VALUES(?,?,?,?)
    """, (o.work_id, o.from_user_id, o.to_user_id, o.offer_points))

    c.commit()
    return {"message": "オファー送信"}

@app.get("/offers/inbox/{user_id}")
def inbox(user_id: str):
    cur = db().cursor()
    data = cur.execute("SELECT * FROM offers WHERE to_user=? AND status='pending'", (user_id,)).fetchall()
    return [dict(x) for x in data]

@app.post("/offers/{id}/accept")
def accept(id: int):
    c = db()
    cur = c.cursor()

    offer = cur.execute("SELECT * FROM offers WHERE id=?", (id,)).fetchone()

    if not offer:
        raise HTTPException(404)

    # 分配
    total = offer["points"]
    fee = int(total * 0.3)
    remain = total - fee
    half = remain // 2

    # 所有者
    cur.execute("UPDATE users SET points = points + ? WHERE user_id=?", (half, offer["to_user"]))

    # 作者
    work = cur.execute("SELECT creator_id FROM works WHERE id=?", (offer["work_id"],)).fetchone()
    cur.execute("UPDATE users SET points = points + ? WHERE user_id=?", (half, work["creator_id"]))

    # 所有移転
    cur.execute("UPDATE ownership SET owner_id=? WHERE work_id=?", (offer["from_user"], offer["work_id"]))

    cur.execute("UPDATE offers SET status='accepted' WHERE id=?", (id,))

    c.commit()
    return {"message": "成立"}

@app.post("/offers/{id}/reject")
def reject(id: int):
    db().cursor().execute("UPDATE offers SET status='rejected' WHERE id=?", (id,))
    db().commit()
    return {"ok": True}

# =========================
# マーケット
# =========================

@app.post("/market/list")
def list_item(m: MarketList):
    db().cursor().execute(
        "INSERT INTO market(work_id,seller,price) VALUES(?,?,?)",
        (m.work_id, m.user_id, m.price_points)
    )
    db().commit()
    return {"ok": True}

@app.get("/market/listings")
def listings():
    cur = db().cursor()
    rows = cur.execute("""
    SELECT market.id, works.title, market.price, works.image_url
    FROM market
    JOIN works ON works.id = market.work_id
    """).fetchall()
    return [dict(x) for x in rows]

@app.post("/market/buy")
def buy(b: Buy):
    c = db()
    cur = c.cursor()

    item = cur.execute("SELECT * FROM market WHERE id=?", (b.listing_id,)).fetchone()

    if not item:
        raise HTTPException(404)

    price = item["price"]

    # 分配
    fee = int(price * 0.3)
    remain = price - fee
    half = remain // 2

    # 所有者
    cur.execute("UPDATE users SET points=points+? WHERE user_id=?", (half, item["seller"]))

    # 作者
    creator = cur.execute("SELECT creator_id FROM works WHERE id=?", (item["work_id"],)).fetchone()
    cur.execute("UPDATE users SET points=points+? WHERE user_id=?", (half, creator["creator_id"]))

    # 所有移転
    cur.execute("UPDATE ownership SET owner_id=? WHERE work_id=?", (b.buyer_user_id, item["work_id"]))

    cur.execute("DELETE FROM market WHERE id=?", (b.listing_id,))
    c.commit()

    return {"message": "購入成功"}

# =========================
# 所有作品
# =========================

@app.get("/users/{user_id}/works")
def myworks(user_id: str):
    cur = db().cursor()

    rows = cur.execute("""
    SELECT works.*
    FROM works
    JOIN ownership ON works.id = ownership.work_id
    WHERE ownership.owner_id=?
    """, (user_id,)).fetchall()

    return [dict(x) for x in rows]
