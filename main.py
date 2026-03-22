from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# =========================================================
# 設定
# =========================================================
DATABASE_URL = "sqlite:///./app.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

app = FastAPI(title="Bijo Gacha Quest API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番は絞る
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# DBモデル
# =========================================================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    display_name = Column(String(255), default="")
    points = Column(Integer, default=0)
    exp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    free_draw_count = Column(Integer, default=1)
    max_rarity = Column(String(16), default="N")
    created_at = Column(DateTime, default=datetime.utcnow)

    works = relationship("OwnedCard", back_populates="user", cascade="all, delete-orphan")


class Work(Base):
    __tablename__ = "works"

    id = Column(Integer, primary_key=True)
    creator_user_id = Column(String(64), nullable=False, index=True)
    creator_name = Column(String(255), default="")
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    genre = Column(String(255), default="")
    type = Column(String(16), default="image")  # image / video
    image_url = Column(Text, default="")
    video_url = Column(Text, default="")
    thumbnail_url = Column(Text, default="")
    link_url = Column(Text, default="")
    rarity = Column(String(16), default="N")
    hp = Column(Integer, default=10)
    atk = Column(Integer, default=10)
    defense = Column(Integer, default=10)
    spd = Column(Integer, default=10)
    luk = Column(Integer, default=10)
    draw_count = Column(Integer, default=0)
    like_count = Column(Integer, default=0)
    exp_reward = Column(Integer, default=5)
    is_active = Column(Integer, default=1)
    is_official = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class OwnedCard(Base):
    __tablename__ = "owned_cards"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), ForeignKey("users.user_id"), nullable=False, index=True)
    work_id = Column(Integer, ForeignKey("works.id"), nullable=False, index=True)
    rarity = Column(String(16), default="N")
    level = Column(Integer, default=1)
    exp = Column(Integer, default=0)
    hp = Column(Integer, default=10)
    atk = Column(Integer, default=10)
    defense = Column(Integer, default=10)
    spd = Column(Integer, default=10)
    luk = Column(Integer, default=10)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="works")
    work = relationship("Work")

    __table_args__ = (
        UniqueConstraint("user_id", "work_id", "created_at", name="uq_owned_card_instance"),
    )


class GachaLog(Base):
    __tablename__ = "gacha_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    work_id = Column(Integer, nullable=False, index=True)
    draw_type = Column(String(16), default="free")  # free / paid
    created_at = Column(DateTime, default=datetime.utcnow)


class LikeLog(Base):
    __tablename__ = "like_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    work_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "work_id", name="uq_like_once"),
    )


class BattleQueue(Base):
    __tablename__ = "battle_queue"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    owned_card_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class BattleLog(Base):
    __tablename__ = "battle_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    opponent_user_id = Column(String(64), default="")
    result = Column(String(16), default="lose")  # win / lose / draw
    log_text = Column(Text, default="")
    reward_exp = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class PointPurchaseRequest(Base):
    __tablename__ = "point_purchase_requests"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    requested_points = Column(Integer, nullable=False)
    status = Column(String(32), default="pending")  # pending / approved / rejected
    created_at = Column(DateTime, default=datetime.utcnow)


# =========================================================
# Pydantic
# =========================================================
class LoginRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=255)


class LikeRequest(BaseModel):
    user_id: str
    work_id: int


class BattleEntryRequest(BaseModel):
    user_id: str
    work_id: int


class PointRequestIn(BaseModel):
    user_id: str
    points: int = Field(..., gt=0)


class AdXpRequest(BaseModel):
    user_id: str


# =========================================================
# ユーティリティ
# =========================================================
RARITY_ORDER = ["N", "R", "SR", "SSR", "UR"]


def rarity_rank(r: str) -> int:
    try:
        return RARITY_ORDER.index(r)
    except ValueError:
        return 0


