// ui/app.js

let selectedVersion = null;
let selectedVersionDisplay = null;
let versionsList = [];
let categoriesList = [];
let settingsState = {};
let activeInstallPollers = {};
let isShiftDown = false;

// ---------------- API helper ----------------

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  return await res.json();
}

function imageAttachErrorPlaceholder(img, placeholder_link) {
  img.addEventListener("error", function () {
    if (!img.src.endsWith(placeholder_link)) {
      img.src = placeholder_link;
    }
  });
}

// ---------------- Settings / Home info ----------------

async function init_settings(data) {
  settingsState = { ...settingsState, ...data };

  const favRaw = settingsState.favorite_versions;
  let favList = [];
  if (Array.isArray(favRaw)) {
    favList = favRaw.map(s => (typeof s === "string" ? s.trim() : "")).filter(s => s.length > 0);
  } else if (typeof favRaw === "string") {
    favList = favRaw.split(",").map(s => s.trim()).filter(s => s.length > 0);
  }
  settingsState.favorite_versions = favList;

  const u = document.getElementById("settings-username");
  if (u) u.value = settingsState.username || "Player";
  const min = document.getElementById("settings-min-ram");
  if (min) min.value = settingsState.min_ram || "256M";
  const max = document.getElementById("settings-max-ram");
  if (max) max.value = settingsState.max_ram || "1024M";
  const proxyEl = document.getElementById("settings-url-proxy");
  if (proxyEl) proxyEl.value = settingsState.url_proxy || "";

  updateHomeInfo();
}

function updateHomeInfo() {
  const infoVersion = document.getElementById("info-version");
  const infoUsername = document.getElementById("info-username");
  const infoRam = document.getElementById("info-ram");

  const infoVersion_imgHTML = '<img width="16px" height="16px" src="assets/images/library.png"/>';
  const infoUsername_imgHTML = '<img width="16px" height="16px" src="assets/images/settings.gif"/>';
  const infoRam_imgHTML = '<img width="16px" height="16px" src="assets/images/settings.gif"/>';

  if (selectedVersionDisplay) {
    infoVersion.innerHTML = `${infoVersion_imgHTML} Version: ${selectedVersionDisplay}`;
  } else {
    infoVersion.innerHTML = `${infoVersion_imgHTML} Version: (none selected)`;
  }

  const username = settingsState.username || "Player";
  infoUsername.innerHTML = `${infoUsername_imgHTML} Account: ${username}`;

  const minRam = (settingsState.min_ram || "256M").toUpperCase();
  const maxRam = (settingsState.max_ram || "1024M").toUpperCase();
  infoRam.innerHTML = `${infoRam_imgHTML} RAM Limit: ${minRam}B - ${maxRam}B`;
}

// ---------------- Category / filtering ----------------

function buildCategoryListFromVersions(list) {
  const set = new Set();
  list.forEach(v => {
    if (v.category) set.add(v.category);
  });
  return Array.from(set).sort();
}

function initCategoryFilter() {
  const sel = document.getElementById("versions-category-select");
  if (!sel) return;

  sel.innerHTML = "";

  const allOpt = document.createElement("option");
  allOpt.value = "";
  allOpt.textContent = "* All";
  sel.appendChild(allOpt);

  categoriesList.forEach(c => {
    const opt = document.createElement("option");
    opt.value = c;
    opt.textContent = c;
    sel.appendChild(opt);
  });

  sel.value = "";
  sel.addEventListener("change", () => {
    renderAllVersionSections();
  });

  const searchEl = document.getElementById("versions-search");
  if (searchEl) {
    searchEl.addEventListener("input", () => {
      renderAllVersionSections();
    });
  }
}

function getFilterState() {
  const sel = document.getElementById("versions-category-select");
  const searchEl = document.getElementById("versions-search");
  const category = sel ? sel.value : "";
  const q = searchEl ? (searchEl.value || "").trim().toLowerCase() : "";
  return { category, q };
}

