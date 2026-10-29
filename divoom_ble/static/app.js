"use strict";
(() => {
  const N = 16;
  const token = new URLSearchParams(location.search).get("token");
  let device = localStorage.getItem("device");          // which screen this page controls
  const withParams = (path, withDevice = true) => {
    const q = new URLSearchParams();
    if (withDevice && device) q.set("device", device);
    if (token) q.set("token", token);
    const qs = q.toString();
    return qs ? `${path}${path.includes("?") ? "&" : "?"}${qs}` : path;
  };
  const withToken = (path) => withParams(path);
  const $ = (id) => document.getElementById(id);

  // ---- state -----------------------------------------------------------------
  let pixels = new Array(N * N).fill("000000");
  let ws = null, lastLocalPaint = 0, drawing = false, tool = "pen";
  let penColour = "f2c230";
  let pendingPaint = new Map();
  let state = {};

  // ---- toast -----------------------------------------------------------------
  let toastTimer;
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
  }

  // ---- LED panel ---------------------------------------------------------------
  const canvas = $("panel");
  const ctx = canvas.getContext("2d");
  const cell = canvas.width / N;
  function render() {
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const r = cell * 0.40;
    for (let i = 0; i < N * N; i++) {
      const x = (i % N) * cell + cell / 2, y = Math.floor(i / N) * cell + cell / 2;
      const hex = pixels[i];
      const lit = hex !== "000000";
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      if (lit) {
        ctx.shadowColor = "#" + hex;
        ctx.shadowBlur = cell * 0.55;
        ctx.fillStyle = "#" + hex;
      } else {
        ctx.shadowBlur = 0;
        ctx.fillStyle = "#15181b";
      }
      ctx.fill();
    }
    ctx.shadowBlur = 0;
  }

  // ---- connection ------------------------------------------------------------
  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    else toast("Not connected to the server yet");
  }
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const sock = new WebSocket(withToken(`${proto}://${location.host}/ws`));
    ws = sock;
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "frame") {
        if (drawing || performance.now() - lastLocalPaint < 400) return;   // keep the local stroke crisp
        pixels = msg.pixels;
        render();
      } else if (msg.type === "state") {
        applyState(msg);
      } else if (msg.type === "error") {
        toast(msg.error);
      }
    };
    sock.onclose = () => {
      if (ws !== sock) return;                        // replaced by a device switch
      applyState({ ...state, server: false });
      setTimeout(() => { if (ws === sock) connect(); }, 1500);
    };
  }

  // ---- devices ---------------------------------------------------------------
  let devices = [];
  function renderDevices() {
    const nav = $("devices");
    nav.replaceChildren(...devices.map((d) => {
      const b = document.createElement("button");
      b.className = "device";
      b.dataset.state = d.connected ? "on" : "off";
      b.setAttribute("aria-pressed", String(d.device === device));
      b.title = d.connected ? `${d.title} is connected` : `${d.title} is not connected`;
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.setAttribute("aria-hidden", "true");
      b.append(dot, d.title);
      b.addEventListener("click", () => switchDevice(d.device));
      return b;
    }));
  }
  async function loadDevices() {
    try {
      devices = await (await fetch(withParams("/api/devices", false))).json();
    } catch (e) { return; }
    if (!devices.some((d) => d.device === device)) device = devices[0] && devices[0].device;
    renderDevices();
  }
  function switchDevice(key) {
    if (key === device) return;
    device = key;
    localStorage.setItem("device", key);
    pixels = new Array(N * N).fill("000000");
    render();
    renderDevices();
    const old = ws;
    connect();
    if (old) old.close();
  }

  function applyState(s) {
    state = s;
    const link = $("link"), text = $("link-text");
    const name = s.title || "the screen";
    if (s.server === false) {
      link.dataset.state = "off"; text.textContent = "Server not reachable, retrying";
    } else if (s.connected) {
      link.dataset.state = "on";
      text.textContent = "Connected";
    } else {
      link.dataset.state = "off"; text.textContent = `Looking for the ${name}…`;
    }
    const d = devices.find((x) => x.device === s.device);
    if (d && s.server !== false && d.connected !== !!s.connected) { d.connected = !!s.connected; renderDevices(); }
    if (s.brightness != null && document.activeElement !== $("brightness")) {
      $("brightness").value = s.brightness;
      $("brightness-out").textContent = s.brightness;
    }
    let caption = `This is what the ${name} shows. Draw on it.`;
    if (s.upload != null) { $("caption").textContent = `Sending the animation to the ${name}, ${Math.round(s.upload * 100)}%`; markPresets(s.scene); return; }
    const sc = s.scene;
    if (s.channel === "device") caption = `The ${name} switched to its own mode from a button press.`;
    else if (s.channel) caption = `The ${name} is showing its built-in ${s.channel} mode.`;
    else if (sc && sc.kind === "preset") caption = `Playing ${sc.title}.`;
    else if (sc && sc.kind === "text") caption = "Showing your text.";
    else if (sc && sc.kind === "value") caption = "Showing your data widget.";
    else if (sc && sc.kind === "image") caption = sc.frames > 1 ? `Playing ${sc.name} (${sc.frames} frames).` : `Showing ${sc.name}.`;
    $("caption").textContent = caption;
    markPresets(sc);
  }
  function markPresets(sc) {
    document.querySelectorAll("#presets button").forEach((b) =>
      b.setAttribute("aria-pressed", String(!!(sc && sc.kind === "preset" && sc.name === b.dataset.preset))));
  }

  // ---- drawing ---------------------------------------------------------------
  function cellAt(ev) {
    const rect = canvas.getBoundingClientRect();
    const x = Math.floor(((ev.clientX - rect.left) / rect.width) * N);
    const y = Math.floor(((ev.clientY - rect.top) / rect.height) * N);
    return x >= 0 && x < N && y >= 0 && y < N ? y * N + x : -1;
  }
  function paintAt(i) {
    if (i < 0) return;
    const colour = tool === "erase" ? "000000" : penColour;
    if (pixels[i] === colour) return;
    pixels[i] = colour;
    pendingPaint.set(i, colour);
    lastLocalPaint = performance.now();
    render();
  }
  function floodFill(start) {
    const from = pixels[start], to = penColour;
    if (from === to) return;
    const stack = [start];
    while (stack.length) {
      const i = stack.pop();
      if (pixels[i] !== from) continue;
      pixels[i] = to;
      const x = i % N, y = Math.floor(i / N);
      if (x > 0) stack.push(i - 1);
      if (x < N - 1) stack.push(i + 1);
      if (y > 0) stack.push(i - N);
      if (y < N - 1) stack.push(i + N);
    }
    lastLocalPaint = performance.now();
    render();
    send({ type: "pixels", pixels });
  }
  setInterval(() => {
    if (!pendingPaint.size) return;
    send({ type: "paint", changes: [...pendingPaint.entries()] });
    pendingPaint = new Map();
  }, 40);

  canvas.addEventListener("pointerdown", (ev) => {
    const i = cellAt(ev);
    if (i < 0) return;
    if (tool === "pick") { setPen(pixels[i]); selectTool("pen"); return; }
    if (tool === "fill") { floodFill(i); return; }
    drawing = true;
    canvas.setPointerCapture(ev.pointerId);
    paintAt(i);
  });
  canvas.addEventListener("pointermove", (ev) => { if (drawing) paintAt(cellAt(ev)); });
  const stop = () => { drawing = false; };
  canvas.addEventListener("pointerup", stop);
  canvas.addEventListener("pointercancel", stop);

  function selectTool(name) {
    tool = name;
    document.querySelectorAll(".tool").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tool === name)));
  }
  document.querySelectorAll(".tool").forEach((b) => b.addEventListener("click", () => selectTool(b.dataset.tool)));

  const SWATCHES = ["ffffff", "f2c230", "ff8a00", "ff2d55", "c03cff", "2f5bea", "00c8ff", "2bd67b",
                    "7a4a2a", "ffb3c7", "9aa3ad", "4a5560"];
  function setPen(hex) {
    penColour = hex.replace("#", "").toLowerCase();
    $("pen-colour").value = "#" + penColour;
    document.querySelectorAll("#swatches button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.c === penColour)));
  }
  for (const c of SWATCHES) {
    const b = document.createElement("button");
    b.style.background = "#" + c;
    b.dataset.c = c;
    b.setAttribute("aria-label", `Colour #${c}`);
    b.addEventListener("click", () => { setPen(c); if (tool === "erase" || tool === "pick") selectTool("pen"); });
    $("swatches").appendChild(b);
  }
  $("pen-colour").addEventListener("input", (e) => setPen(e.target.value));
  $("clear").addEventListener("click", () => {
    pixels = new Array(N * N).fill("000000");
    lastLocalPaint = performance.now();
    render();
    send({ type: "fill", color: "#000000" });
  });

  // ---- tabs ------------------------------------------------------------------
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    document.querySelectorAll(".pane").forEach((p) => { p.hidden = p.id !== `pane-${b.dataset.tab}`; });
    if (b.dataset.tab === "text") sendText();
    if (b.dataset.tab === "widget") sendWidget();
  }));

  // ---- text & widget (live) ----------------------------------------------------
  const debounce = (fn, ms) => { let t; return () => { clearTimeout(t); t = setTimeout(fn, ms); }; };
  const sendText = () => send({
    type: "text", text: $("text").value, font: $("text-font").value,
    color: $("text-colour").value, bg: $("text-bg").value, speed: Number($("text-speed").value),
  });
  const sendWidget = () => send({
    type: "value", label: $("w-label").value, value: $("w-value").value,
    bar: $("w-bar-on").checked ? Number($("w-bar").value) / 100 : null,
    color: $("w-colour").value, label_color: $("w-label-colour").value, bar_color: $("w-bar-colour").value,
  });
  const liveText = debounce(sendText, 300), liveWidget = debounce(sendWidget, 200);
  ["text", "text-font", "text-colour", "text-bg", "text-speed"].forEach((id) => $(id).addEventListener("input", liveText));
  ["w-label", "w-value", "w-bar-on", "w-bar", "w-colour", "w-label-colour", "w-bar-colour"].forEach((id) => $(id).addEventListener("input", liveWidget));

  // ---- picture ---------------------------------------------------------------
  async function upload(file) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("fit", $("fit").value);
    try {
      const r = await fetch(withToken("/api/image"), { method: "POST", body: form });
      const j = await r.json();
      if (!j.ok) toast(j.error || "Upload failed");
    } catch (e) { toast("Upload failed: " + e.message); }
  }
  $("file").addEventListener("change", (e) => upload(e.target.files[0]));
  const drop = $("drop");
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); upload(e.dataTransfer.files[0]); });

  // ---- built-in channels & brightness ---------------------------------------
  document.querySelectorAll("[data-channel]").forEach((b) => b.addEventListener("click", () => {
    const kind = b.dataset.channel;
    const msg = { type: "channel", kind };
    if (kind === "vj") msg.index = Number($("vj-index").value);
    if (kind === "light") msg.color = $("light-colour").value;
    send(msg);
  }));
  $("redraw").addEventListener("click", () => send({ type: "redraw" }));
  const sendBrightness = debounce(() => send({ type: "brightness", value: Number($("brightness").value) }), 120);
  $("brightness").addEventListener("input", (e) => { $("brightness-out").textContent = e.target.value; sendBrightness(); });

  // ---- presets ---------------------------------------------------------------
  fetch(withToken("/api/presets")).then((r) => r.json()).then((list) => {
    for (const p of list) {
      const b = document.createElement("button");
      b.className = "ghost";
      b.dataset.preset = p.name;
      b.textContent = p.title;
      b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", () => send({ type: "preset", name: p.name }));
      $("presets").appendChild(b);
    }
    applyState(state);
  });

  // ---- API examples ----------------------------------------------------------
  const base = location.origin, t = token ? `?token=${token}` : "";
  $("api-examples").textContent =
`# show a data widget
curl -X POST ${base}/api/value${t} -H "Content-Type: application/json" \\
     -d '{"label":"BPM","value":"72","bar":0.6}'

# show (or scroll) text
curl -X POST ${base}/api/text${t} -H "Content-Type: application/json" \\
     -d '{"text":"On my way","color":"#f2c230"}'

# play a preset
curl -X POST ${base}/api/preset${t} -H "Content-Type: application/json" \\
     -d '{"name":"heartbeat"}'`;

  setPen(penColour);
  render();
  loadDevices().then(connect);
  setInterval(loadDevices, 4000);          // keep every device's connection dot current
})();
