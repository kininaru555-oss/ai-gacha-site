let works = [];
let currentWork = null;
let isDrawing = false;
let ownershipMap = {};
let currentUserPoints = 0;
let currentPointExpireAt = "";

const API_URL = "https://script.google.com/macros/s/AKfycbzRW9dHBTOaRkM8gibA09i9L8zSiDDdd1YNWikqT4wn7zQWSaJQpo3-5CJx61od6-sNbQ/exec";
const OWNERSHIP_API = "/api/ownerships";
const POINT_API_BASE = "/api/points";
const VENDING_MACHINES_API = "/api/vending-machines";
const VENDING_AVAILABLE_API = "/api/vending-machines/available/for-listing";

const DRAW_COST = 30;
const SHARE_REWARD_POINTS = 30;

const drawButton = document.getElementById("drawButton");
const stage = document.getElementById("stage");
const placeholder = document.getElementById("placeholder");
const resultImage = document.getElementById("resultImage");
const resultVideo = document.getElementById("resultVideo");
const meta = document.getElementById("meta");
const likeButton = document.getElementById("likeButton");
const linkButton = document.getElementById("linkButton");
const shareButton = document.getElementById("shareButton");
const ticketInfo = document.getElementById("ticketInfo");

const promptBox = document.getElementById("promptBox");
const togglePromptBtn = document.getElementById("togglePromptBtn");
const copyPromptBtn = document.getElementById("copyPromptBtn");

const statusEl = document.getElementById("status");
const buybackPriceEl = document.getElementById("buybackPrice");
const featuredTypeEl = document.getElementById("featuredType");
const listingArea = document.getElementById("listingArea");
const listToMachineBtn = document.getElementById("listToMachineBtn");
const listingMessage = document.getElementById("listingMessage");
const listingFullBox = document.getElementById("listingFullBox");

// 当たり表示
const jackpotEl = document.createElement("div");
jackpotEl.id = "jackpot";
jackpotEl.style.display = "none";
jackpotEl.style.color = "gold";
jackpotEl.style.fontWeight = "bold";
jackpotEl.style.marginTop = "10px";
jackpotEl.textContent = "🎉 当たり！";

if (meta) {
  meta.appendChild(jackpotEl);
}

function getOrCreateUserId() {
  let userId = localStorage.getItem("gacha_user_id");

  if (!userId) {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      userId = "user_" + window.crypto.randomUUID();
    } else {
      userId = "user_" + Date.now() + "_" + Math.floor(Math.random() * 1000000);
    }
    localStorage.setItem("gacha_user_id", userId);
  }

  return userId;
}

function isPosterFreeUser() {
  return localStorage.getItem("gacha_is_poster_free") === "1";
}

function setPosterFreeUser(value) {
  localStorage.setItem("gacha_is_poster_free", value ? "1" : "0");
}

function clearStageHitClasses() {
  if (!stage) return;

  stage.classList.remove(
    "rare",
    "ssr",
    "hit-new",
    "hit-buyback",
    "hit-pickup",
    "reveal-delay"
  );
}

function clearJackpotClasses() {
  if (!jackpotEl) return;

  jackpotEl.classList.remove(
    "jackpot-new",
    "jackpot-buyback",
    "jackpot-pickup"
  );
}

function getHitType(work) {
  const newWork = isNewWork(work);
  const buybackPrice = Number(work.buyback_price || 0);
  const operatorPick = isOperatorPick(work);
  const rarity = normalizeRarity(work.rarity);

  if (newWork) {
    return "new";
  }

  if (buybackPrice > 0) {
    return "buyback";
  }

  if (operatorPick) {
    return "pickup";
  }

  if (rarity === "SSR" || rarity === "SR" || rarity === "R") {
    return "rare";
  }

  return "normal";
}

function getRevealDelayMs(work) {
  const hitType = getHitType(work);

  if (hitType === "new") return 1400;
  if (hitType === "buyback") return 1300;
  if (hitType === "pickup") return 1200;
  if (hitType === "rare") return 1050;
  return 850;
}

