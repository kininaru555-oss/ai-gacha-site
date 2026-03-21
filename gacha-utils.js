import {
  jackpotEl,
  rarityEl,
  stage
} from "./gacha-dom.js";
import { state } from "./gacha-state.js";

function getWorkId(work) {
  return String(work?.content_id ?? work?.id ?? "").trim();
}

export function normalizeRarity(r) {
  if (!r) return "N";

  const v = String(r).toUpperCase().trim();

  if (v === "SSR") return "SSR";
  if (v === "SR") return "SR";
  if (v === "R" || v === "RARE") return "R";
  return "N";
}

export function isNewWork(work) {
  const id = getWorkId(work);
  if (!id) return false;
  return !state.ownershipMap[id];
}

export function isBuybackTarget(work) {
  return Number(work?.buyback_price || 0) > 0;
}

export function isOperatorPick(work) {
  return String(work?.featured_type || "").trim() === "operator_pick";
}

export function getHitType(work) {
  if (Boolean(work?.got_distribution_right)) return "new";
  if (isNewWork(work)) return "new";
  if (isBuybackTarget(work)) return "buyback";
  if (isOperatorPick(work)) return "pickup";

  const rarity = normalizeRarity(work?.rarity);
  if (rarity === "SSR" || rarity === "SR" || rarity === "R") {
    return "rare";
  }

  return "normal";
}

export function getRevealDelayMs(work) {
  const hitType = getHitType(work);

  if (hitType === "new") return 1400;
  if (hitType === "buyback") return 1300;
  if (hitType === "pickup") return 1200;
  if (hitType === "rare") return 1050;
  return 850;
}

export function getJackpotMessage(work) {
  if (Boolean(work?.got_distribution_right)) {
    return "🎉 二次流通権を獲得しました！";
  }

  if (isNewWork(work)) {
    return "🎉 未出品作品候補です！";
  }

  if (isBuybackTarget(work)) {
    return `🎉 高価還元対象！${Number(work?.buyback_price || 0)}ポイントバック対象です`;
  }

  if (isOperatorPick(work)) {
    return "⭐ 運営特選作品を引きました！";
  }

  const rarity = normalizeRarity(work?.rarity);

  if (rarity === "SSR") return "🌈 特別作品を引きました！";
  if (rarity === "SR") return "✨ 注目作品を引きました！";
  if (rarity === "R") return "💎 レア作品を引きました！";
  return "";
}

export function optimizeCloudinary(url) {
  if (!url) return "";

  if (url.includes("res.cloudinary.com") && !url.includes("f_auto")) {
    return url.replace("/upload/", "/upload/f_auto,q_auto/");
  }

  return url;
}

export function getMediaType(work) {
  const type = String(work?.type || "").trim();

  if (type === "video" || type === "動画") return "video";
  if (type === "image" || type === "画像") return "image";
  if (work?.video_url || work?.videoUrl || work?.video) return "video";

  return "image";
}

export function getMediaUrl(work) {
  const mediaType = getMediaType(work);

  if (mediaType === "video") {
    return optimizeCloudinary(
      work?.video_url || work?.videoUrl || work?.video || work?.file || ""
    );
  }

  return optimizeCloudinary(
    work?.image_url || work?.imageUrl || work?.image || work?.thumbnail_url || work?.file || ""
  );
}

export function clearStageHitClasses() {
  if (!stage) return;

  stage.classList.remove(
    "rare",
    "ssr",
    "hit-new",
    "hit-buyback",
    "hit-pickup",
    "reveal-delay"
  );
}

export function clearJackpotClasses() {
  if (!jackpotEl) return;

  jackpotEl.classList.remove(
    "jackpot-new",
    "jackpot-buyback",
    "jackpot-pickup"
  );
}

export function setRarityStyle(rarityText) {
  if (!rarityEl || !stage) return;

  const r = normalizeRarity(rarityText);

  stage.classList.remove("rare", "ssr");
  rarityEl.textContent = r;

  if (r === "SSR") {
    rarityEl.style.background = "#d4af37";
    rarityEl.style.color = "#111";
    stage.classList.add("ssr");
  } else if (r === "SR" || r === "R") {
    rarityEl.style.background = "#7b61ff";
    rarityEl.style.color = "#fff";
    stage.classList.add("rare");
  } else {
    rarityEl.style.background = "#444";
    rarityEl.style.color = "#fff";
  }
}

export function applyHitVisuals(work) {
  const hitType = getHitType(work);

  clearStageHitClasses();
  clearJackpotClasses();

  if (!stage) return;

  if (hitType === "new") {
    stage.classList.add("ssr", "hit-new");
    if (jackpotEl) jackpotEl.classList.add("jackpot-new");
    return;
  }

  if (hitType === "buyback") {
    stage.classList.add("ssr", "hit-buyback");
    if (jackpotEl) jackpotEl.classList.add("jackpot-buyback");
    return;
  }

  if (hitType === "pickup") {
    stage.classList.add("rare", "hit-pickup");
    if (jackpotEl) jackpotEl.classList.add("jackpot-pickup");
    return;
  }

  setRarityStyle(work?.rarity);
}

export function resetMedia() {
  // index画面では結果表示を直接持たない設計にしたため、
  // ここでは何もしない
}

export function formatExpireDate(isoText) {
  if (!isoText) return "";

  try {
    const dt = new Date(isoText);
    if (Number.isNaN(dt.getTime())) return "";
    return dt.toLocaleDateString("ja-JP");
  } catch {
    return "";
  }
}
