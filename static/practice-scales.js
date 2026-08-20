(function () {
  function clamp(value) {
    return Math.max(0, Math.min(100, Number(value) || 0));
  }

  function colorFor(percent) {
    if (percent < 20) return "red";
    if (percent < 50) return "yellow";
    if (percent < 80) return "light";
    return "dark";
  }

  function parseStats(box) {
    var text = String(box.textContent || "").replace(/\s+/g, " ");
    var doneMatch = text.match(/(\d+)\s*из\s*(\d+)/);
    if (!doneMatch) return null;
    var done = Number(doneMatch[1]);
    var total = Number(doneMatch[2]);
    var correctMatch = text.match(/Верно:\s*(\d+)/i);
    var correct = correctMatch ? Number(correctMatch[1]) : 0;
    var color = colorFor(total ? Math.round((100 * done) / total) : 0);
    return { done: done, total: total, correct: correct, color: color };
  }

  function scalesHtml(stats) {
    var done = stats.done;
    var total = stats.total;
    var correct = stats.correct;
    var doneWidth = clamp(total ? Math.round((100 * done) / total) : 0);
    var accuracyWidth = clamp(done ? Math.round((100 * correct) / done) : 0);
    return (
      '<div class="practice-scale">' +
      '<div class="scale-head"><span>Сделано</span><strong>' +
      done +
      " из " +
      total +
      "</strong></div>" +
      '<div class="scale-track" aria-label="Сделано ' +
      done +
      " из " +
      total +
      '">' +
      '<div class="scale-fill progress-' +
      stats.color +
      '" style="width: ' +
      doneWidth +
      '%"></div></div></div>' +
      '<div class="practice-scale">' +
      '<div class="scale-head"><span>Верно</span><strong>' +
      correct +
      " из " +
      done +
      "</strong></div>" +
      '<div class="scale-track" aria-label="Верно ' +
      correct +
      " из " +
      done +
      '">' +
      '<div class="scale-fill scale-accuracy" style="width: ' +
      accuracyWidth +
      '%"></div></div></div>' +
      '<p class="stats-hint">Запишите номера рядов без пробелов, как в бланке ЕГЭ: например 245.</p>'
    );
  }

  function upgrade(view) {
    if (!view) return;
    var boxes = view.querySelectorAll(".practice-stats");
    Array.prototype.forEach.call(boxes, function (box) {
      var stats = parseStats(box);
      if (!stats) return;
      var wrap = document.createElement("div");
      wrap.className = "practice-scales";
      wrap.innerHTML = scalesHtml(stats);
      box.replaceWith(wrap);
    });
  }

  function bind() {
    var view = document.getElementById("practice-view");
    if (!view) return;
    upgrade(view);
    new MutationObserver(function () {
      upgrade(view);
    }).observe(view, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