function filterVersionsForUI() {
  const { category, q } = getFilterState();
  let list = versionsList.slice();

  if (category) {
    list = list.filter(v => v.category === category);
  }

  if (q) {
    list = list.filter(v => {
      const hay = `${v.display} ${v.folder} ${v.category}`.toLowerCase();
      return hay.includes(q);
    });
  }

  const installed = list.filter(v => v.installed && !v.installing);
  const installing = list.filter(v => v.installing);
  const available = list.filter(v => !v.installed && !v.installing);

  return { installed, installing, available };
}

// ---------------- Badges / size ----------------

function formatSizeBadge(v) {
  if (typeof v.size_mb === "number" && v.size_mb > 0) {
    return `${v.size_mb.toFixed(1)} MB`;
  }
  return null;
}

// ---------------- Message Box ----------------

function showMessageBox({ title = "", message = "", buttons = [] }) {
  const overlay = document.getElementById("msgbox-overlay");
  const boxTitle = document.getElementById("msgbox-title");
  const boxText = document.getElementById("msgbox-text");
  const btnContainer = document.getElementById("msgbox-buttons");

  boxTitle.textContent = title;
  boxText.textContent = message;

  btnContainer.innerHTML = "";

  buttons.forEach(btn => {
    const el = document.createElement("button");
    el.textContent = btn.label;
    if (btn.primary) el.classList.add("primary");

    el.addEventListener("click", () => {
      overlay.classList.add("hidden");
      if (btn.onClick) btn.onClick();
    });

    btnContainer.appendChild(el);
  });

  overlay.classList.remove("hidden");
}

// ---------------- Version card creation ----------------

