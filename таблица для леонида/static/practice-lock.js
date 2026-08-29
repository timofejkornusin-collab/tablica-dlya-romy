(function () {
  function isStudentUi() { return document.body.classList.contains("student-preview"); }
  function lockCard(card) {
    if (!card || card.querySelector(".task-locked")) return;
    var input = card.querySelector("input[data-role='given']");
    if (!input || !String(input.value || "").trim()) return;
    input.readOnly = true;
    card.classList.add("locked");
    var btn = card.querySelector(".save-answer");
    var note = document.createElement("p");
    note.className = "task-locked";
    note.textContent = "Ответ сохранён. Изменить его нельзя.";
    if (btn && btn.parentNode) btn.parentNode.replaceChild(note, btn);
    else card.appendChild(note);
  }
  function lockAll(view) {
    if (!view || !isStudentUi()) return;
    var cards = view.querySelectorAll(".task-card.ok, .task-card.bad, .task-card.saved, .task-card.locked");
    Array.prototype.forEach.call(cards, lockCard);
  }
  document.addEventListener("click", function (event) {
    if (!isStudentUi()) return;
    var btn = event.target.closest(".save-answer");
    if (!btn) return;
    var card = btn.closest(".task-card");
    var input = card && card.querySelector("input[data-role='given']");
    if (input && input.readOnly) {
      event.preventDefault();
      event.stopPropagation();
      alert("Ответ уже сохранён. Изменить его нельзя.");
    }
  }, true);
  function bind() {
    var view = document.getElementById("practice-view");
    if (!view) return;
    lockAll(view);
    new MutationObserver(function () { lockAll(view); }).observe(view, { childList: true, subtree: true, attributes: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind);
  else bind();
})();