def update_user_level(user: User) -> None:
    new_level = max(1, 1 + user.exp // 100)
    user.level = new_level


def update_user_max_rarity(user: User, rarity: str) -> None:
    if rarity_rank(rarity) > rarity_rank(user.max_rarity):
        user.max_rarity = rarity


def serialize_work(work: Work) -> dict:
    media_url = work.video_url if work.type == "video" else work.image_url
    return {
        "id": work.id,
        "creator_user_id": work.creator_user_id,
        "creator_name": work.creator_name,
        "title": work.title,
        "description": work.description,
        "genre": work.genre,
        "type": work.type,
        "image_url": work.image_url,
        "video_url": work.video_url,
        "thumbnail_url": work.thumbnail_url,
        "link_url": work.link_url,
        "media_url": media_url,
        "rarity": work.rarity,
        "hp": work.hp,
        "atk": work.atk,
        "def": work.defense,
        "spd": work.spd,
        "luk": work.luk,
        "draw_count": work.draw_count,
        "likes": work.like_count,
        "exp_reward": work.exp_reward,
        "comment": work.description,
    }


def serialize_owned_card(owned: OwnedCard) -> dict:
    work = owned.work
    return {
        "id": owned.id,
        "work_id": work.id,
        "title": work.title,
        "creator_name": work.creator_name,
        "type": work.type,
        "image_url": work.image_url,
        "video_url": work.video_url,
        "media_url": work.video_url if work.type == "video" else work.image_url,
        "thumbnail_url": work.thumbnail_url or work.image_url,
        "rarity": owned.rarity,
        "hp": owned.hp,
        "atk": owned.atk,
        "def": owned.defense,
        "spd": owned.spd,
        "luk": owned.luk,
        "level": owned.level,
        "exp": owned.exp,
        "created_at": owned.created_at.isoformat(),
    }


def ensure_user(db, user_id: str) -> User:
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが存在しません")
    return user


def get_owned_card_for_work(db, user_id: str, work_id: int) -> Optional[OwnedCard]:
    return (
        db.query(OwnedCard)
        .join(Work, Work.id == OwnedCard.work_id)
        .filter(OwnedCard.user_id == user_id, OwnedCard.work_id == work_id)
        .order_by(OwnedCard.created_at.desc())
        .first()
    )


def calc_card_status(work: Work, user_level: int, official_bonus: bool = False) -> dict:
    level_bonus = max(0, user_level - 1)
    official_extra = 3 if official_bonus else 0

    hp = work.hp + random.randint(0, 6) + level_bonus + official_extra
    atk = work.atk + random.randint(0, 6) + math.floor(level_bonus / 2) + official_extra
    defense = work.defense + random.randint(0, 6) + math.floor(level_bonus / 2) + official_extra
    spd = work.spd + random.randint(0, 4)
    luk = work.luk + random.randint(0, 4)

    return {
        "hp": hp,
        "atk": atk,
        "defense": defense,
        "spd": spd,
        "luk": luk,
    }


def weighted_draw(db, user: User) -> Work:
    works = db.query(Work).filter(Work.is_active == 1).all()
    if not works:
        raise HTTPException(status_code=400, detail="排出対象の作品がありません")

    level = user.level

    weights_by_rarity = {
        "N": max(55 - level, 20),
        "R": 25 + min(level, 10),
        "SR": min(10 + level, 25),
        "SSR": min(3 + level // 3, 12),
        "UR": min(1 + level // 10, 4),
    }

    pool = []
    for work in works:
        weight = weights_by_rarity.get(work.rarity, 10)
        if work.is_official:
            weight += 5
        pool.append((work, max(weight, 1)))

    total = sum(weight for _, weight in pool)
    roll = random.randint(1, total)
    current = 0
    for work, weight in pool:
        current += weight
        if roll <= current:
            return work

    return random.choice(works)


def create_owned_card(db, user: User, work: Work) -> OwnedCard:
    params = calc_card_status(work, user.level, official_bonus=bool(work.is_official))
    owned = OwnedCard(
        user_id=user.user_id,
        work_id=work.id,
        rarity=work.rarity,
        level=1,
        exp=0,
        hp=params["hp"],
        atk=params["atk"],
        defense=params["defense"],
        spd=params["spd"],
        luk=params["luk"],
    )
    db.add(owned)

    work.draw_count += 1
    user.exp += work.exp_reward
    update_user_level(user)
    update_user_max_rarity(user, work.rarity)

    return owned


def battle_formula(card_a: OwnedCard, card_b: OwnedCard) -> tuple[str, str, int, int]:
    score_a = (
        card_a.hp * 0.30
        + card_a.atk * 1.25
        + card_a.defense * 0.95
        + card_a.spd * 0.75
        + card_a.luk * 0.55
        + random.randint(0, 15)
    )
    score_b = (
        card_b.hp * 0.30
        + card_b.atk * 1.25
        + card_b.defense * 0.95
        + card_b.spd * 0.75
        + card_b.luk * 0.55
        + random.randint(0, 15)
    )

    if abs(score_a - score_b) < 4:
        result = "draw"
        log = f"接戦の末に引き分け。 A={score_a:.1f} / B={score_b:.1f}"
        exp_a = 5
        exp_b = 5
    elif score_a > score_b:
        result = "win"
        log = f"攻撃と総合力で上回り勝利。 A={score_a:.1f} / B={score_b:.1f}"
        exp_a = 15
        exp_b = 5
    else:
        result = "lose"
        log = f"相手の総合力が上回り敗北。 A={score_a:.1f} / B={score_b:.1f}"
        exp_a = 5
        exp_b = 15

    return result, log, exp_a, exp_b


def grant_creator_reward(db, work: Work) -> None:
    creator = db.query(User).filter(User.user_id == work.creator_user_id).first()
    if creator:
        creator.points += 10


def seed_data() -> None:
    db = SessionLocal()
    try:
        if db.query(Work).count() > 0:
            return

        sample_users = [
            User(user_id="admin", password="admin123", display_name="運営", points=1000, free_draw_count=999),
            User(user_id="creator1", password="1234", display_name="投稿者1", points=0, free_draw_count=1),
            User(user_id="creator2", password="1234", display_name="投稿者2", points=0, free_draw_count=1),
        ]
        db.add_all(sample_users)
        db.flush()

        sample_works = [
            Work(
                creator_user_id="creator1",
                creator_name="投稿者1",
                title="月下の魔導姫",
                description="銀髪の二次元美少女イラスト",
                genre="ファンタジー",
                type="image",
                image_url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
                thumbnail_url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
                link_url="https://example.com/creator1",
                rarity="N",
                hp=18, atk=12, defense=11, spd=10, luk=8,
                exp_reward=8,
            ),
            Work(
                creator_user_id="creator1",
                creator_name="投稿者1",
                title="深紅の踊り子",
                description="華やかな二次元キャラ",
                genre="和風",
                type="image",
                image_url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
                thumbnail_url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
                link_url="https://example.com/creator1",
                rarity="R",
                hp=20, atk=16, defense=12, spd=15, luk=10,
                exp_reward=10,
            ),
            Work(
                creator_user_id="creator2",
                creator_name="投稿者2",
                title="電脳天使ユリナ",
                description="近未来系の二次元動画カード",
                genre="SF",
                type="video",
                video_url="https://www.w3schools.com/html/mov_bbb.mp4",
                thumbnail_url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
                link_url="https://example.com/creator2",
                rarity="SR",
                hp=22, atk=20, defense=16, spd=18, luk=12,
                exp_reward=15,
            ),
            Work(
                creator_user_id="admin",
                creator_name="運営",
                title="運営限定・白銀神姫",
                description="運営カード。経験値ボーナス対象。",
                genre="限定",
                type="image",
                image_url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
                thumbnail_url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
                link_url="https://example.com/admin",
                rarity="SSR",
                hp=28, atk=26, defense=22, spd=18, luk=16,
                exp_reward=25,
                is_official=1,
            ),
        ]
        db.add_all(sample_works)
        db.commit()
    finally:
        db.close()


# =========================================================
# 起動時
# =========================================================
Base.metadata.create_all(bind=engine)
seed_data()

# =========================================================
# API
# =========================================================
@app.get("/")
def root():
    return {"message": "Bijo Gacha Quest API running"}


@app.post("/auth/login")
def auth_login(payload: LoginRequest):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == payload.user_id).first()
        if user:
            if user.password != payload.password:
                raise HTTPException(status_code=401, detail="パスワードが違います")
        else:
            user = User(
                user_id=payload.user_id,
                password=payload.password,
                display_name=payload.user_id,
                points=0,
                exp=0,
                level=1,
                free_draw_count=1,
                max_rarity="N",
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "points": user.points,
            "exp": user.exp,
            "level": user.level,
            "free_draw_count": user.free_draw_count,
            "max_rarity": user.max_rarity,
        }
    finally:
        db.close()


@app.get("/users/{user_id}")
def get_user(user_id: str):
    db = SessionLocal()
    try:
        user = ensure_user(db, user_id)
        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "points": user.points,
            "exp": user.exp,
            "level": user.level,
            "free_draw_count": user.free_draw_count,
            "max_rarity": user.max_rarity,
            "created_at": user.created_at.isoformat(),
        }
    finally:
        db.close()


@app.post("/gacha/free/{user_id}")
def gacha_free(user_id: str):
    db = SessionLocal()
    try:
        user = ensure_user(db, user_id)

        if user.free_draw_count <= 0:
            raise HTTPException(status_code=400, detail="無料ガチャ回数がありません")

        work = weighted_draw(db, user)
        create_owned_card(db, user, work)
        user.free_draw_count -= 1

        db.add(GachaLog(user_id=user.user_id, work_id=work.id, draw_type="free"))
        db.commit()

        return {
            "message": "無料ガチャ完了",
            "result": serialize_work(work),
            "user": {
                "user_id": user.user_id,
                "points": user.points,
                "exp": user.exp,
                "level": user.level,
                "free_draw_count": user.free_draw_count,
                "max_rarity": user.max_rarity,
            },
        }
    finally:
        db.close()


@app.post("/gacha/paid/{user_id}")
def gacha_paid(user_id: str):
    db = SessionLocal()
    try:
        user = ensure_user(db, user_id)

        cost = 30
        if user.points < cost:
            raise HTTPException(status_code=400, detail="ポイント不足です")

        work = weighted_draw(db, user)
        create_owned_card(db, user, work)

        user.points -= cost
        grant_creator_reward(db, work)

        db.add(GachaLog(user_id=user.user_id, work_id=work.id, draw_type="paid"))
        db.commit()

        return {
            "message": "ポイントガチャ完了",
            "result": serialize_work(work),
            "user": {
                "user_id": user.user_id,
                "points": user.points,
                "exp": user.exp,
                "level": user.level,
                "free_draw_count": user.free_draw_count,
                "max_rarity": user.max_rarity,
            },
        }
    finally:
        db.close()


@app.post("/works/{work_id}/like")
def like_work(work_id: int, payload: LikeRequest):
    db = SessionLocal()
    try:
        ensure_user(db, payload.user_id)
        work = db.query(Work).filter(Work.id == work_id, Work.is_active == 1).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品がありません")

        exists = (
            db.query(LikeLog)
            .filter(LikeLog.user_id == payload.user_id, LikeLog.work_id == work_id)
            .first()
        )
        if exists:
            return {"message": "すでにいいね済みです", "likes": work.like_count}

        db.add(LikeLog(user_id=payload.user_id, work_id=work_id))
        work.like_count += 1
        db.commit()

        return {"message": "いいねしました", "likes": work.like_count}
    finally:
        db.close()


@app.get("/users/{user_id}/works")
def get_user_works(user_id: str):
    db = SessionLocal()
    try:
        ensure_user(db, user_id)

        rows = (
            db.query(OwnedCard)
            .join(Work, Work.id == OwnedCard.work_id)
            .filter(OwnedCard.user_id == user_id)
            .order_by(OwnedCard.created_at.desc())
            .all()
        )
        return {"works": [serialize_owned_card(row) for row in rows]}
    finally:
        db.close()


@app.post("/battle/entry")
def battle_entry(payload: BattleEntryRequest):
    db = SessionLocal()
    try:
        user = ensure_user(db, payload.user_id)

        owned = get_owned_card_for_work(db, payload.user_id, payload.work_id)
        if not owned:
            raise HTTPException(status_code=404, detail="そのカードを所持していません")

        waiting = (
            db.query(BattleQueue)
            .filter(BattleQueue.user_id != payload.user_id)
            .order_by(BattleQueue.created_at.asc())
            .first()
        )

        if not waiting:
            db.add(BattleQueue(user_id=payload.user_id, owned_card_id=owned.id))
            db.commit()
            return {"message": "対戦待機に入りました。次の参加者とバトルします。"}

        opponent_queue = waiting
        opponent_owned = db.query(OwnedCard).filter(OwnedCard.id == opponent_queue.owned_card_id).first()
        if not opponent_owned:
            db.delete(opponent_queue)
            db.commit()
            return {"message": "対戦相手の待機データが壊れていたため、再度参加してください"}

        result_for_user, log_text, exp_user, exp_opponent = battle_formula(owned, opponent_owned)

        if result_for_user == "win":
            result_for_opponent = "lose"
        elif result_for_user == "lose":
            result_for_opponent = "win"
        else:
            result_for_opponent = "draw"

        owned.exp += exp_user
        opponent_owned.exp += exp_opponent

        while owned.exp >= 30:
            owned.exp -= 30
            owned.level += 1
            owned.hp += 2
            owned.atk += 2
            owned.defense += 2

        while opponent_owned.exp >= 30:
            opponent_owned.exp -= 30
            opponent_owned.level += 1
            opponent_owned.hp += 2
            opponent_owned.atk += 2
            opponent_owned.defense += 2

        user.exp += exp_user
        update_user_level(user)

        opponent_user = db.query(User).filter(User.user_id == opponent_owned.user_id).first()
        if opponent_user:
            opponent_user.exp += exp_opponent
            update_user_level(opponent_user)

        db.add(
            BattleLog(
                user_id=payload.user_id,
                opponent_user_id=opponent_owned.user_id,
                result=result_for_user,
                log_text=log_text,
                reward_exp=exp_user,
            )
        )
        db.add(
            BattleLog(
                user_id=opponent_owned.user_id,
                opponent_user_id=payload.user_id,
                result=result_for_opponent,
                log_text=log_text,
                reward_exp=exp_opponent,
            )
        )

        db.delete(opponent_queue)
        db.commit()

        return {
            "message": "バトルが完了しました",
            "result": result_for_user,
            "log": log_text,
            "reward_exp": exp_user,
        }
    finally:
        db.close()


@app.get("/battle/logs/{user_id}")
def get_battle_logs(user_id: str):
    db = SessionLocal()
    try:
        ensure_user(db, user_id)

        rows = (
            db.query(BattleLog)
            .filter(BattleLog.user_id == user_id)
            .order_by(BattleLog.created_at.desc())
            .limit(50)
            .all()
        )

        return {
            "logs": [
                {
                    "id": row.id,
                    "opponent_id": row.opponent_user_id,
                    "opponent_name": row.opponent_user_id,
                    "result": row.result,
                    "log": row.log_text,
                    "reward_exp": row.reward_exp,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
        }
    finally:
        db.close()


@app.post("/points/request")
def request_points(payload: PointRequestIn):
    db = SessionLocal()
    try:
        ensure_user(db, payload.user_id)

        db.add(
            PointPurchaseRequest(
                user_id=payload.user_id,
                requested_points=payload.points,
                status="pending",
            )
        )
        db.commit()

        return {
            "message": f"{payload.points}pt の購入申請を受け付けました。PayPay確認後に手動付与してください。"
        }
    finally:
        db.close()


@app.post("/admin/points/add/{user_id}")
def admin_add_points(user_id: str, points: int):
    db = SessionLocal()
    try:
        user = ensure_user(db, user_id)
        if points <= 0:
            raise HTTPException(status_code=400, detail="加算ポイントは1以上にしてください")

        user.points += points
        db.commit()

        return {
            "message": f"{user.user_id} に {points}pt 追加しました",
            "points": user.points,
        }
    finally:
        db.close()


@app.post("/admin/free-draw/add/{user_id}")
def admin_add_free_draw(user_id: str, count: int = 1):
    db = SessionLocal()
    try:
        user = ensure_user(db, user_id)
        if count <= 0:
            raise HTTPException(status_code=400, detail="加算回数は1以上にしてください")

        user.free_draw_count += count
        db.commit()

        return {
            "message": f"{user.user_id} に無料ガチャ {count} 回追加しました",
            "free_draw_count": user.free_draw_count,
        }
    finally:
        db.close()


@app.post("/rewards/ad-xp")
def reward_ad_xp(payload: AdXpRequest):
    db = SessionLocal()
    try:
        user = ensure_user(db, payload.user_id)
        reward = 20
        user.exp += reward
        update_user_level(user)
        db.commit()

        return {
            "message": f"広告報酬でEXP {reward} を付与しました",
            "exp": user.exp,
            "level": user.level,
        }
    finally:
        db.close()


@app.get("/works")
def get_works():
    db = SessionLocal()
    try:
        rows = (
            db.query(Work)
            .filter(Work.is_active == 1)
            .order_by(Work.created_at.desc())
            .all()
        )
        return {"works": [serialize_work(w) for w in rows]}
    finally:
        db.close()


@app.post("/admin/works/create")
def admin_create_work(data: dict):
    db = SessionLocal()
    try:
        required = ["creator_user_id", "creator_name", "title", "type"]
        for key in required:
            if key not in data:
                raise HTTPException(status_code=400, detail=f"{key} が必要です")

        creator = db.query(User).filter(User.user_id == data["creator_user_id"]).first()
        if not creator:
            raise HTTPException(status_code=404, detail="creator_user_id のユーザーが存在しません")

        work = Work(
            creator_user_id=data["creator_user_id"],
            creator_name=data.get("creator_name", ""),
            title=data["title"],
            description=data.get("description", ""),
            genre=data.get("genre", ""),
            type=data.get("type", "image"),
            image_url=data.get("image_url", ""),
            video_url=data.get("video_url", ""),
            thumbnail_url=data.get("thumbnail_url", ""),
            link_url=data.get("link_url", ""),
            rarity=data.get("rarity", "N"),
            hp=int(data.get("hp", 10)),
            atk=int(data.get("atk", 10)),
            defense=int(data.get("defense", 10)),
            spd=int(data.get("spd", 10)),
            luk=int(data.get("luk", 10)),
            exp_reward=int(data.get("exp_reward", 5)),
            is_active=int(data.get("is_active", 1)),
            is_official=int(data.get("is_official", 0)),
        )
        db.add(work)
        db.commit()
        db.refresh(work)

        # 投稿者特典: 無料ガチャ1回
        creator.free_draw_count += 1
        db.commit()

        return {
            "message": "作品を登録しました。投稿者に無料ガチャ1回を付与しました。",
            "work": serialize_work(work),
            "creator_free_draw_count": creator.free_draw_count,
        }
    finally:
        db.close()


@app.get("/admin/point-requests")
def admin_point_requests():
    db = SessionLocal()
    try:
        rows = (
            db.query(PointPurchaseRequest)
            .order_by(PointPurchaseRequest.created_at.desc())
            .all()
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "requested_points": row.requested_points,
                    "status": row.status,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
        }
    finally:
        db.close()
