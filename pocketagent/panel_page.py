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
button.stop{font:inherit;font-weight:800;letter-spacing:.06em;font-size:16px;padding:9px 22px;border-radius:10px;
border:0;background:#d32f2f;color:#fff;cursor:pointer;box-shadow:0 2px 0 #8e1b1b}
button.stop:active{transform:translateY(1px)}
#approvals{max-width:980px;margin:0 auto;padding:0 16px}
.approval{border:2px solid var(--warn);background:var(--warn-bg)}
.approval .params{font-family:ui-monospace,Consolas,monospace;font-size:13.5px;white-space:pre-wrap;overflow-wrap:anywhere;
background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:8px 0}
.switch{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.state-on{color:var(--warn);font-weight:700}
.state-off{color:var(--ok);font-weight:700}
.list{list-style:none;margin:6px 0;padding:0}
.list li{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;border-bottom:1px solid var(--line);padding:6px 0}
.list .what{flex:1 1 300px;overflow-wrap:anywhere;font-family:ui-monospace,Consolas,monospace;font-size:13px}
.list .when{color:var(--muted);font-size:12.5px;white-space:nowrap}
.picker{max-height:380px;overflow:auto;border:1px solid var(--line);border-radius:10px;margin:8px 0}
.picker table{width:100%;border-collapse:collapse;font-size:13.5px}
.picker th{position:sticky;top:0;background:var(--card);text-align:left;font-weight:600;padding:6px 8px;
border-bottom:1px solid var(--line)}
.picker td{padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:middle}
.picker td.mid{overflow-wrap:anywhere;font-family:ui-monospace,Consolas,monospace;font-size:13px}
.picker td.mid .tag{margin-left:6px;font-family:system-ui,sans-serif}
.subcard{border:1px dashed var(--line);border-radius:10px;padding:10px 14px;margin-top:14px}
.subcard h3{margin-top:4px}
input.narrow{width:76px}
label.inline{display:inline-flex;gap:6px;align-items:center}
.sp-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;border-bottom:1px solid var(--line);padding:10px 0}
.sp-kind{min-width:140px}
.sp-row select{max-width:100%}
.try-result{flex-basis:100%}
img.shot{max-width:min(100%,420px);border-radius:10px;display:block;margin-top:8px;border:1px solid var(--line)}
audio{display:block;margin-top:8px;max-width:100%}
label.choice{display:flex;gap:8px;align-items:center;border:1px solid var(--line);border-radius:10px;padding:8px 12px;cursor:pointer}
label.choice input{margin:0}
textarea.wide{width:100%;min-height:70px;resize:vertical}
#lock .card{max-width:440px;margin:12vh auto 0}
[hidden]{display:none!important}
@media (max-width:560px){.msg{max-width:100%}header{flex-wrap:wrap}}
</style>
</head>
<body>
<header>
  <div class="brand"><span aria-hidden="true">🤖</span><b id="agent-name">PocketAgent</b><span class="chips" id="chips"></span></div>
  <div class="tools">
    <button class="stop" id="stop" type="button" data-t="stop"></button>
    <button class="btn small" id="lock-now" type="button" data-t="access.lock_now" hidden></button>
    <select id="lang" aria-label="Language"><option value="tr">TR</option><option value="en">EN</option></select>
  </div>
</header>
<section id="lock" hidden>
  <article class="card">
    <h2>🔒 <span data-t="lock.title"></span></h2>
    <p class="hint" data-t="lock.hint"></p>
    <form class="row" id="unlock-form">
      <input id="unlock-password" class="grow" type="password" autocomplete="current-password" data-ph="lock.password">
      <button class="btn primary" data-t="lock.open"></button>
    </form>
    <button class="btn small" type="button" id="forgot" data-t="lock.forgot"></button>
  </article>
</section>
<section id="approvals" aria-live="assertive"></section>
<nav id="tabs">
  <button data-tab="setup" data-t="tab.setup"></button>
  <button data-tab="chat" data-t="tab.chat"></button>
  <button data-tab="safety" data-t="tab.safety"></button>
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
      </div>
      <textarea id="personality" class="wide" maxlength="2000" data-ph="name.personality"></textarea>
      <div class="row"><button class="btn primary" id="save-name" data-t="save"></button></div>
    </article>
    <article class="card" id="step-access">
      <h2><span class="num done">4</span><span data-t="step.access"></span><span class="tag" id="access-now"></span></h2>
      <p class="hint" data-t="access.hint"></p>
      <div class="row">
        <label class="choice"><input type="radio" name="access" value="open"><span data-t="access.open"></span></label>
        <label class="choice"><input type="radio" name="access" value="locked"><span data-t="access.locked"></span></label>
      </div>
      <div class="row" id="access-password" hidden>
        <input id="pw1" class="grow" type="password" autocomplete="new-password" data-ph="access.pw1">
        <input id="pw2" class="grow" type="password" autocomplete="new-password" data-ph="access.pw2">
      </div>
      <div class="row"><button class="btn primary" id="save-access" data-t="save"></button></div>
    </article>
    <article class="card" id="step-specialists">
      <h2><span class="num">5</span><span data-t="step.specialists"></span><span class="tag" data-t="optional"></span></h2>
      <p class="hint" data-t="sp.intro"></p>
      <div id="specialists"></div>
    </article>
    <article class="card" id="step-more">
      <h2><span class="num">+</span><span data-t="step.more"></span></h2>
      <label class="row"><input type="checkbox" id="autostart"><span data-t="auto.label"></span></label>
      <p class="hint" id="autostart-hint"></p>
      <p class="hint" id="memory"></p>
    </article>
  </section>
  <section id="tab-safety" hidden>
    <article class="card">
      <h2 data-t="cu.title"></h2>
      <div class="switch"><span id="cu-state"></span><button class="btn" id="cu-toggle" type="button"></button></div>
      <p class="hint" data-t="cu.always"></p>
    </article>
    <article class="card">
      <h2 data-t="rules.title"></h2>
      <p class="hint" data-t="rules.hint"></p>
      <ul class="list" id="rules"></ul>
    </article>
    <article class="card">
      <h2 data-t="jobs.title"></h2>
      <ul class="list" id="jobs"></ul>
    </article>
    <article class="card">
      <h2 data-t="audit.title"></h2>
      <ul class="list" id="audit"></ul>
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
 "chip.brain": "brain", "chip.nobrain": "no brain yet", "chip.tg": "Telegram", "chip.notg": "Telegram off",
 "name.personality": "Personality (optional): how should your agent talk and behave?",
 "lock.title": "The panel is locked", "lock.hint": "Enter the panel password. Your API keys are encrypted with it.",
 "lock.password": "Password", "lock.open": "Unlock", "lock.forgot": "I forgot the password",
 "lock.forgot_confirm": "Without the password the encrypted keys cannot be recovered. Delete them now and connect the brains and Telegram again?",
 "step.access": "Access", "access.open": "Open: no password", "access.locked": "Locked: password + encrypted keys",
 "access.hint": "Open: the panel opens without a password and the keys are stored as plain text in your user folder.\nLocked: the panel asks for a password, and the API keys and the Telegram token are encrypted with a key made from it (scrypt + AES-256). The password is never stored: if you forget it, you enter the keys again.",
 "access.pw1": "Password (at least 8 characters)", "access.pw2": "Repeat the password",
 "access.mismatch": "The two passwords are different.",
 "access.to_open": "Your keys will be saved as plain text on this computer. Continue?",
 "access.now_open": "now: open", "access.now_locked": "now: locked ✓", "access.lock_now": "🔒 Lock",
 "step.more": "More", "auto.label": "Start PocketAgent when Windows starts",
 "auto.hint": "Adds a shortcut to your Startup folder. The agent window stays visible on the taskbar.",
 "auto.unsupported": "Only available on Windows.",
 "memory.line": "Memory (stays the same whichever brain answers): {notes} notes, {decisions} decisions.",
 "pick.search": "Search models…", "pick.free": "only free", "pick.tools": "only with tool calling",
 "pick.any": "any context", "pick.more": "{n} more: narrow the search.", "pick.none": "No model matches.",
 "pick.manual": "…or type a model name:", "pick.col_model": "Model", "pick.col_ctx": "Context",
 "pick.col_tools": "Tools", "pick.col_in": "Input", "pick.add": "Add",
 "brain.auto": "auto", "brain.busy_added": "The model is busy right now, but it was added: it answers when it can.",
 "free.title": "Add OpenRouter's free models automatically",
 "free.hint": "Adds the free models that can use tools, biggest context first, behind your own brains as fallbacks; openrouter/free goes last. Free models come and go, so keep the list current. A model you move by hand stays; one you remove is not added again.",
 "free.count": "How many", "free.min": "Minimum context", "free.now": "Add / update now",
 "free.auto": "Keep it current (every 12 hours)", "free.last": "Last update:", "free.done": "{added} added, {removed} removed.",
 "step.specialists": "Specialists: images, speech, writing",
 "sp.intro": "Your agent writes the prompt; a specialist model makes the result. Files are saved in the workspace's media folder and appear in the chat and on Telegram. What you send to these services leaves your computer.",
 "sp.image": "🖼 Images", "sp.speech": "🔊 Speech", "sp.writer": "✍️ Writing / code", "sp.off": "Off",
 "sp.model": "Model", "sp.default": "(default model)", "sp.voice": "Voice, e.g. nova", "sp.try": "Try",
 "sp.paid": "paid: asks every time", "sp.key": "Pollinations key (optional, free)", "sp.getkey": "Get a free key ↗",
 "sp.nokey": "Without a key, images come from Pollinations' classic model (slower) and speech is not available. A free key unlocks both and more models.",
 "sp.writer_hint": "The writer is one of your brains, e.g. a coding model for long code or documents.",
 "svc.pollinations": "Pollinations (free)", "svc.pollinations_key": "Pollinations (free key needed)",
 "svc.openrouter": "OpenRouter image models",
 "svc.custom": "Your own server (OpenAI-compatible)", "svc.local": "This computer's voices (offline)",
 "stop": "STOP", "stop.done": "Stopped everything. Computer use is off.", "tab.safety": "Safety",
 "cu.title": "Computer use", "cu.off": "OFF: safe mode, chat only. Nothing runs on this computer.",
 "cu.on": "ON: the agent may run commands and open web pages, and you approve every action.",
 "cu.turn_on": "Turn on", "cu.turn_off": "Turn off",
 "cu.always": "Always asked, never saved as a rule: spending money, deleting files, sending messages, passwords and keys, and anything that comes after the agent read a web page, a file or command output. There is no limit on approved actions. STOP (or /dur in Telegram) ends everything at once and turns computer use off.",
 "ap.title": "Approval needed", "ap.from": "asked from", "ap.once": "✅ Allow once", "ap.rule": "📌 Allow + remember",
 "ap.deny": "❌ Deny", "ap.always": "⚠️ Always asks:", "ap.after": "⚠️ Comes after reading untrusted content:",
 "rules.title": "Saved approval rules", "rules.none": "No saved rules.", "rules.delete": "Delete",
 "rules.hint": "A rule allows one exact action again: the same command in the same folder, or the same site. Anything else is asked again.",
 "jobs.title": "Background jobs", "jobs.none": "No jobs yet.", "audit.title": "Audit log (newest first)",
 "audit.none": "Nothing yet.", "chat.stopped": "🛑 Stopped.",
 "class.money": "spending money", "class.delete": "deleting files", "class.message": "sending a message",
 "class.secrets": "passwords or keys", "class.untrusted": "after web/file content"
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
 "chip.brain": "beyin", "chip.nobrain": "beyin yok", "chip.tg": "Telegram", "chip.notg": "Telegram kapalı",
 "name.personality": "Kişilik (isteğe bağlı): ajanın nasıl konuşsun, nasıl davransın?",
 "lock.title": "Panel kilitli", "lock.hint": "Panel şifreni gir. API anahtarların bu şifreyle şifrelendi.",
 "lock.password": "Şifre", "lock.open": "Kilidi aç", "lock.forgot": "Şifremi unuttum",
 "lock.forgot_confirm": "Şifre olmadan şifreli anahtarlar geri getirilemez. Şimdi silinsin ve beyinler ile Telegram yeniden mi bağlansın?",
 "step.access": "Erişim", "access.open": "Açık: şifre yok", "access.locked": "Şifreli: şifre + şifrelenmiş anahtarlar",
 "access.hint": "Açık: panel şifresiz açılır, anahtarlar kullanıcı klasöründe düz metin olarak durur.\nŞifreli: panel şifre ister; API anahtarları ve Telegram token'ı bu şifreden türetilen bir anahtarla şifrelenir (scrypt + AES-256). Şifre hiçbir yere kaydedilmez: unutursan anahtarları yeniden girersin.",
 "access.pw1": "Şifre (en az 8 karakter)", "access.pw2": "Şifreyi tekrarla",
 "access.mismatch": "İki şifre aynı değil.",
 "access.to_open": "Anahtarların bu bilgisayarda düz metin olarak kaydedilecek. Devam edilsin mi?",
 "access.now_open": "şu an: açık", "access.now_locked": "şu an: şifreli ✓", "access.lock_now": "🔒 Kilitle",
 "step.more": "Diğer", "auto.label": "Windows açılışında PocketAgent'ı başlat",
 "auto.hint": "Başlangıç klasörüne bir kısayol ekler. Ajan penceresi görev çubuğunda görünür kalır.",
 "auto.unsupported": "Sadece Windows'ta kullanılabilir.",
 "memory.line": "Hafıza (hangi beyin cevap verirse versin aynı kalır): {notes} not, {decisions} karar.",
 "pick.search": "Model ara…", "pick.free": "sadece ücretsiz", "pick.tools": "sadece araç kullanabilenler",
 "pick.any": "her bağlam", "pick.more": "{n} model daha: aramayı daralt.", "pick.none": "Eşleşen model yok.",
 "pick.manual": "…ya da model adını yaz:", "pick.col_model": "Model", "pick.col_ctx": "Bağlam",
 "pick.col_tools": "Araç", "pick.col_in": "Girdi", "pick.add": "Ekle",
 "brain.auto": "otomatik", "brain.busy_added": "Model şu an meşgul ama eklendi: boşaldığında cevap verir.",
 "free.title": "OpenRouter'ın ücretsiz modellerini otomatik ekle",
 "free.hint": "Araç kullanabilen ücretsiz modelleri, en büyük bağlam önce, kendi beyinlerinin arkasına yedek olarak ekler; openrouter/free en sona gelir. Ücretsiz modeller gelip gider, listeyi güncel tut. Elle taşıdığın model kalır; çıkardığın model yeniden eklenmez.",
 "free.count": "Kaç model", "free.min": "En az bağlam", "free.now": "Şimdi ekle / güncelle",
 "free.auto": "Güncel tut (12 saatte bir)", "free.last": "Son güncelleme:", "free.done": "{added} eklendi, {removed} çıkarıldı.",
 "step.specialists": "Uzmanlar: görsel, ses, yazı",
 "sp.intro": "Ajanın istemi yazar, uzman model sonucu üretir. Dosyalar çalışma klasöründeki media klasörüne kaydedilir; sohbette ve Telegram'da görünür. Bu servislere gönderdiklerin bilgisayarından çıkar.",
 "sp.image": "🖼 Görsel", "sp.speech": "🔊 Ses", "sp.writer": "✍️ Yazı / kod", "sp.off": "Kapalı",
 "sp.model": "Model", "sp.default": "(varsayılan model)", "sp.voice": "Ses, ör. nova", "sp.try": "Dene",
 "sp.paid": "ücretli: her seferinde sorar", "sp.key": "Pollinations anahtarı (isteğe bağlı, ücretsiz)",
 "sp.getkey": "Ücretsiz anahtar al ↗",
 "sp.nokey": "Anahtarsız görseller Pollinations'ın klasik modelinden gelir (daha yavaş), ses ise kullanılamaz. Ücretsiz anahtar ikisini ve daha fazla modeli açar.",
 "sp.writer_hint": "Yazar, beyinlerinden biridir; ör. uzun kod ya da belgeler için bir kod modeli.",
 "svc.pollinations": "Pollinations (ücretsiz)", "svc.pollinations_key": "Pollinations (ücretsiz anahtar gerekir)",
 "svc.openrouter": "OpenRouter görsel modelleri",
 "svc.custom": "Kendi sunucun (OpenAI uyumlu)", "svc.local": "Bu bilgisayarın sesleri (çevrimdışı)",
 "stop": "DURDUR", "stop.done": "Her şey durduruldu. Bilgisayar kullanımı kapalı.", "tab.safety": "Güvenlik",
 "cu.title": "Bilgisayar kullanımı", "cu.off": "KAPALI: güvenli mod, sadece sohbet. Bu bilgisayarda hiçbir şey çalışmaz.",
 "cu.on": "AÇIK: ajan komut çalıştırabilir ve web sayfası açabilir; her eylemi sen onaylarsın.",
 "cu.turn_on": "Aç", "cu.turn_off": "Kapat",
 "cu.always": "Her zaman sorulur, asla kural olarak kaydedilmez: para harcama, dosya silme, mesaj gönderme, şifre ve anahtar işlemleri ve ajanın bir web sayfası, dosya ya da komut çıktısı okuduktan sonra yapmak istediği her şey. Onaylanan eylemlerde üst sınır yoktur. DURDUR (ya da Telegram'da /dur) her şeyi anında keser ve bilgisayar kullanımını kapatır.",
 "ap.title": "Onay gerekiyor", "ap.from": "isteyen", "ap.once": "✅ Bir kez izin ver", "ap.rule": "📌 İzin ver + hatırla",
 "ap.deny": "❌ Reddet", "ap.always": "⚠️ Her zaman sorulur:", "ap.after": "⚠️ Güvenilmeyen içerik okunduktan sonra geldi:",
 "rules.title": "Kayıtlı onay kuralları", "rules.none": "Kayıtlı kural yok.", "rules.delete": "Sil",
 "rules.hint": "Bir kural tek bir eylemin aynısına yeniden izin verir: aynı klasörde aynı komut ya da aynı site. Farklı olan her şey yeniden sorulur.",
 "jobs.title": "Arka plan işleri", "jobs.none": "Henüz iş yok.", "audit.title": "Denetim günlüğü (en yeni üstte)",
 "audit.none": "Henüz bir şey yok.", "chat.stopped": "🛑 Durduruldu.",
 "class.money": "para harcama", "class.delete": "dosya silme", "class.message": "mesaj gönderme",
 "class.secrets": "şifre/anahtar", "class.untrusted": "web/dosya içeriğinden sonra"
}};
let lang = document.documentElement.lang || "en";        // English unless the user picks Türkçe
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
  if (reply.status === 401 && data.locked && path !== "state") setTimeout(refresh, 0);   // locked meanwhile
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
  if (S.locked) { fill($("chips")); delete shown.chips; return; }
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

