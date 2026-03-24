from pathlib import Path

content = r'''window.APP_CONFIG = (() => {
  const hostname = window.location.hostname;
  const isLocal =
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "";

  const DEFAULTS = {
    // ローカル開発時は FastAPI を直接参照
    API_BASE: isLocal ? "http://127.0.0.1:8000" : "",

    // 必要に応じて実値へ差し替え
    APPS_SCRIPT_URL: "",
    CLOUDINARY_CLOUD_NAME: "",
    CLOUDINARY_UPLOAD_PRESET: "",

    // localStorage keys
    AUTH_STORAGE_KEY: "gacha_app_auth_v1",
    RESULT_STORAGE_KEY: "gacha_last_result",
    POST_SUCCESS_NOTICE_KEY: "gacha_post_success_notice",
  };

  // HTML 側で window.__APP_CONFIG__ を先に定義していれば上書き可能
  const OVERRIDES = window.__APP_CONFIG__ || {};

  const config = { ...DEFAULTS, ...OVERRIDES };

  // 末尾スラッシュを除去
  if (typeof config.API_BASE === "string") {
    config.API_BASE = config.API_BASE.replace(/\/+$/, "");
  }
  if (typeof config.APPS_SCRIPT_URL === "string") {
    config.APPS_SCRIPT_URL = config.APPS_SCRIPT_URL.replace(/\/+$/, "");
  }

  return Object.freeze(config);
})();
'''

path = Path("/mnt/data/config_fixed.js")
path.write_text(content, encoding="utf-8")
print(path)
