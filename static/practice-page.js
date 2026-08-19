(function () {
  var view = document.getElementById("practice-view");
  if (!view) return;

  function isOpen() {
    return view && !view.classList.contains("hidden") && view.innerHTML.trim();
  }

  function sync() {
    var open = isOpen();
    document.body.classList.toggle("practice-open", open);
    if (!open) return;
    if (!view.querySelector(".practice-back")) {
      var bar = document.createElement("div");
      bar.className = "practice-toolbar";
      bar.innerHTML = '<button type="button" class="primary-btn practice-back">← К таблице</button>';
      view.insertBefore(bar, view.firstChild);
    }
    view.scrollTop = 0;
  }

  var observer = new MutationObserver(sync);
  observer.observe(view, { attributes: true, attributeFilter: ["class"], childList: true, subtree: true });
  document.addEventListener(
    "click",
    function (event) {
      if (!event.target.closest(".practice-back")) return;
      event.preventDefault();
      event.stopPropagation();
      document.body.classList.remove("practice-open");
      var back = document.getElementById("back-btn");
      if (back) back.click();
    },
    true
  );
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", sync);
  } else {
    sync();
  }
})();