const pick = {q: "", free: true, tools: false, ctx: 0};       // the model table's filters
const CONTEXTS = [0, 128000, 256000, 1000000];

function fmtCtx(n) {
  if (!n) return "?";
  return n >= 1e6 ? +(n / 1e6).toFixed(1) + "M" : Math.round(n / 1000) + "K";
}

function checkbox(label, value, onchange) {
  const box = h("input", {type: "checkbox", checked: value, onchange: () => onchange(box.checked)});
  return h("label", {class: "inline"}, box, label);
}

function contextSelect(value, onchange) {
  const select = h("select", {"aria-label": t("pick.col_ctx"), onchange: () => onchange(+select.value)},
    CONTEXTS.map(v => h("option", {value: v, selected: v === value}, v ? fmtCtx(v) + "+" : t("pick.any"))));
  return select;
}

function renderModelChooser(p) {
  const box = $("model-box");
  if (!box) return;
  if (p.id === "custom" ? !S.custom_url : p.needs_key && !p.has_key)
    return fill(box, h("p", {class: "hint", text: t("brain.nokey")}));
  const list = models[p.id] || [];
  if (p.local && !list.length)
    return fill(box, h("div", {class: "note warn", text: local && local[p.id] ? t("brain.local_empty") : t("brain.local_none")}));
  const problem = h("div", {class: "note bad", hidden: true});         // stays until the next try
  const add = (button, id, free) => act(button, async () => {
    problem.hidden = true;
    toast(t("brain.testing"));
    try {
      const added = await api("brains/add", {provider: p.id, model: id, free});
      toast(added.warning ? t("brain.busy_added") : t("brain.added"));
      await refresh();
    } catch (error) {
      problem.hidden = false;
      problem.textContent = id + ": " + error.message;
      throw error;
    }
  });
  const table = h("div", {class: "picker"});
  const draw = () => {
    const q = pick.q.toLowerCase();
    const rows = list.filter(m => (!q || m.id.toLowerCase().includes(q)) && (!pick.free || p.id !== "openrouter" || m.free)
      && (!pick.tools || m.tools) && (!pick.ctx || (m.context || 0) >= pick.ctx));
    const shown = rows.slice(0, 80);
    const head = ["pick.col_model", "pick.col_ctx", "pick.col_tools", "pick.col_in", ""].map(k => h("th", {text: k ? t(k) : ""}));
    fill(table, rows.length ? h("table", {}, h("thead", {}, h("tr", {}, head)), h("tbody", {}, shown.map(m => {
      const button = h("button", {class: "btn small", type: "button", text: t("pick.add"), onclick: () => add(button, m.id, m.free)});
      return h("tr", {},
        h("td", {class: "mid"}, m.id, p.id === "openrouter" ? h("span", {class: "tag" + (m.free ? " free" : ""), text: m.free ? t("brain.free") : "$"}) : null),
        h("td", {text: fmtCtx(m.context)}),
        h("td", {text: m.tools === true ? "✓" : m.tools === false ? "–" : "?"}),
        h("td", {text: (m.input || []).join(", ")}),
        h("td", {}, button));
    }))) : h("p", {class: "hint", text: t("pick.none")}),
    rows.length > shown.length ? h("p", {class: "hint", text: t("pick.more").replace("{n}", rows.length - shown.length)}) : null);
  };
  const search = h("input", {class: "grow", type: "search", placeholder: t("pick.search"), value: pick.q,
                             "aria-label": t("pick.search"), oninput: () => { pick.q = search.value; draw(); }});
  const manual = h("input", {class: "grow", placeholder: p.suggested_model || t("brain.model_ph"), autocomplete: "off",
                             "aria-label": t("brain.model")});
  const addManual = h("button", {class: "btn", type: "button", text: t("brain.add"), onclick: () => add(addManual, manual.value.trim(), true)});
  fill(box,
    list.length ? h("div", {class: "row"}, search, contextSelect(pick.ctx, v => { pick.ctx = v; draw(); }),
      p.id === "openrouter" ? checkbox(t("pick.free"), pick.free, v => { pick.free = v; draw(); }) : null,
      checkbox(t("pick.tools"), pick.tools, v => { pick.tools = v; draw(); })) : null,
    list.length ? table : null,
    h("p", {class: "hint", text: t("pick.manual")}), h("div", {class: "row"}, manual, addManual), problem,
    p.id === "openrouter" ? freeSyncBox() : null);
  if (list.length) draw();
}

