from pathlib import Path

content = r'''const API_BASE = window.APP_CONFIG.API_BASE;
const AUTH_STORAGE_KEY = window.APP_CONFIG.AUTH_STORAGE_KEY;
const RESULT_STORAGE_KEY = window.APP_CONFIG.RESULT_STORAGE_KEY;
const POST_SUCCESS_NOTICE_KEY = window.APP_CONFIG.POST_SUCCESS_NOTICE_KEY;

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

const pointsBox = document.getElementById("pointsBox");
const expBox = document.getElementById("expBox");
const levelBox = document.getElementById("levelBox");
const freeDrawBox = document.getElementById("freeDrawBox");

const freeDrawButton = document.getElementById("freeDrawButton");
const paidDrawButton = document.getElementById("paidDrawButton");

const placeholder = document.getElementById("placeholder");
const resultImage = document.getElementById("resultImage");
const resultVideo = document.getElementById("resultVideo");

const systemMessage = document.getElementById("systemMessage");
const rewardNotice = document.getElementById("rewardNotice");
const rewardNoticeText = document.getElementById("rewardNoticeText");
const rewardDrawButton = document.getElementById("rewardDrawButton");

const creatorTopList = document.getElementById("creatorTopList");

let authUser = null;
let isDrawing = false;
let previousFreeDrawCount = null;
let previousPointCount = null;

function showMessage(text) {
  if (!systemMessage) return;
  systemMessage.textContent = text;
  systemMessage.classList.add("show");
}

function clearMessage() {
  if (!systemMessage) return;
  systemMessage.textContent = "";
  systemMessage.classList.remove("show");
}

function showRewardNotice(text) {
  if (!rewardNotice) return;
  if (rewardNoticeText) {
    rewardNoticeText.textContent = text;
  } else {
    rewardNotice.textContent = text;
  }
  rewardNotice.style.display = "block";
}

function clearRewardNotice() {
  if (!rewardNotice) return;
  rewardNotice.style.display = "none";
  if (rewardNoticeText) rewardNoticeText.textContent = "";
}

function saveAuth(data) {
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(data));
}

function loadAuth() {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (error) {
    console.warn("auth parse failed", error);
    return null;
  }
}

function clearAuth() {
  localStorage.removeItem(AUTH_STORAGE_KEY);
}

function saveResult(data) {
  const payload = {
    saved_at: new Date().toISOString(),
    user_id: authUser?.user_id || null,
    data,
  };
  localStorage.setItem(RESULT_STORAGE_KEY, JSON.stringify(payload));
}

function clearResultCache() {
  localStorage.removeItem(RESULT_STORAGE_KEY);
}

function consumePostSuccessNotice() {
  try {
    const raw = localStorage.getItem(POST_SUCCESS_NOTICE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    localStorage.removeItem(POST_SUCCESS_NOTICE_KEY);
    return data;
  } catch (error) {
    localStorage.removeItem(POST_SUCCESS_NOTICE_KEY);
    return null;
  }
}

function getAuthToken() {
  return (
    authUser?.token ||
    authUser?.access_token ||
    authUser?.jwt ||
    null
  );
}

function buildAuthHeaders() {
  const token = getAuthToken();
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...buildAuthHeaders(),
    ...(options.headers || {})
  };

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail || "APIエラーが発生しました。しばらく待ってから再試行してください。");
  }

  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function updateLoginUI() {
  if (authUser && authUser.user_id) {
    loginStatus.textContent = `ログイン中: ${authUser.user_id}`;
    logoutButton.style.display = "block";
    userIdInput.value = authUser.user_id || "";
  } else {
    loginStatus.textContent = "未ログイン";
    logoutButton.style.display = "none";
    userIdInput.value = "";
  }
}

function flashBox(element) {
  if (!element) return;
  element.classList.add("flash");
  setTimeout(() => {
    element.classList.remove("flash");
  }, 1200);
}

function animateFreeDrawIncrease(oldValue, newValue) {
  if (oldValue === null || oldValue === undefined) return;
  if (newValue > oldValue) {
    flashBox(freeDrawBox);
  }
}

function animatePointsIncrease(oldValue, newValue) {
  if (oldValue === null || oldValue === undefined) return;
  if (newValue > oldValue) {
    flashBox(pointsBox);
  }
}

function updateStatusUI(user) {
  if (!user) return;

  const newPoints = user.points ?? 0;
  const newFreeDrawCount = user.free_draw_count ?? 0;

  pointsText.textContent = newPoints;
  expText.textContent = user.exp ?? 0;
  levelText.textContent = user.level ?? 1;
  freeDrawText.textContent = newFreeDrawCount;
  reviveText.textContent = user.revive_item_count ?? user.revive_items ?? 0;
  ballText.textContent = `${user.ball_count ?? user.legend_ball_count ?? 0} / 7`;

  animatePointsIncrease(previousPointCount, newPoints);
  animateFreeDrawIncrease(previousFreeDrawCount, newFreeDrawCount);

  previousPointCount = newPoints;
  previousFreeDrawCount = newFreeDrawCount;
}

function clearPreview() {
  if (resultImage) {
    resultImage.style.display = "none";
    resultImage.src = "";
  }

  if (resultVideo) {
    resultVideo.style.display = "none";
    resultVideo.pause();
    resultVideo.removeAttribute("src");
    resultVideo.load();
  }

  if (placeholder) {
    placeholder.style.display = "block";
  }
}

function previewResult(result) {
  if (!result) return;

  if (placeholder) {
    placeholder.style.display = "none";
  }

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

  let data = null;
  const token = getAuthToken();

  if (token) {
    try {
      data = await api("/users/me");
    } catch (_) {
      // 互換用 fallback
    }
  }

  if (!data) {
    data = await api(`/users/${encodeURIComponent(authUser.user_id)}`);
  }

  authUser = { ...authUser, ...data };
  saveAuth(authUser);
  updateStatusUI(authUser);
  updateLoginUI();
}

async function loadUserStatus() {
  if (!authUser || !authUser.user_id) return;
  await refreshUser();
}

async function handleLogin() {
  const userId = (userIdInput.value || "").trim();
  const password = (passwordInput.value || "").trim();

  if (!userId || !password) {
    showMessage("ユーザーIDとパスワードを入力してください。");
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

    previousPointCount = authUser.points ?? 0;
    previousFreeDrawCount = authUser.free_draw_count ?? 0;

    updateLoginUI();
    updateStatusUI(authUser);
    showMessage("ログインしました。");
  } catch (error) {
    showMessage(error.message || "ログインに失敗しました。ユーザーIDとパスワードを確認してください。");
  } finally {
    loginButton.disabled = false;
    loginButton.textContent = "ログイン / 新規登録";
  }
}

function handleLogout() {
  authUser = null;
  previousFreeDrawCount = null;
  previousPointCount = null;
  clearAuth();
  clearResultCache();
  clearRewardNotice();
  localStorage.removeItem(POST_SUCCESS_NOTICE_KEY);

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
    showMessage("ガチャを引くにはログインが必要です。");
    return;
  }

  try {
    isDrawing = true;
    clearMessage();

    freeDrawButton.disabled = true;
    paidDrawButton.disabled = true;
    freeDrawButton.textContent = "抽選中...";
    paidDrawButton.textContent = "抽選中...";

    let data = null;
    const token = getAuthToken();

    // 新API優先、なければ旧互換APIへフォールバック
    if (token) {
      try {
        data = await api(type === "paid" ? "/gacha/paid" : "/gacha/free", { method: "POST" });
      } catch (_) {
        // fallback below
      }
    }

    if (!data) {
      const path = type === "paid"
        ? `/gacha/paid/${encodeURIComponent(authUser.user_id)}`
        : `/gacha/free/${encodeURIComponent(authUser.user_id)}`;
      data = await api(path, { method: "POST" });
    }

    saveResult(data);
    previewResult(data.result);

    location.href = "result.html";
  } catch (error) {
    showMessage(error.message || "ガチャに失敗しました。しばらく待ってから再試行してください。");
  } finally {
    isDrawing = false;
    freeDrawButton.disabled = false;
    paidDrawButton.disabled = false;
    freeDrawButton.textContent = "無料ガチャを引く";
    paidDrawButton.textContent = "30ptガチャを引く";
  }
}

async function drawFreeFromNotice() {
  clearRewardNotice();
  await drawGacha("free");
}

async function waitForPointsUpdate(expectedMinPoints, maxRetry = 8, intervalMs = 1500) {
  for (let i = 0; i < maxRetry; i++) {
    await new Promise(resolve => setTimeout(resolve, intervalMs));
    try {
      await refreshUser();
      if ((authUser?.points ?? 0) >= expectedMinPoints) {
        return true;
      }
    } catch (_) {
      // リトライ継続
    }
  }
  return false;
}

async function handleStripeResult() {
  const params = new URLSearchParams(window.location.search);
  const success = params.get("success");
  const cancel = params.get("cancel");

  if (success === "1") {
    history.replaceState({}, "", location.pathname);

    if (!authUser || !authUser.user_id) {
      showMessage("決済が完了しました。ログインしてポイントを確認してください。");
      return;
    }

    const pointsBefore = authUser.points ?? 0;
    showMessage("決済が完了しました。ポイントを反映中です…");

    const reflected = await waitForPointsUpdate(pointsBefore + 1);

    if (reflected) {
      showMessage("✓ ポイントが反映されました！");
      flashBox(pointsBox);
    } else {
      showMessage("決済は完了しています。ポイント反映に時間がかかる場合があります。しばらくお待ちください。");
      refreshUser().catch(() => {});
    }
  }

  if (cancel === "1") {
    history.replaceState({}, "", location.pathname);
    showMessage("決済がキャンセルされました。");
  }
}

async function buyPoints(type) {
  if (!authUser || !authUser.user_id) {
    showMessage("ポイント購入にはログインが必要です。");
    return;
  }

  try {
    clearMessage();

    const token = getAuthToken();
    let body;

    if (token) {
      body = JSON.stringify({ type });
    } else {
      body = JSON.stringify({
        user_id: authUser.user_id,
        type
      });
    }

    const response = await fetch(`${API_BASE}/create-checkout-session`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
      },
      body
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.detail || "決済セッションの作成に失敗しました。");
    }

    if (!data.url) {
      throw new Error("決済URLを取得できませんでした。");
    }

    window.location.href = data.url;
  } catch (error) {
    showMessage(error.message || "決済の開始に失敗しました。しばらく待ってから再試行してください。");
  }
}

function injectPointPurchaseButtons() {
  const existing = document.getElementById("pointPurchaseCard");
  if (existing) return;

  const cards = document.querySelectorAll(".card");
  if (!cards || cards.length < 3) return;

  const purchaseCard = document.createElement("div");
  purchaseCard.className = "card";
  purchaseCard.id = "pointPurchaseCard";
  purchaseCard.innerHTML = `
    <h2>ポイント購入</h2>
    <p class="sub">初回購入はポイント50%増量です。</p>
    <div class="button-group">
      <button id="buy300Button" class="btn-link" type="button">300pt / ¥300（初回 450pt）</button>
      <button id="buy1000Button" class="btn-link" type="button">1,100pt / ¥1,000（初回 1,650pt）</button>
    </div>
  `;

  const targetCard = cards[2];
  targetCard.parentNode.insertBefore(purchaseCard, targetCard.nextSibling);

  document.getElementById("buy300Button")?.addEventListener("click", () => buyPoints("300"));
  document.getElementById("buy1000Button")?.addEventListener("click", () => buyPoints("1000"));
}

function firstCreatorLink(item) {
  return item.link_url || item.booth_url || item.fanbox_url || item.skeb_url || item.pixiv_url || "";
}

async function loadCreatorTopRanking() {
  if (!creatorTopList) return;

  try {
    const data = await api("/creators/ranking");
    const items = (data.items || []).slice(0, 3);

    if (!items.length) {
      creatorTopList.innerHTML = `<div class="sub">まだランキング対象のクリエイターがいません。</div>`;
      return;
    }

    creatorTopList.innerHTML = items.map(item => {
      const link = firstCreatorLink(item);

      return `
        <div class="creator-rank-card">
          <div class="creator-rank-head">
            <span class="creator-rank-badge">#${item.rank ?? "-"}</span>
            <span class="creator-rank-badge">スコア ${item.score ?? 0}</span>
            <span class="creator-rank-badge">作品 ${item.total_works ?? 0}</span>
            <span class="creator-rank-badge">排出 ${item.total_draws ?? 0}</span>
          </div>

          <div class="creator-rank-name">${escapeHtml(item.creator_name || item.creator_id || "不明")}</div>

          <div class="creator-rank-meta">
            代表カード: ${escapeHtml(item.top_card?.title || "なし")}<br>
            平均Lv: ${item.avg_level ?? 0}<br>
            いいね: ${item.total_likes ?? 0}
            ${item.legend_count > 0 ? `<br>LEGEND: ${item.legend_count}` : ""}
          </div>

          ${
            link
              ? `<a class="creator-rank-link" href="${escapeAttr(link)}" target="_blank" rel="noopener noreferrer">販売ページへ</a>`
              : `<div class="sub">販売ページリンク未設定</div>`
          }
        </div>
      `;
    }).join("");
  } catch (error) {
    creatorTopList.innerHTML = `<div class="sub">ランキングを読み込めませんでした。</div>`;
  }
}

function boot() {
  injectPointPurchaseButtons();

  authUser = loadAuth();
  updateLoginUI();

  if (authUser) {
    previousPointCount = authUser.points ?? 0;
    previousFreeDrawCount = authUser.free_draw_count ?? 0;

    refreshUser()
      .then(() => {
        const notice = consumePostSuccessNotice();
        if (notice && notice.message) {
          showRewardNotice(notice.message);
        } else {
          clearRewardNotice();
        }
      })
      .catch((error) => {
        console.warn("refreshUser failed", error);
        updateStatusUI(authUser);
      });
  } else {
    updateStatusUI({
      points: 0,
      exp: 0,
      level: 1,
      free_draw_count: 0,
      revive_item_count: 0,
      ball_count: 0
    });
    clearRewardNotice();
  }

  clearPreview();

  loginButton?.addEventListener("click", handleLogin);
  logoutButton?.addEventListener("click", handleLogout);
  freeDrawButton?.addEventListener("click", () => drawGacha("free"));
  paidDrawButton?.addEventListener("click", () => drawGacha("paid"));

  if (rewardDrawButton) {
    rewardDrawButton.addEventListener("click", drawFreeFromNotice);
  }

  passwordInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") handleLogin();
  });

  handleStripeResult();
  loadCreatorTopRanking();
}

document.addEventListener("DOMContentLoaded", boot);
'''

path = Path("/mnt/data/gacha_fixed.js")
path.write_text(content, encoding="utf-8")
print(path)