function applyHitVisuals(work) {
  const hitType = getHitType(work);

  clearStageHitClasses();
  clearJackpotClasses();

  if (!stage) return;

  if (hitType === "new") {
    stage.classList.add("ssr", "hit-new");
    if (jackpotEl) jackpotEl.classList.add("jackpot-new");
    return;
  }

  if (hitType === "buyback") {
    stage.classList.add("ssr", "hit-buyback");
    if (jackpotEl) jackpotEl.classList.add("jackpot-buyback");
    return;
  }

  if (hitType === "pickup") {
    stage.classList.add("rare", "hit-pickup");
    if (jackpotEl) jackpotEl.classList.add("jackpot-pickup");
    return;
  }

  if (hitType === "rare") {
    setRarityStyle(work.rarity, false);
    return;
  }

  setRarityStyle(work.rarity, false);
}

function getJackpotMessage(work) {
  const newWork = isNewWork(work);
  const buybackPrice = Number(work.buyback_price || 0);
  const operatorPick = isOperatorPick(work);
  const rarity = normalizeRarity(work.rarity);

  if (newWork) {
    return "🎉 未出品作品！自販機出品権を獲得！";
  }

  if (buybackPrice > 0) {
    return `🎉 高価還元対象！${buybackPrice}ポイントバック対象です`;
  }

  if (operatorPick) {
    return "⭐ 運営特選作品を引きました！";
  }

  if (rarity === "SSR") {
    return "🌈 特別作品を引きました！";
  }

  if (rarity === "SR") {
    return "✨ 注目作品を引きました！";
  }

  if (rarity === "R") {
    return "💎 レア作品を引きました！";
  }

  return "";
}

async function loadWorks() {
  try {
    const response = await fetch(API_URL + "?t=" + Date.now(), {
      cache: "no-store"
    });

    if (!response.ok) {
      throw new Error("APIの読み込みに失敗しました");
    }

    const raw = await response.json();
    works = Array.isArray(raw) ? raw : (raw.items || []);

    if (!Array.isArray(works) || works.length === 0) {
      if (placeholder) {
        placeholder.textContent = "まだ投稿作品がありません";
      }
      if (drawButton) {
        drawButton.disabled = true;
      }
      renderLatestWorks();
      return;
    }

    if (drawButton) {
      drawButton.disabled = false;
    }

    renderLatestWorks();
  } catch (e) {
    if (placeholder) {
      placeholder.textContent = "作品を読み込めません";
    }
    if (drawButton) {
      drawButton.disabled = true;
    }
    renderLatestWorks();
    console.error(e);
  }
}

async function loadOwnerships() {
  try {
    const response = await fetch(OWNERSHIP_API + "?t=" + Date.now(), {
      cache: "no-store"
    });

    if (!response.ok) {
      throw new Error("ownership APIの読み込みに失敗しました");
    }

    const data = await response.json();
    const items = Array.isArray(data.items) ? data.items : [];

    ownershipMap = {};
    items.forEach((item) => {
      ownershipMap[String(item.content_id)] = item;
    });
  } catch (e) {
    ownershipMap = {};
    console.warn("ownership取得失敗", e);
  }
}

async function loadUserPoints() {
  const userId = getOrCreateUserId();

  try {
    const response = await fetch(`${POINT_API_BASE}/${encodeURIComponent(userId)}`, {
      cache: "no-store"
    });

    if (!response.ok) {
      throw new Error("ポイント取得に失敗しました");
    }

    const data = await response.json();
    const user = data.user || {};

    currentUserPoints = Number(user.points || 0);
    currentPointExpireAt = user.point_expire_at || "";
  } catch (e) {
    currentUserPoints = 0;
    currentPointExpireAt = "";
    console.warn("ポイント取得失敗", e);
  }
}

function formatExpireDate(isoText) {
  if (!isoText) return "";

  try {
    const dt = new Date(isoText);
    if (Number.isNaN(dt.getTime())) return "";
    return dt.toLocaleDateString("ja-JP");
  } catch (e) {
    return "";
  }
}

function updateTicket() {
  if (!ticketInfo) return;

  if (isPosterFreeUser()) {
    ticketInfo.textContent = "投稿者モード：無料でガチャを引けます";
    return;
  }

  const expireText = formatExpireDate(currentPointExpireAt);
  ticketInfo.textContent =
    `所持ポイント：${currentUserPoints}pt / 1回 ${DRAW_COST}pt` +
    (expireText ? ` / 有効期限 ${expireText}` : "");
}

function getWorkId(work) {
  return work.id || (
    (work.title || "") + "_" +
    (work.creator || "") + "_" +
    (work.file || "")
  );
}