function freeSyncBox() {
  const settings = S.free_sync;
  const count = h("input", {class: "narrow", type: "number", min: 0, max: 20, value: settings.count, "aria-label": t("free.count")});
  let minimum = settings.min_context;
  const now = h("button", {class: "btn primary", type: "button", text: t("free.now"), onclick: () => act(now, async () => {
    const result = await api("free/sync", {count: +count.value, min_context: minimum});
    toast(t("free.done").replace("{added}", result.added.length).replace("{removed}", result.removed.length));
    await refresh();
  })});
  const keep = checkbox(t("free.auto"), settings.enabled, enabled => act(null, async () => {
    await api("free/settings", {enabled, count: +count.value, min_context: minimum});
    await refresh();
  }));
  return h("div", {class: "subcard"},
    h("h3", {text: "🔄 " + t("free.title")}), h("p", {class: "hint", text: t("free.hint")}),
    h("div", {class: "row"}, h("label", {class: "inline"}, t("free.count"), count),
      h("label", {class: "inline"}, t("free.min"), contextSelect(minimum, v => { minimum = v; })), now),
    h("div", {class: "row"}, keep),
    settings.last ? h("p", {class: "hint", text: t("free.last") + " " + settings.last.replace("T", " ")}) : null);
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
      b.auto ? h("span", {class: "tag", text: "🔄 " + t("brain.auto")}) : null,
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
  if (!changed("name", S.identity)) return;
  if (document.activeElement !== $("name")) $("name").value = S.identity.name;
  if (document.activeElement !== $("personality")) $("personality").value = S.identity.personality || "";
}

