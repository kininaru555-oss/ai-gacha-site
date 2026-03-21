import { API_BASE, DRAW_COST } from "./gacha-config.js";
import { fetchAvailableMachine, fetchMachineStatusRows } from "./gacha-api.js";
import { getOrCreateUserId, isPosterFreeUser, state } from "./gacha-state.js";

const drawButton = document.getElementById("drawButton");
const stage = document.getElementById("stage");
const placeholder = document.getElementById("placeholder");
const resultImage = document.getElementById("resultImage");
const resultVideo = document.getElementById("resultVideo");
const mypageBtn = document.getElementById("mypageBtn");
const ticketInfo = document.getElementById("ticketInfo");
const machineStatusBox = document.getElementById("machineStatusBox");
const listingArea = document.getElementById("listingArea");
const listToMachineBtn = document.getElementById("listToMachineBtn");
const listingMessage = document.getElementById("listingMessage");
const listingFullBox = document.getElementById("listingFullBox");
const latestWorksBox = document.getElementById("latestWorks");
const titleEl = document.getElementById("title");
const creatorEl = document.getElementById("creator");
const genreEl = document.getElementById("genre");
const descriptionEl = document.getElementById("description");
const mediaTypeEl = document.getElementById("mediaType");
const statusEl = document.getElementById("status");
const buybackPriceEl = document.getElementById("buybackPrice");
const featuredTypeEl = document.getElementById("featuredType");
const rarityEl = document.getElementById("rarity");

const jackpotEl = document.createElement("div");
jackpotEl.id = "jackpot";
jackpotEl.style.display = "none";
jackpotEl.style.color = "gold";
jackpotEl.style.fontWeight = "bold";
jackpotEl.style.marginTop = "10px";
if (document.getElementById("meta")) {
  document.getElementById("meta").appendChild(jackpotEl);
}

export function initMypageLink() {
  const userId = getOrCreateUserId();
  if (mypageBtn) {
    mypageBtn.href = `${API_BASE}/mypage/${encodeURIComponent(userId)}`;
  }
}

export function normalizeRarity(r) {
  if (!r) return "N";
  const v = String(r).toUpperCase().trim();
  if (v === "SSR") return "SSR";
  if (v === "SR") return "SR";
  if (v === "R" || v === "RARE") return "R";
  return "N";
}

export function getWorkId(work) {
  return work.id || (
    (work.title || "") + "_" +
    (work.creator || "") + "_" +
    (work.file || "")
  );
}

export function isNewWork(work) {
  const id = String(work.id ?? "");
  return !state.ownershipMap[id];
}

export function isBuybackTarget(work) {
  return Number(work.buyback_price || 0) > 0;
}

export function isOperatorPick(work) {
  return String(work.featured_type || "").trim() === "operator_pick";
}