function createVersionCard(v, sectionType) {
  const fullId = `${v.category}/${v.folder}`;

  const card = document.createElement("div");
  card.className = "version-card";
  card.setAttribute("data-full-id", fullId);

  if (sectionType !== "installed") {
    card.classList.add("unselectable");
  }

  const img = document.createElement("img");
  img.className = "version-image";
  img.src =
    v.image_url ||
    (v.is_remote
      ? "assets/images/version_placeholder.png"
      : `clients/${v.category}/${v.folder}/display.png`);
  img.alt = v.display || "";
  imageAttachErrorPlaceholder(img, "assets/images/version_placeholder.png");

  const info = document.createElement("div");
  info.className = "version-info";

  const headerRow = document.createElement("div");
  headerRow.className = "version-header-row";

  const disp = document.createElement("div");
  disp.className = "version-display";
  disp.textContent = v.display;

  const folder = document.createElement("div");
  folder.className = "version-folder";
  folder.textContent = v.category;

  const iconsRow = document.createElement("div");
  iconsRow.className = "version-actions-icons";

  if (sectionType === "installed") {
    const favBtn = document.createElement("div");
    favBtn.className = "icon-button";
    const favImg = document.createElement("img");
    favImg.alt = "favorite";
    const fullKey = fullId;
    const favs = settingsState.favorite_versions || [];
    favImg.src = favs.includes(fullKey)
      ? "assets/images/filled_favorite.png"
      : "assets/images/unfilled_favorite.png";
    imageAttachErrorPlaceholder(favImg, "assets/images/placeholder.png");
    favBtn.appendChild(favImg);

    favBtn.addEventListener("mouseenter", () => {
      const listFav = settingsState.favorite_versions || [];
      if (!listFav.includes(fullKey)) {
        favImg.src = "assets/images/filled_favorite.png";
      }
    });
    favBtn.addEventListener("mouseleave", () => {
      const listFav = settingsState.favorite_versions || [];
      favImg.src = listFav.includes(fullKey)
        ? "assets/images/filled_favorite.png"
        : "assets/images/unfilled_favorite.png";
    });

    favBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const listFav = settingsState.favorite_versions || [];
      const isFav = listFav.includes(fullKey);
      if (isFav) {
        settingsState.favorite_versions = listFav.filter(x => x !== fullKey);
        favImg.src = "assets/images/unfilled_favorite.png";
      } else {
        settingsState.favorite_versions = [...listFav, fullKey];
        favImg.src = "assets/images/filled_favorite.png";
      }
      await api("/api/settings", "POST", {
        favorite_versions: settingsState.favorite_versions.join(", ")
      });
      renderAllVersionSections();
    });

    iconsRow.appendChild(favBtn);

    const delBtn = document.createElement("div");
    delBtn.className = "icon-button";
    const delImg = document.createElement("img");
    delImg.alt = "delete";
    delImg.src = "assets/images/unfilled_delete.png";
    imageAttachErrorPlaceholder(delImg, "assets/images/placeholder.png");
    delBtn.appendChild(delImg);

    delBtn.addEventListener("mouseenter", () => {
      delImg.src = "assets/images/filled_delete.png";
    });
    delBtn.addEventListener("mouseleave", () => {
      delImg.src = "assets/images/unfilled_delete.png";
    });

    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();

      showMessageBox({
        title: "Delete Version",
        message: `Are you sure you want to permanently delete ${v.category}/${v.folder}? This cannot be undone.`,
        buttons: [
          {
            label: "Yes",
            primary: true,
            onClick: async () => {
              const res = await api("/api/delete", "POST", {
                category: v.category,
                folder: v.folder
              });

              if (res && res.ok) {
                versionsList = versionsList.filter(
                  x => !(x.category === v.category && x.folder === v.folder)
                );
                renderAllVersionSections();

                if (selectedVersion === `${v.category}/${v.folder}`) {
                  selectedVersion = null;
                  selectedVersionDisplay = null;
                  updateHomeInfo();
                }
              } else {
                showMessageBox({
                  title: "Error",
                  message: res.error || "Failed to delete version.",
                  buttons: [{ label: "OK", primary: true }]
                });
              }
            }
          },
          { label: "No" }
        ]
      });
    });

    iconsRow.appendChild(delBtn);
  }

  headerRow.appendChild(disp);
  headerRow.appendChild(iconsRow);

  info.appendChild(headerRow);
  info.appendChild(folder);

  const badgeRow = document.createElement("div");
  badgeRow.className = "version-badge-row";

  const badgeMain = document.createElement("span");
  badgeMain.className =
    "version-badge " +
    (sectionType === "installed"
      ? "installed"
      : sectionType === "installing"
      ? "available"
      : "available");
  badgeMain.textContent =
    sectionType === "installed"
      ? "INSTALLED"
      : sectionType === "installing"
      ? "INSTALLING"
      : "AVAILABLE";
  badgeRow.appendChild(badgeMain);

  if (v.is_remote) {
    if (v.source === "mojang") {
      const badgeSourceOfficial = document.createElement("span");
      badgeSourceOfficial.className = "version-badge official";
      badgeSourceOfficial.textContent = "MOJANG";
      badgeRow.appendChild(badgeSourceOfficial);
    } else {
      const badgeSourceNotOfficial = document.createElement("span");
      badgeSourceNotOfficial.className = "version-badge nonofficial";
      badgeSourceNotOfficial.textContent = "PROXY";
      badgeRow.appendChild(badgeSourceNotOfficial);
    }
  }

  const sizeLabel = formatSizeBadge(v);
  if (sizeLabel) {
    const badgeSize = document.createElement("span");
    badgeSize.className = "version-badge size";
    badgeSize.textContent = sizeLabel;
    badgeRow.appendChild(badgeSize);
  }

  if (v.full_install) {
    const badgeFull = document.createElement("span");
    badgeFull.className = "version-badge full";
    badgeFull.textContent = "FULL";
    badgeRow.appendChild(badgeFull);
  }

  const actions = document.createElement("div");
  actions.className = "version-actions";

  if (sectionType === "available") {
    const installBtn = document.createElement("button");
    installBtn.textContent = "Download";
    installBtn.className = "primary";

    let fullDownloadMode = false;

    const updateInstallButtonVisual = () => {
      if (fullDownloadMode) {
        installBtn.classList.add("full-download");
        installBtn.textContent = "Full Download";
      } else {
        installBtn.classList.remove("full-download");
        installBtn.textContent = "Download";
      }
    };

    installBtn.addEventListener("mouseenter", () => {
      if (isShiftDown) {
        fullDownloadMode = true;
        updateInstallButtonVisual();
      }
    });

    installBtn.addEventListener("mouseleave", () => {
      fullDownloadMode = false;
      updateInstallButtonVisual();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Shift") {
        isShiftDown = true;
      }
    });
    document.addEventListener("keyup", (e) => {
      if (e.key === "Shift") {
        isShiftDown = false;
        fullDownloadMode = false;
        updateInstallButtonVisual();
      }
    });

    installBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await handleInstallClick(v, card, installBtn, fullDownloadMode);
    });

    actions.appendChild(installBtn);
  } else if (sectionType === "installing") {
    const cancelBtn = document.createElement("button");
    cancelBtn.textContent = "Cancel";
    cancelBtn.className = "primary";

    cancelBtn.addEventListener("click", (e) => {
      e.stopPropagation();

      showMessageBox({
        title: "Cancel Download",
        message: `Do you want to cancel downloading ${v.category}/${v.folder}?`,
        buttons: [
          {
            label: "Yes",
            primary: true,
            onClick: async () => {
              if (!v._installKey) return;
              await cancelInstallForVersionKey(v._installKey);
            }
          },
          { label: "No" }
        ]
      });
    });

    actions.appendChild(cancelBtn);
  }

  if (sectionType === "installed") {
    card.addEventListener("click", async () => {
      document.querySelectorAll(".version-card").forEach(c => c.classList.remove("selected"));
      card.classList.add("selected");
      selectedVersion = fullId;
      selectedVersionDisplay = v.display;
      settingsState.selected_version = selectedVersion;
      updateHomeInfo();
      await api("/api/settings", "POST", { selected_version: selectedVersion });
    });
  }

  if (sectionType === "installing") {
    const progressBar = document.createElement("div");
    progressBar.className = "version-progress";
    const fill = document.createElement("div");
    fill.className = "version-progress-fill";
    progressBar.appendChild(fill);
    card.appendChild(progressBar);

    const progressText = document.createElement("div");
    progressText.style.fontSize = "11px";
    progressText.style.padding = "4px 10px 8px 10px";
    progressText.style.color = "#9ca3af";
    progressText.textContent = v._progressText || "";
    card.appendChild(progressText);

    card._progressFill = fill;
    card._progressTextEl = progressText;

    if (typeof v._progressOverall === "number") {
      fill.style.width = `${v._progressOverall}%`;
    }
  }

  card.appendChild(img);
  card.appendChild(info);
  card.appendChild(badgeRow);
  card.appendChild(actions);

  return card;
}

