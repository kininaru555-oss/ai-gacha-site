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

export function isPosterFreeUser() {
  return localStorage.getItem("gacha_is_poster_free") === "1";
}
