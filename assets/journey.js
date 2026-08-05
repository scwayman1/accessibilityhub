/* Accessibility Hub — educator journey enhancement (first-party, same-origin).
 *
 * Progressive enhancement only. Every page works with this file absent or
 * scripting disabled: the drop form posts natively and the processing page
 * falls back to its <noscript> meta refresh. Nothing here gates results,
 * touches third parties, or runs when the user prefers reduced motion
 * (animation-wise; navigation polling still runs — it is not motion).
 */
(function () {
  "use strict";

  var motionOk = true;
  try {
    motionOk = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (error) {
    motionOk = true;
  }

  var BURST_COLORS = ["#F0563F", "#CF3A24", "#FFC94D", "#0E7C66", "#232A33"];

  function each(list, fn) {
    Array.prototype.forEach.call(list, fn);
  }

  /* ---------------------------------------------------------------- *
   * Drop page: a real drag-over state and a named-file confirmation. *
   * ---------------------------------------------------------------- */
  var zone = document.querySelector("[data-dropzone]");
  if (zone) {
    var input = zone.querySelector("input[type=file]");
    var hint = zone.querySelector("[data-drop-hint]");

    var showChosen = function () {
      if (!input || !input.files || !input.files.length) {
        return;
      }
      zone.classList.add("has-file");
      if (hint) {
        hint.textContent = "Ready to transform: " + input.files[0].name;
      }
    };

    each(["dragenter", "dragover"], function (type) {
      zone.addEventListener(type, function (event) {
        event.preventDefault();
        zone.classList.add("is-dragover");
      });
    });
    each(["dragleave", "dragend", "drop"], function (type) {
      zone.addEventListener(type, function () {
        zone.classList.remove("is-dragover");
      });
    });
    zone.addEventListener("drop", function (event) {
      event.preventDefault();
      var files = event.dataTransfer && event.dataTransfer.files;
      if (files && files.length && input) {
        input.files = files;
        showChosen();
      }
    });
    if (input) {
      input.addEventListener("change", showChosen);
      showChosen();
    }
  }

  /* ------------------------------------------------------------------ *
   * Processing page: poll the first-party status endpoint and move the *
   * document along its journey without full-page reloads. The server's *
   * <noscript> meta refresh remains the no-JS path.                    *
   * ------------------------------------------------------------------ */
  var STAGE_ORDER = ["reading", "improving", "verifying"];
  var STAGE_COPY = {
    reading: "Reading your document…",
    improving: "Applying safe improvements…",
    verifying: "Verifying the new copy…"
  };

  function sparkAt(scene, x, y) {
    if (!motionOk || !scene) {
      return;
    }
    var spark = document.createElement("span");
    spark.className = "journey-spark";
    spark.setAttribute("aria-hidden", "true");
    spark.style.left = x + "%";
    spark.style.top = y + "%";
    spark.style.setProperty("--dx", (Math.random() * 44 - 22).toFixed(0) + "px");
    spark.style.setProperty("--dy", (-14 - Math.random() * 26).toFixed(0) + "px");
    scene.appendChild(spark);
    window.setTimeout(function () {
      if (spark.parentNode) {
        spark.parentNode.removeChild(spark);
      }
    }, 900);
  }

  function sparkleBurst(scene, stage) {
    var anchors = { reading: 10, improving: 50, verifying: 88 };
    var x = anchors[stage] === undefined ? 50 : anchors[stage];
    for (var index = 0; index < 7; index += 1) {
      sparkAt(scene, x + (Math.random() * 10 - 5), 26 + Math.random() * 22);
    }
  }

  var card = document.querySelector('[data-journey="processing"]');
  if (card && window.fetch) {
    var statusUrl = card.getAttribute("data-status-url");
    var scene = card.querySelector(".journey-scene");
    var headline = card.querySelector("[data-journey-headline]");
    var misses = 0;

    var applyStage = function (stage) {
      if (STAGE_ORDER.indexOf(stage) < 0 || card.getAttribute("data-stage") === stage) {
        return;
      }
      card.setAttribute("data-stage", stage);
      if (headline && STAGE_COPY[stage]) {
        headline.textContent = STAGE_COPY[stage];
      }
      var reached = STAGE_ORDER.indexOf(stage);
      each(card.querySelectorAll("[data-stage-item]"), function (item) {
        var own = STAGE_ORDER.indexOf(item.getAttribute("data-stage-item"));
        item.className = own < reached ? "done" : own === reached ? "active" : "";
      });
      sparkleBurst(scene, stage);
    };

    var arriveAt = function (location) {
      try {
        window.sessionStorage.setItem("hub-journey-arrival", "1");
      } catch (error) { /* storage may be unavailable; celebration is optional */ }
      window.location.replace(location);
    };

    // Fast pipelines can leap from "reading" straight to done between two
    // polls. When that happens, walk the document through the remaining
    // named stages so the journey is seen, then arrive. Motion users only:
    // under prefers-reduced-motion (or on failure) we navigate immediately —
    // the animation adds about two seconds and never gates the result, which
    // is already complete and reachable by refresh the whole time.
    var arriving = false;
    var arriveThrough = function (data) {
      if (arriving) {
        return;
      }
      arriving = true;
      var destination = data.location || window.location.pathname;
      var remaining = STAGE_ORDER.slice(STAGE_ORDER.indexOf(card.getAttribute("data-stage")) + 1);
      if (!motionOk || data.stage !== "ready" || !remaining.length) {
        arriveAt(destination);
        return;
      }
      var step = function () {
        if (!remaining.length) {
          window.setTimeout(function () { arriveAt(destination); }, 700);
          return;
        }
        applyStage(remaining.shift());
        window.setTimeout(step, 850);
      };
      step();
    };

    var tick = function () {
      if (arriving) {
        return;
      }
      window.fetch(statusUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("status " + response.status);
          }
          return response.json();
        })
        .then(function (data) {
          misses = 0;
          if (data.stage === "ready" || data.stage === "failed") {
            arriveThrough(data);
            return;
          }
          applyStage(data.stage);
          window.setTimeout(tick, 1200);
        })
        .catch(function () {
          misses += 1;
          if (misses >= 4) {
            window.location.reload(); // Hand back to the server-rendered flow.
            return;
          }
          window.setTimeout(tick, 2000);
        });
    };
    window.setTimeout(tick, 800);

    // Ambient trail: an occasional sparkle drifting off the traveling document.
    if (motionOk && scene) {
      var anchors = { reading: 12, improving: 50, verifying: 86 };
      window.setInterval(function () {
        var stage = card.getAttribute("data-stage");
        var x = anchors[stage] === undefined ? 50 : anchors[stage];
        sparkAt(scene, x + (Math.random() * 8 - 4), 20 + Math.random() * 18);
      }, 1700);
    }
  }

  /* ------------------------------------------------------------- *
   * Ready page: one celebratory arrival, then calm. The burst is  *
   * decorative, runs once, and never appears under reduced motion. *
   * ------------------------------------------------------------- */
  var ready = document.querySelector('[data-journey="ready"]');
  if (ready) {
    var arrived = false;
    try {
      arrived = window.sessionStorage.getItem("hub-journey-arrival") === "1";
      window.sessionStorage.removeItem("hub-journey-arrival");
    } catch (error) {
      arrived = false;
    }
    var badge = ready.querySelector(".seal-badge");
    if (badge && motionOk) {
      badge.classList.add("celebrate");
    }
    if (arrived && motionOk) {
      var layer = document.createElement("div");
      layer.className = "burst-layer";
      layer.setAttribute("aria-hidden", "true");
      for (var index = 0; index < 26; index += 1) {
        var piece = document.createElement("span");
        piece.className = "burst-piece";
        piece.style.left = (8 + Math.random() * 84) + "%";
        piece.style.background = BURST_COLORS[index % BURST_COLORS.length];
        piece.style.setProperty("--dx", (Math.random() * 120 - 60).toFixed(0) + "px");
        piece.style.setProperty("--dy", (140 + Math.random() * 180).toFixed(0) + "px");
        piece.style.setProperty("--rot", (Math.random() * 540 - 270).toFixed(0) + "deg");
        piece.style.setProperty("--delay", (Math.random() * 0.35).toFixed(2) + "s");
        layer.appendChild(piece);
      }
      ready.appendChild(layer);
      window.setTimeout(function () {
        if (layer.parentNode) {
          layer.parentNode.removeChild(layer);
        }
      }, 2600);
    }
  }
})();
