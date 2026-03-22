const API_BASE = "http://127.0.0.1:8000";
const AUTH_STORAGE_KEY = "gacha_app_auth_v1";
const RESULT_STORAGE_KEY = "gacha_last_result";

const userIdInput = document.getElementById("userIdInput");
const passwordInput = document.getElementById("passwordInput");
const loginButton = document.getElementById("loginButton");
const logoutButton = document.getElementById("logoutButton");
const loginStatus = document.getElementById("loginStatus");

const pointsText = document.getElementById("pointsText");
const expText = document.getElementById("expText");
const levelText = document.getElementById("levelText");
const freeDrawText = document.getElementById("freeDrawText");
const reviveText = document.getElementById("reviveText");
const ballText = document.getElementById("ballText");

const freeDrawButton = document.getElementById("freeDrawButton");
const paidDrawButton = document.getElementById("paidDrawButton");

const placeholder = document.getElementById("placeholder");
const resultImage = document.getElementById("resultImage");
const resultVideo = document.getElementById("resultVideo");

const systemMessage = document.getElementById("systemMessage");

let authUser = null;
let isDrawing = false;

function showMessage(text) {
  systemMessage.textContent = text;
  systemMessage.classList.add("show");
}

function clearMessage() {
  systemMessage.textContent = "";
  systemMessage.classList.remove("show");
}

function saveAuth(data) {
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(data));
}

function loadAuth() {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function clearAuth() {
  localStorage.removeItem(AUTH_STORAGE_KEY);
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw new Error(data.detail || "APIエラー");
  }

  return data;
}

function updateLoginUI() {
  if (authUser && authUser.user_id) {
    loginStatus.textContent = `ログイン中: ${authUser.user_id}`;
    logoutButton.style.display = "block";
  } else {
    loginStatus.textContent = "未ログイン";
    logoutButton.style.display = "none";
  }
}

function updateStatusUI(user) {
  if (!user) return;
  pointsText.textContent = user.points ?? 0;
  expText.textContent = user.exp ?? 0;
  levelText.textContent = user.level ?? 1;
  freeDrawText.textContent = user.free_draw_count ?? 0;
  reviveText.textContent = user.revive_item_count ?? 0;
  ballText.textContent = `${user.ball_count ?? 0} / 7`;
}

function clearPreview() {
  resultImage.style.display = "none";
  resultVideo.style.display = "none";
  resultImage.src = "";
  resultVideo.pause();
  resultVideo.removeAttribute("src");
  resultVideo.load();
  placeholder.style.display = "block";
}

function previewResult(result) {
  if (!result) return;
  placeholder.style.display = "none";

  if (result.type === "video" && result.video_url) {
    resultVideo.src = result.video_url;
    resultVideo.style.display = "block";
    resultImage.style.display = "none";
  } else {
    resultImage.src = result.image_url || "";
    resultImage.style.display = "block";
    resultVideo.style.display = "none";
  }
}

async function refreshUser() {
  if (!authUser || !authUser.user_id) return;
  const data = await api(`/users/${encodeURIComponent(authUser.user_id)}`);
  authUser = { ...authUser, ...data };
  saveAuth(authUser);
  updateStatusUI(authUser);
  updateLoginUI();
}

async function handleLogin() {
  const userId = (userIdInput.value || "").trim();
  const password = (passwordInput.value || "").trim();

  if (!userId || !password) {
    showMessage("ユーザーIDと簡易パスワードを入力してください。");
    return;
  }

  try {
    clearMessage();
    loginButton.disabled = true;
    loginButton.textContent = "ログイン中...";

    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        user_id: userId,
        password: password
      })
    });

    authUser = data;
    saveAuth(authUser);
    updateLoginUI();
    updateStatusUI(authUser);
    showMessage("ログインしました。");
  } catch (error) {
    showMessage(error.message || "ログインに失敗しました。");
  } finally {
    loginButton.disabled = false;
    loginButton.textContent = "ログイン / 新規作成";
  }
}

function handleLogout() {
  authUser = null;
  clearAuth();
  updateLoginUI();
  updateStatusUI({
    points: 0,
    exp: 0,
    level: 1,
    free_draw_count: 0,
    revive_item_count: 0,
    ball_count: 0
  });
  clearPreview();
  showMessage("ログアウトしました。");
}

async function drawGacha(type) {
  if (isDrawing) return;
  if (!authUser || !authUser.user_id) {
    showMessage("先にログインしてください。");
    return;
  }

  try {
    isDrawing = true;
    clearMessage();

    freeDrawButton.disabled = true;
    paidDrawButton.disabled = true;
    freeDrawButton.textContent = "ガチャ中...";
    paidDrawButton.textContent = "ガチャ中...";

    const path = type === "paid"
      ? `/gacha/paid/${encodeURIComponent(authUser.user_id)}`
      : `/gacha/free/${encodeURIComponent(authUser.user_id)}`;

    const data = await api(path, { method: "POST" });

    previewResult(data.result);
    localStorage.setItem(RESULT_STORAGE_KEY, JSON.stringify(data));

    await refreshUser();

    location.href = "result.html";
  } catch (error) {
    showMessage(error.message || "ガチャに失敗しました。");
  } finally {
    isDrawing = false;
    freeDrawButton.disabled = false;
    paidDrawButton.disabled = false;
    freeDrawButton.textContent = "無料ガチャ";
    paidDrawButton.textContent = "30ptガチャ";
  }
}

function boot() {
  authUser = loadAuth();
  updateLoginUI();

  if (authUser) {
    refreshUser().catch(() => {});
  } else {
    updateStatusUI({
      points: 0,
      exp: 0,
      level: 1,
      free_draw_count: 0,
      revive_item_count: 0,
      ball_count: 0
    });
  }

  clearPreview();

  loginButton.addEventListener("click", handleLogin);
  logoutButton.addEventListener("click", handleLogout);
  freeDrawButton.addEventListener("click", () => drawGacha("free"));
  paidDrawButton.addEventListener("click", () => drawGacha("paid"));

  passwordInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      handleLogin();
    }
  });
}

document.addEventListener("DOMContentLoaded", boot);
