// ui/app.js
let selectedVersion = null;
let selectedVersionDisplay = null;
let versionsList = [];
let categoriesList = [];
let settingsState = {};

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  return await res.json();
}

async function performSearch(query, category) {
  if (!query || query.trim().length === 0) {
    renderVersionCardsForCurrentFilter();
    return;
  }

  const body = { q: query };
  if (category) body.category = category;

  try {
    const res = await api("/api/search", "POST", body);
    const list = res.results || [];
    const normalized = list.map(v => ({
      category: v.category,
      folder: v.folder,
      display: v.display,
      launch_disabled: v.launch_disabled,
      launch_disabled_message: v.launch_disabled_message
    }));
    renderVersionCards(normalized);
  } catch (e) {
    //console.error("Search failed", e);
    renderVersionCardsForCurrentFilter();
  }
}

function imageAttachErrorPlaceholder(img) {
  img.addEventListener('error', function() {
    if (img.src !== "assets/images/placeholder.png") {
      img.src = "assets/images/placeholder.png";
    }
  });
}

async function init_settings(data) {
  settingsState = { ...settingsState, ...data };

  const favRaw = settingsState.favorite_versions;

  let favList = [];
  if (Array.isArray(favRaw)) {
    favList = favRaw.map(s => (typeof s === "string" ? s.trim() : "")).filter(s => s.length > 0);
  } else if (typeof favRaw === "string") {
    favList = favRaw
      .split(",")
      .map(s => s.trim())
      .filter(s => s.length > 0);
  } else {
    favList = [];
  }
  settingsState.favorite_versions = favList;

  document.getElementById("settings-username").value = settingsState.username || "Player";
  document.getElementById("settings-min-ram").value = settingsState.min_ram || "256M";
  document.getElementById("settings-max-ram").value = settingsState.max_ram || "1024M";

  updateHomeInfo();
}

function updateHomeInfo() {
  const infoVersion = document.getElementById("info-version");
  const infoUsername = document.getElementById("info-username");
  const infoRam = document.getElementById("info-ram");

  const infoVersion_imgHTML = '<img width="16px" height="16px" src="assets/images/library.png"/>'
  const infoUsername_imgHTML = '<img width="16px" height="16px" src="assets/images/settings.gif"/>'
  const infoRam_imgHTML = '<img width="16px" height="16px" src="assets/images/settings.gif"/>'

  if (selectedVersionDisplay) {
    infoVersion.innerHTML = `${infoVersion_imgHTML} Version: ${selectedVersionDisplay}`;
  } else {
    infoVersion.innerHTML = `${infoVersion_imgHTML} Version: (none selected)`;
  }

  const username = settingsState.username || "Player";
  infoUsername.innerHTML = `${infoUsername_imgHTML} Account: ${username}`;

  const minRam =  settingsState.min_ram.toUpperCase() || "256M";
  const maxRam = settingsState.max_ram.toUpperCase() || "1024M";
  infoRam.innerHTML = `${infoRam_imgHTML} RAM Limit: ${minRam}B - ${maxRam}B`;
}

async function init() {
  const overlay = document.getElementById("loading-overlay");
  const box = document.getElementById("loading-box");

  overlay.classList.remove("hidden");
  box.classList.remove("hidden");

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

  try{
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
  }catch(e){}

  document.getElementById("status").textContent = "";

  versionsList = data.versions || [];
  categoriesList = data.categories || [];
  selectedVersion = data.selected_version || null;

  await init_settings(data.settings || {});

  initCategoryFilter();
  renderVersionCardsForCurrentFilter();

  if (selectedVersion) {
    const selectedCard = document.querySelector(`.version-card[data-full-id="${selectedVersion}"]`);
    if (selectedCard) {
      document.querySelectorAll(".version-card").forEach(c => c.classList.remove("selected"));
      selectedCard.classList.add("selected");

      const found = versionsList.find(v => `${v.category}/${v.folder}` === selectedVersion);
      console.debug(found);
      if (found) {
        selectedVersionDisplay = found.display;
      }
    } else { console.debug(selectedCard); selectedVersionDisplay = null; }
    updateHomeInfo();
  }

  overlay.classList.add("hidden");
  box.classList.add("hidden");
}

function initCategoryFilter() {
  const sel = document.getElementById("versions-category-select");
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
    const q = document.getElementById("versions-search").value || "";
    if (q.trim().length > 0) {
      performSearch(q, sel.value);
    } else {
      renderVersionCardsForCurrentFilter();
    }
  });

  const searchEl = document.getElementById("versions-search");
  searchEl.addEventListener("input", () => {
    const q = searchEl.value || "";
    performSearch(q, sel.value);
  });
}

function renderVersionCardsForCurrentFilter() {
  const sel = document.getElementById("versions-category-select");
  const cat = sel.value;
  const filtered = cat ? versionsList.filter(v => v.category === cat) : versionsList;
  renderVersionCards(filtered);
}

