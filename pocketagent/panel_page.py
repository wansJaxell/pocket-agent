"""The panel page: HTML, CSS and JavaScript in one string, so the app stays a single file.

Everything shown from the server (model answers, names, logs) is inserted with textContent,
never as HTML, so a web page or a model answer cannot inject code into the panel.
"""

PAGE = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="pocket-token" content="__TOKEN__">
<title>PocketAgent</title>
<style nonce="__NONCE__">
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2330;--muted:#5d6678;--line:#dfe3ea;--accent:#2f6fec;--accent-text:#fff;
--ok:#16834a;--warn:#9a6200;--warn-bg:#fff6e0;--bad:#c62828;--bad-bg:#fdecec;--chip:#eef1f6;--me:#e7efff}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--card:#1b2029;--text:#e7eaf0;--muted:#9aa3b5;--line:#2c3340;
--accent:#6b9bff;--accent-text:#0b1020;--ok:#4cc38a;--warn:#f0b54a;--warn-bg:#2d2412;--bad:#ff6b6b;--bad-bg:#3a1c1c;
--chip:#262c37;--me:#1f2b45}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;z-index:5;display:flex;gap:12px;align-items:center;justify-content:space-between;
padding:10px 16px;background:var(--card);border-bottom:1px solid var(--line)}
.brand{display:flex;gap:10px;align-items:center;flex-wrap:wrap;min-width:0}
.brand b{font-size:17px}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{background:var(--chip);color:var(--muted);border-radius:99px;padding:2px 10px;font-size:12.5px;white-space:nowrap}
.chip.on{color:var(--ok)}
.tools{display:flex;gap:8px;align-items:center}
.stack{flex-direction:column}
nav{display:flex;gap:4px;max-width:980px;margin:14px auto 0;padding:0 16px}
nav button{border:0;background:none;color:var(--muted);padding:8px 14px;border-radius:8px;font:inherit;cursor:pointer}
nav button.active{background:var(--card);color:var(--text);font-weight:600;box-shadow:0 1px 0 var(--line)}
main{max-width:980px;margin:0 auto;padding:12px 16px 60px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}
.card h2{margin:0 0 6px;font-size:17px;display:flex;gap:10px;align-items:center}
.card h3{margin:18px 0 6px;font-size:14.5px}
.num{display:inline-grid;place-items:center;width:26px;height:26px;border-radius:50%;background:var(--chip);font-size:13px}
.num.done{background:var(--ok);color:#fff}
.hint{color:var(--muted);margin:4px 0 10px;white-space:pre-line}
.providers{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
.providers button{border:1px solid var(--line);background:var(--bg);color:var(--text);border-radius:10px;padding:8px 12px;
font:inherit;cursor:pointer}
.providers button.selected{border-color:var(--accent);outline:2px solid var(--accent)}
.providers .key{color:var(--ok);margin-left:4px}
.detail{border-top:1px dashed var(--line);margin-top:10px;padding-top:10px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}
input,select,textarea{font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:8px;
padding:8px 10px;min-width:0}
input.grow,select.grow{flex:1 1 240px}
button.btn{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--text);border-radius:8px;
padding:8px 14px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-text);font-weight:600}
button.small{padding:3px 9px;font-size:13px}
button:disabled{opacity:.55;cursor:wait}
a{color:var(--accent)}
.linkbtn{display:inline-block;border:1px solid var(--accent);border-radius:8px;padding:7px 12px;text-decoration:none}
.note{border-radius:8px;padding:8px 12px;margin:8px 0}
.note.warn{background:var(--warn-bg);color:var(--warn)}
.note.bad{background:var(--bad-bg);color:var(--bad)}
.ok{color:var(--ok)}
ol.brains{margin:6px 0;padding-left:0;list-style:none;counter-reset:b}
ol.brains li{counter-increment:b;display:flex;gap:8px;align-items:center;flex-wrap:wrap;border:1px solid var(--line);
border-radius:10px;padding:8px 10px;margin:6px 0}
ol.brains li::before{content:counter(b);font-weight:700;color:var(--muted);width:18px}
ol.brains .label{flex:1 1 220px;font-weight:600;overflow-wrap:anywhere}
.tag{font-size:12px;border-radius:99px;padding:1px 8px;background:var(--chip);color:var(--muted)}
.tag.free{color:var(--ok)}
.messages{display:flex;flex-direction:column;gap:10px;min-height:45vh;padding:4px 0}
.msg{max-width:85%;padding:10px 14px;border-radius:14px;white-space:pre-wrap;overflow-wrap:anywhere;
border:1px solid var(--line);background:var(--card)}
.msg.me{align-self:flex-end;background:var(--me)}
.msg.notice{align-self:center;background:none;border-style:dashed;color:var(--muted);font-size:13.5px}
.msg .meta{margin-top:6px;font-size:12.5px;color:var(--muted);white-space:normal}
.msg.pending{color:var(--muted);font-style:italic}
form.send{position:sticky;bottom:0;display:flex;gap:8px;padding:10px 0;background:var(--bg)}
form.send textarea{flex:1;resize:vertical;min-height:46px;max-height:40vh}
#toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);max-width:min(92vw,620px);padding:10px 16px;
border-radius:10px;background:var(--text);color:var(--bg);opacity:0;transition:opacity .2s;pointer-events:none;z-index:20}
#toast.show{opacity:1}
#toast.bad{background:var(--bad);color:#fff}
[hidden]{display:none!important}
@media (max-width:560px){.msg{max-width:100%}header{flex-wrap:wrap}}
</style>
</head>
<body>
<header>
  <div class="brand"><span aria-hidden="true">🤖</span><b id="agent-name">PocketAgent</b><span class="chips" id="chips"></span></div>
  <div class="tools">
    <select id="lang" aria-label="Language"><option value="tr">TR</option><option value="en">EN</option></select>
  </div>
