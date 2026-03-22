// gacha-dom.js
// NOTE: このファイルはDOMの参照のみ行う。副作用（appendChild等）は
//       DOMContentLoaded後に呼ぶ initDom() に集約する。

// ===== 基本UI =====
export const drawButton = document.getElementById("drawButton");
export const stage      = document.getElementById("stage");
export const placeholder= document.getElementById("placeholder");
export const ticketInfo = document.getElementById("ticketInfo");
export const statusEl   = document.getElementById("statusBox");

// ===== 表示エリア =====
export const meta = document.getElementById("meta");

// ===== 自販機関連 =====
export const listingArea      = document.getElementById("listingArea");
export const listToMachineBtn = document.getElementById("listToMachineBtn");
export const listingMessage   = document.getElementById("listingMessage");
export const machineStatusBox = document.getElementById("machineStatusBox");

// ===== ナビ =====
export const mypageBtn = document.getElementById("mypageBtn");

// ===== 最新作品 =====
export const latestWorksBox = document.getElementById("latestWorks");

// ===== メタ情報 =====
export const titleEl       = document.getElementById("title");
export const creatorEl     = document.getElementById("creator");
export const genreEl       = document.getElementById("genre");
export const descriptionEl = document.getElementById("description");
export const mediaTypeEl   = document.getElementById("mediaType");
export const rarityEl      = document.getElementById("rarity");

// ===== 演出: jackpotEl =====
// ── 修正: トップレベルでのDOM副作用をやめ、遅延生成に変更 ──
// gacha-app.js の init() 内で initDom() を呼ぶこと
let _jackpotEl = null;

export function getJackpotEl() {
  return _jackpotEl;
}

export function initDom() {
  if (_jackpotEl || !meta) return;

  _jackpotEl = document.createElement("div");
  _jackpotEl.id = "jackpot";
  _jackpotEl.style.display     = "none";
  _jackpotEl.style.color       = "gold";
  _jackpotEl.style.fontWeight  = "bold";
  _jackpotEl.style.marginTop   = "10px";
  _jackpotEl.textContent       = "🎉 当たり！";
  meta.appendChild(_jackpotEl);
}

// 後方互換: 直接参照している箇所は getJackpotEl() に移行すること
// gacha-utils.js / gacha-render.js は getJackpotEl() を使う
export { _jackpotEl as jackpotEl };
