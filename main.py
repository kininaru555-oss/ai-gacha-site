"""
main_thin_router.py — 薄いルーター専用 main.py（完全版）

変更方針:
1. 独自 get_db / init_db / seed_data を main.py から排除
2. 独自 helper 群を main.py から排除
3. database / security / helpers / routers を import して使うだけにする
4. main.py には app生成 / CORS / router登録 / startup初期化 だけを残す
5. 旧 password / def / SQLite 前提処理を main.py から排除
6. /users/me / gacha / market / works / battle は各 router 側を正とする

前提:
- 以下の“正本”ファイルを、実プロジェクト側で通常の import 名に配置すること
  - database_final_unified_defense.py   -> database.py
  - security_final_aligned.py           -> security.py
  - helpers_gacha_integrated.py         -> helpers.py
  - models_aligned_v2.py                -> models.py
  - battle_fixed_unified_defense.py     -> routers/battle.py
  - gacha_pg_aligned.py                 -> routers/gacha.py
  - works_aligned_v3.py                 -> routers/works.py
  - market_aligned_v3.py                -> routers/market.py
  - creators (必要なら)                  -> routers/creators.py
  - payments.py                         -> routers/payments.py
  - me.py                               -> routers/me.py
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routers.battle import router as battle_router
from routers.gacha import router as gacha_router
from routers.market import router as market_router
from routers.works import router as works_router
from routers.auth import router as auth_router

# 任意ルーター（存在する場合のみ有効化したいなら try/except にしてもよい）
from routers.creators import router as creators_router
from routers.payments import router as payments_router
from routers.me import router as me_router


APP_TITLE = os.getenv("APP_TITLE", "Bijo Gacha Quest API")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
ALLOW_ORIGINS_RAW = os.getenv("ALLOW_ORIGINS", "*")
ALLOW_ORIGINS = [x.strip() for x in ALLOW_ORIGINS_RAW.split(",") if x.strip()] or ["*"]

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
    )

  

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOW_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup() -> None:
        logger.info("Initializing database...")
        init_db()
        logger.info("Database initialized.")

    @app.get("/")
    def root() -> dict[str, str]:
        return {"message": f"{APP_TITLE} running"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # ルーター登録
    app.include_router(gacha_router)
    app.include_router(works_router)
    app.include_router(market_router)
    app.include_router(battle_router)
    app.include_router(creators_router)
    app.include_router(payments_router)
    app.include_router(me_router)
    app.include_router(auth_router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main_thin_router:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