</header>
<nav id="tabs">
  <button data-tab="setup" data-t="tab.setup"></button>
  <button data-tab="chat" data-t="tab.chat"></button>
</nav>
<main>
  <section id="tab-setup" hidden>
    <article class="card" id="step-brain">
      <h2><span class="num" id="num-brain">1</span><span data-t="step.brain"></span></h2>
      <p class="hint" data-t="brain.intro"></p>
      <div class="providers" id="providers"></div>
      <div class="detail" id="detail" hidden></div>
      <h3 data-t="brain.order"></h3>
      <ol class="brains" id="brains"></ol>
      <p class="hint" data-t="brain.fallback"></p>
    </article>
    <article class="card" id="step-telegram">
      <h2><span class="num" id="num-telegram">2</span><span data-t="step.telegram"></span>
        <span class="tag" data-t="optional"></span></h2>
      <div id="telegram"></div>
    </article>
    <article class="card" id="step-name">
      <h2><span class="num done">3</span><span data-t="step.name"></span></h2>
      <div class="row">
        <input id="name" class="grow" maxlength="40" autocomplete="off" aria-label="Name">
        <button class="btn primary" id="save-name" data-t="save"></button>
      </div>
    </article>
  </section>
  <section id="tab-chat" hidden>
    <div class="messages" id="messages" aria-live="polite"></div>
    <form class="send" id="send">
      <textarea id="text" rows="2" data-ph="chat.placeholder"></textarea>
      <div class="tools stack">
        <button class="btn primary" data-t="chat.send"></button>
        <button class="btn small" type="button" id="reset" data-t="chat.reset"></button>
      </div>
    </form>
  </section>
