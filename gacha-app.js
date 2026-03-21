import {
  drawFreeGacha,
  fetchMachineStatusRows,
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

  try {
    state.machineStatusRows = await fetchMachineStatusRows();
  } catch (e) {
    console.warn("自販機状況取得失敗", e);
    state.machineStatusRows = [];
  }

  await renderMachineStatus();
  renderLatestWorks();
  updateTicket();
  setLoadingState(state.works.length > 0);
}

async function handleDraw() {
  if (state.isDrawing) return;

  state.isDrawing = true;
  setLoadingState(false);

  try {
    clearStageHitClasses();
    setDrawingAnimation(true);

    const result = await drawFreeGacha();

    if (!result) {
      state.isDrawing = false;
      setDrawingAnimation(false);
      setLoadingState(state.works.length > 0);
      return;
    }

    state.currentWork = result;

    const revealDelay = getRevealDelayMs(result);

    setTimeout(async () => {
      try {
        // index 上でも軽く見せたい場合のために残す
        await renderWork(result);
      } catch (e) {
        console.error("描画処理失敗", e);
      }
    }, Math.max(0, revealDelay - 150));

    setTimeout(() => {
      setDrawingAnimation(false);
      state.isDrawing = false;
      setLoadingState(state.works.length > 0);

      window.location.href = "result.html";
    }, revealDelay + 250);
  } catch (e) {
    console.error(e);
    alert(e.message || "ガチャ処理に失敗しました");
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

  const contentId = Number(state.currentWork.content_id || state.currentWork.id || 0);
  if (!contentId) {
    listingMessage.textContent = "作品IDが見つかりません。";
    return;
  }

  listingMessage.textContent = "自販機に追加しています...";
  listToMachineBtn.disabled = true;

  try {
    await listWorkToMachine(machineId, contentId, ownerId);

    listingMessage.textContent = "100ptスタートで自販機に出品しました！";
    listToMachineBtn.style.display = "none";

    state.ownershipMap[String(contentId)] = {
      content_id: contentId,
      owner_id: ownerId,
      ownership_type:
        state.ownershipMap[String(contentId)]?.ownership_type || "copyright_transfer",
      status: "listed"
    };

    state.machineStatusRows = await fetchMachineStatusRows();
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