function optimizeCloudinary(url) {
  if (!url) return "";
  if (url.includes("res.cloudinary.com") && !url.includes("f_auto")) {
    return url.replace("/upload/", "/upload/f_auto,q_auto/");
  }
  return url;
}

function normalizeRarity(r) {
  if (!r) return "N";

  const v = String(r).toUpperCase().trim();

  if (v === "SSR") return "SSR";
  if (v === "SR") return "SR";
  if (v === "R" || v === "RARE") return "R";
  return "N";
}

function setRarityStyle(rarityText, forceSSR = false) {
  const rarity = document.getElementById("rarity");
  if (!rarity || !stage) return;

  const r = forceSSR ? "SSR" : normalizeRarity(rarityText);

  stage.classList.remove("rare", "ssr");
  rarity.textContent = r;

  if (r === "SSR") {
    rarity.style.background = "#d4af37";
    rarity.style.color = "#111";
    stage.classList.add("ssr");
  } else if (r === "SR" || r === "R") {
    rarity.style.background = "#7b61ff";
    rarity.style.color = "#fff";
    stage.classList.add("rare");
  } else {
    rarity.style.background = "#444";
    rarity.style.color = "#fff";
  }
}

function resetMedia() {
  if (resultImage) {
    resultImage.style.display = "none";
    resultImage.removeAttribute("src");
  }

  if (resultVideo) {
    resultVideo.style.display = "none";
    resultVideo.pause();
    resultVideo.removeAttribute("src");
    resultVideo.load();
  }
}

function getMediaType(work) {
  const type = String(work.type || "").trim();

  if (type === "video" || type === "動画") return "video";
  if (type === "image" || type === "画像") return "image";
  if (work.videoUrl) return "video";

  return "image";
}

function getMediaUrl(work) {
  const mediaType = getMediaType(work);

  if (mediaType === "video") {
    return optimizeCloudinary(work.videoUrl || work.file || "");
  }

  return optimizeCloudinary(work.imageUrl || work.file || "");
}

function drawRandom() {
  return works[Math.floor(Math.random() * works.length)];
}

function buildShareText(work) {
  if (!work) return "権利ガチャ";

  return (
    "権利ガチャで " +
    normalizeRarity(work.rarity) +
    " を引いた！\n" +
    "作品：「" + (work.title || "") + "」\n" +
    "作者：" + (work.creator || "不明") + "\n" +
    "#AIガチャ #AI画像"
  );
}

function buildShareUrl(work) {
  const shareText = buildShareText(work);
  return (
    "https://twitter.com/intent/tweet?text=" +
    encodeURIComponent(shareText) +
    "&url=" +
    encodeURIComponent(location.href)
  );
}

function getTodayKey() {
  const now = new Date();
  return now.toISOString().slice(0, 10);
}

function getShareRewardKey() {
  return "share_reward_" + getTodayKey();
}

function hasReceivedShareRewardToday() {
  return localStorage.getItem(getShareRewardKey()) === "1";
}

function markShareRewardReceived() {
  localStorage.setItem(getShareRewardKey(), "1");
}