// ---------- step 5: specialists ----------
const specialistModels = {};      // "image|pollinations" -> the service's model list

function specialistRow(kind, saved) {
  const current = saved[kind] || {};
  const service = h("select", {"aria-label": t("sp." + kind)}, h("option", {value: ""}, t("sp.off")));
  if (kind === "writer") {
    S.brains.forEach(b => service.append(h("option", {value: b.provider + "|" + b.model,
      selected: current.provider === b.provider && current.model === b.model}, b.label)));
  } else {
    saved.services[kind].forEach(x => service.append(h("option", {value: x.id, selected: current.provider === x.id},
      t(kind === "speech" && x.id === "pollinations" ? "svc.pollinations_key" : "svc." + x.id)
        + (x.paid ? " · " + t("sp.paid") : ""))));
  }
  const model = h("select", {"aria-label": t("sp.model")});
  const typed = h("input", {class: "grow", placeholder: t("sp.model"), value: current.model || "", "aria-label": t("sp.model")});
  const voice = h("input", {placeholder: t("sp.voice"), value: current.voice || "", "aria-label": t("sp.voice")});
  const result = h("div", {class: "try-result"});
  const listed = id => id && kind !== "writer" && id !== "custom" && id !== "local";
  const layout = () => {
    model.hidden = !listed(service.value);
    typed.hidden = service.value !== "custom";
    voice.hidden = kind !== "speech" || !service.value;
  };
  const loadModels = async () => {
    fill(model, h("option", {value: ""}, t("sp.default")));
    if (!listed(service.value)) return;
    const cacheKey = kind + "|" + service.value;
    if (!specialistModels[cacheKey])
      specialistModels[cacheKey] = (await api("specialist/models?kind=" + kind + "&provider=" + service.value)
        .catch(() => ({models: []}))).models;
    specialistModels[cacheKey].forEach(m => model.append(h("option", {value: m.id, selected: m.id === current.model}, m.label)));
  };
  service.addEventListener("change", () => { layout(); loadModels(); });
  const save = h("button", {class: "btn primary", type: "button", text: t("save"), onclick: () => act(save, async () => {
    let provider = service.value, chosen = provider === "custom" ? typed.value : model.value;
    if (kind === "writer" && provider) {
      const split = provider.indexOf("|");
      [provider, chosen] = [provider.slice(0, split), provider.slice(split + 1)];
    }
    await api("specialist", {kind, provider, model: chosen, voice: voice.value});
    toast(t("saved"));
    await refresh();
  })});
  const tryIt = h("button", {class: "btn", type: "button", text: t("sp.try"), onclick: () => act(tryIt, async () => {
    fill(result, h("p", {class: "hint", text: "…"}));
    const outcome = await api("specialist/try", {kind});
    fill(result, outcome.text ? h("p", {text: outcome.text}) : null);
    for (const path of outcome.files) await attach(result, path);
  })});
  layout();
  loadModels();
  return h("div", {class: "sp-row"}, h("b", {class: "sp-kind", text: t("sp." + kind)}), service, model, typed, voice, save,
    current.provider ? tryIt : null, result,
    kind === "writer" ? h("p", {class: "hint", text: t("sp.writer_hint")}) : null);
}

