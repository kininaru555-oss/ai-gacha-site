import {
  API_BASE,
  CONTENTS_API,
  DRAW_COST,
  FREE_GACHA_API,
  LIST_START_PRICE,
  OWNERSHIP_LATEST_MAP_API,
  POINT_API_BASE,
  VENDING_AVAILABLE_API,
  VENDING_MACHINES_API
} from "./gacha-config.js";
import {
  consumeFreeDraw,
  getOrCreateUserId,
  hasFreeDraw,
  state
} from "./gacha-state.js";

// ── 修正①: OWNERSHIP_LATEST_MAP_API / FREE_GACHA_API の再定義を削除し config から import ──

function normalizeResultData(raw, drawMode) {
  const src = raw?.result || raw?.item || raw?.work || raw?.data || raw || {};

  const typeRaw = String(src.type || src.media_type || "").trim();
  const inferredType =
    typeRaw ||
    (src.video_url || src.videoUrl || src.video ? "動画" : "画像");

  const imageUrl =
    src.image_url ||
    src.imageUrl ||
    src.image ||
    src.thumbnail_url ||
    ((typeRaw === "画像" || typeRaw === "image" || (!src.video_url && !src.videoUrl && !src.video))
      ? (src.file || "")
      : "") ||
    "";

  const videoUrl =
    src.video_url ||
    src.videoUrl ||
    src.video ||
    ((typeRaw === "動画" || typeRaw === "video") ? (src.file || "") : "") ||
    "";

  const permissionValue =
    src.agreed ?? src.permission ?? src.allow_distribution ?? src.allow_resale ?? "";

  const creator = src.creator || src.author || src.creator_name || "不明";

  return {
    content_id: Number(src.content_id || src.id || src.work_id || 0),
    title:      src.title || src.name || "無題",
    image_url:  imageUrl,
    video_url:  videoUrl,
    creator,
    author:     creator,
    rarity:     src.rarity || src.rank || "N",
    genre:      src.genre  || src.category || "-",
    type:       inferredType,
    right_type: src.right_type || src.rightType || "",
    agreed:     permissionValue,
    permission: permissionValue,
    got_distribution_right: Boolean(
      src.got_distribution_right || src.granted_distribution_right || src.has_distribution_right || false
    ),
    is_unlisted_stock: Boolean(
      src.is_unlisted_stock || src.unlisted_stock || src.is_stock || false
    ),
    site_license_enabled:       Number(src.site_license_enabled       || 0),
    copyright_transfer_enabled: Number(src.copyright_transfer_enabled || 0),
    site_license_price:         Number(src.site_license_price         || 0),
    copyright_transfer_price:   Number(src.copyright_transfer_price   || 0),
    comment:        src.comment        || "",
    prompt:         src.prompt         || "",
    negative_prompt:src.negative_prompt|| "",
    work_link:      src.work_link      || src.link || "",
    x_account:      src.x_account      || "",
    draw_mode:      drawMode,
    _raw:           raw
  };
}

export async function fetchWorks() {
  const res = await fetch(`${CONTENTS_API}?t=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error("作品一覧の読み込みに失敗しました");
  const data = await res.json();
  return Array.isArray(data.items) ? data.items : [];
}

export async function fetchOwnerships() {
  const res = await fetch(`${OWNERSHIP_LATEST_MAP_API}?t=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error("ownership の読み込みに失敗しました");
  const data = await res.json();
  return data.items || {};
}

export async function fetchUserPoints() {
  const userId = getOrCreateUserId();
  const res = await fetch(`${POINT_API_BASE}/${encodeURIComponent(userId)}`, { cache: "no-store" });
  if (!res.ok) throw new Error("ポイント取得に失敗しました");
  const data = await res.json();
  return data.user || {};
}

export async function consumeDrawCostIfNeeded() {
  if (hasFreeDraw()) {
    consumeFreeDraw();
    return { ok: true, drawMode: "free" };
  }

  const userId = getOrCreateUserId();

  if (state.currentUserPoints < DRAW_COST) {
    alert(`ポイントが足りません。ガチャ1回 ${DRAW_COST}pt 必要です。`);
    return { ok: false, drawMode: "points" };
  }

  const res = await fetch(`${POINT_API_BASE}/${encodeURIComponent(userId)}/use`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ amount: DRAW_COST, note: "無料ガチャ実行" })
  });

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "ポイント消費に失敗しました");

  state.currentUserPoints  = Number(data.user?.points        || 0);
  state.currentPointExpireAt = data.user?.point_expire_at    || "";

  return { ok: true, drawMode: "points" };
}

export async function drawFreeGacha() {
  const userId      = getOrCreateUserId();
  const costResult  = await consumeDrawCostIfNeeded();
  if (!costResult.ok) return null;

  const res  = await fetch(FREE_GACHA_API, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ owner_id: userId })
  });

  const data = await res.json();
  localStorage.setItem("last_gacha_raw_response", JSON.stringify(data, null, 2));
  if (!res.ok) throw new Error(data.detail || "ガチャに失敗しました");

  const result = normalizeResultData(data, costResult.drawMode);
  if (!result.content_id && !result.image_url && !result.video_url) {
    throw new Error("ガチャ結果の形式が不正です");
  }

  localStorage.setItem("last_gacha_result", JSON.stringify(result));
  return result;
}

export async function fetchAvailableMachine() {
  const res  = await fetch(VENDING_AVAILABLE_API, { cache: "no-store" });
  const data = await res.json();
  if (!res.ok || !data.available) return null;
  return data;
}

// ── 修正②: start_price を LIST_START_PRICE から送るよう修正 ──
export async function listWorkToMachine(machineId, contentId, ownerId) {
  const res  = await fetch(
    `${API_BASE}/api/vending-machines/${encodeURIComponent(machineId)}/items`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content_id:  contentId,
        owner_id:    ownerId,
        item_order:  0,
        start_price: LIST_START_PRICE  // ← 修正: 抜けていた start_price を追加
      })
    }
  );

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "自販機追加に失敗しました");
  return data;
}

// ── 修正③: 直列ループ → Promise.all で並列fetch ──
export async function fetchMachineStatusRows() {
  const res  = await fetch(VENDING_MACHINES_API, { cache: "no-store" });
  const data = await res.json();
  if (!res.ok) throw new Error("自販機一覧の取得に失敗しました");

  const machines = Array.isArray(data.items) ? data.items : [];

  // 各台の詳細を並列取得
  const details = await Promise.all(
    machines.map(m =>
      fetch(`${API_BASE}/api/vending-machines/${m.id}`, { cache: "no-store" })
        .then(r => r.ok ? r.json() : null)
        .catch(() => null)
    )
  );

  return machines
    .map((machine, i) => {
      const detail = details[i];
      if (!detail) return null;
      return {
        id:             machine.id,
        name:           machine.name,
        currentCount:   Number(detail.current_count   || 0),
        remainingSlots: Number(detail.remaining_slots || 0)
      };
    })
    .filter(Boolean);
      }
