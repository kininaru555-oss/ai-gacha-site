let works = [];
let currentWork = null;
let isDrawing = false;
let ownershipMap = {};
let currentUserPoints = 0;
let currentPointExpireAt = "";

const API_URL = "https://script.google.com/macros/s/AKfycbzRW9dHBTOaRkM8gibA09i9L8zSiDDdd1YNWikqT4wn7zQWSaJQpo3-5CJx61od6-sNbQ/exec";
const OWNERSHIP_API = "/api/ownerships";
const POINT_API_BASE = "/api/points";
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

function render(work) {
  currentWork = work;

  if (placeholder) placeholder.style.display = "none";
  if (meta) meta.style.display = "block";

  resetMedia();
  resetPromptArea();

  if (jackpotEl) {
    jackpotEl.style.display = "none";
    jackpotEl.textContent = "🎉 当たり！";
  }

  if (listingArea) {
    listingArea.style.display = "none";
  }

  if (listingMessage) {
    listingMessage.textContent = "";
  }

  const mediaType = getMediaType(work);
  const mediaUrl = getMediaUrl(work);
  const newWork = isNewWork(work);
  const buybackPrice = Number(work.buyback_price || 0);
  const operatorPick = isOperatorPick(work);

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

  if (newWork && jackpotEl) {
    jackpotEl.style.display = "block";
    jackpotEl.textContent = "🎉 未出品作品！自販機出品権を獲得！";
    if (listingArea) {
      listingArea.style.display = "block";
    }
  } else if (buybackPrice > 0 && jackpotEl) {
    jackpotEl.style.display = "block";
    jackpotEl.textContent = `🎉 高価還元対象！${buybackPrice}ポイントバック対象です`;
  } else if (operatorPick && jackpotEl) {
    jackpotEl.style.display = "block";
    jackpotEl.textContent = "⭐ 運営特選作品を引きました！";
  }

  setRarityStyle(work.rarity, newWork || buybackPrice > 0);
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
  if (!currentWork || !listingMessage) return;

  listingMessage.textContent = "このページの自販機追加機能は後で接続します。";
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

    if (stage) {
      stage.classList.add("animating");
    }

    setTimeout(() => {
      render(drawRandom());
    }, 500);

    setTimeout(() => {
      if (stage) {
        stage.classList.remove("animating");
      }
      drawButton.disabled = false;
      isDrawing = false;
    }, 850);
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
    loadUserPoints()
  ]);
  updateTicket();
})();