function renderSpecialists() {
  const saved = S.specialists;
  if (!changed("specialists", [saved, S.brains.map(b => b.label)])) return;
  const key = h("input", {class: "grow", type: "password", placeholder: t("sp.key"), autocomplete: "off", "aria-label": t("sp.key")});
  const saveKey = h("button", {class: "btn", type: "button", text: t("save"), onclick: () => act(saveKey, async () => {
    await api("specialist/key", {service: "pollinations", key: key.value});
    for (const cached in specialistModels) delete specialistModels[cached];
    toast(t("saved"));
    await refresh();
  })});
  fill($("specialists"), ["image", "speech", "writer"].map(kind => specialistRow(kind, saved)),
    h("h3", {text: t("sp.key")}),
    h("div", {class: "row"}, key, saveKey, h("a", {class: "linkbtn", href: "https://enter.pollinations.ai/keys",
      target: "_blank", rel: "noopener noreferrer", text: t("sp.getkey")})),
    h("p", {class: saved.pollinations_key ? "ok" : "hint",
            text: saved.pollinations_key ? t("brain.saved") + " " + saved.pollinations_key : t("sp.nokey")}));
}

async function attach(container, path) {
  const extension = path.split(".").pop().toLowerCase();
  const kind = ["png", "jpg", "jpeg", "webp", "gif"].includes(extension) ? "image"
    : ["mp3", "wav", "ogg", "aac", "flac", "aiff"].includes(extension) ? "audio" : "file";
  const name = path.split("/").pop();
  try {
    const reply = await fetch("/api/file?path=" + encodeURIComponent(path), {headers: {"X-Pocket-Token": TOKEN}});
    if (!reply.ok) throw new Error("HTTP " + reply.status);
    const url = URL.createObjectURL(await reply.blob());
    container.append(kind === "image" ? h("a", {href: url, download: name}, h("img", {class: "shot", src: url, alt: name}))
      : kind === "audio" ? h("audio", {controls: true, src: url})
      : h("a", {class: "linkbtn", href: url, download: name, text: "📎 " + name}));
  } catch (error) {
    container.append(h("p", {class: "hint", text: "📎 " + path + " (" + error.message + ")"}));
  }
}