// ---------------- Install handling ----------------

async function handleInstallClick(v, card, installBtn, fullDownloadMode) {
  const folder = v.folder;
  const category = v.category || "Release";

  if (!folder || !folder.trim()) {
    installBtn.textContent = "Error";
    setTimeout(() => { installBtn.textContent = "Download"; }, 1500);
    return;
  }

  installBtn.disabled = true;
  installBtn.textContent = fullDownloadMode ? "Starting full..." : "Starting...";
  card.classList.add("installing");

  const versionKey = await startInstallForFolder(folder, category, fullDownloadMode);
  if (!versionKey) {
    card.classList.remove("installing");
    installBtn.disabled = false;
    installBtn.textContent = "Download";
    return;
  }

  v._installKey = versionKey;
  v.installing = true;
  v.full_install = fullDownloadMode;
  v._progressText = "Starting...";
  v._progressOverall = 0;

  versionsList = versionsList.map(x => {
    if (x.category === v.category && x.folder === v.folder) {
      return {
        ...x,
        installing: true,
        _installKey: versionKey,
        full_install: fullDownloadMode,
        image_url: x.image_url,
        _progressText: "Starting...",
        _progressOverall: 0
      };
    }
    return x;
  });

  renderAllVersionSections();
  startPollingForInstall(versionKey, v);
}

