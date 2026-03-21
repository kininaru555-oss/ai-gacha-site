export const state = {
  works: [],
  currentWork: null,
  isDrawing: false,
  ownershipMap: {},
  currentUserPoints: 0,
  currentPointExpireAt: ""
};

export function getOrCreateUserId() {
  let userId = localStorage.getItem("gacha_user_id");

  if (!userId) {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      userId = "user_" + window.crypto.randomUUID();
    } else {
      userId =
        "user_" + Date.now() + "_" + Math.floor(Math.random() * 1000000);
    }

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
  const current = getFreeDrawCount();
  const next = Math.max(0, current - 1);
  localStorage.setItem("gacha_free_draw_count", String(next));
  return next;
}

export function addFreeDraw(count = 1) {
  const current = getFreeDrawCount();
  const next = Math.max(0, current + Number(count || 0));
  localStorage.setItem("gacha_free_draw_count", String(next));
  return next;
}