// ---------- step 4: access; more ----------
function renderAccess() {
  $("lock-now").hidden = S.access !== "locked";
  $("access-now").textContent = t(S.access === "locked" ? "access.now_locked" : "access.now_open");
  if (changed("access", S.access)) {
    document.querySelectorAll('input[name="access"]').forEach(r => r.checked = r.value === S.access);
    $("access-password").hidden = S.access !== "locked";
  }
}

function renderMore() {
  const auto = S.autostart;
  $("autostart").checked = auto.enabled;
  $("autostart").disabled = !auto.supported;
  $("autostart-hint").textContent = t(auto.supported ? "auto.hint" : "auto.unsupported");
  $("memory").textContent = t("memory.line").replace("{notes}", S.memory.notes).replace("{decisions}", S.memory.decisions);
}

// ---------- approvals, safety ----------
function renderApprovals() {
  if (!changed("approvals", S.approvals || [])) return;
  fill($("approvals"), (S.approvals || []).map(p => {
    const answer = (approve, remember) => act(null, async () => {
      await api("approvals/answer", {id: p.id, approve, remember});
      await refresh();
    });
    const always = p.classes.filter(c => c !== "untrusted").map(c => t("class." + c));
    return h("article", {class: "card approval"},
      h("h2", {}, "🔐 " + t("ap.title"), h("span", {class: "tag", text: t("ap.from") + ": " + (p.source || "?")})),
      h("p", {text: p.summary}),
      h("div", {class: "params", text: Object.entries(p.params).map(([k, v]) => k + ": " + v).join("\n")}),
      always.length ? h("p", {class: "note warn", text: t("ap.always") + " " + always.join(", ")}) : null,
      p.tainted.length ? h("p", {class: "note warn", text: t("ap.after") + " " + p.tainted.join(", ")}) : null,
      h("div", {class: "row"},
        h("button", {class: "btn primary", type: "button", text: t("ap.once"), onclick: () => answer(true, false)}),
        p.can_remember ? h("button", {class: "btn", type: "button", text: t("ap.rule"), onclick: () => answer(true, true)}) : null,
        h("button", {class: "btn", type: "button", text: t("ap.deny"), onclick: () => answer(false, false)})));
  }));
}