function renderVersionCards(list) {
  const container = document.getElementById("version-cards");
  container.innerHTML = "";

  if (!list || list.length === 0) {
    const empty = document.createElement("div");
    empty.style.padding = "20px";
    empty.style.color = "#9ca3af";
    empty.textContent = "No versions found.";
    container.appendChild(empty);
    return;
  }

  const favs = settingsState.favorite_versions || [];

  const sorted = [...list].sort((a, b) => {
    const aId = `${a.category}/${a.folder}`;
    const bId = `${b.category}/${b.folder}`;
    const aFav = favs.includes(aId);
    const bFav = favs.includes(bId);
    if (aFav && !bFav) return -1;
    if (!aFav && bFav) return 1;
    return 0;
  });

  sorted.forEach(v => {
    const fullId = `${v.category}/${v.folder}`;

    const card = document.createElement("div");
    card.className = "version-card";
    card.setAttribute("data-full-id", fullId);

    const img = document.createElement("img");
    img.className = "version-image";
    img.src = `clients/${v.category}/${v.folder}/display.png`;
    img.alt = v.display || "";
    imageAttachErrorPlaceholder(img);

    const info = document.createElement("div");
    info.className = "version-info";

    const disp = document.createElement("div");
    disp.className = "version-display";
    disp.textContent = v.display;

    const folder = document.createElement("div");
    folder.className = "version-folder";
    folder.textContent = v.folder;

    info.appendChild(disp);
    info.appendChild(folder);

    const star = document.createElement("div");
    star.className = "favorite-star";

    const starImg = document.createElement("img");
    starImg.alt = "favorite";
    starImg.src = favs.includes(fullId)
      ? "assets/images/filled_favorite.png"
      : "assets/images/unfilled_favorite.png";
    imageAttachErrorPlaceholder(starImg);
    star.appendChild(starImg);

    star.addEventListener("click", async (e) => {
      e.stopPropagation();

      const listFav = settingsState.favorite_versions || [];
      const isFav = listFav.includes(fullId);

      if (isFav) {
        settingsState.favorite_versions = listFav.filter(x => x !== fullId);
        starImg.src = "assets/images/unfilled_favorite.png";
      } else {
        settingsState.favorite_versions = [...listFav, fullId];
        starImg.src = "assets/images/filled_favorite.png";
      }

      await api("/api/settings", "POST", {
        favorite_versions: settingsState.favorite_versions.join(", ")
      });

      renderVersionCardsForCurrentFilter();
    });

    if (selectedVersion === fullId) {
      card.classList.add("selected");
    }

    card.addEventListener("click", async () => {
      document.querySelectorAll(".version-card").forEach(c => c.classList.remove("selected"));
      card.classList.add("selected");

      selectedVersion = fullId;
      selectedVersionDisplay = v.display;
      settingsState.selected_version = selectedVersion;

      updateHomeInfo();
      await api("/api/settings", "POST", { selected_version: selectedVersion });
    });

    card.appendChild(img);
    card.appendChild(info);
    card.appendChild(star);
    container.appendChild(card);
  });
}

function showPage(page) {
  document.querySelectorAll(".page").forEach(p => p.classList.add("hidden"));
  document.getElementById(`page-${page}`).classList.remove("hidden");
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
    if (icon.dataset && icon.dataset.anim) icon.src = icon.dataset.anim;
  });

  item.addEventListener("mouseleave", () => {
    if (!item.classList.contains("active") && icon.dataset && icon.dataset.static) {
      icon.src = icon.dataset.static;
    }
  });
});

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

  if (meta.launch_disabled) {
    const msg = meta.launch_disabled_message || "This version cannot be launched yet.";
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

  setTimeout(function(){
    document.getElementById("status").textContent = res.message;
    
    overlay.classList.add("hidden");
    box.classList.add("hidden");
  }, 3000+(Math.random()*7000));
});

document.getElementById("refresh-btn").addEventListener("click", e => {
  if (e.shiftKey) {
    location.reload();
    return;
  }
  init();
});

function autoSaveSetting(key, value) {
  settingsState[key] = value;
  updateHomeInfo();
  api("/api/settings", "POST", { [key]: value });
}

document.getElementById("settings-username").addEventListener("input", e => {
  autoSaveSetting("username", e.target.value);
});

document.getElementById("settings-min-ram").addEventListener("input", e => {
  autoSaveSetting("min_ram", e.target.value);
});

document.getElementById("settings-max-ram").addEventListener("input", e => {
  autoSaveSetting("max_ram", e.target.value);
});

document.addEventListener('DOMContentLoaded', () => {
  const images = document.getElementsByTagName('img'); 
  var srcList = [];
  for(var i = 0; i < images.length; i++) { srcList.push(images[i]); }

  srcList.forEach(imageAttachErrorPlaceholder);

  init();
});