let works = [];
let currentWork = null;
let isDrawing = false;

const API_URL = "https://script.google.com/macros/s/AKfycbzWLUWKFwRJjIa6QVN8XPr7xRLFfTxmI34XBYb80yvIaDuxzzDR5caWnWEB8KQTUe4E4Q/exec";

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

async function loadWorks() {
  try {
    const response = await fetch(API_URL, { cache: "no-store" });

    if (!response.ok) {
      throw new Error("APIの読み込みに失敗しました");
    }

    const raw = await response.json();
    works = Array.isArray(raw) ? raw : (raw.items || []);

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
  ticketInfo.textContent =
    t > 0 ? "ガチャチケット：" + t + "枚" : "投稿するとガチャを1回引けます";
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

function weightedDraw() {
  const recommended = works.filter((w) => w.recommended === true);
  const ssr = works.filter((w) => normalizeRarity(w.rarity) === "SSR");
  const sr = works.filter((w) => normalizeRarity(w.rarity) === "SR");
  const r = works.filter((w) => normalizeRarity(w.rarity) === "R");
  const n = works.filter((w) => normalizeRarity(w.rarity) === "N");

  const roll = Math.random() * 100;

  if (roll < 8 && recommended.length) {
    return recommended[Math.floor(Math.random() * recommended.length)];
  }
  if (roll < 12 && ssr.length) {
    return ssr[Math.floor(Math.random() * ssr.length)];
  }
  if (roll < 25 && sr.length) {
    return sr[Math.floor(Math.random() * sr.length)];
  }
  if (roll < 55 && r.length) {
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

function giveShareRewardOncePerDay() {
  if (hasReceivedShareRewardToday()) return false;

  setTicket(getTicket() + 1);
  markShareRewardReceived();
  updateTicket();
  return true;
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

function render(work) {
  currentWork = work;

  placeholder.style.display = "none";
  meta.style.display = "block";

  resetMedia();
  resetPromptArea();

  const mediaType = getMediaType(work);
  const mediaUrl = getMediaUrl(work);

  if (mediaType === "video") {
    resultVideo.src = mediaUrl;
    resultVideo.style.display = "block";
    resultVideo.play().catch(() => {});
  } else {
    resultImage.src = mediaUrl;
    resultImage.alt = work.title || "作品画像";
    resultImage.style.display = "block";
  }

  document.getElementById("title").textContent = work.title || "";
  document.getElementById("creator").textContent = work.creator || "";
  document.getElementById("genre").textContent = work.genre || "";
  document.getElementById("description").textContent = work.description || "";
  document.getElementById("mediaType").textContent =
    mediaType === "video" ? "動画" : "画像";

  document.getElementById("likeCount").textContent = work.likes || 0;

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

drawButton.addEventListener("click", () => {
  if (isDrawing || !works.length) return;

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
    render(weightedDraw());
  }, 500);

  setTimeout(() => {
    stage.classList.remove("animating");
    drawButton.disabled = false;
    isDrawing = false;
  }, 850);
});

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
      document.getElementById("likeCount").textContent = data.likes || 0;
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

shareButton.addEventListener("click", () => {
  const rewarded = giveShareRewardOncePerDay();

  setTimeout(() => {
    alert(
      rewarded
        ? "シェアありがとう！チケット+1しました。"
        : "シェアありがとう！報酬は1日1回までです。"
    );
  }, 200);
});

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

loadWorks().then(() => {
  renderLatestWorks();
});

updateTicket();
