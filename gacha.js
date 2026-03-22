const API_BASE = "http://127.0.0.1:8000";  // 本番では環境変数化推奨
const AUTH_STORAGE_KEY = "gacha_app_auth_v1";
const RESULT_STORAGE_KEY = "gacha_last_result";

const elements = {
  userIdInput: document.getElementById("userIdInput"),
  passwordInput: document.getElementById("passwordInput"),
  loginButton: document.getElementById("loginButton"),
  logoutButton: document.getElementById("logoutButton"),
  loginStatus: document.getElementById("loginStatus"),
  pointsText: document.getElementById("pointsText"),
  expText: document.getElementById("expText"),
  levelText: document.getElementById("levelText"),
  freeDrawText: document.getElementById("freeDrawText"),
  reviveText: document.getElementById("reviveText"),
  ballText: document.getElementById("ballText"),
  freeDrawButton: document.getElementById("freeDrawButton"),
  paidDrawButton: document.getElementById("paidDrawButton"),
  placeholder: document.getElementById("placeholder"),
  resultImage: document.getElementById("resultImage"),
  resultVideo: document.getElementById("resultVideo"),
  systemMessage: document.getElementById("systemMessage"),
  stage: document.getElementById("stage"),  // 演出用
};

let authUser = null;
let isDrawing = false;

function showMessage(text, isError = false) {
  elements.systemMessage.textContent = text;
  elements.systemMessage.style.color = isError ? "#ff6b6b" : "#4ade80";
  elements.systemMessage.classList.add("show");
}

function clearMessage() {
  elements.systemMessage.textContent = "";
  elements.systemMessage.classList.remove("show");
}

function saveAuth(data) {
  // password は絶対保存しない
  const safeData = { user_id: data.user_id, token: data.token };
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(safeData));
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
  const headers = {
    "Content-Type": "application/json",
    ...(authUser?.token ? { "Authorization": `Bearer ${authUser.token}` } : {}),
    ...(options.headers || {}),
  };

  const res = await fetch(`\( {API_BASE} \){path}`, {
    ...options,
    headers,
  });

  let data;
  try {
    data = await res.json();
  } catch {
    data = {};
  }

  if (!res.ok) {
    throw new Error(data.detail || data.message || `HTTP ${res.status}`);
  }

  return data;
}

function updateLoginUI() {
  if (authUser?.user_id) {
    elements.loginStatus.textContent = `ログイン中: ${authUser.user_id}`;
    elements.logoutButton.style.display = "block";
    elements.loginButton.style.display = "none";
  } else {
    elements.loginStatus.textContent = "未ログイン";
    elements.logoutButton.style.display = "none";
    elements.loginButton.style.display = "block";
  }
}

function updateStatusUI(user = {}) {
  elements.pointsText.textContent    = user.points ?? 0;
  elements.expText.textContent       = user.exp ?? 0;
  elements.levelText.textContent     = user.level ?? 1;
  elements.freeDrawText.textContent  = user.free_draw_count ?? 0;
  elements.reviveText.textContent    = user.revive_item_count ?? 0;
  elements.ballText.textContent      = `${user.ball_count ?? 0} / 7`;
}

function updateDrawButtons() {
  if (!authUser) {
    elements.freeDrawButton.disabled = true;
    elements.paidDrawButton.disabled = true;
    return;
  }

  const hasFree = (authUser.free_draw_count ?? 0) > 0;
  const hasPoints = (authUser.points ?? 0) >= 30;

  elements.freeDrawButton.disabled = !hasFree;
  elements.paidDrawButton.disabled = !hasPoints;

  elements.freeDrawButton.textContent = hasFree ? "無料ガチャ" : "無料回数0";
  elements.paidDrawButton.textContent = hasPoints ? "30ptガチャ" : "pt不足";
}

function clearPreview() {
  elements.resultImage.style.display = "none";
  elements.resultVideo.style.display = "none";
  elements.resultImage.src = "";
  elements.resultVideo.pause();
  elements.resultVideo.removeAttribute("src");
  elements.resultVideo.load();
  elements.placeholder.style.display = "block";
  elements.stage.classList.remove("ssr", "rare");
}

