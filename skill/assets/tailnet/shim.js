/* Tailnet /choices: stands in for claude.ai's window.claude (db + user). Picks and notes save to this server's
   own /state/<key> endpoint (a file on Jon's Mac, reachable only on his tailnet), so Claude reads them from disk.
   The picker code is unchanged.

   Saves merge per question: what this page changed since its last save wins, and everything else keeps the
   server's copy (picks made on another device, items Claude moved to Done, sections this build doesn't show).

   Live pages (CHOICES_TAILNET.live) also stream updates: version.json is polled every 20 s and whenever the page
   becomes visible. A new version shows a small banner ("N new items: tap to load"). The page reloads by itself only
   when no text box has focus and nothing was typed or picked for 30 s; otherwise it waits for the tap. Pending
   picks and notes are on the server before any reload. */
(function () {
  var CFG = window.CHOICES_TAILNET || {};
  var URL_ = "/state/" + CFG.key;
  var VOTER = CFG.voter || "jon";
  var KNOWN = CFG.groups || null;  // { sectionKey: [groupKey, ...] } in this build of the page
  var latest = { votes: {}, closed: false }, base = {}, voteSubs = [], stateSubs = [];
  var chain = Promise.resolve(), pending = 0;

  function clone(x) { return x === undefined ? undefined : JSON.parse(JSON.stringify(x)); }
  function same(a, b) { return JSON.stringify(a === undefined ? null : a) === JSON.stringify(b === undefined ? null : b); }
  function unavailable(why) { var e = new Error("save failed (" + why + ")"); e.code = "unavailable"; return e; }
  function mine(state) { var v = ((state && state.votes) || {})[VOTER]; return clone((v && v.sections) || {}); }

  function emit() {
    var snap = { docs: Object.keys(latest.votes).map(function (id) {
      return { id: id, data: function () { return { sections: latest.votes[id].sections }; } };
    }) };
    voteSubs.forEach(function (s) { try { s(snap); } catch (e) {} });
    var st = { exists: true, data: function () { return { closed: !!latest.closed }; } };
    stateSubs.forEach(function (s) { try { s(st); } catch (e) {} });
  }
  function fetchState() {
    return fetch(URL_, { cache: "no-store" }).then(function (r) {
      if (r.status === 404) return { votes: {}, closed: false };
      if (!r.ok) throw unavailable(r.status);
      return r.json();
    });
  }
  function load() {
    return fetchState().then(function (j) {
      if (j && j.votes) { latest = j; base = mine(j); }
      emit();
    }, function () { emit(); });
  }
  function merge(server, page) {
    if (!KNOWN) return clone(page);
    var out = clone(server) || {};
    Object.keys(KNOWN).forEach(function (sk) {
      var b = base[sk] || {}, p = page[sk] || {};
      var o = out[sk] || (out[sk] = {});
      o.picks = o.picks || {};
      o.comments = o.comments || {};
      KNOWN[sk].forEach(function (gk) {
        ["picks", "comments"].forEach(function (f) {
          var bv = (b[f] || {})[gk], pv = (p[f] || {})[gk];
          if (same(bv, pv)) return;
          if (pv === undefined || pv === "") delete o[f][gk]; else o[f][gk] = clone(pv);
        });
      });
      if (!same(b.note || "", p.note || "")) o.note = p.note || "";
      if (typeof o.note !== "string") o.note = "";
    });
    return out;
  }
  function save(pageSections) {
    pending++;
    var run = chain.then(function () {
      return fetchState().then(function (server) {
        if (server.closed) { var e = new Error("closed"); e.code = "closed"; throw e; }
        server.votes = server.votes || {};
        var merged = merge(((server.votes[VOTER] || {}).sections) || {}, pageSections);
        server.votes[VOTER] = { sections: merged, at: new Date().toISOString() };
        return fetch(URL_, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(server) })
          .then(function (r) {
            if (!r.ok) throw unavailable(r.status);
            base = clone(pageSections);
            latest = server;
          });
      });
    });
    chain = run.catch(function () {});
    return run.then(function () { if (--pending === 0) emit(); }, function (e) {
      pending--;
      throw (e && e.code) ? e : unavailable("network");
    });
  }
  var ready = load();

  var db = {
    doc: function (path) {
      return {
        set: function (value) {
          if (path.indexOf("votes/") !== 0) return Promise.reject(Object.assign(new Error("read only"), { code: "forbidden" }));
          if (latest.closed) return Promise.reject(Object.assign(new Error("closed"), { code: "closed" }));
          latest.votes[path.slice(6)] = { sections: clone(value.sections), at: new Date().toISOString() };
          emit();
          return save(value.sections || {});
        },
        onSnapshot: function (cb) { if (path === "meta/state") { stateSubs.push(cb); emit(); } return function () {}; }
      };
    },
    collection: function (name) {
      return { onSnapshot: function (cb) { if (name === "votes") { voteSubs.push(cb); emit(); } return function () {}; } };
    }
  };
  var user = {
    me: function () { return Promise.resolve({ isOwner: true, canEdit: true }); },
    id: function () { return Promise.resolve(VOTER); },
    profiles: function (ids) {
      var out = {};
      (ids || []).forEach(function (id) { out[id] = { name: CFG.name || "Jon" }; });
      return Promise.resolve(out);
    }
  };
  window.claude = {
    use: function (name) {
      if (name === "db") return ready.then(function () { return db; });
      if (name === "user") return ready.then(function () { return user; });
      return Promise.resolve(null);
    }
  };

  if (CFG.live) live();

  function live() {
    var CSS = [
      ".ct-wrap { position: fixed; left: 0; right: 0; bottom: calc(env(safe-area-inset-bottom, 0px) + 16px); z-index: 50;",
      "  display: flex; justify-content: center; padding: 0 16px; pointer-events: none; }",
      ".ct-banner { pointer-events: auto; max-width: 100%; min-height: 44px; padding: 10px 20px; border: 0; border-radius: 999px;",
      "  font: 600 15px/1.3 var(--sans, system-ui, sans-serif); color: var(--card, #fff); background: var(--accent, #2457D6);",
      "  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.18); cursor: pointer; }",
      ".ct-banner:focus-visible { outline: 3px solid var(--ink, #000); outline-offset: 2px; }",
      "#done > header h2 { color: var(--muted, #565B66); }",
      "#done:not(.ct-open) > .group, #done:not(.ct-open) > .note { display: none; }",
      ".ct-toggle { display: inline-flex; align-items: center; margin-top: 8px; min-height: 40px; padding: 6px 14px; cursor: pointer;",
      "  font: 600 14px var(--sans, system-ui, sans-serif); color: var(--ink, #16181D); background: var(--card, #fff);",
      "  border: 1px solid var(--line, #D9DCE2); border-radius: 999px; }",
      "#empty > .note { display: none; }"
    ].join("\n");
    var seen = CFG.version || 0, lastActivity = Date.now(), wrap = null, banner = null, reloading = false;
    var Y_KEY = "choices-y-" + CFG.key;

    var style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);
    ["input", "keydown"].forEach(function (t) {
      document.addEventListener(t, function () { lastActivity = Date.now(); }, true);
    });
    // A pick counts as activity; a text box's own change event (fired when it loses focus) doesn't.
    document.addEventListener("change", function (e) { if (!isText(e.target)) lastActivity = Date.now(); }, true);

    function onReady() {
      var done = document.getElementById("done");
      if (done) {
        var n = done.querySelectorAll(":scope > .group").length;
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ct-toggle";
        btn.setAttribute("aria-expanded", "false");
        var label = function () {
          var open = done.classList.contains("ct-open");
          btn.textContent = (open ? "Hide " : "Show ") + n + " done";
          btn.setAttribute("aria-expanded", String(open));
        };
        btn.addEventListener("click", function () { done.classList.toggle("ct-open"); label(); });
        label();
        var head = done.querySelector(":scope > header");
        (head || done).appendChild(btn);
      }
      var y = null;
      try { y = sessionStorage.getItem(Y_KEY); sessionStorage.removeItem(Y_KEY); } catch (e) {}
      if (y) window.addEventListener("load", function () {
        setTimeout(function () { if (window.scrollY < 10) window.scrollTo(0, Number(y) || 0); }, 50);
      });
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", onReady); else onReady();

    function isText(el) {
      if (!el || !el.tagName) return false;
      if (el.tagName === "TEXTAREA" || el.isContentEditable) return true;
      return el.tagName === "INPUT" && !/^(radio|checkbox|button|submit|reset|range|color|file|image|hidden)$/i.test(el.type || "text");
    }
    function typingFocus() { return isText(document.activeElement); }
    function setText(t) { if (banner) banner.textContent = t; }
    function showBanner(n) {
      if (!wrap) {
        wrap = document.createElement("div");
        wrap.className = "ct-wrap";
        wrap.setAttribute("role", "status");
        banner = document.createElement("button");
        banner.type = "button";
        banner.className = "ct-banner";
        banner.id = "ct-banner";
        banner.addEventListener("click", function () { if (!reloading) go(); });
        wrap.appendChild(banner);
        document.body.appendChild(wrap);
      }
      if (!reloading) setText(n > 0 ? n + " new item" + (n === 1 ? "" : "s") + ": tap to load" : "Page updated: tap to load");
    }
    function settled(t0) {
      // The picker waits 350 ms before saving and shows "Saving…" until the server has the change.
      return new Promise(function (resolve) {
        (function check() {
          var st = document.getElementById("status"), mode = st && st.dataset.mode;
          if (pending === 0 && mode !== "saving" && Date.now() - t0 > 500) return resolve(mode !== "error");
          if (Date.now() - t0 > 10000) return resolve(false);
          setTimeout(check, 150);
        })();
      });
    }
    function go() {
      reloading = true;
      setText("Saving…");
      var a = document.activeElement;
      if (a && a.blur && a !== document.body) a.blur();
      settled(Date.now()).then(function (ok) {
        if (!ok) { reloading = false; setText("Not saved yet: tap to try again"); return; }
        setText("Loading…");
        try { sessionStorage.setItem(Y_KEY, String(Math.round(window.scrollY))); } catch (e) {}
        location.reload();
      });
    }
    function poll() {
      if (reloading || document.visibilityState === "hidden") return;
      fetch("version.json", { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (v) {
        if (!v || !(Number(v.version) > seen)) return;
        var n = 0;
        if (Array.isArray(v.log) && v.log.length) {
          v.log.forEach(function (e) { if (Number(e.v) > seen) n += (e.added || []).length; });
        } else n = (v.added || []).length;
        showBanner(n);
      }, function () {});
    }
    setInterval(poll, 20000);
    setInterval(function () {
      if (!banner || reloading || typingFocus() || Date.now() - lastActivity < 30000) return;
      go();
    }, 2000);
    document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") poll(); });
    window.addEventListener("pageshow", function (e) { if (e.persisted) poll(); });
  }
})();
