/* Kontrollpanelen: the page talks to the daemon's API (see /docs).
   Polls /api/state every 2 s while visible; changes are shown at once
   and the next poll corrects them if the panel disagreed. */

"use strict";

const POLL_MS = 2000;
const TIMEOUT_MS = 5000;
const ARM_MS = 3000; // "Släck allt" needs a second tap within this

let state = null;
let pollTimer = null;
let failures = 0;
const touching = new Set(); // sliders being dragged: do not overwrite them

const $ = (id) => document.getElementById(id);

// ---- API -----------------------------------------------------------------

async function call(method, path, body) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const init = { method, signal: ctrl.signal };
    if (body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }
    const res = await fetch(path, init);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(detailOf(data) || `Fel ${res.status}`);
    return data;
  } catch (e) {
    if (e.name === "AbortError") throw new Error("Panelen svarar inte");
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

function detailOf(data) {
  const d = data && data.detail;
  if (!d) return "";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg).join(", ");
  return String(d);
}

const get = (path) => call("GET", path);
const post = (path, body) => call("POST", path, body);

/* Does a change: shows it at once (patch), sends it, refreshes. */
async function act(path, body, patch) {
  if (patch && state) {
    patch(state);
    render(state);
  }
  try {
    await post(path, body);
  } catch (e) {
    toast(e.message, true);
  }
  await refresh();
}

// ---- polling -------------------------------------------------------------

async function refresh() {
  try {
    state = await get("/api/state");
    failures = 0;
    $("banner").classList.add("hidden");
    render(state);
  } catch (e) {
    failures += 1;
    if (failures >= 2) $("banner").classList.remove("hidden");
  }
}

function schedule() {
  clearTimeout(pollTimer);
  if (document.hidden) return;
  pollTimer = setTimeout(async () => {
    await refresh();
    schedule();
  }, POLL_MS);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearTimeout(pollTimer);
  } else {
    refresh().then(schedule);
  }
});

// ---- rendering -----------------------------------------------------------

function setSwitch(el, value) {
  el.indeterminate = value === null || value === undefined;
  el.checked = !!value;
}

function setPill(el, text, on) {
  el.textContent = text;
  el.classList.toggle("on", on === true);
  el.classList.toggle("off", on === false);
}

function render(s) {
  setPill($("st-panel"), `Panel: ${s.text.panel}`, s.switches.master);
  setPill($("st-mega"), s.daemon.mega_connected ? "Mega: ansluten" : "Mega: ej ansluten", s.daemon.mega_connected);
  setPill($("st-alarm"), `Väckning: ${s.text.next_alarm}`);
  $("st-night").classList.toggle("hidden", !s.daemon.night);

  setSwitch($("sw-bed"), s.sockets.bed.on);
  setSwitch($("sw-drawer"), s.sockets.drawer.on);
  $("bed-safety").classList.toggle("hidden", s.sockets.bed.safety);
  $("drawer-safety").classList.toggle("hidden", s.sockets.drawer.safety);

  setSwitch($("sw-backlight"), s.switches.backlight);
  setSwitch($("sw-leds"), s.button_leds);

  const demo = $("sw-demo");
  setSwitch(demo, s.demo);
  demo.disabled = !s.switches.master;
  $("demo-hint").classList.toggle("hidden", s.switches.master);

  for (const seg of s.strips.segments) {
    const box = document.querySelector(`.strip[data-segment="${seg.id}"]`);
    if (!box) continue;
    setSwitch(box.querySelector(".strip-on"), seg.on);
    box.querySelector(".strip-text").textContent = s.text[`strip_${seg.id}`];
    const bri = box.querySelector(".strip-bri");
    if (seg.brightness !== null && !touching.has(bri)) bri.value = seg.brightness;
  }

  const vol = $("vol");
  if (!touching.has(vol)) vol.value = s.audio.volume;
  $("vol-text").textContent = s.text.volume;
  $("muted-hint").classList.toggle("hidden", !s.audio.muted);
  for (const b of document.querySelectorAll("#presets .btn, #sysounds .btn")) b.disabled = s.audio.muted;
  $("btn-stop").classList.toggle("playing", s.audio.playing);
}

// ---- sounds --------------------------------------------------------------

