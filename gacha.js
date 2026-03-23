const API_BASE = "http://127.0.0.1:8000";
const AUTH_STORAGE_KEY = "gacha_app_auth_v1";
const RESULT_STORAGE_KEY = "gacha_last_result";
const POST_SUCCESS_NOTICE_KEY = "gacha_post_success_notice";

let authUser = null;
let isDrawing = false;
let previousFreeDrawCount = null;

// DOM要素をまとめて管理（可読性UP）
const els = {
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
  rewardNotice: document.getElementById("rewardNotice"),
  rewardNoticeText: document.getElementById("rewardNoticeText"),
  rewardDrawButton: document.getElementById("rewardDrawButton"),
};

function showMessage(text, isError = false) {
  els.systemMessage.textContent = text;
  els.systemMessage.style.color = isError ? "#ff6b6b" : "#4ade80";
  els.systemMessage.classList.add("show");
}

function clearMessage() {
  els.systemMessage.textContent = "";
  els.systemMessage.classList.remove("show");
}

function showRewardNotice(text) {
  if (els.rewardNotice && els.rewardNoticeText) {
    els.rewardNoticeText.textContent = text;
    els.rewardNotice.style.display = "block";
  }
}

function clearRewardNotice() {
  if (els.rewardNotice) els.rewardNotice.style.display = "none";
  if (els.rewardNoticeText) els.rewardNoticeText.textContent = "";
}

function saveAuth(data) {
  // passwordは絶対保存しない
  const safe = { user_id: data.user_id, token: data.token };
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(safe));
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

function consumePostSuccessNotice() {
  try {
    const raw = localStorage.getItem(POST_SUCCESS_NOTICE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    localStorage.removeItem(POST_SUCCESS_NOTICE_KEY);
    return data;
  } catch {
    localStorage.removeItem(POST_SUCCESS_NOTICE_KEY);
    return null;
  }
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(authUser?.token ? { "Authorization": `Bearer ${authUser.token}` } : {}),
    ...(options.headers || {}),
  };

  const res = await fetch(`\( {API_BASE} \){path}`, { ...options, headers });
  let data;
  try { data = await res.json(); } catch { data = {}; }

  if (!res.ok) {
    throw new Error(data.detail || data.message || `APIエラー (${res.status})`);
  }
  return data;
}

function updateLoginUI() {
  if (authUser?.user_id) {
    els.loginStatus.textContent = `ログイン中: ${authUser.user_id}`;
    els.logoutButton.style.display = "block";
    els.loginButton.style.display = "none";
  } else {
    els.loginStatus.textContent = "未ログイン";
    els.logoutButton.style.display = "none";
    els.loginButton.style.display = "block";
  }
}

function updateDrawButtons() {
  if (!authUser) {
    els.freeDrawButton.disabled = true;
    els.paidDrawButton.disabled = true;
    return;
  }

  const hasFree = (authUser.free_draw_count ?? 0) > 0;
  const hasPoints = (authUser.points ?? 0) >= 30;

  els.freeDrawButton.disabled = !hasFree;
  els.paidDrawButton.disabled = !hasPoints;

  els.freeDrawButton.textContent = hasFree ? "無料ガチャ" : "無料回数0";
  els.paidDrawButton.textContent = hasPoints ? "30ptガチャ" : "pt不足";
}

function animateFreeDrawIncrease(oldValue, newValue) {
  if (oldValue == null || newValue <= oldValue) return;
  if (els.freeDrawText?.parentElement) {
    const box = els.freeDrawText.parentElement;
    box.classList.add("flash");
    setTimeout(() => box.classList.remove("flash"), 1200);
  }
}

function updateStatusUI(user = {}) {
  els.pointsText.textContent    = user.points ?? 0;
  els.expText.textContent       = user.exp ?? 0;
  els.levelText.textContent     = user.level ?? 1;
  const newFree = user.free_draw_count ?? 0;
  els.freeDrawText.textContent  = newFree;
  els.reviveText.textContent    = user.revive_item_count ?? 0;
  els.ballText.textContent      = `${user.ball_count ?? 0} / 7`;

  animateFreeDrawIncrease(previousFreeDrawCount, newFree);
  previousFreeDrawCount = newFree;

  updateDrawButtons();
}

function clearPreview() {
  els.resultImage.style.display = "none";
  els.resultVideo.style.display = "none";
  els.resultImage.src = "";
  els.resultVideo.pause();
  els.resultVideo.removeAttribute("src");
  els.resultVideo.load();
  els.placeholder.style.display = "block";
}