</main>
<div id="toast" role="status"></div>
<script nonce="__NONCE__">
"use strict";
const TOKEN = document.querySelector('meta[name="pocket-token"]').content;
const T = {
en: {
 "tab.setup": "Setup", "tab.chat": "Chat", "optional": "optional", "save": "Save", "saved": "Saved ✓",
 "step.brain": "Connect a brain", "step.telegram": "Connect Telegram", "step.name": "Name your agent",
 "brain.intro": "Choose where your agent thinks. All of these have a free option. You can add several and put them in order.",
 "brain.getkey": "Get your free key ↗", "brain.key": "Paste the API key", "brain.savekey": "Save key",
 "brain.saved": "Saved key:", "brain.oauth": "Sign in with OpenRouter (no key to copy)",
 "brain.oauthwait": "Finish the login in the new tab, then come back here.", "brain.orpaste": "…or paste a key:",
 "brain.training": "⚠️ On the free tier your messages may be used to train the provider's models. Do not send anything private.",
 "brain.github": "Create a fine-grained token and give it the \"Models: Read\" permission.",
 "brain.custom_url": "API address, e.g. http://192.168.1.5:11434/v1", "brain.model": "Model",
 "brain.model_ph": "Pick from the list or type a model name", "brain.add": "Add and test",
 "brain.testing": "Testing the model…", "brain.added": "Added ✓", "brain.order": "Your brains, in order",
 "brain.none": "No brain yet: add one above.",
 "brain.fallback": "If the first brain runs out of free credit or is rate-limited (HTTP 402/403/429), the next free one answers. Every answer shows which brain was used.",
 "brain.free": "free", "brain.paid": "paid: never used as a fallback", "brain.texttools": "tools as text",
 "brain.test": "Test", "brain.works": "works ✓", "brain.local_none": "No model server is running on this computer. Install Ollama from ollama.com, then run: ollama pull qwen3.5:9b",
 "brain.local_empty": "The server is running but has no models yet. Example: ollama pull qwen3.5:9b",
 "brain.nokey": "Save a key first, then choose a model.",
 "tg.intro": "Talk to your agent from any phone. Only you will be able to use it.",
 "tg.steps": "1. In Telegram, open @BotFather and send /newbot.\n2. Choose a name, then a username ending in \"bot\".\n3. Paste the token it sends you (looks like 123456789:ABC…).",
 "tg.botfather": "Open @BotFather ↗", "tg.token": "Bot token", "tg.connect": "Connect",
 "tg.waiting": "Now open your bot on your phone and press START:",
 "tg.first": "The first person to press START becomes the owner. Waiting…",
 "tg.connected": "Connected:", "tg.owner": "Only your chat can talk to the agent.", "tg.disconnect": "Disconnect",
 "tg.timeout": "Nobody pressed START in time. Try again.", "tg.error": "Something went wrong. Try again.",
 "chat.placeholder": "Write a message… (Enter sends, Shift+Enter: new line)", "chat.send": "Send",
 "chat.reset": "New chat", "chat.thinking": "thinking…", "chat.nobrain": "Connect a brain in Setup first.",
 "chip.brain": "brain", "chip.nobrain": "no brain yet", "chip.tg": "Telegram", "chip.notg": "Telegram off"
},
tr: {
 "tab.setup": "Kurulum", "tab.chat": "Sohbet", "optional": "isteğe bağlı", "save": "Kaydet", "saved": "Kaydedildi ✓",
 "step.brain": "Beyin bağla", "step.telegram": "Telegram bağla", "step.name": "Ajanına bir ad ver",
 "brain.intro": "Ajanının nerede düşüneceğini seç. Hepsinin ücretsiz bir seçeneği var. Birden fazla ekleyip sıraya koyabilirsin.",
 "brain.getkey": "Ücretsiz anahtarını al ↗", "brain.key": "API anahtarını yapıştır", "brain.savekey": "Anahtarı kaydet",
 "brain.saved": "Kayıtlı anahtar:", "brain.oauth": "OpenRouter ile giriş yap (anahtar kopyalamadan)",
 "brain.oauthwait": "Yeni sekmede girişi tamamla, sonra buraya dön.", "brain.orpaste": "…ya da bir anahtar yapıştır:",
 "brain.training": "⚠️ Ücretsiz katmanda mesajların sağlayıcının modellerini eğitmekte kullanılabilir. Özel bir şey gönderme.",
 "brain.github": "İnce ayarlı (fine-grained) bir token oluştur ve ona \"Models: Read\" izni ver.",
 "brain.custom_url": "API adresi, ör. http://192.168.1.5:11434/v1", "brain.model": "Model",
 "brain.model_ph": "Listeden seç ya da model adını yaz", "brain.add": "Ekle ve test et",
 "brain.testing": "Model test ediliyor…", "brain.added": "Eklendi ✓", "brain.order": "Beyinlerin (öncelik sırasıyla)",
 "brain.none": "Henüz beyin yok: yukarıdan bir tane ekle.",
 "brain.fallback": "İlk beyin ücretsiz kotasını bitirirse ya da sınıra takılırsa (HTTP 402/403/429) sıradaki ücretsiz beyin cevap verir. Her cevabın altında hangi beynin kullanıldığı yazar.",
 "brain.free": "ücretsiz", "brain.paid": "ücretli: yedek olarak kullanılmaz", "brain.texttools": "araçlar metinle",
 "brain.test": "Test et", "brain.works": "çalışıyor ✓", "brain.local_none": "Bu bilgisayarda çalışan bir model sunucusu yok. Ollama'yı ollama.com'dan kur, sonra şunu çalıştır: ollama pull qwen3.5:9b",
 "brain.local_empty": "Sunucu çalışıyor ama henüz modeli yok. Örnek: ollama pull qwen3.5:9b",
 "brain.nokey": "Önce anahtarı kaydet, sonra bir model seç.",
 "tg.intro": "Ajanınla her telefondan konuş. Onu sadece sen kullanabileceksin.",
 "tg.steps": "1. Telegram'da @BotFather'ı aç ve /newbot gönder.\n2. Bir ad, sonra \"bot\" ile biten bir kullanıcı adı seç.\n3. Sana gönderdiği token'ı yapıştır (123456789:ABC… gibi görünür).",
 "tg.botfather": "@BotFather'ı aç ↗", "tg.token": "Bot token'ı", "tg.connect": "Bağlan",
 "tg.waiting": "Şimdi telefonunda botunu aç ve START'a bas:",
 "tg.first": "START'a basan ilk kişi sahibi olur. Bekleniyor…",
 "tg.connected": "Bağlı:", "tg.owner": "Ajanla sadece senin sohbetin konuşabilir.", "tg.disconnect": "Bağlantıyı kes",
 "tg.timeout": "Zamanında kimse START'a basmadı. Tekrar dene.", "tg.error": "Bir sorun çıktı. Tekrar dene.",
 "chat.placeholder": "Bir mesaj yaz… (Enter gönderir, Shift+Enter: yeni satır)", "chat.send": "Gönder",
 "chat.reset": "Yeni sohbet", "chat.thinking": "düşünüyor…", "chat.nobrain": "Önce Kurulum'dan bir beyin bağla.",
 "chip.brain": "beyin", "chip.nobrain": "beyin yok", "chip.tg": "Telegram", "chip.notg": "Telegram kapalı"
}};
let lang = document.documentElement.lang || (navigator.language.toLowerCase().startsWith("tr") ? "tr" : "en");
let S = null, selected = null, tab = null, models = {}, local = null;
const shown = {};                       // last rendered data per section: re-render only on change
const t = k => (T[lang] && T[lang][k]) || T.en[k] || k;
const $ = id => document.getElementById(id);

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}

