export const drawButton = document.getElementById("drawButton");
export const stage = document.getElementById("stage");
export const placeholder = document.getElementById("placeholder");
export const resultImage = document.getElementById("resultImage");
export const resultVideo = document.getElementById("resultVideo");
export const meta = document.getElementById("meta");
export const ticketInfo = document.getElementById("ticketInfo");
export const statusEl = document.getElementById("status");
export const buybackPriceEl = document.getElementById("buybackPrice");
export const featuredTypeEl = document.getElementById("featuredType");
export const listingArea = document.getElementById("listingArea");
export const listToMachineBtn = document.getElementById("listToMachineBtn");
export const listingMessage = document.getElementById("listingMessage");
export const listingFullBox = document.getElementById("listingFullBox");
export const machineStatusBox = document.getElementById("machineStatusBox");
export const mypageBtn = document.getElementById("mypageBtn");
export const latestWorksBox = document.getElementById("latestWorks");

export const titleEl = document.getElementById("title");
export const creatorEl = document.getElementById("creator");
export const genreEl = document.getElementById("genre");
export const descriptionEl = document.getElementById("description");
export const mediaTypeEl = document.getElementById("mediaType");
export const rarityEl = document.getElementById("rarity");

export const jackpotEl = document.createElement("div");
jackpotEl.id = "jackpot";
jackpotEl.style.display = "none";
jackpotEl.style.color = "gold";
jackpotEl.style.fontWeight = "bold";
jackpotEl.style.marginTop = "10px";
jackpotEl.textContent = "🎉 当たり！";

if (meta) {
  meta.appendChild(jackpotEl);
}