function previewResult(result) {
  if (!result) return;
  els.placeholder.style.display = "none";

  if (result.type === "video" && result.video_url) {
    els.resultVideo.src = result.video_url;
    els.resultVideo.style.display = "block";
    els.resultImage.style.display = "none";
  } else {
    els.resultImage.src = result.image_url || "";
    els.resultImage.style.display = "block";
    els.resultVideo.style.display = "none";
  }
}

async function refreshUser() {
  if (!authUser?.user_id) return;
  try {
    const data = await api(`/users/${encodeURIComponent(authUser.user_id)}`);
    authUser = { ...authUser, ...data };
    saveAuth(authUser);
    updateStatusUI(authUser);
    updateLoginUI();
  } catch (err) {
    console.error("ユーザー更新失敗", err);
  }
}

async function handleLogin() {
  const userId = els.userIdInput.value.trim();
  const password = els.passwordInput.value.trim();

  if (!userId || !password) {
    showMessage("ユーザーIDとパスワードを入力してください", true);
    return;
  }

  try {
    els.loginButton.disabled = true;
    els.loginButton.textContent = "ログイン中...";
    clearMessage();

    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, password })
    });

    authUser = data;
    saveAuth(authUser);
    previousFreeDrawCount = authUser.free_draw_count ?? 0;
    updateLoginUI();
    await refreshUser();
    showMessage("ログイン成功！");

    // 投稿成功通知があれば表示
    const notice = consumePostSuccessNotice();
    if (notice?.message) showRewardNotice(notice.message);

  } catch (err) {
    showMessage(err.message || "ログインに失敗しました", true);
  } finally {
    els.loginButton.disabled = false;
    els.loginButton.textContent = "ログイン / 新規作成";
  }
}

function handleLogout() {
  authUser = null;
  previousFreeDrawCount = null;
  clearAuth();
  clearRewardNotice();
  localStorage.removeItem(POST_SUCCESS_NOTICE_KEY);
  updateLoginUI();
  updateStatusUI();
  clearPreview();
  showMessage("ログアウトしました");
}

async function drawGacha(type) {
  if (isDrawing || !authUser) return;

  isDrawing = true;
  clearMessage();

  const btn = type === "paid" ? els.paidDrawButton : els.freeDrawButton;
  btn.disabled = true;
  btn.textContent = "ガチャ中...";

  try {
    const path = type === "paid"
      ? `/gacha/paid/${encodeURIComponent(authUser.user_id)}`
      : `/gacha/free/${encodeURIComponent(authUser.user_id)}`;

    const data = await api(path, { method: "POST" });

    previewResult(data.result);
    localStorage.setItem(RESULT_STORAGE_KEY, JSON.stringify(data));

    await refreshUser();

    // 少し演出待機してから結果ページへ
    setTimeout(() => {
      location.href = "result.html";
    }, 800);

  } catch (err) {
    let msg = "ガチャに失敗しました";
    if (err.message.includes("points")) msg = "ポイントが不足しています";
    if (err.message.includes("free"))  msg = "無料回数がありません";
    showMessage(msg, true);
  } finally {
    isDrawing = false;
    btn.disabled = false;
    btn.textContent = type === "paid" ? "30ptガチャ" : "無料ガチャ";
    updateDrawButtons();
  }
}

async function drawFreeFromNotice() {
  clearRewardNotice();
  await drawGacha("free");
}

function init() {
  authUser = loadAuth();
  updateLoginUI();

  if (authUser) {
    previousFreeDrawCount = authUser.free_draw_count ?? 0;
    refreshUser().then(() => {
      const notice = consumePostSuccessNotice();
      if (notice?.message) showRewardNotice(notice.message);
    });
  } else {
    updateStatusUI();
  }

  clearPreview();

  els.loginButton.addEventListener("click", handleLogin);
  els.logoutButton.addEventListener("click", handleLogout);
  els.freeDrawButton.addEventListener("click", () => drawGacha("free"));
  els.paidDrawButton.addEventListener("click", () => drawGacha("paid"));

  if (els.rewardDrawButton) {
    els.rewardDrawButton.addEventListener("click", drawFreeFromNotice);
  }

  els.passwordInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleLogin();
  });
}

document.addEventListener("DOMContentLoaded", init);}

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
