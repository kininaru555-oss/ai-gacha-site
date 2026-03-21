import { API_BASE, DRAW_COST } from "./gacha-config.js";
import {
  buybackPriceEl,
  creatorEl,
  descriptionEl,
  featuredTypeEl,
  genreEl,
  jackpotEl,
  latestWorksBox,
  listingArea,
  listingFullBox,
  listingMessage,
  listToMachineBtn,
  machineStatusBox,
  mediaTypeEl,
  mypageBtn,
  placeholder,
  resultImage,
  resultVideo,
  stage,
  statusEl,
  ticketInfo,
  titleEl
} from "./gacha-dom.js";
import { fetchAvailableMachine, fetchMachineStatusRows } from "./gacha-api.js";
import { getOrCreateUserId, isPosterFreeUser, state } from "./gacha-state.js";
import {
  applyHitVisuals,
  formatExpireDate,
  getHitType,
  getJackpotMessage,
  getMediaType,
  getMediaUrl,
  isNewWork,
  isOperatorPick,
  normalizeRarity,
  resetMedia,
  setRarityStyle
} from "./gacha-utils.js";

function isRightsAllowed(work) {
  return String(work?.agreed || "").trim() === "はい";
}

function getOwnership(work) {
  const workId = String(work?.id ?? "").trim();
  if (!workId) return null;
  return state.ownershipMap[workId] || null;
}

function getStatusText(work) {
  const ownership = getOwnership(work);

  if (ownership) {
    if (ownership.status === "listed") {
      return "出品済み";
    }
    if (ownership.status === "owned") {
      return "権利取得済み";
    }
    return ownership.status || "流通済み";
  }

  if (isRightsAllowed(work)) {
    return "🔥未出品（当たり）";
  }

  return "🔒 権利未開放（購入のみ）";
}

function getListingGuideText(work, available) {
  if (!isRightsAllowed(work)) {
    return "この作品は権利未開放です。購入でのみ取得できます。";
  }

  if (!isNewWork(work)) {
    return "";
  }

  if (!available) {
    return "未出品作品です。現在自販機は満杯のため、マイページで再販売してください。";
  }

  return `未出品作品です。自販機ガチャオークションに出品できます（空き ${available.remaining_slots} / 30）。またはマイページで再販売できます。`;
}

function updateMypageResaleLink(work) {
  const resaleBtn = document.getElementById("resaleFromMypageBtn");
  if (!resaleBtn) return;

  const userId = getOrCreateUserId();

  if (!work || !isRightsAllowed(work)) {
    resaleBtn.style.display = "none";
    resaleBtn.href = "#";
    return;
  }

  resaleBtn.style.display = "inline-flex";
  resaleBtn.href =
    `${API_BASE}/mypage/${encodeURIComponent(userId)}` +
    `?highlight=${encodeURIComponent(work.id || "")}`;
}

export function initMypageLink() {
  const userId = getOrCreateUserId();

  if (mypageBtn) {
    mypageBtn.href = `${API_BASE}/mypage/${encodeURIComponent(userId)}`;
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
      const creator = work.author || "投稿者";
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
      machineStatusBox.innerHTML =
        "<strong>有料自販機の空き状況</strong><br>現在表示できる自販機情報がありません";
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
    machineStatusBox.innerHTML =
      "<strong>有料自販機の空き状況</strong><br>読み込みに失敗しました";
  }
}

export async function updateListingAreaForCurrentWork(work) {
  if (!listingArea || !listingMessage || !listToMachineBtn) return;

  listingArea.style.display = "none";
  listingMessage.textContent = "";
  listingArea.dataset.machineId = "";

  if (listingFullBox) {
    listingFullBox.style.display = "none";
    listingFullBox.textContent = "";
  }

  updateMypageResaleLink(work);

  if (!work) {
    return;
  }

  const ownership = getOwnership(work);

  if (ownership) {
    if (listToMachineBtn) {
      listToMachineBtn.style.display = "none";
      listToMachineBtn.disabled = false;
    }
    listingArea.style.display = "block";
    listingMessage.textContent =
      ownership.status === "listed"
        ? "この作品はすでに自販機または市場に出品されています。"
        : "この作品の権利はすでに取得済みです。マイページから再販売できます。";
    return;
  }

  if (!isRightsAllowed(work)) {
    if (listToMachineBtn) {
      listToMachineBtn.style.display = "none";
      listToMachineBtn.disabled = false;
    }
    listingArea.style.display = "block";
    listingMessage.textContent = "この作品は権利未開放です。購入でのみ取得できます。";
    return;
  }

  const available = await fetchAvailableMachine();
  listingArea.style.display = "block";
  listingMessage.textContent = getListingGuideText(work, available);

  if (!available) {
    listToMachineBtn.style.display = "none";

    if (listingFullBox) {
      listingFullBox.style.display = "block";
      listingFullBox.textContent = "現在、自販機は満杯です。";
    }

    jackpotEl.style.display = "block";
    jackpotEl.textContent = "🎉 未出品作品を獲得！ただいま自販機は満杯です";
    return;
  }

  listToMachineBtn.style.display = "inline-flex";
  listToMachineBtn.disabled = false;
  listingArea.dataset.machineId = String(available.machine.id);
}

export async function renderWork(work) {
  state.currentWork = work;
  window.currentWork = work;

  if (placeholder) {
    placeholder.style.display = "none";
  }

  resetMedia();

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
    listingFullBox.textContent = "";
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

  if (titleEl) {
    titleEl.textContent = work.title || "";
  }

  if (creatorEl) {
    creatorEl.textContent = work.author || "";
  }

  if (genreEl) {
    genreEl.textContent = work.genre || "";
  }

  if (descriptionEl) {
    descriptionEl.textContent = work.comment || "";
  }

  if (mediaTypeEl) {
    mediaTypeEl.textContent = mediaType === "video" ? "動画" : "画像";
  }

  if (statusEl) {
    statusEl.textContent = getStatusText(work);
  }

  if (buybackPriceEl) {
    const buybackPrice = Number(work.buyback_price || 0);
    buybackPriceEl.textContent = buybackPrice > 0 ? `${buybackPrice}pt` : "-";
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
  const canUse = Boolean(canDraw);

  if (drawButton) {
    drawButton.disabled = !canUse;
  }
}

export function setDrawingAnimation(active) {
  if (!stage) return;

  if (active) {
    stage.classList.add("animating", "reveal-delay");
  } else {
    stage.classList.remove("animating", "reveal-delay");
  }
}
