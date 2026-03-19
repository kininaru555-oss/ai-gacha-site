import csv
import io

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI()

CSV_URL = "ここに公開したCSVのURLを入れる"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/sales")
def get_sales():
    response = requests.get(CSV_URL, timeout=10)
    response.raise_for_status()

    text_data = response.text
    reader = csv.DictReader(io.StringIO(text_data))

    items = []
    for row in reader:
        items.append(
            {
                "timestamp": row.get("タイムスタンプ", ""),
                "author": row.get("作者名", ""),
                "title": row.get("作品タイトル", ""),
                "image_url": row.get("作品画像URL", ""),
                "video_url": row.get("作品動画URL（任意）", ""),
                "genre": row.get("ジャンル", ""),
                "rarity": row.get("レアリティ（自己評価）", ""),
                "price": row.get("販売価格（円）", ""),
                "right_type": row.get("販売権利タイプ", ""),
                "gacha": row.get("ガチャ掲載", ""),
                "commercial_use": row.get("商用利用", ""),
                "agreed": row.get("規約同意", ""),
            }
        )

    return JSONResponse(content={"items": items})