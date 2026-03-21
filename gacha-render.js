import { API_BASE, DRAW_COST } from "./gacha-config.js";
import {
  buybackPriceEl,
  creatorEl,
  descriptionEl,
  drawButton,
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
  if (creatorEl) creatorEl.textContent = work.author || "";
  if (genreEl) genreEl.textContent = work.genre || "";
  if (descriptionEl) descriptionEl.textContent = work.comment || "";
  if (mediaTypeEl) mediaTypeEl.textContent = mediaType === "video" ? "動画" : "画像";

  if (statusEl) {
    statusEl.textContent = isNewWork(work) ? "🔥未出品（当たり）" : "出品済み";
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
  if (drawButton) {
    drawButton.disabled = !canDraw;
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
