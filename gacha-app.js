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

  const workId = String(work.id ?? "");
  if (!workId) {
    return;
  }

  // すでに流通済みなら付与しない
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
      setLoadingState(true);
      return;
    }

    updateTicket();

    const selected = drawRandom();
    const revealDelay = getRevealDelayMs(selected);

    clearStageHitClasses();
    setDrawingAnimation(true);

    setTimeout(async () => {
      await grantFreeGachaOwnershipIfAllowed(selected);
      await renderWork(selected);
    }, revealDelay);

    setTimeout(() => {
      setDrawingAnimation(false);
      state.isDrawing = false;
      setLoadingState(true);
    }, revealDelay + 250);
  } catch (e) {
    console.error(e);
    alert("ガチャ処理に失敗しました");
    state.isDrawing = false;
    setDrawingAnimation(false);
    setLoadingState(true);
  }
}

async function handleListToMachine() {
  if (!state.currentWork || !listingArea || !listingMessage || !listToMachineBtn) return;

  const machineId = listingArea.dataset.machineId;

  if (!machineId) {
    listingMessage.textContent = "出品先の自販機が見つかりません。";
    return;
  }

  listingMessage.textContent = "自販機に追加しています...";
  listToMachineBtn.disabled = true;

  try {
    await listWorkToMachine(machineId, state.currentWork.id);

    listingMessage.textContent = "100ptスタートで自販機に出品しました！";
    listToMachineBtn.style.display = "none";

    state.ownershipMap[String(state.currentWork.id)] = {
      content_id: Number(state.currentWork.id),
      status: "listed"
    };

    await renderMachineStatus();
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