async function giveShareRewardOncePerDay() {
  if (hasReceivedShareRewardToday()) return false;

  const userId = getOrCreateUserId();

  try {
    const response = await fetch(
      `${POINT_API_BASE}/${encodeURIComponent(userId)}/add?amount=${SHARE_REWARD_POINTS}&note=${encodeURIComponent("Xシェア報酬")}`,
      { method: "POST" }
    );

    if (!response.ok) {
      throw new Error("シェア報酬付与に失敗しました");
    }

    markShareRewardReceived();
    await loadUserPoints();
    updateTicket();
    return true;
  } catch (e) {
    console.error(e);
    return false;
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function resetPromptArea() {
  if (!promptBox || !togglePromptBtn || !copyPromptBtn) return;

  promptBox.style.display = "none";
  promptBox.innerHTML = "";
  togglePromptBtn.textContent = "プロンプトを見る";
  copyPromptBtn.style.display = "none";
  copyPromptBtn.textContent = "コピー";
}

function isNewWork(work) {
  const id = String(work.id ?? "");
  return !ownershipMap[id];
}

function isBuybackTarget(work) {
  return Number(work.buyback_price || 0) > 0;
}

function isOperatorPick(work) {
  return String(work.featured_type || "").trim() === "operator_pick";
}

async function getAvailableMachine() {
  try {
    const res = await fetch(VENDING_AVAILABLE_API, {
      cache: "no-store"
    });

    const data = await res.json();

    if (!res.ok) {
      return null;
    }

    if (!data.available) {
      return null;
    }

    return data;
  } catch (e) {
    console.error(e);
    return null;
  }
}

async function updateListingAreaForCurrentWork(work) {
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

  const available = await getAvailableMachine();

  listingArea.style.display = "block";

  if (!available) {
    listToMachineBtn.style.display = "none";

    if (listingFullBox) {
      listingFullBox.style.display = "block";
    }

    if (jackpotEl) {
      jackpotEl.style.display = "block";
      jackpotEl.textContent = "🎉 未出品作品を獲得！ただいま自販機は満杯です";
    }

    listingMessage.textContent = "未出品作品は獲得済みです。空きが出たら出品できるようになります。";
    return;
  }

  listToMachineBtn.style.display = "inline-flex";
  listingArea.dataset.machineId = String(available.machine.id);
  listingMessage.textContent =
    `この作品は100ptスタートで出品できます（空き ${available.remaining_slots} / 30）`;
}

function render(work) {
  currentWork = work;

  if (placeholder) placeholder.style.display = "none";
  if (meta) meta.style.display = "block";

  resetMedia();
  resetPromptArea();
  clearStageHitClasses();
  clearJackpotClasses();

  if (jackpotEl) {
    jackpotEl.style.display = "none";
    jackpotEl.textContent = "";
  }

  if (listingArea) {
    listingArea.style.display = "none";
    listingArea.dataset.machineId = "";
  }

  if (listingMessage) {
    listingMessage.textContent = "";
  }

  if (listToMachineBtn) {
    listToMachineBtn.style.display = "inline-flex";
    listToMachineBtn.disabled = false;
  }

  if (listingFullBox) {
    listingFullBox.style.display = "none";
  }

  const mediaType = getMediaType(work);
  const mediaUrl = getMediaUrl(work);
  const newWork = isNewWork(work);
  const buybackPrice = Number(work.buyback_price || 0);
  const operatorPick = isOperatorPick(work);
  const jackpotMessage = getJackpotMessage(work);

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

  const titleEl = document.getElementById("title");
  const creatorEl = document.getElementById("creator");
  const genreEl = document.getElementById("genre");
  const descriptionEl = document.getElementById("description");
  const mediaTypeEl = document.getElementById("mediaType");
  const likeCountEl = document.getElementById("likeCount");

  if (titleEl) titleEl.textContent = work.title || "";
  if (creatorEl) creatorEl.textContent = work.creator || "";
  if (genreEl) genreEl.textContent = work.genre || "";
  if (descriptionEl) descriptionEl.textContent = work.description || "";
  if (mediaTypeEl) mediaTypeEl.textContent = mediaType === "video" ? "動画" : "画像";
  if (likeCountEl) likeCountEl.textContent = work.likes || 0;

  if (linkButton) {
    if (work.link && work.link !== "#") {
      linkButton.href = work.link;
      linkButton.style.display = "inline-flex";
    } else {
      linkButton.style.display = "none";
    }
  }

  if (shareButton) {
    shareButton.href = buildShareUrl(work);
  }

  if (statusEl) {
    if (newWork) {
      statusEl.textContent = "🔥未出品（当たり）";
    } else {
      statusEl.textContent = "出品済み";
    }
  }

  if (buybackPriceEl) {
    buybackPriceEl.textContent = buybackPrice > 0 ? `${buybackPrice}pt` : "-";
  }

  if (featuredTypeEl) {
    featuredTypeEl.textContent = operatorPick ? "運営特選" : "-";
  }

  if (jackpotEl && jackpotMessage) {
    jackpotEl.style.display = "block";
    jackpotEl.textContent = jackpotMessage;
  }

  applyHitVisuals(work);

  if (getHitType(work) === "normal") {
    setRarityStyle(work.rarity, false);
  } else if (getHitType(work) === "rare") {
    setRarityStyle(work.rarity, false);
  }

  updateListingAreaForCurrentWork(work);
}

function renderLatestWorks() {
  const box = document.getElementById("latestWorks");
  if (!box) return;

  if (!works.length) {
    box.innerHTML = "<strong>新着作品</strong><br>まだ作品がありません";
    return;
  }

  const latest = [...works].slice(-3).reverse();

  box.innerHTML = `
    <strong>新着作品</strong><br>
    ${latest
      .map((work) => {
        const creator = work.creator || "投稿者";
        const genre = work.genre || "AI作品";
        const rarity = normalizeRarity(work.rarity);
        return `・${creator} / ${genre} / ${rarity}`;
      })
      .join("<br>")}
  `;
}

async function renderMachineStatus() {
  const box = document.getElementById("machineStatusBox");
  if (!box) return;

  try {
    const res = await fetch(VENDING_MACHINES_API, {
      cache: "no-store"
    });

    const data = await res.json();

    if (!res.ok) {
      box.innerHTML = "<strong>有料自販機の空き状況</strong><br>読み込みに失敗しました";
      return;
    }

    const machines = Array.isArray(data.items) ? data.items : [];

    if (!machines.length) {
      box.innerHTML = "<strong>有料自販機の空き状況</strong><br>現在稼働中の自販機はありません";
      return;
    }

    const rows = [];

    for (const machine of machines) {
      const detailRes = await fetch(`/api/vending-machines/${machine.id}`, {
        cache: "no-store"
      });

      const detailData = await detailRes.json();

      if (!detailRes.ok) {
        continue;
      }

      const currentCount = Number(detailData.current_count || 0);
      const remainingSlots = Number(detailData.remaining_slots || 0);

      rows.push(
        `・${machine.name}：${currentCount} / 30` +
        (remainingSlots > 0 ? `（空き ${remainingSlots}）` : "（満杯）")
      );
    }

    if (!rows.length) {
      box.innerHTML = "<strong>有料自販機の空き状況</strong><br>現在表示できる自販機情報がありません";
      return;
    }

    box.innerHTML = `
      <strong>有料自販機の空き状況</strong><br>
      ${rows.join("<br>")}
    `;
  } catch (e) {
    console.error(e);
    box.innerHTML = "<strong>有料自販機の空き状況</strong><br>読み込みに失敗しました";
  }
}

async function consumeDrawCostIfNeeded() {
  if (isPosterFreeUser()) {
    return true;
  }

  const userId = getOrCreateUserId();

  if (currentUserPoints < DRAW_COST) {
    alert(`ポイントが足りません。ガチャ1回 ${DRAW_COST}pt 必要です。`);
    return false;
  }

  try {
    const response = await fetch(
      `${POINT_API_BASE}/${encodeURIComponent(userId)}/use?amount=${DRAW_COST}&note=${encodeURIComponent("有料自販機ガチャ")}`,
      { method: "POST" }
    );

    const data = await response.json();

    if (!response.ok) {
      alert(data.detail || "ポイント消費に失敗しました");
      return false;
    }

    currentUserPoints = Number(data.user?.points || 0);
    currentPointExpireAt = data.user?.point_expire_at || "";
    updateTicket();
    return true;
  } catch (e) {
    console.error(e);
    alert("ポイント消費に失敗しました");
    return false;
  }
}

async function listCurrentWorkToMachine() {
  if (!currentWork || !listingMessage || !listingArea || !listToMachineBtn) return;

  const machineId = listingArea.dataset.machineId;

  if (!machineId) {
    listingMessage.textContent = "出品先の自販機が見つかりません。";
    return;
  }

  listingMessage.textContent = "自販機に追加しています...";
  listToMachineBtn.disabled = true;

  try {
    const res = await fetch(
      `/api/vending-machines/${machineId}/items?content_id=${encodeURIComponent(currentWork.id)}&item_order=0`,
      {
        method: "POST"
      }
    );

    const data = await res.json();

    if (!res.ok) {
      listingMessage.textContent = data.detail || "自販機追加に失敗しました。";
      listToMachineBtn.disabled = false;
      return;
    }

    listingMessage.textContent = "100ptスタートで自販機に出品しました！";
    listToMachineBtn.style.display = "none";

    ownershipMap[String(currentWork.id)] = {
      content_id: Number(currentWork.id),
      status: "listed"
    };

    if (statusEl) {
      statusEl.textContent = "出品済み";
    }

    if (jackpotEl) {
      jackpotEl.style.display = "none";
    }

    await renderMachineStatus();
  } catch (e) {
    console.error(e);
    listingMessage.textContent = "通信に失敗しました。";
    listToMachineBtn.disabled = false;
  }
}

if (drawButton) {
  drawButton.addEventListener("click", async () => {
    if (isDrawing || !works.length) return;

    isDrawing = true;
    drawButton.disabled = true;

    const ok = await consumeDrawCostIfNeeded();

    if (!ok) {
      drawButton.disabled = false;
      isDrawing = false;
      return;
    }

    const selectedWork = drawRandom();
    const revealDelay = getRevealDelayMs(selectedWork);

    if (stage) {
      clearStageHitClasses();
      stage.classList.add("animating", "reveal-delay");
    }

    setTimeout(() => {
      render(selectedWork);
      if (stage) {
        stage.classList.remove("reveal-delay");
      }
    }, Math.max(450, revealDelay - 250));

    setTimeout(() => {
      if (stage) {
        stage.classList.remove("animating");
      }
      drawButton.disabled = false;
      isDrawing = false;
    }, revealDelay);
  });
}

if (listToMachineBtn) {
  listToMachineBtn.addEventListener("click", async () => {
    await listCurrentWorkToMachine();
  });
}

if (likeButton) {
  likeButton.addEventListener("click", async () => {
    if (!currentWork) return;

    likeButton.disabled = true;

    try {
      const response = await fetch(API_URL, {
        method: "POST",
        headers: {
          "Content-Type": "text/plain;charset=utf-8"
        },
        body: JSON.stringify({
          mode: "like",
          id: getWorkId(currentWork)
        })
      });

      const data = await response.json();

      if (data.success) {
        const likeCountEl = document.getElementById("likeCount");
        if (likeCountEl) {
          likeCountEl.textContent = data.likes || 0;
        }
        currentWork.likes = data.likes || 0;
      } else {
        alert("いいねに失敗しました");
      }
    } catch (e) {
      console.error(e);
      alert("いいねに失敗しました");
    } finally {
      likeButton.disabled = false;
    }
  });
}

if (shareButton) {
  shareButton.addEventListener("click", async (e) => {
    if (!currentWork) {
      e.preventDefault();
      alert("先にガチャを引いてください");
      return;
    }

    const rewarded = await giveShareRewardOncePerDay();

    setTimeout(() => {
      alert(
        rewarded
          ? `シェアありがとう！${SHARE_REWARD_POINTS}ポイント付与しました。`
          : "シェアありがとう！報酬は1日1回までです。"
      );
    }, 200);
  });
}

if (togglePromptBtn) {
togglePromptBtn.addEventListener("click", () => {
    if (!currentWork) return;

    const prompt = (currentWork.prompt || "").trim();
    const negativePrompt = (currentWork.negativePrompt || "").trim();

    if (!prompt && !negativePrompt) {
      alert("この作品にはプロンプトがありません");
      return;
    }

    const isOpen = promptBox.style.display === "block";

    if (isOpen) {
      promptBox.style.display = "none";
      togglePromptBtn.textContent = "プロンプトを見る";
      copyPromptBtn.style.display = "none";
      return;
    }

    let html = "";

    if (prompt) {
      html += "<strong>Prompt:</strong><br>" + escapeHtml(prompt) + "<br><br>";
    }

    if (negativePrompt) {
      html += "<strong>Negative:</strong><br>" + escapeHtml(negativePrompt);
    }

    promptBox.innerHTML = html;
    promptBox.style.display = "block";
    togglePromptBtn.textContent = "閉じる";
    copyPromptBtn.style.display = "inline-flex";
  });
}

if (copyPromptBtn) {
  copyPromptBtn.addEventListener("click", async () => {
    if (!currentWork) return;

    const prompt = (currentWork.prompt || "").trim();
    const negativePrompt = (currentWork.negativePrompt || "").trim();

    if (!prompt && !negativePrompt) {
      alert("コピーできるプロンプトがありません");
      return;
    }

    let text = "";

    if (prompt) {
      text += prompt;
    }

    if (negativePrompt) {
      text += (text ? "\n\n" : "") + "Negative: " + negativePrompt;
    }

    try {
      await navigator.clipboard.writeText(text);
      copyPromptBtn.textContent = "コピー済み";
      setTimeout(() => {
        copyPromptBtn.textContent = "コピー";
      }, 1200);
    } catch (e) {
      console.error(e);
      alert("コピーに失敗しました");
    }
  });
}

if (shareButton) {
  shareButton.href = buildShareUrl(null);
}

(async function init() {
  getOrCreateUserId();
  await Promise.all([
    loadWorks(),
    loadOwnerships(),
    loadUserPoints(),
    renderMachineStatus()
  ]);
  updateTicket();
})();
