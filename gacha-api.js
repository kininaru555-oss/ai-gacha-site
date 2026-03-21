import {
  API_BASE,
  CONTENTS_API,
  DRAW_COST,
  OWNERSHIP_API,
  POINT_API_BASE,
  VENDING_AVAILABLE_API,
  VENDING_MACHINES_API
} from "./gacha-config.js";
import { getOrCreateUserId, isPosterFreeUser, state } from "./gacha-state.js";

export async function fetchWorks() {
  const response = await fetch(`${CONTENTS_API}?t=${Date.now()}`, {
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error("作品一覧の読み込みに失敗しました");
  }

  const data = await response.json();
  return Array.isArray(data.items) ? data.items : [];
}

export async function fetchOwnerships() {
  const response = await fetch(`${OWNERSHIP_API}?t=${Date.now()}`, {
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error("ownership の読み込みに失敗しました");
  }

  const data = await response.json();
  const items = Array.isArray(data.items) ? data.items : [];
  const map = {};

  items.forEach((item) => {
    map[String(item.content_id)] = item;
  });

  return map;
}

export async function fetchUserPoints() {
  const userId = getOrCreateUserId();

  const response = await fetch(`${POINT_API_BASE}/${encodeURIComponent(userId)}`, {
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error("ポイント取得に失敗しました");
  }

  const data = await response.json();
  return data.user || {};
}

export async function consumeDrawCostIfNeeded() {
  if (isPosterFreeUser()) {
    return true;
  }

  const userId = getOrCreateUserId();

  if (state.currentUserPoints < DRAW_COST) {
    alert(`ポイントが足りません。ガチャ1回 ${DRAW_COST}pt 必要です。`);
    return false;
  }

  const response = await fetch(
    `${POINT_API_BASE}/${encodeURIComponent(userId)}/use?amount=${DRAW_COST}&note=${encodeURIComponent("有料自販機ガチャ")}`,
    { method: "POST" }
  );

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "ポイント消費に失敗しました");
  }

  state.currentUserPoints = Number(data.user?.points || 0);
  state.currentPointExpireAt = data.user?.point_expire_at || "";

  return true;
}

export async function fetchAvailableMachine() {
  const res = await fetch(VENDING_AVAILABLE_API, {
    cache: "no-store"
  });

  const data = await res.json();

  if (!res.ok || !data.available) {
    return null;
  }

  return data;
}

export async function listWorkToMachine(machineId, contentId) {
  const res = await fetch(
    `${API_BASE}/api/vending-machines/${machineId}/items?content_id=${encodeURIComponent(contentId)}&item_order=0`,
    { method: "POST" }
  );

  const data = await res.json();

  if (!res.ok) {
    throw new Error(data.detail || "自販機追加に失敗しました");
  }

  return data;
}

export async function fetchMachineStatusRows() {
  const res = await fetch(VENDING_MACHINES_API, {
    cache: "no-store"
  });

  const data = await res.json();

  if (!res.ok) {
    throw new Error("自販機一覧の取得に失敗しました");
  }

  const machines = Array.isArray(data.items) ? data.items : [];
  const rows = [];

  for (const machine of machines) {
    const detailRes = await fetch(`${API_BASE}/api/vending-machines/${machine.id}`, {
      cache: "no-store"
    });

    const detailData = await detailRes.json();

    if (!detailRes.ok) {
      continue;
    }

    rows.push({
      name: machine.name,
      currentCount: Number(detailData.current_count || 0),
      remainingSlots: Number(detailData.remaining_slots || 0)
    });
  }

  return rows;
}
