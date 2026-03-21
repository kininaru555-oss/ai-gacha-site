// ===== 基本UI =====
export const drawButton = document.getElementById("drawButton");
export const stage = document.getElementById("stage");
export const placeholder = document.getElementById("placeholder");

export const ticketInfo = document.getElementById("ticketInfo");
export const statusEl = document.getElementById("statusBox");

// ===== 表示エリア =====
export const meta = document.getElementById("meta");

// ===== 自販機関連 =====
export const listingArea = document.getElementById("listingArea");
export const listToMachineBtn = document.getElementById("listToMachineBtn");
export const listingMessage = document.getElementById("listingMessage");

export const machineStatusBox = document.getElementById("machineStatusBox");

// ===== ナビ =====
export const mypageBtn = document.getElementById("mypageBtn");

// ===== 最新作品 =====
export const latestWorksBox = document.getElementById("latestWorks");

// ===== メタ情報 =====
export const titleEl = document.getElementById("title");
export const creatorEl = document.getElementById("creator");
export const genreEl = document.getElementById("genre");
export const descriptionEl = document.getElementById("description");
export const mediaTypeEl = document.getElementById("mediaType");
export const rarityEl = document.getElementById("rarity");

// ===== 演出 =====
export const jackpotEl = (() => {
  const el = document.createElement("div");
  el.id = "jackpot";
  el.style.display = "none";
  el.style.color = "gold";
  el.style.fontWeight = "bold";
  el.style.marginTop = "10px";
  el.textContent = "🎉 当たり！";
  return el;
})();

// metaがあるページだけ追加
if (meta) {
  meta.appendChild(jackpotEl);
}
