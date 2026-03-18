let works = [];
let currentWork = null;
let isDrawing = false;

// ★ 新しいGAS URL
const API_URL = "https://script.google.com/macros/s/AKfycbwLrNDEaGQyPJVwq3ggfOfUpHQe0gIrfCrcoXJTs6SRXbBTX957uSY3ndsi_f_ylV12jw/exec";

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

    if (!response.ok) throw new Error("APIエラー");

    const raw = await response.json();
    works = Array.isArray(raw) ? raw : [];

    if (!works.length) {
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

// ★ 重要：ID統一
function getWorkId(work) {
  return work.id || (
    (work.title || "") + "_" +
    (work.creator || "") + "_" +
    (work.file || "")
  );
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

function optimizeCloudinary(url) {
  if (!url) return "";
  if (url.includes("res.cloudinary.com") && !url.includes("f_auto")) {
    return url.replace("/upload/", "/upload/f_auto,q_auto/");
  }
  return url;
}

function normalizeRarity(r) {
  if (!r) return "N";
  const v = String(r).toUpperCase();
  if (v === "SSR") return "SSR";
  if (v === "SR") return "SR";
  if (v === "R") return "R";
  return "N";
}

function setRarityStyle(r) {
  const rarity = document.getElementById("rarity");
  const v = normalizeRarity(r);

  rarity.textContent = v;
  stage.classList.remove("rare", "ssr");

  if (v === "SSR") stage.classList.add("ssr");
  else if (v === "SR" || v === "R") stage.classList.add("rare");
}

function resetMedia() {
  resultImage.style.display = "none";
  resultVideo.style.display = "none";
  resultVideo.pause();
  resultVideo.src = "";
}

function render(work) {
  currentWork = work;

  placeholder.style.display = "none";
  meta.style.display = "block";

  resetMedia();

  const url = optimizeCloudinary(work.file);

  if (work.type === "video") {
    resultVideo.src = url;
    resultVideo.style.display = "block";
  } else {
    resultImage.src = url;
    resultImage.style.display = "block";
  }

  document.getElementById("title").textContent = work.title || "";
  document.getElementById("creator").textContent = work.creator || "";
  document.getElementById("genre").textContent = work.genre || "";
  document.getElementById("description").textContent = work.description || "";
  document.getElementById("likeCount").textContent = work.likes || 0;

  if (work.link && work.link !== "#") {
    linkButton.href = work.link;
    linkButton.style.display = "inline-flex";
  } else {
    linkButton.style.display = "none";
  }

  setRarityStyle(work.rarity);
}

function weightedDraw() {
  return works[Math.floor(Math.random() * works.length)];
}

drawButton.addEventListener("click", () => {
  if (isDrawing || !works.length) return;

  const ticket = getTicket();
  if (ticket <= 0) {
    alert("チケットがありません");
    return;
  }

  isDrawing = true;
  drawButton.disabled = true;

  setTicket(ticket - 1);
  updateTicket();

  setTimeout(() => {
    render(weightedDraw());
    drawButton.disabled = false;
    isDrawing = false;
  }, 500);
});

// ★ いいね
likeButton.addEventListener("click", async () => {
  if (!currentWork) return;

  try {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: JSON.stringify({
        mode: "like",
        id: getWorkId(currentWork)
      })
    });

    const data = await res.json();

    if (data.success) {
      currentWork.likes = data.likes;
      document.getElementById("likeCount").textContent = data.likes;
    } else {
      alert("いいね失敗");
    }
  } catch (e) {
    console.error(e);
    alert("通信エラー");
  }
});

loadWorks();
updateTicket();