async function startInstallForFolder(folder, category, fullDownloadMode) {
  if (!folder || typeof folder !== "string" || folder.trim().length === 0) {
    console.error("startInstallForFolder: missing folder");
    return null;
  }
  if (!category || typeof category !== "string") {
    category = "release";
  }

  const fullFlag = !!fullDownloadMode;

  const payloads = [
    { version: folder, category: category, full_assets: fullFlag },
    { folder: folder, category: category, full_assets: fullFlag },
    { version_key: `${category.toLowerCase()}/${folder}`, full_assets: fullFlag },
    { key: `${category.toLowerCase()}/${folder}`, full_assets: fullFlag },
    `${category.toLowerCase()}/${folder}`
  ];

  for (const payload of payloads) {
    try {
      const res = await fetch("/api/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      let json;
      try {
        json = await res.json();
      } catch (e) {
        const txt = await res.text().catch(() => "<no body>");
        console.error("install response not JSON:", res.status, txt);
        continue;
      }

      if (json && json.started) {
        return json.version || `${category.toLowerCase()}/${folder}`;
      }
      if (json && json.error) {
        console.warn("install attempt returned error:", json.error, "payload:", payload);
        continue;
      }
      if (json && typeof json === "object" && json.version) {
        return json.version;
      }
    } catch (e) {
      console.warn("install start failed for payload", payload, e);
      continue;
    }
  }

  console.error("install start failed: all payload attempts returned errors");
  return null;
}

async function cancelInstallForVersionKey(versionKey) {
  try {
    const res = await fetch(`/api/cancel/${versionKey}`, { method: "POST" });
    const json = await res.json();
    console.log("cancel response", json);
  } catch (e) {
    console.warn("cancel failed", e);
  }
}

function startPollingForInstall(versionKey, vMeta) {
  if (activeInstallPollers[versionKey]) return;

  const poll = async () => {
    try {
      const r = await fetch(`/api/status/${versionKey}`);
      if (!r.ok) {
        activeInstallPollers[versionKey] = setTimeout(poll, 300);
        return;
      }

      const s = await r.json();
      if (!s) {
        activeInstallPollers[versionKey] = setTimeout(poll, 300);
        return;
      }

      const status = s.status;
      
      if (status === "unknown") {
        activeInstallPollers[versionKey] = setTimeout(poll, 200);
        return;
      }

      const pct = s.overall_percent || 0;
      const bytesDone = s.bytes_done || 0;
      const bytesTotal = s.bytes_total || 0;

      const mbDone = bytesDone / (1024 * 1024);
      const mbTotal = bytesTotal / (1024 * 1024);

      let text = "";
      let keepPolling = true;

      if (status === "downloading" || status === "starting") {
        text = bytesTotal > 0
          ? `${pct}% (${mbDone.toFixed(1)} MB / ${mbTotal.toFixed(1)} MB)`
          : `${pct}%`;
      } else if (status === "installed") {
        text = "Installed";
        keepPolling = false;

        versionsList = versionsList.map(x => {
            if (`${x.category}/${x.folder}` === `${vMeta.category}/${vMeta.folder}`) {
                return {
                    ...x,
                    installed: true,
                    installing: false,
                    _installKey: null,
                    _progressOverall: 100,
                    _progressText: "Installed"
                };
            }
            return x;
        });
      } else if (status === "failed") {
        text = "Failed: " + (s.message || "");
        keepPolling = false;
      } else if (status === "cancelled") {
        text = "Cancelled";
        keepPolling = false;
      }

      const card = document.querySelector(`.version-card[data-full-id="${vMeta.category}/${vMeta.folder}"]`);
      if (card) {
        if (card._progressFill) card._progressFill.style.width = `${pct}%`;
        if (card._progressTextEl) card._progressTextEl.textContent = text;
      }

      vMeta._progressText = text;
      vMeta._progressOverall = pct;

      if (keepPolling) {
        activeInstallPollers[versionKey] = setTimeout(poll, 200);
      } else {
        renderAllVersionSections();
        clearTimeout(activeInstallPollers[versionKey]);
        delete activeInstallPollers[versionKey];
      }
    } catch (e) {
      activeInstallPollers[versionKey] = setTimeout(poll, 300);
    }
  };

  activeInstallPollers[versionKey] = setTimeout(poll, 200);
}

// ---------------- Rendering sections ----------------

function renderAllVersionSections() {
  const installedContainer = document.getElementById("installed-versions");
  const installingContainer = document.getElementById("installing-versions");
  const availableContainer = document.getElementById("available-versions");
  const availableSection = document.getElementById("available-section");
  const installingSection = document.getElementById("installing-section");

  installedContainer.innerHTML = "";
  installingContainer.innerHTML = "";
  availableContainer.innerHTML = "";

  const { installed, installing, available } = filterVersionsForUI();

  if (installed.length === 0) {
    const empty = document.createElement("div");
    empty.style.padding = "12px";
    empty.style.color = "#9ca3af";
    empty.textContent = "No installed versions yet.";
    installedContainer.appendChild(empty);
  } else {
    installed.forEach(v => {
      installedContainer.appendChild(createVersionCard(v, "installed"));
    });
  }

  if (installing.length === 0) {
    installingSection.classList.add("hidden");
  } else {
    installingSection.classList.remove("hidden");
    installing.forEach(v => {
      const card = createVersionCard(v, "installing");
      if (card._progressFill && typeof v._progressOverall === "number") {
        card._progressFill.style.width = `${v._progressOverall}%`;
      }
      if (card._progressTextEl && typeof v._progressText === "string") {
        card._progressTextEl.textContent = v._progressText;
      }
      installingContainer.appendChild(card);
    });
  }

  if (available.length === 0) {
    availableSection.style.display = "none";
  } else {
    availableSection.style.display = "";
    available.forEach(v => {
      availableContainer.appendChild(createVersionCard(v, "available"));
    });
  }
}

// ---------------- Navigation / sidebar ----------------

function showPage(page) {
  document.querySelectorAll(".page").forEach(p => p.classList.add("hidden"));
  const el = document.getElementById(`page-${page}`);
  if (el) el.classList.remove("hidden");
}

document.querySelectorAll(".sidebar-item").forEach(item => {
  item.addEventListener("click", () => {
    document.querySelectorAll(".sidebar-item").forEach(i => {
      i.classList.remove("active");
      const ic = i.querySelector(".sidebar-icon");
      if (ic && ic.dataset && ic.dataset.static) ic.src = ic.dataset.static;
    });

    item.classList.add("active");
    const icon = item.querySelector(".sidebar-icon");
    if (icon && icon.dataset && icon.dataset.anim) icon.src = icon.dataset.anim;

    showPage(item.dataset.page);
  });
});

document.querySelectorAll(".sidebar-item").forEach(item => {
  const icon = item.querySelector(".sidebar-icon");
  if (!icon) return;

  item.addEventListener("mouseenter", () => {
    if (icon && icon.dataset && icon.dataset.anim) icon.src = icon.dataset.anim;
  });

  item.addEventListener("mouseleave", () => {
    if (!item.classList.contains("active") && icon && icon.dataset && icon.dataset.static) {
      icon.src = icon.dataset.static;
    }
  });
});

// ---------------- Launch button (Home) ----------------

document.getElementById("launch-btn").addEventListener("click", async () => {
  if (!selectedVersion) {
    document.getElementById("status").textContent = "Please select a version on the Versions page first!";
    return;
  }

  const meta = versionsList.find(v => `${v.category}/${v.folder}` === selectedVersion);
  if (!meta) {
    document.getElementById("status").textContent = "Selected version metadata not found.";
    return;
  }

  if (meta.raw && meta.raw.launch_disabled) {
    const msg = meta.raw.launch_disabled_message || "This version cannot be launched yet.";
    window.alert(msg);
    document.getElementById("status").textContent = "Failed to launch: " + msg;
    return;
  }

  const overlay = document.getElementById("loading-overlay");
  const box = document.getElementById("launching-box");

  overlay.classList.remove("hidden");
  box.classList.remove("hidden");

  const username = settingsState.username || "Player";
  const [category, folder] = selectedVersion.split("/");

  const res = await api("/api/launch", "POST", { category, folder, username });

  setTimeout(function () {
    document.getElementById("status").textContent = res.message;
    overlay.classList.add("hidden");
    box.classList.add("hidden");
  }, 3000 + (Math.random() * 7000));
});

// ---------------- Refresh button ----------------

document.getElementById("refresh-btn").addEventListener("click", e => {
  if (e.shiftKey) {
    location.reload();
    return;
  }
  init();
});

// ---------------- Settings autosave ----------------

function autoSaveSetting(key, value) {
  settingsState[key] = value;
  updateHomeInfo();
  api("/api/settings", "POST", { [key]: value });
}

const usernameInput = document.getElementById("settings-username");
if (usernameInput) usernameInput.addEventListener("input", function (e) {
  let v = e.target.value;
  v = v.replace(/[^ _0-9a-zA-Z]/g, '');
  v = v.replace(/ /g, '_');

  const firstUnderscoreIndex = v.indexOf('_');
  if (firstUnderscoreIndex !== -1) {
    v = v.replace(/_/g, '');
    v = v.slice(0, firstUnderscoreIndex) + '_' + v.slice(firstUnderscoreIndex);
  }

  e.target.value = v;
  autoSaveSetting("username", v);
});

const minRamInput = document.getElementById("settings-min-ram");
if (minRamInput) minRamInput.addEventListener("input", function (e) {
  let v = e.target.value.toUpperCase();
  v = v.replace(/[^0-9KMG T]/gi, '').toUpperCase();

  const numbers = v.match(/^\d+/);
  const letter = v.match(/[KMGT]/i);
  let finalValue = "";

  if (numbers || !letter) {
    if (numbers) finalValue += numbers[0];
    if (letter) finalValue += letter[0];
  }

  e.target.value = finalValue;
  autoSaveSetting("min_ram", finalValue);
});

const maxRamInput = document.getElementById("settings-max-ram");
if (maxRamInput) maxRamInput.addEventListener("input", function (e) {
  let v = e.target.value.toUpperCase();
  v = v.replace(/[^0-9KMG T]/gi, '').toUpperCase();

  const numbers = v.match(/^\d+/);
  const letter = v.match(/[KMGT]/i);
  let finalValue = "";

  if (numbers || !letter) {
    if (numbers) finalValue += numbers[0];
    if (letter) finalValue += letter[0];
  }

  e.target.value = finalValue;
  autoSaveSetting("max_ram", finalValue);
});

const proxyInput = document.getElementById("settings-url-proxy");
if (proxyInput) proxyInput.addEventListener("input", e => autoSaveSetting("url_proxy", e.target.value.trim()));

const storageSelect = document.getElementById("settings-storage-dir");
if (storageSelect) storageSelect.addEventListener("change", e => {
  const val = e.target.value === "version" ? "version" : "global";
  autoSaveSetting("storage_directory", val);
});

const openDataFolderButton = document.getElementById("open-data-folder-btn");
openDataFolderButton.addEventListener("click", async () => await api("/api/open_data_folder", "POST"));

// ---------------- Init ----------------

async function init() {
  const overlay = document.getElementById("loading-overlay");
  const box = document.getElementById("loading-box");

  if (overlay) overlay.classList.remove("hidden");
  if (box) box.classList.remove("hidden");

  const data = await api("/api/initial");

  let localVersion = null;
  let isOutdated = false;

  try {
    const fetchWithTimeout = (url, ms = 5000) => {
      const controller = new AbortController();
      const id = setTimeout(() => controller.abort(), ms);
      return fetch(url, { signal: controller.signal }).finally(() => clearTimeout(id));
    };

    const [lvRes, iloRes] = await Promise.allSettled([
      fetchWithTimeout("/launcher/version.dat"),
      fetchWithTimeout("/api/is-launcher-outdated/"),
    ]);

    if (lvRes.status === "fulfilled" && lvRes.value && lvRes.value.ok) {
      try {
        localVersion = (await lvRes.value.text()).trim();
      } catch (e) {
        localVersion = null;
      }
    }

    if (iloRes.status === "fulfilled" && iloRes.value && iloRes.value.ok) {
      try {
        isOutdated = await iloRes.value.json();
        isOutdated = !!isOutdated;
      } catch (e) {
        isOutdated = false;
      }
    }
  } catch (e) {
    localVersion = localVersion || null;
    isOutdated = false;
  }

  try {
    const el = document.getElementById("sidebar-version");
    if (el) {
      if (localVersion) {
        if (isOutdated) {
          el.classList.add("outdated");
          el.textContent = `${localVersion} (outdated)`;
        } else {
          el.classList.remove("outdated");
          el.textContent = localVersion;
        }
      } else {
        el.classList.remove("outdated");
        el.textContent = "unknown";
      }
    }
  } catch (e) {}

  const statusEl = document.getElementById("status");
  if (statusEl) statusEl.textContent = "";

  const warn = document.getElementById("versions-section-warning");
  if (data.manifest_error) {
    const availableSection = document.getElementById("available-section");
    if (availableSection) availableSection.style.display = "none";

    warn.textContent = "Unable to fetch downloadable versions, please check your internet connection (or URL Proxy in settings)!";
    warn.classList.remove("hidden");
  } else {
    warn.classList.add("hidden");
  }

  const versions = data.versions || [];
  versionsList = versions.map(v => ({ ...v, installing: false, full_install: false }));

  categoriesList = buildCategoryListFromVersions(versionsList);
  selectedVersion = data.selected_version || null;

  await init_settings(data.settings || {});

  // Rehydrate installing versions from backend so they appear immediately
  const installingList = data.installing || [];
  installingList.forEach(item => {
    const key = item.version_key;
    const cat = item.category;
    const folder = item.folder;
    const display = item.display || folder;
    const pct = item.overall_percent || 0;
    const bytesDone = item.bytes_done || 0;
    const bytesTotal = item.bytes_total || 0;

    let v = versionsList.find(
      x => x.category.toLowerCase() === cat.toLowerCase() && x.folder === folder
    );

    if (!v) {
      v = {
        display,
        category: cat,
        folder,
        installed: false,
        is_remote: true,
        source: "mojang",
        image_url: "assets/images/version_placeholder.png",
        size_mb: null
      };
      versionsList.push(v);
    }

    v.installing = true;
    v._installKey = key;

    const mbDone = bytesDone > 0 ? (bytesDone / (1024 * 1024)) : 0;
    const mbTotal = bytesTotal > 0 ? (bytesTotal / (1024 * 1024)) : 0;
    let text = "";
    if (bytesTotal > 0) {
      text = `${pct}% ( ${mbDone.toFixed(1)} MB / ${mbTotal.toFixed(1)} MB )`;
    } else {
      text = `${pct}%`;
    }
    v._progressText = text;
    v._progressOverall = pct;

    startPollingForInstall(key, v);
  });

  initCategoryFilter();
  renderAllVersionSections();

  if (selectedVersion) {
    const found = versionsList.find(v => `${v.category}/${v.folder}` === selectedVersion);
    if (found) {
      selectedVersionDisplay = found.display;
      updateHomeInfo();
    }
  }

  if (overlay) overlay.classList.add("hidden");
  if (box) box.classList.add("hidden");
}

document.addEventListener("DOMContentLoaded", init);