function fill(el, ...kids) {           // like replaceChildren, but skips null / false parts
  el.replaceChildren(...kids.flat().filter(k => k != null && k !== false));
  return el;
}

async function api(path, body) {
  const options = {headers: {"X-Pocket-Token": TOKEN}};
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const reply = await fetch("/api/" + path, options);
  const data = await reply.json().catch(() => ({}));
  if (!reply.ok) throw new Error(data.error || ("HTTP " + reply.status));
  return data;
}

let toastTimer;
function toast(message, bad) {
  const box = $("toast");
  box.textContent = message;
  box.className = "show" + (bad ? " bad" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.className = "", bad ? 7000 : 2500);
}

async function act(button, work) {
  if (button) button.disabled = true;
  try { return await work(); }
  catch (error) { toast(error.message, true); }
  finally { if (button) button.disabled = false; }
}

function changed(section, data) {
  const key = JSON.stringify(data) + lang;
  if (shown[section] === key) return false;
  shown[section] = key;
  return true;
}

function applyLanguage() {
  document.documentElement.lang = lang;
  $("lang").value = lang;
  document.querySelectorAll("[data-t]").forEach(el => el.textContent = t(el.dataset.t));
  document.querySelectorAll("[data-ph]").forEach(el => el.placeholder = t(el.dataset.ph));
  for (const key in shown) delete shown[key];
  if (S) render();
}