function previewResult(result) {
  if (!result) return;
  elements.placeholder.style.display = "none";

  if (result.type === "video" && result.video_url) {
    elements.resultVideo.src = result.video_url;
    elements.resultVideo.style.display = "block";
    elements.resultImage.style.display = "none";
  } else if (result.image_url) {
    elements.resultImage.src = result.image_url;
    elements.resultImage.style.display = "block";
    elements.resultVideo.style.display = "none";
  }

  // レアリティによるクラス付与（CSSで光らせたい場合）
  if (result.rarity === "SSR") {
    elements.stage.classList.add("ssr");
  } else if (result.rarity === "RARE") {
    elements.stage.classList.add("rare");
  }
}

async function refreshUser() {
  if (!authUser?.user_id) return;
  try {
    const data = await api(`/users/${encodeURIComponent(authUser.user_id)}`);
    authUser = { ...authUser, ...data };
    saveAuth(authUser);
    updateStatusUI(authUser);
    updateDrawButtons();
  } catch (err) {
    console.error("ユーザー情報更新失敗", err);
  }
}

async function handleLogin() {
  const userId = elements.userIdInput.value.trim();
  const password = elements.passwordInput.value.trim();

  if (!userId || !password) {
    showMessage("ユーザーIDとパスワードを入力してください", true);
    return;
  }

  try {
    elements.loginButton.disabled = true;
    elements.loginButton.textContent = "ログイン中...";
    clearMessage();

    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, password }),
    });

    authUser = data;
    saveAuth(authUser);
    updateLoginUI();
    await refreshUser();
    showMessage("ログイン成功！");
  } catch (err) {
    showMessage(err.message || "ログインに失敗しました", true);
  } finally {
    elements.loginButton.disabled = false;
    elements.loginButton.textContent = "ログイン / 新規作成";
  }
}

function handleLogout() {
  authUser = null;
  clearAuth();
  updateLoginUI();
  updateStatusUI();
  updateDrawButtons();
  clearPreview();
  showMessage("ログアウトしました");
}

async function drawGacha(type) {
  if (isDrawing || !authUser) return;

  isDrawing = true;
  clearMessage();

  const btn = type === "paid" ? elements.paidDrawButton : elements.freeDrawButton;
  btn.disabled = true;
  btn.textContent = "ガチャ中...";
  elements.stage.classList.add("animating");

  try {
    const path = type === "paid"
      ? `/gacha/paid/${encodeURIComponent(authUser.user_id)}`
      : `/gacha/free/${encodeURIComponent(authUser.user_id)}`;

    const data = await api(path, { method: "POST" });

    previewResult(data.result);
    localStorage.setItem(RESULT_STORAGE_KEY, JSON.stringify(data));

    await refreshUser();

    // 演出を少し見せてから結果ページへ
    setTimeout(() => {
      location.href = "result.html";
    }, 1200);

  } catch (err) {
    let msg = "ガチャに失敗しました";
    if (err.message.includes("points")) msg = "ポイントが不足しています";
    if (err.message.includes("free"))  msg = "無料回数がありません";
    showMessage(msg, true);
  } finally {
    isDrawing = false;
    btn.disabled = false;
    btn.textContent = type === "paid" ? "30ptガチャ" : "無料ガチャ";
    elements.stage.classList.remove("animating");
    updateDrawButtons();
  }
}

function init() {
  authUser = loadAuth();
  updateLoginUI();

  if (authUser) {
    refreshUser().catch(() => {});
  } else {
    updateStatusUI();
    updateDrawButtons();
  }

  clearPreview();

  // イベントリスナー
  elements.loginButton.addEventListener("click", handleLogin);
  elements.logoutButton.addEventListener("click", handleLogout);
  elements.freeDrawButton.addEventListener("click", () => drawGacha("free"));
  elements.paidDrawButton.addEventListener("click", () => drawGacha("paid"));

  elements.passwordInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleLogin();
  });
}

document.addEventListener("DOMContentLoaded", init);
