function optimizeCloudinary(url) {
  if (!url) return "";

  if (url.includes("res.cloudinary.com") && !url.includes("f_auto")) {
    return url.replace("/upload/", "/upload/f_auto,q_auto/");
  }

  return url;
}

function makeLightMosaicImage(url) {
  if (!url) return "";

  if (url.includes("res.cloudinary.com")) {
    return url.replace("/upload/", "/upload/f_auto,q_50,e_pixelate:8/");
  }

  return url;
}

function makeLightBlurImage(url) {
  if (!url) return "";

  if (url.includes("res.cloudinary.com")) {
    return url.replace("/upload/", "/upload/f_auto,q_50,e_blur:400/");
  }

  return url;
}

function makeMosaicVideoPoster(url) {
  if (!url) return "";

  if (url.includes("res.cloudinary.com")) {
    return url.replace(
      "/video/upload/",
      "/video/upload/so_0,e_pixelate:8,f_jpg/"
    );
  }

  return "";
}

function makeBlurVideoPoster(url) {
  if (!url) return "";

  if (url.includes("res.cloudinary.com")) {
    return url.replace(
      "/video/upload/",
      "/video/upload/so_0,e_blur:400,f_jpg/"
    );
  }

  return "";
}

function getViewAccessIds() {
  try {
    const raw = localStorage.getItem("view_access_content_ids");
    const ids = raw ? JSON.parse(raw) : [];
    return Array.isArray(ids) ? ids.map(String) : [];
  } catch (e) {
    return [];
  }
}

export function hasViewAccess(contentId) {
  if (!contentId) return false;
  return getViewAccessIds().includes(String(contentId));
}

export function grantViewAccess(contentId) {
  if (!contentId) return;

  try {
    const currentIds = getViewAccessIds();
    const next = new Set(currentIds);
    next.add(String(contentId));
    localStorage.setItem(
      "view_access_content_ids",
      JSON.stringify([...next])
    );
  } catch (e) {
    localStorage.setItem(
      "view_access_content_ids",
      JSON.stringify([String(contentId)])
    );
  }
}

export function revokeViewAccess(contentId) {
  if (!contentId) return;

  try {
    const currentIds = getViewAccessIds();
    const next = currentIds.filter((id) => id !== String(contentId));
    localStorage.setItem(
      "view_access_content_ids",
      JSON.stringify(next)
    );
  } catch (e) {
    // 何もしない
  }
}

export function clearAllViewAccess() {
  localStorage.removeItem("view_access_content_ids");
}

export function getDisplayMedia(work, options = {}) {
  const contentId = work?.content_id || work?.id || 0;
  const unlocked = hasViewAccess(contentId);

  const mosaicMode = options.mosaicMode || "pixelate";
  const type = String(work?.type || "").trim();

  const isVideo =
    type === "動画" ||
    type === "video" ||
    Boolean(work?.video_url || work?.videoUrl || work?.video);

  if (isVideo) {
    const videoUrl = optimizeCloudinary(
      work?.video_url || work?.videoUrl || work?.video || ""
    );

    const posterUrl =
      mosaicMode === "blur"
        ? makeBlurVideoPoster(videoUrl)
        : makeMosaicVideoPoster(videoUrl);

    if (unlocked) {
      return {
        unlocked: true,
        mediaType: "video",
        src: videoUrl,
        poster: posterUrl,
        contentId
      };
    }

    return {
      unlocked: false,
      mediaType: "video_locked",
      src: "",
      poster: posterUrl,
      contentId
    };
  }

  const imageUrl = optimizeCloudinary(
    work?.image_url ||
    work?.imageUrl ||
    work?.image ||
    work?.thumbnail_url ||
    work?.file ||
    ""
  );

  const lockedImageUrl =
    mosaicMode === "blur"
      ? makeLightBlurImage(imageUrl)
      : makeLightMosaicImage(imageUrl);

  if (unlocked) {
    return {
      unlocked: true,
      mediaType: "image",
      src: imageUrl,
      contentId
    };
  }

  return {
    unlocked: false,
    mediaType: "image_locked",
    src: lockedImageUrl,
    contentId
  };
}

export function renderMediaHtml(work, options = {}) {
  const media = getDisplayMedia(work, options);
  const title = String(work?.title || "作品");

  if (media.mediaType === "video") {
    return `
      <video
        class="card-media"
        src="${media.src}"
        poster="${media.poster || ""}"
        controls
        playsinline
        preload="metadata"
      ></video>
    `;
  }

  if (media.mediaType === "video_locked") {
    return `
      <div class="locked-media-wrap">
        <img
          class="card-media"
          src="${media.poster || ""}"
          alt="${title}"
          loading="lazy"
        />
        <div class="locked-overlay">
          🔒 ガチャで動画再生を解放
        </div>
      </div>
    `;
  }

  if (media.mediaType === "image") {
    return `
      <img
        class="card-media"
        src="${media.src}"
        alt="${title}"
        loading="lazy"
      />
    `;
  }

  return `
    <div class="locked-media-wrap">
      <img
        class="card-media"
        src="${media.src}"
        alt="${title}"
        loading="lazy"
      />
      <div class="locked-overlay">
        🔒 ガチャで高画質表示を解放
      </div>
    </div>
  `;
        }
