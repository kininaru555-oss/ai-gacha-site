from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import requests
from PIL import Image, ImageFilter, ImageStat


@dataclass
class GeneratedStats:
    hp: int
    atk: int
    defense: int
    spd: int
    luk: int
    score_detail: Dict[str, float]


KEYWORD_RULES = {
    "hp": {
        "天使": 6, "姫": 5, "神": 7, "聖": 5, "癒し": 4, "花": 3,
        "森": 2, "月": 2, "光": 3
    },
    "atk": {
        "炎": 7, "剣": 6, "戦": 6, "魔王": 6, "竜": 5, "雷": 5,
        "爆": 6, "紅": 4, "深淵": 4
    },
    "defense": {
        "盾": 7, "鎧": 7, "城": 5, "要塞": 8, "闇": 4, "黒": 3,
        "鋼": 6
    },
    "spd": {
        "風": 7, "雷": 6, "電脳": 7, "忍": 7, "瞬": 6, "流": 4,
        "羽": 3
    },
    "luk": {
        "奇跡": 8, "夢": 5, "虹": 6, "星": 5, "月": 3, "運命": 7,
        "秘宝": 6
    },
}


def clamp_stat(value: float, min_value: int = 5, max_value: int = 99) -> int:
    return max(min_value, min(max_value, int(round(value))))


def fetch_image(image_url: str, timeout: int = 20) -> Image.Image:
    res = requests.get(image_url, timeout=timeout)
    res.raise_for_status()
    img = Image.open(io.BytesIO(res.content)).convert("RGB")
    return img


def normalize(value: float, src_min: float, src_max: float, dst_min: float = 0.0, dst_max: float = 1.0) -> float:
    if src_max - src_min == 0:
      return dst_min
    ratio = (value - src_min) / (src_max - src_min)
    ratio = max(0.0, min(1.0, ratio))
    return dst_min + ratio * (dst_max - dst_min)


def compute_image_features(img: Image.Image) -> Dict[str, float]:
    img_small = img.resize((256, 256))
    arr = np.asarray(img_small).astype(np.float32) / 255.0

    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]

    brightness = float(arr.mean())
    contrast = float(arr.std())

    # 彩度近似: RGB平均との差
    rgb_mean = arr.mean(axis=2, keepdims=True)
    saturation_like = float(np.abs(arr - rgb_mean).mean())

    red_bias = float((r - (g + b) / 2.0).mean())
    blue_bias = float((b - (r + g) / 2.0).mean())
    dark_ratio = float((arr.mean(axis=2) < 0.25).mean())
    bright_ratio = float((arr.mean(axis=2) > 0.75).mean())

    gray = img_small.convert("L")
    gray_arr = np.asarray(gray).astype(np.float32) / 255.0

    # エッジ量
    edge_img = gray.filter(ImageFilter.FIND_EDGES)
    edge_arr = np.asarray(edge_img).astype(np.float32) / 255.0
    edge_strength = float(edge_arr.mean())

    # シャープさ
    sharpness = float(np.abs(np.diff(gray_arr, axis=0)).mean() + np.abs(np.diff(gray_arr, axis=1)).mean())

    return {
        "brightness": brightness,
        "contrast": contrast,
        "saturation_like": saturation_like,
        "red_bias": red_bias,
        "blue_bias": blue_bias,
        "dark_ratio": dark_ratio,
        "bright_ratio": bright_ratio,
        "edge_strength": edge_strength,
        "sharpness": sharpness,
    }


def apply_keyword_bonus(base_stats: Dict[str, float], text: str) -> Dict[str, float]:
    result = dict(base_stats)
    joined = text or ""

    for stat_name, rules in KEYWORD_RULES.items():
        for keyword, bonus in rules.items():
            if keyword in joined:
                result[stat_name] += bonus

    return result