function showTab(name) {
  tab = name;
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll("main > section").forEach(s => s.hidden = s.id !== "tab-" + name);
  if (name === "chat") loadHistory();
}

// ---------- header ----------
function renderHeader() {
  $("agent-name").textContent = S.identity.name;
  document.title = S.identity.name + " · PocketAgent";
  if (!changed("chips", [S.brains[0] && S.brains[0].label, S.telegram.connected])) return;
  fill($("chips"), 
    h("span", {class: "chip" + (S.brains.length ? " on" : ""),
               text: S.brains.length ? "🧠 " + S.brains[0].label : t("chip.nobrain")}),
    h("span", {class: "chip" + (S.telegram.connected ? " on" : ""),
               text: S.telegram.connected ? "✈️ @" + S.telegram.username : t("chip.notg")}));
}

// ---------- step 1: brains ----------
function provider(id) { return S.providers.find(p => p.id === id); }

function renderProviders() {
  $("num-brain").className = "num" + (S.setup.brain ? " done" : "");
  if (!changed("providers", [selected, S.providers.map(p => [p.id, p.has_key])])) return;
  fill($("providers"), ...S.providers.map(p => h("button", {
      class: p.id === selected ? "selected" : "", type: "button",
      onclick: () => { selected = p.id; renderProviders(); renderDetail(); }},
    p.name, p.has_key ? h("span", {class: "key", text: "✓"}) : null)));
}

async function loadModels(p) {
  if (p.local) {
    local = local || await api("local").catch(() => ({}));
    models[p.id] = (local[p.id] || []).map(id => ({id, free: true}));
  } else if (p.has_key || p.id === "custom") {
    models[p.id] = (await api("models?provider=" + p.id).catch(() => ({models: []}))).models;
  }
}

async function renderDetail() {
  const box = $("detail"), p = provider(selected);
  box.hidden = !p;
  if (!p) return;
  const parts = [h("p", {class: "hint", text: p.label})];
  if (p.trains_on_data) parts.push(h("div", {class: "note warn", text: t("brain.training")}));
  if (p.oauth) {
    const button = h("button", {class: "btn primary", type: "button", text: t("brain.oauth"), onclick: () => act(button, async () => {
      const {url} = await api("openrouter/start", {});
      window.open(url, "_blank", "noopener");
      toast(t("brain.oauthwait"));
    })});
    parts.push(h("div", {class: "row"}, button), h("p", {class: "hint", text: t("brain.orpaste")}));
  }
  if (p.id === "github") parts.push(h("p", {class: "hint", text: t("brain.github")}));
  if (p.needs_key) {
    const url = h("input", {class: "grow", placeholder: t("brain.custom_url"), value: S.custom_url || "",
                            autocomplete: "off", "aria-label": "URL"});
    const key = h("input", {class: "grow", type: "password", placeholder: t("brain.key"), autocomplete: "off",
                            "aria-label": t("brain.key")});
    const save = h("button", {class: "btn primary", type: "button", text: t("brain.savekey"), onclick: () => act(save, async () => {
      const result = await api("key", {provider: p.id, key: key.value, base_url: url.value});
      models[p.id] = result.models;
      toast(t("saved"));
      await refresh();
      renderDetail();
    })});
    if (p.id === "custom") parts.push(h("div", {class: "row"}, url));
    parts.push(h("div", {class: "row"}, key, save,
      p.key_url ? h("a", {class: "linkbtn", href: p.key_url, target: "_blank", rel: "noopener noreferrer",
                          text: t("brain.getkey")}) : null));
    if (p.has_key) parts.push(h("p", {class: "ok", text: t("brain.saved") + " " + p.key_hint}));
  }
  fill(box, ...parts, h("div", {id: "model-box"}));
  if (models[p.id] === undefined) await loadModels(p);
  if (selected === p.id) renderModelChooser(p);
}

