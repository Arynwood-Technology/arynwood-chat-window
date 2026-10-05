/*! Arynwood Chat Window — https://github.com/Arynwood-Technology/arynwood-chat-window (AGPL-3.0) */
(function () {
  'use strict';
  var script = document.currentScript;
  if (!script || window.__arynwoodChatWindow) return;
  window.__arynwoodChatWindow = true;

  var SITE = script.getAttribute('data-site') || '';
  var ENDPOINT = (script.getAttribute('data-endpoint') || new URL(script.src, location.href).origin).replace(/\/+$/, '');
  var ACCENT = script.getAttribute('data-accent') || '#2f6f5e';
  var SIDE = script.getAttribute('data-position') === 'left' ? 'left' : 'right';
  var LABEL = script.getAttribute('data-label') || 'Chat';
  var STORE_KEY = 'arynwood-chat-window:' + SITE;

  var CSS = [
    ':host{all:initial}',
    '*{box-sizing:border-box;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}',
    '.cw{--accent:' + ACCENT + ';--bg:#ffffff;--fg:#1d1f21;--muted:#5d6166;--line:#d9dcdf;--bubble:#f1f3f4;',
    'position:fixed;bottom:20px;' + SIDE + ':20px;z-index:2147483000;color:var(--fg);font-size:15px;line-height:1.45}',
    '@media (prefers-color-scheme:dark){.cw{--bg:#1c1e21;--fg:#e8eaed;--muted:#a6abb1;--line:#3a3d42;--bubble:#2a2d31;',
    '--link:color-mix(in srgb,var(--accent) 40%,#fff)}}',
    '.launch{display:flex;align-items:center;gap:8px;border:0;border-radius:999px;padding:12px 18px;cursor:pointer;',
    'background:var(--accent);color:#fff;font-size:15px;font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,.25)}',
    '.launch svg{width:20px;height:20px}',
    '.panel{display:none;flex-direction:column;width:min(380px,calc(100vw - 32px));height:min(600px,calc(100vh - 100px));',
    'background:var(--bg);border:1px solid var(--line);border-radius:14px;overflow:hidden;box-shadow:0 10px 40px rgba(0,0,0,.3)}',
    '.cw.open .panel{display:flex}.cw.open .launch{display:none}',
    '@media (max-width:480px){.cw.open{inset:0}.cw.open .panel{width:100vw;height:100%;border-radius:0;border:0}}',
    '.head{display:flex;align-items:center;gap:6px;padding:10px 10px 10px 16px;background:var(--accent);color:#fff}',
    '.head h2{flex:1;margin:0;font-size:16px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.icon{border:0;background:transparent;color:inherit;cursor:pointer;padding:6px;border-radius:8px;display:flex}',
    '.icon:hover{background:rgba(255,255,255,.18)}.icon svg{width:18px;height:18px}',
    '.notice{margin:0;padding:8px 16px;font-size:12px;color:var(--muted);border-bottom:1px solid var(--line)}',
    '.notice a{color:inherit}',
    '.log{flex:1;overflow-y:auto;padding:14px 16px;display:flex;flex-direction:column;gap:10px}',
    '.msg{max-width:88%;padding:9px 12px;border-radius:12px;white-space:normal;overflow-wrap:anywhere}',
    '.msg p{margin:0 0 6px}.msg p:last-child{margin:0}.msg ul{margin:4px 0;padding-left:20px}',
    '.bot{align-self:flex-start;background:var(--bubble)}',
    '.me{align-self:flex-end;background:var(--accent);color:#fff}',
    '.msg a{color:var(--link,var(--accent));font-weight:600}.me a{color:#fff}',
    '.err{align-self:center;font-size:13px;color:#b3261e;text-align:center}',
    '.sources{margin-top:6px;font-size:12px;color:var(--muted)}.sources a{display:block;color:var(--link,var(--accent))}',
    '.chips{display:flex;flex-wrap:wrap;gap:6px}',
    '.chip{border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:999px;padding:6px 10px;',
    'font-size:13px;cursor:pointer;text-align:left}',
    '.chip:hover{border-color:var(--accent)}',
    'form{display:flex;gap:8px;padding:10px;border-top:1px solid var(--line)}',
    'textarea{flex:1;resize:none;border:1px solid var(--line);border-radius:10px;padding:9px 10px;font-size:15px;',
    'background:var(--bg);color:var(--fg);max-height:120px;min-height:40px}',
    '.send{border:0;border-radius:10px;padding:0 14px;background:var(--accent);color:#fff;font-weight:600;cursor:pointer}',
    '.send:disabled{opacity:.5;cursor:default}',
    ':focus-visible{outline:2px solid var(--accent);outline-offset:2px}.head :focus-visible{outline-color:#fff}',
    '.typing::after{content:"…";animation:blink 1s steps(2) infinite}@keyframes blink{50%{opacity:0}}',
    '@media (prefers-reduced-motion:reduce){.typing::after{animation:none}}',
    '.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}'
  ].join('');

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k.slice(0, 2) === 'on') node.addEventListener(k.slice(2), attrs[k]);
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) node.appendChild(c); });
    return node;
  }

  function icon(paths) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('aria-hidden', 'true');
    paths.forEach(function (d) {
      var p = document.createElementNS(ns, 'path');
      p.setAttribute('d', d);
      svg.appendChild(p);
    });
    return svg;
  }

  var storage = {
    get: function () { try { return sessionStorage.getItem(STORE_KEY) || ''; } catch (e) { return ''; } },
    set: function (v) { try { if (v) sessionStorage.setItem(STORE_KEY, v); else sessionStorage.removeItem(STORE_KEY); } catch (e) { /* private mode */ } }
  };

  // Links are clickable only when they point at the site's own domains; anything else stays plain text.
  var linkDomains = [];
  function allowedUrl(href) {
    try {
      var u = new URL(href);
      if (u.protocol !== 'https:' && u.protocol !== 'http:') return false;
      return linkDomains.some(function (d) { return u.hostname === d || u.hostname.slice(-d.length - 1) === '.' + d; });
    } catch (e) { return false; }
  }

  function inline(text, parent) {
    var re = /\[([^\]\n]{1,200})\]\(([^)\s]{1,500})\)|\*\*([^*\n]{1,200})\*\*|(https?:\/\/[^\s<>()\[\]"']+)/g;
    var last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (m[1] !== undefined) {
        if (allowedUrl(m[2])) parent.appendChild(el('a', { href: m[2], target: '_blank', rel: 'noopener noreferrer nofollow', text: m[1] }));
        else parent.appendChild(document.createTextNode(m[1]));
      } else if (m[3] !== undefined) {
        parent.appendChild(el('strong', { text: m[3] }));
      } else {
        var url = m[4].replace(/[.,;:!?]+$/, '');
        var trail = m[4].slice(url.length);
        if (allowedUrl(url)) parent.appendChild(el('a', { href: url, target: '_blank', rel: 'noopener noreferrer nofollow', text: url }));
        else parent.appendChild(document.createTextNode(url));
        if (trail) parent.appendChild(document.createTextNode(trail));
      }
      last = re.lastIndex;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }

  function render(text, node) {
    node.textContent = '';
    var list = null;
    text.split(/\n/).forEach(function (line) {
      var item = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
      if (item) {
        if (!list) { list = el('ul'); node.appendChild(list); }
        var li = el('li'); inline(item[1], li); list.appendChild(li);
      } else if (line.trim()) {
        list = null;
        var p = el('p'); inline(line.replace(/^#{1,6}\s+/, ''), p); node.appendChild(p);
      } else {
        list = null;
      }
    });
  }

  var host = el('div', { id: 'arynwood-chat-window' });
  var root = host.attachShadow({ mode: 'open' });
  try {
    var sheet = new CSSStyleSheet();
    sheet.replaceSync(CSS);
    root.adoptedStyleSheets = [sheet];
  } catch (e) {
    root.appendChild(el('style', { text: CSS }));
  }

  var config = null, busy = false, controller = null;
  var title = el('h2', { id: 'cw-title', text: LABEL });
  var notice = el('p', { 'class': 'notice' });
  var log = el('div', { 'class': 'log', role: 'log', 'aria-live': 'polite', 'aria-labelledby': 'cw-title' });
  var input = el('textarea', { rows: '1', 'aria-label': 'Your question', placeholder: 'Ask a question…' });
  var send = el('button', { 'class': 'send', type: 'submit', text: 'Send' });
  var form = el('form', { onsubmit: function (e) { e.preventDefault(); ask(input.value); } }, [input, send]);
  var launch = el('button', { 'class': 'launch', type: 'button', 'aria-expanded': 'false', onclick: open },
    [icon(['M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z']), el('span', { text: LABEL })]);
  var del = el('button', { 'class': 'icon', type: 'button', title: 'Delete this chat', 'aria-label': 'Delete this chat', onclick: forget },
    [icon(['M3 6h18', 'M8 6V4h8v2', 'M19 6l-1 14H6L5 6'])]);
  var close = el('button', { 'class': 'icon', type: 'button', title: 'Close', 'aria-label': 'Close chat', onclick: shut },
    [icon(['M6 6l12 12', 'M18 6L6 18'])]);
  var panel = el('div', { 'class': 'panel', role: 'dialog', 'aria-labelledby': 'cw-title' },
    [el('div', { 'class': 'head' }, [title, del, close]), notice, log, form]);
  var wrap = el('div', { 'class': 'cw' }, [launch, panel]);
  root.appendChild(wrap);

  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); }
  });
  input.addEventListener('input', function () {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });
  panel.addEventListener('keydown', function (e) { if (e.key === 'Escape') shut(); });

  function say(text, who) {
    var node = el('div', { 'class': 'msg ' + who });
    if (who === 'bot') render(text, node); else node.textContent = text;
    log.appendChild(node);
    log.scrollTop = log.scrollHeight;
    return node;
  }

  function fail(text) {
    log.appendChild(el('p', { 'class': 'err', text: text }));
    log.scrollTop = log.scrollHeight;
  }

  function api(path, options) {
    return fetch(ENDPOINT + path, Object.assign({ credentials: 'omit', referrerPolicy: 'no-referrer' }, options || {}));
  }

  function greet() {
    say(config.greeting, 'bot');
    if (config.suggestions && config.suggestions.length) {
      var chips = el('div', { 'class': 'chips' });
      config.suggestions.forEach(function (s) {
        chips.appendChild(el('button', { 'class': 'chip', type: 'button', text: s, onclick: function () { chips.remove(); ask(s); } }));
      });
      log.appendChild(chips);
    }
  }

  function open() {
    wrap.classList.add('open');
    launch.setAttribute('aria-expanded', 'true');
    input.focus();
    if (config) return;
    api('/v1/sites/' + encodeURIComponent(SITE)).then(function (r) { return r.json(); }).then(function (c) {
      if (c.error) { fail(c.error); return; }
      config = c;
      linkDomains = c.link_domains || [];
      title.textContent = c.name;
      input.maxLength = c.max_message_chars || 600;
      notice.textContent = c.notice + ' ';
      if (c.privacy_url && allowedUrl(c.privacy_url)) notice.appendChild(el('a', { href: c.privacy_url, target: '_blank', rel: 'noopener', text: 'Privacy' }));
      if (!c.available) { fail('The assistant is offline right now. Please try again later.'); return; }
      greet();
    }).catch(function () { fail('The assistant is offline right now. Please try again later.'); });
  }

  function shut() {
    wrap.classList.remove('open');
    launch.setAttribute('aria-expanded', 'false');
    launch.focus();
  }

  function forget() {
    var session = storage.get();
    if (controller) controller.abort();
    storage.set('');
    log.textContent = '';
    if (session) api('/v1/sessions/' + encodeURIComponent(session) + '?site=' + encodeURIComponent(SITE), { method: 'DELETE' }).catch(function () {});
    if (config) greet();
  }

  function ask(text) {
    text = (text || '').trim();
    if (!text || busy || !config || !config.available) return;
    busy = true; send.disabled = true;
    input.value = ''; input.style.height = 'auto';
    say(text, 'me');
    var bubble = say('', 'bot');
    bubble.classList.add('typing');
    var reply = '', sources = [], buffer = '';
    controller = window.AbortController ? new AbortController() : null;
    api('/v1/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller && controller.signal,
      body: JSON.stringify({ site: SITE, message: text, session: storage.get() || undefined })
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (j) { throw new Error(j.error || 'Something went wrong.'); });
      var reader = r.body.getReader(), decoder = new TextDecoder();
      function pump() {
        return reader.read().then(function (step) {
          if (step.done) return;
          buffer += decoder.decode(step.value, { stream: true });
          var events = buffer.split('\n\n');
          buffer = events.pop();
          events.forEach(function (raw) {
            var name = (raw.match(/^event: (.*)$/m) || [])[1];
            var data = (raw.match(/^data: (.*)$/m) || [])[1];
            if (!name || data === undefined) return;
            var value = JSON.parse(data);
            if (name === 'session') storage.set(value.session);
            else if (name === 'sources') sources = value;
            else if (name === 'token') { reply += value.t; render(reply, bubble); log.scrollTop = log.scrollHeight; }
            else if (name === 'error') throw new Error(value.message);
          });
          return pump();
        });
      }
      return pump();
    }).then(function () {
      bubble.classList.remove('typing');
      if (!reply) bubble.remove();
      var links = sources.filter(function (s) { return allowedUrl(s.url); });
      if (links.length) {
        var box = el('div', { 'class': 'sources' }, [el('span', { text: 'From this site:' })]);
        links.forEach(function (s) { box.appendChild(el('a', { href: s.url, target: '_blank', rel: 'noopener', text: s.title })); });
        bubble.appendChild(box);
      }
    }).catch(function (err) {
      bubble.classList.remove('typing');
      if (!reply) bubble.remove();
      if (!err || err.name !== 'AbortError') fail(err && err.message ? err.message : 'Something went wrong.');
    }).then(function () {
      busy = false; send.disabled = false; controller = null;
      log.scrollTop = log.scrollHeight;
    });
  }

  if (document.body) document.body.appendChild(host);
  else document.addEventListener('DOMContentLoaded', function () { document.body.appendChild(host); });
})();
