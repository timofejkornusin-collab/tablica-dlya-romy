(function () {
  function $(id) {
    return document.getElementById(id);
  }

  function hideFindDialog() {
    var box = $("find-dialog");
    if (box) box.classList.add("hidden");
    var err = $("find-error");
    if (err) err.textContent = "";
  }

  function ensureDialog() {
    if ($("find-dialog")) return;
    var wrap = document.createElement("div");
    wrap.id = "find-dialog";
    wrap.className = "row-confirm hidden";
    wrap.setAttribute("role", "dialog");
    wrap.innerHTML =
      '<form id="find-form" class="row-confirm-card find-card">' +
      "<p>Найти строку по дате</p>" +
      '<label>Дата урока<input id="find-date" type="text" maxlength="20" placeholder="например 10.09.2026" autocomplete="off" /></label>' +
      '<p id="find-error" class="error"></p>' +
      '<div class="row-confirm-actions">' +
      '<button id="find-cancel" class="secondary-btn" type="button">Отмена</button>' +
      '<button class="primary-btn" type="submit">Найти</button>' +
      "</div></form>";
    document.body.appendChild(wrap);
  }

  function ensureButton() {
    var existing = $("find-row-btn");
    var old = $("add-row-btn");
    if (existing) {
      if (old && old !== existing) old.style.display = "none";
      existing.classList.remove("hidden");
      return existing;
    }
    if (old) {
      old.textContent = "Найти";
      old.id = "find-row-btn";
      old.classList.remove("hidden");
      old.style.display = "";
      var clone = old.cloneNode(true);
      old.parentNode.replaceChild(clone, old);
      return clone;
    }
    var btn = document.createElement("button");
    btn.id = "find-row-btn";
    btn.type = "button";
    btn.className = "secondary-btn";
    btn.textContent = "Найти";
    var actions = $("table-actions");
    var bar = document.querySelector(".topbar-right");
    if (actions) actions.appendChild(btn);
    else if (bar) bar.appendChild(btn);
    return btn;
  }

  function showFindButtonIfTableOpen() {
    var table = $("table-view");
    var actions = $("table-actions");
    var btn = $("find-row-btn");
    var open = table && !table.classList.contains("hidden");
    if (actions && open) actions.classList.remove("hidden");
    if (btn) btn.classList.toggle("hidden", !open);
  }

  function parseDateParts(value) {
    var raw = String(value || "").trim();
    var iso = raw.match(/(\d{4})[./-](\d{1,2})[./-](\d{1,2})/);
    if (iso) return { year: Number(iso[1]), month: Number(iso[2]), day: Number(iso[3]) };
    var dmy = raw.match(/(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?/);
    if (!dmy) return null;
    var year = dmy[3] ? Number(dmy[3]) : null;
    if (year != null && year < 100) year += 2000;
    return { year: year, month: Number(dmy[2]), day: Number(dmy[1]) };
  }

  function rowMatchesDate(row, query) {
    var needle = String(query || "").trim();
    if (!needle) return false;
    var rowDate = String((row && row.date) || "");
    var wanted = parseDateParts(needle);
    var got = parseDateParts(rowDate);
    if (wanted && got) {
      if (wanted.day !== got.day || wanted.month !== got.month) return false;
      if (wanted.year != null && got.year != null && wanted.year !== got.year) return false;
      return true;
    }
    return rowDate.replace(/\s+/g, "").toLowerCase().indexOf(needle.replace(/\s+/g, "").toLowerCase()) !== -1;
  }

  function scrollToIndex(index) {
    var cell = document.querySelector('textarea[data-row="' + index + '"][data-key="date"]');
    var row = cell && cell.closest("tr");
    if (!row) row = document.querySelector('tr[data-row="' + index + '"]');
    if (!row) return false;
    document.querySelectorAll("tr.row-found").forEach(function (item) {
      item.classList.remove("row-found");
    });
    row.classList.add("row-found");
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(function () {
      row.classList.remove("row-found");
    }, 2600);
    return true;
  }

  function findLesson(query) {
    if (typeof currentStudent !== "function") {
      return { ok: false, error: "Журнал ещё не открылся. Обновите страницу." };
    }
    var student = currentStudent();
    var rows = student && student.rows ? student.rows : [];
    if (!student || !rows.length) return { ok: false, error: "Сначала откройте таблицу." };
    var index = -1;
    for (var i = 0; i < rows.length; i++) {
      if (rowMatchesDate(rows[i], query)) {
        index = i;
        break;
      }
    }
    if (index < 0) return { ok: false, error: "Строка с такой датой не найдена." };
    if (typeof state === "object" && state) state.revealedRowIndex = index;
    if (typeof renderTable === "function") renderTable();
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        scrollToIndex(index);
        showFindButtonIfTableOpen();
      });
    });
    return { ok: true };
  }

  function openDialog() {
    ensureDialog();
    var box = $("find-dialog");
    var err = $("find-error");
    var input = $("find-date");
    if (err) err.textContent = "";
    if (box) box.classList.remove("hidden");
    if (input) {
      input.value = "";
      input.focus();
    }
  }

  function wire() {
    ensureDialog();
    ensureButton();
    document.addEventListener(
      "click",
      function (event) {
        if (event.target.closest("#find-row-btn") || (event.target.closest("#add-row-btn") && event.target.closest("#add-row-btn").textContent.indexOf("Найти") >= 0)) {
          event.preventDefault();
          event.stopPropagation();
          openDialog();
          return;
        }
        if (event.target.closest("#find-cancel") || event.target.id === "find-dialog") {
          hideFindDialog();
        }
      },
      true
    );
    document.addEventListener(
      "submit",
      function (event) {
        if (!event.target || event.target.id !== "find-form") return;
        event.preventDefault();
        var input = $("find-date");
        var err = $("find-error");
        var query = input ? input.value.trim() : "";
        if (!query) {
          if (err) err.textContent = "Введите дату, например 10.09.2026";
          return;
        }
        var result = findLesson(query);
        if (!result.ok) {
          if (err) err.textContent = result.error;
          return;
        }
        hideFindDialog();
      },
      true
    );
    if (typeof visibleRowIndexes === "function") {
      var originalVisible = visibleRowIndexes;
      window.visibleRowIndexes = function (student) {
        var list = originalVisible(student) || [];
        var revealed = typeof state === "object" && state ? state.revealedRowIndex : null;
        var rows = student && student.rows ? student.rows : [];
        if (Number.isInteger(revealed) && revealed >= 0 && revealed < rows.length && list.indexOf(revealed) < 0) {
          list = list.concat([revealed]).sort(function (a, b) {
            return a - b;
          });
        }
        return list;
      };
    }
    if (typeof renderTable === "function") {
      var original = renderTable;
      window.renderTable = function () {
        var result = original.apply(this, arguments);
        showFindButtonIfTableOpen();
        return result;
      };
    }
    showFindButtonIfTableOpen();
    setInterval(showFindButtonIfTableOpen, 800);
  }

  if (!document.getElementById("find-date-style")) {
    var style = document.createElement("style");
    style.id = "find-date-style";
    style.textContent =
      "tbody tr.row-found td{background:#fff6df;box-shadow:inset 0 0 0 2px var(--gold,#c9a227)}" +
      ".find-card{text-align:left}" +
      ".find-card p{text-align:center}" +
      ".find-card label{display:flex;flex-direction:column;gap:8px;margin-bottom:12px;font-weight:600}" +
      ".find-card input{width:100%;min-height:44px;box-sizing:border-box}" +
      "#add-row-btn{display:none !important}";
    document.head.appendChild(style);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
