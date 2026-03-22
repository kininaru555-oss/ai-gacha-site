export const state = {
  works: [],
  currentWork: null,
  isDrawing: false,
  ownershipMap: {},
  currentUserPoints: 0,
  currentPointExpireAt: "",
  machineStatusRows: []
};

export function getOrCreateUserId() {
  let userId = localStorage.getItem("gacha_user_id");

  if (!userId) {
    userId = window.crypto?.randomUUID
      ? "user_" + window.crypto.randomUUID()
      : "user_" + Date.now() + "_" + Math.floor(Math.random() * 1000000);
    localStorage.setItem("gacha_user_id", userId);
  }

  return userId;
}

export function getFreeDrawCount() {
  return Number(localStorage.getItem("gacha_free_draw_count") || "0");
}

export function hasFreeDraw() {
  return getFreeDrawCount() > 0;
}

export function consumeFreeDraw() {
  const next = Math.max(0, getFreeDrawCount() - 1);
  localStorage.setItem("gacha_free_draw_count", String(next));
  return next;
}

export function addFreeDraw(count = 1) {
  const next = Math.max(0, getFreeDrawCount() + Number(count || 0));
  localStorage.setItem("gacha_free_draw_count", String(next));
  return next;
}

export function setLastGachaResult(result) {
  if (!result) return;
  localStorage.setItem("last_gacha_result", JSON.stringify(result));
}

export function getLastGachaResult() {
  try {
    const raw = localStorage.getItem("last_gacha_result");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearLastGachaResult() {
  localStorage.removeItem("last_gacha_result");
}

export function setLastGachaRawResponse(rawResponse) {
  if (rawResponse == null) return;
  localStorage.setItem(
    "last_gacha_raw_response",
    typeof rawResponse === "string"
      ? rawResponse
      : JSON.stringify(rawResponse, null, 2)
  );
}

export function getLastGachaRawResponse() {
  try {
    return localStorage.getItem("last_gacha_raw_response") || "";
  } catch {
    return "";
  }
}

export function clearLastGachaRawResponse() {
  localStorage.removeItem("last_gacha_raw_response");
}
