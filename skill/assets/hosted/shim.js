/* Hosted /choices: stands in for claude.ai's window.claude (db + user) using this page's own api/.
   The picker code is unchanged. A personal link (?v=<token>) is remembered for this page, then removed from the
   address bar so it isn't shared by accident. */
(function () {
  var KEY = "choices-token:" + location.pathname;
  var qs = new URLSearchParams(location.search);
  var token = qs.get("v");
  if (token) {
    try { localStorage.setItem(KEY, token); } catch (e) {}
    history.replaceState(null, "", location.pathname + location.hash);
  } else {
    try { token = localStorage.getItem(KEY); } catch (e) {}
  }

  function api(path, opts) {
    opts = opts || {};
    var headers = { "content-type": "application/json" };
    if (token) headers["x-hl-token"] = token;
    opts.headers = headers;
    return fetch("api/" + path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) {
          var e = new Error(j.error || String(r.status));
          e.code = r.status >= 500 || r.status === 429 ? "unavailable" : r.status === 409 ? "closed" : "forbidden";
          e.status = r.status;
          throw e;
        }
        return j;
      });
    });
  }

  var me = null, latest = null, voteSubs = [], stateSubs = [], timer = null;
  function emit() {
    if (!latest) return;
    var snap = { docs: latest.votes.map(function (v) { return { id: v.id, data: function () { return { sections: v.sections }; } }; }) };
    voteSubs.forEach(function (s) { try { s(snap); } catch (e) {} });
    var st = { exists: true, data: function () { return { closed: latest.closed }; } };
    stateSubs.forEach(function (s) { try { s(st); } catch (e) {} });
  }
  function poll() {
    return api("votes").then(function (d) { latest = d; emit(); }, function () {});
  }
  function startPolling() {
    if (timer) return;
    poll();
    timer = setInterval(function () { if (!document.hidden) poll(); }, 4000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
  }

  function joinBox() {
    var css = document.createElement("style");
    css.textContent = ".join{display:grid;gap:8px;margin:0 0 20px;padding:14px 16px;border:1px solid var(--line,#ccc);" +
      "border-left:4px solid var(--accent,#1663c7);border-radius:8px;max-width:72ch}.join div{display:flex;gap:8px;flex-wrap:wrap}" +
      ".join input{flex:1 1 200px;font:inherit;padding:8px 10px;border-radius:6px;border:1px solid var(--line,#ccc)}" +
      ".join button{font:inherit;padding:8px 14px;border-radius:6px;border:0;background:var(--accent,#1663c7);color:#fff}" +
      ".join-err{color:#b42318;margin:0}";
    document.head.appendChild(css);
    var box = document.createElement("form");
    box.className = "join";
    box.innerHTML = '<label for="join-name">Your name, so your picks show up for everyone</label>' +
      '<div><input id="join-name" maxlength="40" autocomplete="name" required> <button type="submit">Start voting</button></div>' +
      '<p class="join-err" hidden></p>';
    box.addEventListener("submit", function (e) {
      e.preventDefault();
      api("join", { method: "POST", body: JSON.stringify({ name: box.querySelector("input").value }) }).then(function (j) {
        try { localStorage.setItem(KEY, j.token); } catch (err) {}
        location.reload();
      }, function (err) {
        var p = box.querySelector(".join-err"); p.hidden = false; p.textContent = err.message;
      });
    });
    var main = document.querySelector("main") || document.body;
    main.insertBefore(box, main.firstChild);
  }

  var ready = api("me").then(function (m) { me = m; return m; }, function () {
    if (window.CHOICES_HOSTED && window.CHOICES_HOSTED.open) {
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", joinBox); else joinBox();
    }
    return null;
  });

  var db = {
    doc: function (path) {
      return {
        set: function (value) {
          if (path.indexOf("votes/") !== 0) return Promise.reject(Object.assign(new Error("read only"), { code: "forbidden" }));
          return api("votes", { method: "PUT", body: JSON.stringify({ sections: value.sections }) }).then(function () { poll(); });
        },
        onSnapshot: function (cb) { if (path === "meta/state") { stateSubs.push(cb); emit(); startPolling(); } return function () {}; }
      };
    },
    collection: function (name) {
      return { onSnapshot: function (cb) { if (name === "votes") { voteSubs.push(cb); emit(); startPolling(); } return function () {}; } };
    }
  };
  var user = {
    me: function () { return Promise.resolve({ isOwner: !!(me && me.owner), canEdit: !!(me && me.owner) }); },
    id: function () { return Promise.resolve(me ? me.id : null); },
    profiles: function (ids) {
      var out = {};
      (ids || []).forEach(function (id) { out[id] = { name: (latest && latest.names && latest.names[id]) || "Someone" }; });
      return Promise.resolve(out);
    }
  };

  window.claude = {
    use: function (name) {
      if (name === "db") return ready.then(function () { return db; });
      if (name === "user") return ready.then(function () { return user; });
      return Promise.resolve(null); // comments stay a claude.ai feature; voters use the notes boxes
    }
  };
})();