function describe(entry) {
  const json = value => JSON.stringify(value || {});
  if (entry.event === "tool") return "🔧 " + entry.tool + " " + json(entry.args) + (entry.tainted ? " ⚠️" : "");
  if (entry.event === "approval") return "🔐 " + entry.decision + " · " + entry.kind + " " + json(entry.params) + (entry.by ? " · " + entry.by : "");
  if (entry.event === "stop") return "🛑 stop · " + entry.by;
  if (entry.event === "computer_use") return "💻 computer use " + (entry.enabled ? "ON" : "OFF") + " · " + entry.by;
  return entry.event + " " + json(Object.fromEntries(Object.entries(entry).filter(([k]) => k !== "time" && k !== "event")));
}

function renderSafety() {
  const on = S.computer_use;
  $("cu-state").className = on ? "state-on" : "state-off";
  $("cu-state").textContent = t(on ? "cu.on" : "cu.off");
  $("cu-toggle").textContent = t(on ? "cu.turn_off" : "cu.turn_on");
  if (changed("rules", S.rules)) {
    fill($("rules"), S.rules.length ? S.rules.map(r => h("li", {},
      h("span", {class: "what", text: "#" + r.id + " " + r.kind + ": " + Object.entries(r.scope).map(([k, v]) => k + "=" + v).join(", ")}),
      h("span", {class: "when", text: r.created.replace("T", " ")}),
      h("button", {class: "btn small", type: "button", text: t("rules.delete"), onclick: () => act(null, async () => {
        await api("rules/delete", {id: r.id});
        await refresh();
      })}))) : h("li", {class: "hint", text: t("rules.none")}));
  }
  if (changed("jobs", S.jobs)) {
    fill($("jobs"), S.jobs.length ? S.jobs.map(j => h("li", {},
      h("span", {class: "what", text: j.label}), h("span", {class: "tag", text: j.status}),
      h("span", {class: "when", text: j.created.replace("T", " ")}))) : h("li", {class: "hint", text: t("jobs.none")}));
  }
  if (changed("audit", S.audit)) {
    const entries = [...S.audit].reverse();
    fill($("audit"), entries.length ? entries.map(e => h("li", {},
      h("span", {class: "when", text: e.time.replace("T", " ")}), h("span", {class: "what", text: describe(e)})))
      : h("li", {class: "hint", text: t("audit.none")}));
  }
}

