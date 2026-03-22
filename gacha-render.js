import { DRAW_COST } from "./gacha-config.js";
import {
  creatorEl,
  descriptionEl,
  drawButton,
  genreEl,
  getJackpotEl,
  latestWorksBox,
  listingArea,
  listingMessage,
  listToMachineBtn,
  machineStatusBox,
  mediaTypeEl,
  mypageBtn,
  placeholder,
  rarityEl,
  stage,
  statusEl,
  ticketInfo,
  titleEl
} from "./gacha-dom.js";
import { fetchAvailableMachine, fetchMachineStatusRows } from "./gacha-api.js";
import { getFreeDrawCount, getOrCreateUserId, state } from "./gacha-state.js";
import {
  applyHitVisuals,
  clearJackpotClasses,
  clearStageHitClasses,
  formatExpireDate,
  getHitType,
  getJackpotMessage,
  getMediaType,
  isNewWork,
  normalizeRarity,
  setRarityStyle
} from "./gacha-utils.js";

function isRightsAllowed(work) {
  return String(work?.agreed || work?.permission || "").trim() === "はい";
}

function getWorkId(work) {
  return String(work?.content_id ?? work?.id ?? "").trim();
}

function getOwnership(work) {
  const workId = getWorkId(work);
  if (!workId) return null;
  return state.ownershipMap[workId] || null;
}

function getStatusText(work) {
  const ownership = getOwnership(work);

  if (ownership) {
    if (ownership.status === "listed") return "出品済み";
    if (ownership.status === "owned")  return "権利取得済み";
    return ownership.status || "流通済み";
  }

  if (Boolean(work?.got_distribution_right)) return "無料ガチャで二次流通権を取得";
  if (isRightsAllowed(work))                 return "未出品在庫候補";
  return "権利未開放（閲覧中心）";
}

function getListingGuideText(work, available) {
  if (!isRightsAllowed(work)) {
    return "この作品は権利未開放です。閲覧中心で、流通権は発生しません。";
  }
  if (!isNewWork(work) && !Boolean(work?.got_distribution_right)) {
    return "この作品はすでに流通中、または販売メニュー付き作品です。作品詳細から確認してください。";
  }
  if (!available) {
    return "未出品作品です。現在自販機は満杯のため、まずはマイページや作品詳細から販売導線を確認してください。";
  }
  return `未出品作品です。自販機ガチャオークションに出品できます（空き ${available.remainingSlots} / 30）。またはマイページから販売導線へ進めます。`;
}

function updateMypageResaleLink(work) {
  const resaleBtn = document.getElementById("resaleFromMypageBtn");
  if (!resaleBtn) return;

  const userId = getOrCreateUserId();
  const workId = getWorkId(work);

  if (!work || !isRightsAllowed(work) || !workId) {
    resaleBtn.style.display = "none";
    resaleBtn.href = "#";
    return;
  }

  resaleBtn.style.display = "inline-flex";
  resaleBtn.href = `/mypage/${encodeURIComponent(userId)}?highlight=${encodeURIComponent(workId)}`;
}

export function initMypageLink() {
  const userId = getOrCreateUserId();
  if (mypageBtn) mypageBtn.href = `/mypage/${encodeURIComponent(userId)}`;
}

export function updateTicket() {
  if (!ticketInfo) return;

  const freeDrawCount = getFreeDrawCount();
  if (freeDrawCount > 0) {
    ticketInfo.textContent =
      `所持ポイント：${state.currentUserPoints}pt / 無料ガチャ ${freeDrawCount}回 / 通常1回 ${DRAW_COST}pt`;
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
    ${latest.map(work => {
      const creator = work.author || work.creator || "投稿者";
      const genre   = work.genre  || "AI作品";
      const rarity  = normalizeRarity(work.rarity);
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
      ${rows.map(row =>
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

  const jackpotEl = getJackpotEl();

  listingArea.style.display     = "none";
  listingMessage.textContent    = "";
  listingArea.dataset.machineId = "";

  updateMypageResaleLink(work);
  if (!work) return;

  const ownership = getOwnership(work);

  if (ownership) {
    listToMachineBtn.style.display = "none";
    listToMachineBtn.disabled      = false;
    listingArea.style.display      = "block";
    listingMessage.textContent =
      ownership.status === "listed"
        ? "この作品はすでに自販機または市場に出品されています。"
        : "この作品の権利はすでに取得済みです。マイページから再販売できます。";
    return;
  }

  if (!isRightsAllowed(work)) {
    listToMachineBtn.style.display = "none";
    listToMachineBtn.disabled      = false;
    listingArea.style.display      = "block";
    listingMessage.textContent     = "この作品は権利未開放です。閲覧中心で、流通権は発生しません。";
    return;
  }

  const available = await fetchAvailableMachine();

  listingArea.style.display  = "block";
  listingMessage.textContent = getListingGuideText(work, available);

  if (!available) {
    listToMachineBtn.style.display = "none";
    listToMachineBtn.disabled      = false;
    if (jackpotEl) {
      jackpotEl.style.display = "block";
      jackpotEl.textContent   = "🎉 未出品作品候補です（現在、自販機は満杯）";
    }
    return;
  }

  listToMachineBtn.style.display    = "inline-flex";
  listToMachineBtn.disabled         = false;
  listingArea.dataset.machineId     = String(available.machine.id);
}

export async function renderWork(work) {
  const jackpotEl = getJackpotEl();

  // ── 修正: window.currentWork へのグローバル代入を削除 ──
  state.currentWork = work;

  if (placeholder) {
    placeholder.innerHTML = `
      <div style="padding: 16px; line-height: 1.8;">
        <strong>${work.title || "無題"}</strong><br>
        ${work.author || work.creator || "不明"} / ${work.genre || "-"} / ${normalizeRarity(work.rarity)}<br>
        結果ページへ移動します...
      </div>
    `;
    placeholder.style.display = "flex";
  }

  if (jackpotEl) {
    jackpotEl.style.display = "none";
    jackpotEl.textContent   = "";
  }

  if (listingArea) {
    listingArea.style.display     = "none";
    listingArea.dataset.machineId = "";
  }

  if (listingMessage) listingMessage.textContent = "";

  const mediaType = getMediaType(work);

  if (titleEl)       titleEl.textContent       = work.title  || "";
  if (creatorEl)     creatorEl.textContent     = work.author || work.creator || "";
  if (genreEl)       genreEl.textContent       = work.genre  || "";
  if (descriptionEl) descriptionEl.textContent = work.comment || "";
  if (mediaTypeEl)   mediaTypeEl.textContent   = mediaType === "video" ? "動画" : "画像";
  if (statusEl)      statusEl.textContent      = getStatusText(work);
  if (rarityEl)      rarityEl.textContent      = normalizeRarity(work.rarity);

  const jackpotMessage = getJackpotMessage(work);
  if (jackpotMessage && jackpotEl) {
    jackpotEl.style.display = "block";
    jackpotEl.textContent   = jackpotMessage;
  }

  applyHitVisuals(work);

  const hitType = getHitType(work);
  if (hitType === "normal" || hitType === "rare") {
    setRarityStyle(work.rarity);
  }

  await updateListingAreaForCurrentWork(work);
}

export function setLoadingState(canDraw) {
  if (!drawButton) return;
  drawButton.disabled = !Boolean(canDraw);
}

// ── 修正: インデント崩れを修正 ──
export function setDrawingAnimation(active) {
  if (!stage) return;
  if (active) {
    stage.classList.add("animating", "reveal-delay");
  } else {
    stage.classList.remove("animating", "reveal-delay");
  }
    }
