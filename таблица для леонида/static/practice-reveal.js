(function () {
  var answers = {};

  function remember(data) {
    answers = {};
    ((data && data.tasks) || []).forEach(function (task) {
      if (!task || task.status !== "bad") return;
      var value = task.correctAnswer || "";
      if (value) answers[String(task.n)] = String(value);
    });
  }

  function inject(view) {
    if (!view) return;
    var cards = view.querySelectorAll(".task-card.bad");
    Array.prototype.forEach.call(cards, function (card) {
      if (card.querySelector(".task-correct")) return;
      var answer = answers[String(card.getAttribute("data-n") || "")];
      if (!answer) return;
      var line = document.createElement("p");
      line.className = "task-correct";
      line.appendChild(document.createTextNode("Правильный ответ: "));
      var strong = document.createElement("strong");
      strong.textContent = answer;
      line.appendChild(strong);
      card.appendChild(line);
    });
  }

  var originalFetch = window.fetch;
  window.fetch = function () {
    var args = arguments;
    return originalFetch.apply(this, args).then(function (response) {
      try {
        var url = "";
        if (typeof args[0] === "string") url = args[0];
        else if (args[0] && args[0].url) url = args[0].url;
        if (url.indexOf("/api/practice") !== -1 && response && response.clone) {
          response
            .clone()
            .json()
            .then(function (data) {
              remember(data);
              inject(document.getElementById("practice-view"));
            })
            .catch(function () {});
        }
      } catch (_error) {}
      return response;
    });
  };

  function bind() {
    var view = document.getElementById("practice-view");
    if (!view) return;
    inject(view);
    new MutationObserver(function () {
      inject(view);
    }).observe(view, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