function renderModelChooser(p) {
  const box = $("model-box");
  if (!box) return;
  if (p.id === "custom" ? !S.custom_url : p.needs_key && !p.has_key)
    return fill(box, h("p", {class: "hint", text: t("brain.nokey")}));
  const list = models[p.id] || [];
  if (p.local && !list.length)
    return fill(box, h("div", {class: "note warn", text: local && local[p.id] ? t("brain.local_empty") : t("brain.local_none")}));
  const options = h("datalist", {id: "model-options"}, list.map(m => h("option", {value: m.id},
    m.id + (p.id === "openrouter" ? (m.free ? " · " + t("brain.free") : " · $") : ""))));
  const first = list.find(m => m.free) || list[0];
  const input = h("input", {class: "grow", list: "model-options", placeholder: t("brain.model_ph"),
                            value: (first && first.id) || p.suggested_model || "", autocomplete: "off",
                            "aria-label": t("brain.model")});
  const add = h("button", {class: "btn primary", type: "button", text: t("brain.add"), onclick: () => act(add, async () => {
    toast(t("brain.testing"));
    const chosen = list.find(m => m.id === input.value.trim());
    await api("brains/add", {provider: p.id, model: input.value, free: chosen ? chosen.free : true});
    toast(t("brain.added"));
    await refresh();
  })});
  fill(box, h("div", {class: "row"}, h("b", {text: t("brain.model")}), input, options, add));
}

function renderBrains() {
  if (!changed("brains", S.brains)) return;
  const items = S.brains.map((b, i) => {
    const test = h("button", {class: "btn small", type: "button", text: t("brain.test"), onclick: () => act(test, async () => {
      const result = await api("brains/test", {index: i});
      toast(result.ok ? b.label + ": " + t("brain.works") : result.message, !result.ok);
    })});
    const move = (delta, label) => h("button", {class: "btn small", type: "button", text: label, "aria-label": label,
      disabled: (delta < 0 && i === 0) || (delta > 0 && i === S.brains.length - 1),
      onclick: () => act(null, async () => { await api("brains/move", {index: i, delta}); await refresh(); })});
    return h("li", {},
      h("span", {class: "label", text: b.label}),
      h("span", {class: "tag" + (b.free ? " free" : ""), text: b.free ? t("brain.free") : t("brain.paid")}),
      b.native_tools ? null : h("span", {class: "tag", text: t("brain.texttools")}),
      move(-1, "↑"), move(1, "↓"), test,
      h("button", {class: "btn small", type: "button", text: "✕", "aria-label": "remove",
                   onclick: () => act(null, async () => { await api("brains/remove", {index: i}); await refresh(); })}));
  });
  fill($("brains"), ...(items.length ? items : [h("p", {class: "hint", text: t("brain.none")})]));
}

// ---------- step 2: Telegram ----------
function renderTelegram() {
  const tg = S.telegram;
  $("num-telegram").className = "num" + (tg.connected ? " done" : "");
  if (!changed("telegram", tg)) return;
  const box = $("telegram");
  if (tg.connected) {
    const off = h("button", {class: "btn", type: "button", text: t("tg.disconnect"),
                             onclick: () => act(off, async () => { await api("telegram/disconnect", {}); await refresh(); })});
    return fill(box, 
      h("p", {class: "ok"}, t("tg.connected") + " ", h("a", {href: tg.link, target: "_blank", rel: "noopener noreferrer", text: "@" + tg.username})),
      h("p", {class: "hint", text: t("tg.owner")}), off);
  }
  if (tg.status === "waiting") {
    return fill(box, 
      h("p", {}, t("tg.waiting") + " ", h("a", {class: "linkbtn", href: tg.link, target: "_blank", rel: "noopener noreferrer", text: "t.me/" + tg.username + " ↗"})),
      h("p", {class: "hint", text: t("tg.first")}));
  }
  const token = h("input", {class: "grow", type: "password", placeholder: t("tg.token"), autocomplete: "off", "aria-label": t("tg.token")});
  const connect = h("button", {class: "btn primary", type: "button", text: t("tg.connect"),
                               onclick: () => act(connect, async () => { await api("telegram", {token: token.value}); await refresh(); })});
  fill(box, 
    h("p", {class: "hint", text: t("tg.intro")}),
    tg.status === "timeout" ? h("div", {class: "note warn", text: t("tg.timeout")}) : null,
    tg.status === "error" ? h("div", {class: "note bad", text: t("tg.error")}) : null,
    h("p", {class: "hint", text: t("tg.steps")}),
    h("div", {class: "row"}, token, connect,
      h("a", {class: "linkbtn", href: "https://t.me/BotFather", target: "_blank", rel: "noopener noreferrer", text: t("tg.botfather")})));
}