export function getHitType(work) {
  if (isNewWork(work)) return "new";
  if (isBuybackTarget(work)) return "buyback";
  if (isOperatorPick(work)) return "pickup";

  const rarity = normalizeRarity(work.rarity);
  if (rarity === "SSR" || rarity === "SR" || rarity === "R") return "rare";

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

function getJackpotMessage(work) {
  if (isNewWork(work)) {
    return "🎉 未出品作品！自販機出品権を獲得！";
  }
  if (isBuybackTarget(work)) {
    return `🎉 高価還元対象！${Number(work.buyback_price || 0)}ポイントバック対象です`;
  }
  if (isOperatorPick(work)) {
    return "⭐ 運営特選作品を引きました！";
  }

  const rarity = normalizeRarity(work.rarity);
  if (rarity === "SSR") return "🌈 特別作品を引きました！";
  if (rarity === "SR") return "✨ 注目作品を引きました！";
  if (rarity === "R") return "💎 レア作品を引きました！";
  return "";
}

function optimizeCloudinary(url) {
  if (!url) return "";
  if (url.includes("res.cloudinary.com") && !url.includes("f_auto")) {
    return url.replace("/upload/", "/upload/f_auto,q_auto/");
  }
  return url;
}

function getMediaType(work) {
  const type = String(work.type || "").trim();
  if (type === "video" || type === "動画") return "video";
  if (type === "image" || type === "画像") return "image";
  if (work.videoUrl) return "video";
  return "image";
}

function getMediaUrl(work) {
  const mediaType = getMediaType(work);
  if (mediaType === "video") {
    return optimizeCloudinary(work.videoUrl || work.file || "");
  }
  return optimizeCloudinary(work.imageUrl || work.file || "");
}

function clearStageHitClasses() {
  if (!stage) return;
  stage.classList.remove("rare", "ssr", "hit-new", "hit-buyback", "hit-pickup", "reveal-delay");
}

function clearJackpotClasses() {
  jackpotEl.classList.remove("jackpot-new", "jackpot-buyback", "jackpot-pickup");
}

function setRarityStyle(rarityText) {
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

function applyHitVisuals(work) {
  const hitType = getHitType(work);

  clearStageHitClasses();
  clearJackpotClasses();

  if (!stage) return;

  if (hitType === "new") {
    stage.classList.add("ssr", "hit-new");
    jackpotEl.classList.add("jackpot-new");
    return;
  }
  if (hitType === "buyback") {
    stage.classList.add("ssr", "hit-buyback");
    jackpotEl.classList.add("jackpot-buyback");
    return;
  }
  if (hitType === "pickup") {
    stage.classList.add("rare", "hit-pickup");
    jackpotEl.classList.add("jackpot-pickup");
    return;
  }

  setRarityStyle(work.rarity);
}

function resetMedia() {
  if (resultImage) {
    resultImage.style.display = "none";
    resultImage.removeAttribute("src");
  }
  if (resultVideo) {
    resultVideo.style.display = "none";
    resultVideo.pause();
    resultVideo.removeAttribute("src");
    resultVideo.load();
  }
}

function formatExpireDate(isoText) {
  if (!isoText) return "";
  try {
    const dt = new Date(isoText);
    if (Number.isNaN(dt.getTime())) return "";
    return dt.toLocaleDateString("ja-JP");
  } catch {
    return "";
  }
}

export function updateTicket() {
  if (!ticketInfo) return;

  if (isPosterFreeUser()) {
    ticketInfo.textContent = "投稿者モード：無料でガチャを引けます";
    return;
  }

  const expireText = formatExpireDate(state.currentPointExpireAt);
  ticketInfo.textContent =
    `所持ポイント：${state.currentUserPoints}pt / 1回 ${DRAW_COST}pt` +
    (expireText ? ` / 有効期限 ${expireText}` : "");
}

export function renderLatestWorks() {
  if (!latestWorksBox) return;

  if (!state.works.length) {
    latestWorksBox.innerHTML = "<strong>新着作品</strong><br>まだ作品がありません";
    return;
  }

  const latest = [...state.works].slice(-3).reverse();
  latestWorksBox.innerHTML = `
    <strong>新着作品</strong><br>
    ${latest.map((work) => {
      const creator = work.creator || "投稿者";
      const genre = work.genre || "AI作品";
      const rarity = normalizeRarity(work.rarity);
      return `・${creator} / ${genre} / ${rarity}`;
    }).join("<br>")}
  `;
}

export async function renderMachineStatus() {
  if (!machineStatusBox) return;

  try {
    const rows = await fetchMachineStatusRows();

    if (!rows.length) {
      machineStatusBox.innerHTML = "<strong>有料自販機の空き状況</strong><br>現在表示できる自販機情報がありません";
      return;
    }

    machineStatusBox.innerHTML = `
      <strong>有料自販機の空き状況</strong><br>
      ${rows.map((row) =>
        `・${row.name}：${row.currentCount} / 30` +
        (row.remainingSlots > 0 ? `（空き ${row.remainingSlots}）` : "（満杯）")
      ).join("<br>")}
    `;
  } catch (e) {
    console.error(e);
    machineStatusBox.innerHTML = "<strong>有料自販機の空き状況</strong><br>読み込みに失敗しました";
  }
}

export async function updateListingAreaForCurrentWork(work) {
  if (!listingArea || !listingMessage || !listToMachineBtn) return;

  listingArea.style.display = "none";
  listingMessage.textContent = "";
  listingArea.dataset.machineId = "";

  if (listingFullBox) {
    listingFullBox.style.display = "none";
  }

  if (!isNewWork(work)) {
    return;
  }

  const available = await fetchAvailableMachine();
  listingArea.style.display = "block";

  if (!available) {
    listToMachineBtn.style.display = "none";
    if (listingFullBox) {
      listingFullBox.style.display = "block";
    }
    jackpotEl.style.display = "block";
    jackpotEl.textContent = "🎉 未出品作品を獲得！ただいま自販機は満杯です";
    listingMessage.textContent =
      "未出品作品は獲得済みです。空きが出たら出品できるようになります。";
    return;
  }

  listToMachineBtn.style.display = "inline-flex";
  listToMachineBtn.disabled = false;
  listingArea.dataset.machineId = String(available.machine.id);
  listingMessage.textContent =
    `この作品は100ptスタートで出品できます（空き ${available.remaining_slots} / 30）`;
}

export async function renderWork(work) {
  state.currentWork = work;
  window.currentWork = work;

  if (placeholder) placeholder.style.display = "none";

  resetMedia();
  clearStageHitClasses();
  clearJackpotClasses();

  jackpotEl.style.display = "none";
  jackpotEl.textContent = "";

  if (listingArea) {
    listingArea.style.display = "none";
    listingArea.dataset.machineId = "";
  }
  if (listingMessage) {
    listingMessage.textContent = "";
  }
  if (listingFullBox) {
    listingFullBox.style.display = "none";
  }

  const mediaType = getMediaType(work);
  const mediaUrl = getMediaUrl(work);

  if (mediaType === "video") {
    if (resultVideo) {
      resultVideo.src = mediaUrl;
      resultVideo.style.display = "block";
      resultVideo.play().catch(() => {});
    }
  } else {
    if (resultImage) {
      resultImage.src = mediaUrl;
      resultImage.alt = work.title || "作品画像";
      resultImage.style.display = "block";
    }
  }

  if (titleEl) titleEl.textContent = work.title || "";
  if (creatorEl) creatorEl.textContent = work.creator || "";
  if (genreEl) genreEl.textContent = work.genre || "";
  if (descriptionEl) descriptionEl.textContent = work.description || "";
  if (mediaTypeEl) mediaTypeEl.textContent = mediaType === "video" ? "動画" : "画像";
  if (statusEl) statusEl.textContent = isNewWork(work) ? "🔥未出品（当たり）" : "出品済み";
  if (buybackPriceEl) {
    const buyback = Number(work.buyback_price || 0);
    buybackPriceEl.textContent = buyback > 0 ? `${buyback}pt` : "-";
  }
  if (featuredTypeEl) {
    featuredTypeEl.textContent = isOperatorPick(work) ? "運営特選" : "-";
  }

  const jackpotMessage = getJackpotMessage(work);
  if (jackpotMessage) {
    jackpotEl.style.display = "block";
    jackpotEl.textContent = jackpotMessage;
  }

  applyHitVisuals(work);
  if (getHitType(work) === "normal" || getHitType(work) === "rare") {
    setRarityStyle(work.rarity);
  }

  await updateListingAreaForCurrentWork(work);
}

export function setLoadingState(canDraw) {
  if (drawButton) {
    drawButton.disabled = !canDraw;
  }
}

export function setDrawingAnimation(active) {
  if (!stage) return;

  if (active) {
    clearStageHitClasses();
    stage.classList.add("animating", "reveal-delay");
  } else {
    stage.classList.remove("animating", "reveal-delay");
  }
}

export function getDrawButton() {
  return drawButton;
}

export function getListToMachineButton() {
  return listToMachineBtn;
}

export function getListingArea() {
  return listingArea;
}

export function getListingMessage() {
  return listingMessage;
}
