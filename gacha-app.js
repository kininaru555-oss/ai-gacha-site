import { API_BASE } from "./gacha-config.js";
import {
  consumeDrawCostIfNeeded,
  fetchOwnerships,
  fetchUserPoints,
  fetchWorks,
  listWorkToMachine
} from "./gacha-api.js";
import { drawButton, listingArea, listingMessage, listToMachineBtn } from "./gacha-dom.js";
import { state, getOrCreateUserId } from "./gacha-state.js";
import { clearStageHitClasses, getRevealDelayMs } from "./gacha-utils.js";
import {
  initMypageLink,
  renderLatestWorks,
  renderMachineStatus,
  renderWork,
  setDrawingAnimation,
  setLoadingState,
  updateTicket
} from "./gacha-render.js";

function drawRandom() {
  return state.works[Math.floor(Math.random() * state.works.length)];
}

async function grantFreeGachaOwnershipIfAllowed(work) {
  if (!work) return;

  const agreed = String(work.agreed || "").trim();
  if (agreed !== "はい") {
    return;
  }

  const workId = String(work.id ?? "").trim();
  if (!workId) {
    return;
  }

  // すでに流通済みなら無料付与しない
  if (state.ownershipMap[workId]) {
    return;
  }

  const userId = getOrCreateUserId();

  try {
    const res = await fetch(
      `${API_BASE}/api/free-gacha/grant/${encodeURIComponent(work.id)}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          owner_id: userId
        })
      }
    );

    const data = await res.json();

    if (!res.ok) {
      console.warn("無料ガチャ権利付与失敗", data.detail || data);
      return;
    }

    state.ownershipMap[workId] = {
      content_id: Number(work.id),
      owner_id: userId,
      ownership_type: data.ownership_type || "copyright_transfer",
      status: "owned"
    };
  } catch (e) {
    console.warn("無料ガチャ権利付与失敗", e);
  }
}

async function loadInitialData() {
  try {
    state.works = await fetchWorks();
  } catch (e) {
    console.error(e);
    state.works = [];
  }

  try {
    state.ownershipMap = await fetchOwnerships();
  } catch (e) {
    console.warn("ownership取得失敗", e);
    state.ownershipMap = {};
  }

  try {
    const user = await fetchUserPoints();
    state.currentUserPoints = Number(user.points || 0);
    state.currentPointExpireAt = user.point_expire_at || "";
  } catch (e) {
    console.warn("ポイント取得失敗", e);
    state.currentUserPoints = 0;
    state.currentPointExpireAt = "";
  }

  await renderMachineStatus();
  renderLatestWorks();
  updateTicket();
  setLoadingState(state.works.length > 0);
}

async function handleDraw() {
  if (state.isDrawing || !state.works.length) return;

  state.isDrawing = true;
  setLoadingState(false);

  try {
    const ok = await consumeDrawCostIfNeeded();

    if (!ok) {
      state.isDrawing = false;
      setLoadingState(state.works.length > 0);
      return;
    }

    updateTicket();

    const selected = drawRandom();
    const revealDelay = getRevealDelayMs(selected);

    clearStageHitClasses();
    setDrawingAnimation(true);

    setTimeout(async () => {
      try {
        await grantFreeGachaOwnershipIfAllowed(selected);
        await renderWork(selected);
      } catch (e) {
        console.error("描画処理失敗", e);
      }
    }, revealDelay);

    setTimeout(() => {
      setDrawingAnimation(false);
      state.isDrawing = false;
      setLoadingState(state.works.length > 0);
    }, revealDelay + 250);
  } catch (e) {
    console.error(e);
    alert("ガチャ処理に失敗しました");
    state.isDrawing = false;
    setDrawingAnimation(false);
    setLoadingState(state.works.length > 0);
  }
}

async function handleListToMachine() {
  if (!state.currentWork || !listingArea || !listingMessage || !listToMachineBtn) return;

  const machineId = String(listingArea.dataset.machineId || "").trim();
  const ownerId = getOrCreateUserId();

  if (!machineId) {
    listingMessage.textContent = "出品先の自販機が見つかりません。";
    return;
  }

  if (!state.currentWork.id) {
    listingMessage.textContent = "作品IDが見つかりません。";
    return;
  }

  listingMessage.textContent = "自販機に追加しています...";
  listToMachineBtn.disabled = true;

  try {
    await listWorkToMachine(machineId, state.currentWork.id, ownerId);

    listingMessage.textContent = "100ptスタートで自販機に出品しました！";
    listToMachineBtn.style.display = "none";

    state.ownershipMap[String(state.currentWork.id)] = {
      content_id: Number(state.currentWork.id),
      owner_id: ownerId,
      ownership_type: state.ownershipMap[String(state.currentWork.id)]?.ownership_type || "copyright_transfer",
      status: "listed"
    };

    await renderMachineStatus();
    await renderWork(state.currentWork);
  } catch (e) {
    console.error(e);
    listingMessage.textContent = e.message || "自販機追加に失敗しました。";
    listToMachineBtn.disabled = false;
  }
}

function bindEvents() {
  if (drawButton) {
    drawButton.addEventListener("click", handleDraw);
  }

  if (listToMachineBtn) {
    listToMachineBtn.addEventListener("click", handleListToMachine);
  }
}

(async function init() {
  getOrCreateUserId();
  initMypageLink();
  bindEvents();
  await loadInitialData();
})();