// ---------- step 3: name ----------
function renderName() {
  if (changed("name", S.identity.name) && document.activeElement !== $("name")) $("name").value = S.identity.name;
}

// ---------- chat ----------
let historyLoaded = false;
function bubble(kind, text, meta) {
  const el = h("div", {class: "msg " + kind, text});
  if (meta) el.append(h("div", {class: "meta", text: meta}));
  $("messages").append(el);
  el.scrollIntoView({block: "end", behavior: "smooth"});
  return el;
}
function metaOf(result) {
  const parts = [];
  if (result.tools && result.tools.length) parts.push("🔧 " + [...new Set(result.tools)].join(", "));
  if (result.brain) parts.push("🧠 " + result.brain + (result.skipped && result.skipped.length ? " (↪ " + result.skipped.join(", ") + ")" : ""));
  return parts.join("   ");
}
async function loadHistory() {
  if (historyLoaded) return;
  historyLoaded = true;
  const messages = await api("history").catch(() => []);
  // prepend: messages sent while the history was loading stay below it
  $("messages").prepend(...messages.map(m => h("div", {class: "msg" + (m.role === "user" ? " me" : ""), text: m.content})));
  if (S && !S.brains.length) bubble("notice", t("chat.nobrain"));
}
async function send(text) {
  bubble("me", text);
  const waiting = bubble("pending", t("chat.thinking"));
  try {
    let job = await api("chat", {text});
    while (job.status === "queued" || job.status === "running") {
      await new Promise(r => setTimeout(r, 700));
      job = await api("job?id=" + job.id);
    }
    waiting.className = "msg";
    if (job.status === "done") {
      waiting.textContent = job.result.text;
      const meta = metaOf(job.result);
      if (meta) waiting.append(h("div", {class: "meta", text: meta}));
    } else {
      waiting.classList.add("notice");
      waiting.textContent = "⚠️ " + (job.error || job.status);
    }
  } catch (error) {
    waiting.className = "msg notice";
    waiting.textContent = "⚠️ " + error.message;
  }
}

let noticesSeen = null;                 // reminders etc. that arrived while the page is open
function renderNotices() {
  const keys = S.notices.map(n => n.time + n.text);
  if (noticesSeen) S.notices.filter((n, i) => !noticesSeen.has(keys[i])).forEach(n => bubble("notice", n.text));
  noticesSeen = new Set(keys);
}

function render() {
  renderHeader(); renderProviders(); renderBrains(); renderTelegram(); renderName(); renderNotices();
}

async function refresh() {
  try {
    S = await api("state");
    render();
  } catch (error) { toast(error.message, true); }
}

// ---------- wiring ----------
document.querySelectorAll("#tabs button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));
$("lang").addEventListener("change", () => act(null, async () => {
  lang = $("lang").value;
  applyLanguage();
  await api("language", {language: lang});
}));
$("save-name").addEventListener("click", () => act($("save-name"), async () => {
  await api("identity", {name: $("name").value});
  toast(t("saved"));
  await refresh();
}));
$("send").addEventListener("submit", event => {
  event.preventDefault();
  const text = $("text").value.trim();
  if (!text) return;
  $("text").value = "";
  send(text);
});
$("text").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("send").requestSubmit(); }
});
$("reset").addEventListener("click", () => act($("reset"), async () => {
  await api("chat/reset", {});
  fill($("messages"));
}));

(async function start() {
  applyLanguage();
  await refresh();
  if (!S) return;
  if (!S.language) api("language", {language: lang}).catch(() => {});   // Telegram notices follow it
  showTab(S.setup.brain ? "chat" : "setup");
  setInterval(refresh, 2000);
})();
</script>
</body>
</html>
"""


def render_page(token: str, nonce: str, language: str) -> str:
    return (PAGE.replace("__TOKEN__", token).replace("__NONCE__", nonce)
            .replace("__LANG__", language if language in ("en", "tr") else ""))