// ---------- locked panel ----------
function showLock(locked) {
  $("lock").hidden = !locked;
  $("tabs").hidden = locked;
  document.querySelector("main").hidden = locked;
  if (locked) $("unlock-password").focus();
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
      for (const path of job.result.files || []) await attach(waiting, path);
      const meta = metaOf(job.result);
      if (meta) waiting.append(h("div", {class: "meta", text: meta}));
    } else if (job.status === "cancelled") {
      waiting.classList.add("notice");
      waiting.textContent = t("chat.stopped");
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
  renderHeader();
  showLock(!!S.locked);
  if (S.locked) return fill($("approvals"));
  renderApprovals();
  renderProviders(); renderBrains(); renderTelegram(); renderName(); renderSpecialists(); renderAccess();
  renderMore(); renderSafety();
  renderNotices();
}

async function refresh() {
  try {
    const wasLocked = !S || S.locked;
    S = await api("state");
    render();
    if (wasLocked && !S.locked && !tab) showTab(S.setup.brain ? "chat" : "setup");
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
  await api("identity", {name: $("name").value, personality: $("personality").value});
  toast(t("saved"));
  await refresh();
}));
document.querySelectorAll('input[name="access"]').forEach(r => r.addEventListener("change", () => {
  $("access-password").hidden = r.value !== "locked" || !r.checked;
}));
$("save-access").addEventListener("click", () => act($("save-access"), async () => {
  const mode = document.querySelector('input[name="access"]:checked').value;
  if (mode === "locked") {
    if ($("pw1").value !== $("pw2").value) throw new Error(t("access.mismatch"));
    await api("access", {mode, password: $("pw1").value});
  } else {
    if (S.access === "locked" && !confirm(t("access.to_open"))) return;
    await api("access", {mode});
  }
  $("pw1").value = $("pw2").value = "";
  toast(t("saved"));
  await refresh();
}));
$("autostart").addEventListener("change", () => act($("autostart"), async () => {
  S.autostart = await api("autostart", {enabled: $("autostart").checked});
  renderMore();
}));
$("stop").addEventListener("click", () => act($("stop"), async () => {
  await api("stop", {});
  toast(t("stop.done"));
  await refresh();
}));
$("cu-toggle").addEventListener("click", () => act($("cu-toggle"), async () => {
  await api("computer_use", {enabled: !S.computer_use});
  await refresh();
}));
$("lock-now").addEventListener("click", () => act($("lock-now"), async () => {
  await api("lock", {});
  await refresh();
}));
$("unlock-form").addEventListener("submit", event => {
  event.preventDefault();
  act(null, async () => {
    await api("unlock", {password: $("unlock-password").value});
    $("unlock-password").value = "";
    historyLoaded = false;
    await refresh();
  });
});
$("forgot").addEventListener("click", () => act($("forgot"), async () => {
  if (!confirm(t("lock.forgot_confirm"))) return;
  await api("vault/forget", {});
  await refresh();
  showTab("setup");
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
  setInterval(refresh, 2000);
})();
</script>
</body>
</html>
"""


def render_page(token: str, nonce: str, language: str) -> str:
    return (PAGE.replace("__TOKEN__", token).replace("__NONCE__", nonce)
            .replace("__LANG__", "tr" if language == "tr" else "en"))
