let works = [];
let currentWork = null;
let isDrawing = false;

const API_URL = "https://script.google.com/macros/s/AKfycbxh7CW4kVBf1gjBbGzSTq-G8cUEpQ-06347Wlzk2m1VZFPDHgP-JWDWiPVAtCdjvBD1Xw/exec";

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

async function loadWorks() {
  try {
    const response = await fetch(API_URL, { cache: "no-store" });

    if (!response.ok) {
      throw new Error("APIの読み込みに失敗しました");
    }

    works = await response.json();

    if (!Array.isArray(works) || works.length === 0) {
      placeholder.textContent = "まだ投稿作品がありません";
      drawButton.disabled = true;
      return;
    }

    drawButton.disabled = false;
  } catch (e) {
    placeholder.textContent = "作品を読み込めません";
    drawButton.disabled = true;
    console.error(e);
  }
}

function getTicket() {
  return parseInt(localStorage.getItem("gacha_ticket") || "0", 10);
}

function setTicket(n) {
  localStorage.setItem("gacha_ticket", String(Math.max(0, n)));
}

function updateTicket() {
  const t = getTicket();

  if (t > 0) {
    ticketInfo.textContent = "ガチャチケット：" + t + "枚";
  } else {
    ticketInfo.textContent = "投稿するとガチャを1回引けます";
  }
}

function getLikes() {
  const raw = localStorage.getItem("likes");
  return raw ? JSON.parse(raw) : {};
}

function setLikes(likes) {
  localStorage.setItem("likes", JSON.stringify(likes));
}

function getWorkId(work) {
  return work.id || ((work.title || "") + "_" + (work.creator || ""));
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

function setRarityStyle(rarityText) {
  const rarity = document.getElementById("rarity");
  const r = normalizeRarity(rarityText);

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
  resultImage.style.display = "none";
  resultVideo.style.display = "none";
  resultVideo.pause();
  resultVideo.removeAttribute("src");
  resultVideo.load();
}

function weightedDraw() {
  const recommended = works.filter(w => w.recommended === true);
  const ssr = works.filter(w => normalizeRarity(w.rarity) === "SSR");
  const sr = works.filter(w => normalizeRarity(w.rarity) === "SR");
  const r = works.filter(w => normalizeRarity(w.rarity) === "R");
  const n = works.filter(w => normalizeRarity(w.rarity) === "N");

  const roll = Math.random() * 100;

  if (roll < 8 && recommended.length) {
    return recommended[Math.floor(Math.random() * recommended.length)];
  }

  if (roll < 10 && ssr.length) {
    return ssr[Math.floor(Math.random() * ssr.length)];
  }

  if (roll < 20 && sr.length) {
    return sr[Math.floor(Math.random() * sr.length)];
  }

  if (roll < 45 && r.length) {
    return r[Math.floor(Math.random() * r.length)];
  }

  if (n.length) {
    return n[Math.floor(Math.random() * n.length)];
  }

  return works[Math.floor(Math.random() * works.length)];
}

function buildShareText(work) {
  if (!work) return "無料AIガチャMAX R18";

  return (
    "無料AIガチャで " +
    normalizeRarity(work.rarity) +
    " を引いた！\n" +
    "作品：「" + (work.title || "") + "」\n" +
    "作者：" + (work.creator || "不明") + "\n" +
    "#AIガチャ #AI画像"
  );
}

function getTodayKey() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return y + "-" + m + "-" + d;
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

function giveShareRewardOncePerDay() {
  if (hasReceivedShareRewardToday()) {
    return false;
  }

  const ticket = getTicket();
  setTicket(ticket + 1);
  markShareRewardReceived();
  updateTicket();
  return true;
}

function render(work) {
  currentWork = work;

  placeholder.style.display = "none";
  meta.style.display = "block";

  resetMedia();

  const file = optimizeCloudinary(work.file);

  if (work.type === "video") {
    resultVideo.src = file;
    resultVideo.style.display = "block";
    resultVideo.play().catch(() => {});
  } else {
    resultImage.src = file;
    resultImage.alt = work.title || "作品画像";
    resultImage.style.display = "block";
  }

  document.getElementById("title").textContent = work.title || "";
  document.getElementById("creator").textContent = work.creator || "";
  document.getElementById("genre").textContent = work.genre || "";
  document.getElementById("description").textContent = work.description || "";
  document.getElementById("mediaType").textContent = work.type === "video" ? "動画" : "画像";

  const likes = getLikes();
  const id = getWorkId(work);
  document.getElementById("likeCount").textContent = likes[id] || 0;

  if (work.link && work.link !== "#") {
    linkButton.href = work.link;
    linkButton.style.display = "inline-flex";
  } else {
    linkButton.style.display = "none";
  }

  const shareText = buildShareText(work);

  shareButton.href =
    "https://twitter.com/intent/tweet?text=" +
    encodeURIComponent(shareText) +
    "&url=" +
    encodeURIComponent(location.href);

  setRarityStyle(work.rarity);
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
    ${latest.map(work => {
      const creator = work.creator || "投稿者";
      const genre = work.genre || "AI作品";
      const rarity = work.rarity || "NORMAL";
      return `${creator} / ${genre} / ${rarity}`;
    }).join("<br>")}
  `;
}

drawButton.addEventListener("click", () => {
  if (isDrawing) return;
  if (!works.length) return;

  const ticket = getTicket();

  if (ticket <= 0) {
    if (confirm("ガチャチケットがありません。\n作品投稿で1枚GETできます。投稿ページへ移動しますか？")) {
      window.location.href = "upload.html";
    }
    return;
  }

  isDrawing = true;
  drawButton.disabled = true;

  setTicket(ticket - 1);
  updateTicket();

  stage.classList.add("animating");

  setTimeout(() => {
    const work = weightedDraw();
    render(work);
  }, 500);

  setTimeout(() => {
    stage.classList.remove("animating");
    drawButton.disabled = false;
    isDrawing = false;
  }, 850);
});

likeButton.addEventListener("click", () => {
  if (!currentWork) return;

  const likes = getLikes();
  const id = getWorkId(currentWork);

  likes[id] = (likes[id] || 0) + 1;
  setLikes(likes);

  document.getElementById("likeCount").textContent = likes[id];
});

shareButton.addEventListener("click", () => {
  const rewarded = giveShareRewardOncePerDay();

  if (rewarded) {
    setTimeout(() => {
      alert("シェアありがとう！本日のシェア報酬でチケット+1しました。");
    }, 200);
  } else {
    setTimeout(() => {
      alert("シェアありがとう！シェア報酬は1日1回までです。");
    }, 200);
  }
});

loadWorks().then(() => {
  renderLatestWorks();
});

updateTicket();