async function loadSounds() {
  let sounds = [];
  try {
    sounds = await get("/api/sounds");
  } catch (e) {
    return;
  }
  const presets = $("presets");
  const sys = $("sysounds");
  presets.replaceChildren();
  sys.replaceChildren();
  for (const sound of sounds) {
    const isPreset = /^btn_\d+$/.test(sound.id); // btn_clicked is a system sound
    const b = document.createElement("button");
    b.className = "btn" + (isPreset ? " preset" : "");
    b.textContent = sound.label;
    b.addEventListener("click", () => playSound(sound.id, b));
    (isPreset ? presets : sys).appendChild(b);
  }
  if (state) render(state);
}

async function playSound(id, button) {
  button.classList.add("playing");
  try {
    await post(`/api/sounds/${encodeURIComponent(id)}`);
  } catch (e) {
    toast(e.message, true);
  }
  setTimeout(() => button.classList.remove("playing"), 600);
}

// ---- wiring --------------------------------------------------------------

function onSwitch(id, path, patch) {
  $(id).addEventListener("change", (ev) => {
    const on = ev.target.checked;
    act(path, { on }, (s) => patch(s, on));
  });
}

function trackSlider(el) {
  const start = () => touching.add(el);
  const end = () => touching.delete(el);
  el.addEventListener("pointerdown", start);
  el.addEventListener("touchstart", start, { passive: true });
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  el.addEventListener("touchend", end);
  el.addEventListener("touchcancel", end);
}

function hexToRgb(hex) {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
}

function wire() {
  onSwitch("sw-bed", "/api/sockets/bed", (s, on) => (s.sockets.bed.on = on));
  onSwitch("sw-drawer", "/api/sockets/drawer", (s, on) => (s.sockets.drawer.on = on));
  onSwitch("sw-backlight", "/api/backlight", (s, on) => (s.switches.backlight = on));
  onSwitch("sw-leds", "/api/leds", (s, on) => (s.button_leds = on));
  onSwitch("sw-demo", "/api/demo", (s, on) => (s.demo = on));

  $("btn-bedlamp").addEventListener("click", () => act("/api/bedlamp/toggle"));
  $("btn-stop").addEventListener("click", () => act("/api/audio/stop"));

  const vol = $("vol");
  trackSlider(vol);
  vol.addEventListener("change", () => {
    const percent = Number(vol.value);
    act("/api/audio/volume", { percent }, (s) => {
      s.audio.volume = percent;
      s.text.volume = `${percent} %`;
    });
  });
  vol.addEventListener("input", () => ($("vol-text").textContent = `${vol.value} %`));

  for (const box of document.querySelectorAll(".strip")) {
    const seg = Number(box.dataset.segment);
    const base = `/api/strips/${seg}`;
    const patchSeg = (s, values) => Object.assign(s.strips.segments[seg], values);
    box.querySelector(".strip-on").addEventListener("change", (ev) => {
      const on = ev.target.checked;
      act(base, { on }, (s) => patchSeg(s, { on }));
    });
    const bri = box.querySelector(".strip-bri");
    trackSlider(bri);
    bri.addEventListener("change", () => {
      const brightness = Number(bri.value);
      act(base, { brightness }, (s) => patchSeg(s, { brightness }));
    });
    box.querySelector(".strip-color").addEventListener("change", (ev) => {
      act(base, { color: hexToRgb(ev.target.value) });
    });
    box.querySelector(".strip-prev").addEventListener("click", () => act(`${base}/effect/prev`));
    box.querySelector(".strip-next").addEventListener("click", () => act(`${base}/effect/next`));
    box.querySelector(".strip-off").addEventListener("click", () => act(`${base}/effect/off`));
  }

  const allOff = $("btn-alloff");
  let armed = null;
  allOff.addEventListener("click", () => {
    if (armed) {
      clearTimeout(armed);
      armed = null;
      allOff.classList.remove("armed");
      allOff.textContent = "Släck allt";
      act("/api/all-off");
      return;
    }
    allOff.classList.add("armed");
    allOff.textContent = "Tryck igen för att släcka allt";
    armed = setTimeout(() => {
      armed = null;
      allOff.classList.remove("armed");
      allOff.textContent = "Släck allt";
    }, ARM_MS);
  });
}

// ---- toast ---------------------------------------------------------------

let toastTimer = null;
function toast(message, isError) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("error", !!isError);
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3000);
}

// ---- start ---------------------------------------------------------------

wire();
refresh().then(schedule);
loadSounds();
setInterval(loadSounds, 60000);