def generate_stats_from_features(features: Dict[str, float]) -> Dict[str, float]:
    brightness = features["brightness"]
    contrast = features["contrast"]
    saturation_like = features["saturation_like"]
    red_bias = features["red_bias"]
    blue_bias = features["blue_bias"]
    dark_ratio = features["dark_ratio"]
    bright_ratio = features["bright_ratio"]
    edge_strength = features["edge_strength"]
    sharpness = features["sharpness"]

    # ベース 20 + 補正
    hp = (
        20
        + normalize(brightness, 0.2, 0.9, 0, 20)
        + normalize(bright_ratio, 0.0, 0.7, 0, 10)
        + normalize(contrast, 0.05, 0.35, 0, 8)
    )

    atk = (
        20
        + normalize(red_bias, -0.2, 0.2, 0, 18)
        + normalize(contrast, 0.05, 0.35, 0, 12)
        + normalize(saturation_like, 0.02, 0.25, 0, 10)
    )

    defense = (
        20
        + normalize(dark_ratio, 0.0, 0.8, 0, 18)
        + normalize(blue_bias, -0.2, 0.2, 0, 12)
        + normalize(edge_strength, 0.01, 0.18, 0, 8)
    )

    spd = (
        20
        + normalize(edge_strength, 0.01, 0.18, 0, 18)
        + normalize(sharpness, 0.005, 0.25, 0, 14)
        + normalize(contrast, 0.05, 0.35, 0, 6)
    )

    luk = (
        20
        + normalize(saturation_like, 0.02, 0.25, 0, 14)
        + normalize(bright_ratio, 0.0, 0.7, 0, 8)
        + np.random.randint(0, 10)
    )

    return {
        "hp": hp,
        "atk": atk,
        "defense": defense,
        "spd": spd,
        "luk": luk,
    }

# 合計値をある程度固定するバージョン（おすすめ）
def generate_stats_from_features(features: Dict[str, float]) -> Dict[str, float]:
    # ... 既存の計算 ...

    raw = {
        "hp": hp,
        "atk": atk,
        "defense": defense,
        "spd": spd,
        "luk": luk,
    }

    # 合計を300前後に正規化（ランダム±30で変化を付ける）
    total_raw = sum(raw.values())
    target_total = 300 + np.random.randint(-30, 31)
    scale = target_total / total_raw if total_raw > 0 else 1.0

    final = {k: v * scale for k, v in raw.items()}

    # さらに微ランダム
    for k in final:
        final[k] += np.random.uniform(-4, 4)

    return final


# 二次元イラスト向け追加特徴量（オプション）
def compute_extra_features(img: Image.Image, features: Dict) -> Dict:
    # 顔検出簡易版（中央上部が明るい＝顔が大きい？）
    h, w = img.size[1], img.size[0]
    face_area = img.crop((w//4, h//6, w*3//4, h*2//3))
    face_bright = np.asarray(face_area.convert("L")).mean() / 255.0

    # 色相分布（ピンク/紫多め＝かわいい系？）
    hsv = np.asarray(img.convert("HSV")).astype(float)
    hue_mean = hsv[:,:,0].mean()  # 0〜179

    return {
        **features,
        "face_ratio_brightness": face_bright,
        "hue_mean": hue_mean,
    }


# キーワードを増やした例（抜粋）
KEYWORD_RULES["hp"].update({
    "ロリ": -8, "幼": -6, "ちび": -5,        # HP低め
    "爆乳": 4, "巨乳": 3, "おっぱい": 3,      # HP高め（耐久イメージ）
    "清楚": 5, "お嬢様": 5,
})

KEYWORD_RULES["atk"].update({
    "ロリ": -10, "弱そう": -7,
    "筋肉": 8, "マッチョ": 7, "戦士": 6,
})


def generate_auto_stats(
    image_url: str,
    title: str = "",
    description: str = "",
    genre: str = "",
) -> GeneratedStats:
    img = fetch_image(image_url)
    features = compute_image_features(img)

    base_stats = generate_stats_from_features(features)
    text = f"{title} {description} {genre}"
    final_stats = apply_keyword_bonus(base_stats, text)

    return GeneratedStats(
        hp=clamp_stat(final_stats["hp"]),
        atk=clamp_stat(final_stats["atk"]),
        defense=clamp_stat(final_stats["defense"]),
        spd=clamp_stat(final_stats["spd"]),
        luk=clamp_stat(final_stats["luk"]),
        score_detail=features,
    )


if __name__ == "__main__":
    # 動作確認例
    url = "https://res.cloudinary.com/demo/image/upload/sample.jpg"
    stats = generate_auto_stats(
        image_url=url,
        title="月下の魔導姫",
        description="銀髪の幻想的な二次元美少女",
        genre="ファンタジー"
    )
    print(stats)
