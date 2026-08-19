const COLUMNS = [
  { key: "date", label: "Дата урока", className: "col-date" },
  { key: "topic", label: "Тема урока", className: "col-topic" },
  { key: "theory", label: "Теоретический материал", className: "col-theory" },
  { key: "practice", label: "Практические задания", className: "col-practice" },
  { key: "progress", label: "Прогресс", className: "col-progress" },
  { key: "homework", label: "Домашнее задание", className: "col-homework" },
  { key: "comment", label: "Комментарий педагога", className: "col-comment" },
];

const WEEKDAYS = [
  "понедельник",
  "вторник",
  "среда",
  "четверг",
  "пятница",
  "суббота",
  "воскресенье",
];

const TEMPLATE_LABELS = {
  once: "1 раз в неделю",
  twice: "2 раза в неделю",
};

const state = {
  students: [],
  banks: [],
  currentId: null,
  me: null,
  publicUrl: "",
  lanUrl: "",
  lanUrls: [],
  wifiName: "",
  tunnelError: "",
  view: "list",
  practice: null,
  previewAsStudent: false,
};

const els = {
  app: document.getElementById("app"),
  listView: document.getElementById("list-view"),
  tableView: document.getElementById("table-view"),
  practiceView: document.getElementById("practice-view"),
  pageTitle: document.getElementById("page-title"),
  pageSubtitle: document.getElementById("page-subtitle"),
  backBtn: document.getElementById("back-btn"),
  addStudentBtn: document.getElementById("add-student-btn"),
  previewBtn: document.getElementById("preview-btn"),
  exitPreviewBtn: document.getElementById("exit-preview-btn"),
  previewBanner: document.getElementById("preview-banner"),
  tableActions: document.getElementById("table-actions"),
  templateWrap: document.getElementById("template-wrap"),
  templateSelect: document.getElementById("template-select"),
  addRowBtn: document.getElementById("add-row-btn"),
  saveStatus: document.getElementById("save-status"),
  shareBar: document.getElementById("share-bar"),
  shareUrl: document.getElementById("share-url"),
  shareLan: document.getElementById("share-lan"),
  shareLanTitle: document.getElementById("share-lan-title"),
  shareHint: document.getElementById("share-hint"),
  copyLinkBtn: document.getElementById("copy-link-btn"),
  copyLanBtn: document.getElementById("copy-lan-btn"),
  modal: document.getElementById("modal"),
  studentForm: document.getElementById("student-form"),
  studentName: document.getElementById("student-name"),
  startDate: document.getElementById("start-date"),
  weekday0: document.getElementById("weekday-0"),
  weekday1: document.getElementById("weekday-1"),
  time0: document.getElementById("time-0"),
  time1: document.getElementById("time-1"),
  secondSlot: document.getElementById("second-slot"),
  cancelModal: document.getElementById("cancel-modal"),
  createFields: document.getElementById("create-fields"),
  createdBox: document.getElementById("created-box"),
  createSubmit: document.getElementById("create-submit"),
  modalError: document.getElementById("modal-error"),
};

let saveTimer = null;
let pollTimer = null;

function emptyRow() {
  return {
    date: "",
    topic: "",
    theory: "",
    practice: "",
    progress: "",
    homework: "",
    comment: "",
    bankId: "",
  };
}

function isTeacherAccount() {
  return !state.me || state.me.role !== "student";
}

function isStudentView() {
  return !isTeacherAccount() || state.previewAsStudent;
}

function isTeacherUi() {
  return isTeacherAccount() && !state.previewAsStudent;
}

function enterStudentPreview(studentId) {
  if (!isTeacherAccount() || !studentId) return;
  state.previewAsStudent = true;
  state.currentId = studentId;
  renderTable();
}

function exitStudentPreview() {
  state.previewAsStudent = false;
  if (state.currentId) {
    renderTable();
    return;
  }
  renderList();
}

function updateModeChrome() {
  const preview = isTeacherAccount() && state.previewAsStudent;
  const inStudentTable = Boolean(state.currentId) && (state.view === "table" || state.view === "practice");
  if (els.previewBanner) {
    els.previewBanner.classList.toggle("hidden", !preview);
  }
  if (els.exitPreviewBtn) {
    els.exitPreviewBtn.classList.toggle("hidden", !preview);
  }
  if (els.previewBtn) {
    els.previewBtn.classList.toggle("hidden", !isTeacherUi() || !inStudentTable);
  }
  document.body.classList.toggle("student-preview", isStudentView());
}

function currentStudent() {
  return state.students.find((student) => student.id === state.currentId) || null;
}

function setSaveStatus(text) {
  els.saveStatus.textContent = text;
}

function weekdaySelect(id, selected) {
  const options = WEEKDAYS.map(
    (name, index) =>
      `<option value="${index}" ${Number(selected) === index ? "selected" : ""}>${name}</option>`
  ).join("");
  return `<select id="${id}">${options}</select>`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    credentials: "same-origin",
    ...options,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...(options.headers || {}),
    },
  });
  let data = {};
  try {
    data = await response.json();
  } catch (_error) {
    data = {};
  }
  if (!response.ok) {
    throw new Error(data.error || "Ошибка запроса");
  }
  return data;
}

async function loadSession() {
  const data = await api("/api/session");
  state.me = data.user;
  state.publicUrl = data.publicUrl || "";
  state.lanUrl = data.lanUrl || "";
  state.lanUrls = Array.isArray(data.lanUrls) && data.lanUrls.length ? data.lanUrls : data.lanUrl ? [data.lanUrl] : [];
  state.wifiName = data.wifiName || "";
  state.tunnelError = data.tunnelError || "";
  updateShareBar();
  return data;
}

async function loadStudents() {
  const data = await api("/api/students");
  state.students = Array.isArray(data.students) ? data.students : [];
}

async function loadBanks() {
  const data = await api("/api/banks");
  state.banks = Array.isArray(data.banks) ? data.banks : [];
}

function updateShareBar() {
  if (state.view === "practice" || isStudentView()) {
    els.shareBar.classList.add("hidden");
    return;
  }
  els.shareBar.classList.remove("hidden");
  const wifi = state.wifiName ? ` «${state.wifiName}»` : "";
  if (els.shareLanTitle) {
    els.shareLanTitle.textContent = `Запасной адрес в Wi‑Fi${wifi}`;
  }
  if (els.shareLan) {
    els.shareLan.textContent = (state.lanUrls && state.lanUrls.length ? state.lanUrls : [state.lanUrl]).filter(Boolean).join("\n");
  }
  if (state.publicUrl) {
    els.shareUrl.textContent = state.publicUrl;
    els.shareHint.textContent =
      "Верхнюю ссылку можно открыть даже с мобильного интернета. Нижнюю — только если телефон в той же Wi‑Fi, что компьютер, и в адресе http://, не https://.";
  } else if (state.tunnelError) {
    els.shareUrl.textContent = state.tunnelError;
    els.shareHint.textContent =
      `Телефон в Wi‑Fi${wifi || " компьютера"}, адрес с http:// не https://. Если Safari ставит замочек — откройте Chrome. Один раз запустите «разрешить-телефон.bat» и нажмите Да. Если снова не открывается, на компьютере включите Мобильный хот-спот и подключите телефон к нему.`;
  } else {
    els.shareUrl.textContent = "Готовится… подождите 10–20 секунд, окно запуска не закрывайте";
    els.shareHint.textContent =
      "Сначала появится интернет-ссылка. Если нужна только Wi‑Fi — копируйте нижний адрес, обязательно http://, не https://.";
  }
}

function showApp() {
  els.app.classList.remove("hidden");
  els.addStudentBtn.classList.toggle("hidden", !isTeacherUi());
  updateModeChrome();
  updateShareBar();
}

function collectCreateSlots() {
  const template = els.studentForm.template.value === "twice" ? "twice" : "once";
  const slots = [
    { weekday: Number(els.weekday0.value), time: els.time0.value || "16:00" },
  ];
  if (template === "twice") {
    slots.push({ weekday: Number(els.weekday1.value), time: els.time1.value || "16:00" });
  }
  return { template, slots, startDate: els.startDate.value };
}

async function persistCurrent() {
  const student = currentStudent();
  if (!student) return;
  setSaveStatus("Сохранение…");
  const data = await api("/api/table", {
    method: "POST",
    body: JSON.stringify({
      id: student.id,
      rows: student.rows,
      template: student.template,
    }),
  });
  if (data.student) {
    const index = state.students.findIndex((item) => item.id === student.id);
    if (index >= 0) state.students[index] = data.student;
  }
  setSaveStatus("Сохранено");
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    persistCurrent().catch((error) => setSaveStatus(error.message));
  }, 250);
}

function fitTableAreas() {
  els.tableView.querySelectorAll("textarea").forEach((area) => {
    area.style.height = "auto";
    area.style.height = `${Math.max(88, area.scrollHeight)}px`;
  });
}

function toggleSecondSlot() {
  const twice = els.studentForm.template.value === "twice";
  els.secondSlot.classList.toggle("hidden", !twice);
}

function openModal() {
  els.modal.classList.remove("hidden");
  els.createFields.classList.remove("hidden");
  els.createdBox.classList.add("hidden");
  els.createSubmit.classList.remove("hidden");
  els.createSubmit.textContent = "Создать таблицу";
  els.modalError.textContent = "";
  els.studentForm.reset();
  els.studentForm.template.value = "once";
  els.startDate.value = "2026-09-03";
  els.weekday0.value = "3";
  els.time0.value = "16:00";
  els.weekday1.value = "1";
  els.time1.value = "16:00";
  toggleSecondSlot();
  els.studentName.focus();
}

function closeModal() {
  els.modal.classList.add("hidden");
}

function renderList() {
  state.view = "list";
  state.currentId = null;
  state.previewAsStudent = false;
  els.listView.classList.remove("hidden");
  els.tableView.classList.add("hidden");
  els.practiceView.classList.add("hidden");
  els.backBtn.classList.add("hidden");
  els.tableActions.classList.add("hidden");
  if (isTeacherUi()) els.addStudentBtn.classList.remove("hidden");
  els.pageTitle.textContent = "Журнал занятий";
  els.pageSubtitle.textContent = "Выберите ученика или создайте таблицу с расписанием";
  updateModeChrome();
  updateShareBar();

  if (!state.students.length) {
    els.listView.innerHTML = `
      <div class="empty-state">
        <p>Пока нет учеников.</p>
        <p>Добавьте ученика, укажите день и время — даты встанут до последнего такого дня в мае.</p>
      </div>
    `;
    return;
  }

  els.listView.innerHTML = `<div class="cards">${state.students
    .map(
      (student) => `
        <article class="card" data-id="${student.id}">
          <div class="card-top">
            <div class="avatar">${escapeHtml(initial(student.name))}</div>
            <div>
              <h2>${escapeHtml(student.name)}</h2>
              <span class="badge">${TEMPLATE_LABELS[student.template] || TEMPLATE_LABELS.once}</span>
            </div>
          </div>
          <div class="card-actions">
            <button class="primary-btn open-table" type="button">Открыть таблицу</button>
            <button class="secondary-btn preview-student" type="button">Как видит ученик</button>
            <button class="danger-btn delete-student" type="button">Удалить</button>
          </div>
        </article>
      `
    )
    .join("")}</div>`;
}

function bankOptions(selected) {
  const items = state.banks.length ? state.banks : [{ id: "ege-10", title: "Задание 10 ЕГЭ" }];
  return `<option value="">— нет —</option>${items
    .map(
      (bank) =>
        `<option value="${escapeHtml(bank.id)}" ${bank.id === selected ? "selected" : ""}>${escapeHtml(
          bank.title
        )}</option>`
    )
    .join("")}`;
}

function renderTable() {
  const student = currentStudent();
  if (!student) {
    if (isTeacherAccount()) renderList();
    return;
  }

  if (!Array.isArray(student.rows) || student.rows.length === 0) {
    student.rows = [emptyRow(), emptyRow(), emptyRow(), emptyRow(), emptyRow()];
  }

  state.view = "table";
  els.listView.classList.add("hidden");
  els.practiceView.classList.add("hidden");
  els.tableView.classList.remove("hidden");
  els.backBtn.classList.toggle("hidden", isStudentView());
  els.backBtn.textContent = "← К списку";
  els.tableActions.classList.toggle("hidden", isStudentView());
  els.addStudentBtn.classList.add("hidden");
  els.templateWrap.classList.toggle("hidden", !isTeacherUi());
  els.addRowBtn.classList.toggle("hidden", !isTeacherUi());
  els.pageTitle.textContent = student.name;
  els.pageSubtitle.textContent = isStudentView()
    ? "Нажмите на задания, чтобы вписать ответы. Тему, теорию и домашнее задание заполняет педагог."
    : "Одно занятие можно перенести, исправив дату в его строке. Остальные уроки не изменятся.";
  els.templateSelect.value = student.template === "twice" ? "twice" : "once";
  updateModeChrome();
  updateShareBar();

  const schedule = student.schedule || {};
  const slots = Array.isArray(schedule.slots) ? schedule.slots : [];
  const start = schedule.startDate || "2026-09-03";
  const twice = student.template === "twice";
  const scheduleHtml = isTeacherUi()
    ? `<div class="schedule-bar">
        <div class="schedule-head">
          <strong>Расписание</strong>
          <span class="hint">Чтобы перенести одно занятие, исправьте дату прямо в строке урока. Остальные даты не изменятся.</span>
        </div>
        <label>День ${weekdaySelect("table-weekday-0", slots[0] ? slots[0].weekday : 3)}</label>
        <label>Время <input id="table-time-0" type="time" value="${escapeHtml(
          (slots[0] && slots[0].time) || "16:00"
        )}" /></label>
        <span id="table-second-slot" class="${twice ? "" : "hidden"}">
          <label>Ещё день ${weekdaySelect("table-weekday-1", slots[1] ? slots[1].weekday : 1)}</label>
          <label>Время <input id="table-time-1" type="time" value="${escapeHtml(
            (slots[1] && slots[1].time) || "16:00"
          )}" /></label>
        </span>
        <input id="table-start" type="hidden" value="${escapeHtml(start)}" />
        <button id="save-schedule-btn" class="secondary-btn" type="button">Сохранить день и время</button>
      </div>`
    : "";

  const head = COLUMNS.map((column) => `<th class="${column.className}">${column.label}</th>`).join("");
  const body = student.rows
    .map((row, rowIndex) => {
      const cells = COLUMNS.map((column) => {
        if (column.key === "practice") {
          const fraction = row.bankId ? row.practice || "0/0" : "—";
          const teacherSelect = isTeacherUi()
            ? `<select data-row="${rowIndex}" data-role="bank">${bankOptions(row.bankId || "")}</select>`
            : "";
          const openBtn = row.bankId
            ? `<button class="practice-link" type="button" data-row="${rowIndex}" data-bank="${escapeHtml(
                row.bankId
              )}">${escapeHtml(fraction)}</button>`
            : `<span class="hint">выберите задания</span>`;
          return `<td class="col-practice practice-cell"><div class="practice-box">${teacherSelect}${
            isTeacherUi() || row.bankId ? openBtn : "—"
          }</div></td>`;
        }
        if (column.key === "progress") {
          if (!row.bankId) {
            return `<td class="col-progress progress-cell"></td>`;
          }
          const color = row.progressColor || "red";
          return `<td class="col-progress progress-cell"><div class="progress-swatch progress-${color}">${escapeHtml(
            row.progress || "0%"
          )}</div></td>`;
        }
        const value = row[column.key] ?? "";
        const locked = isStudentView();
        const readonly = locked ? "readonly" : "";
        const placeholder = column.key === "date" ? 'placeholder="например 10.09.2026, 17:00"' : "";
        return `<td class="${column.className}">
          <textarea data-row="${rowIndex}" data-key="${column.key}" rows="1" spellcheck="false" ${placeholder} ${readonly}>${escapeHtml(
            String(value)
          )}</textarea>
        </td>`;
      }).join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  els.tableView.innerHTML = `
    ${scheduleHtml}
    <div class="table-wrap">
      <table>
        <thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
  fitTableAreas();
}

async function openPractice(bankId) {
  const student = currentStudent();
  if (!student || !bankId) return;
  const asStudent = isStudentView() ? "&asStudent=1" : "";
  const data = await api(
    `/api/practice?studentId=${encodeURIComponent(student.id)}&bankId=${encodeURIComponent(bankId)}${asStudent}`
  );
  state.view = "practice";
  state.practice = data;
  els.listView.classList.add("hidden");
  els.tableView.classList.add("hidden");
  els.practiceView.classList.remove("hidden");
  els.tableActions.classList.add("hidden");
  els.addStudentBtn.classList.add("hidden");
  els.backBtn.classList.remove("hidden");
  els.backBtn.textContent = "← К таблице";
  els.pageTitle.textContent = data.title;
  els.pageSubtitle.textContent = isStudentView()
    ? `${student.name}. Впишите номера рядов и нажмите «Сохранить».`
    : student.name;
  updateModeChrome();
  updateShareBar();
  renderPractice();
}

function renderPractice() {
  const data = state.practice;
  if (!data) return;
  const stats = data.stats || { done: 0, total: 0, percent: 0, correct: 0 };
  const color = data.statsColor || "red";
  const tasks = (data.tasks || [])
    .map((task) => {
      const options = (task.options || [])
        .map((option, index) => `<li>${escapeHtml(option)}</li>`)
        .join("");
      const keyField = isTeacherUi()
        ? `<label>Ключ <input class="key-input" data-n="${task.n}" data-role="key" value="${escapeHtml(
            task.answer || ""
          )}" placeholder="например 245" /></label>`
        : "";
      return `
        <article class="task-card ${task.status || ""}" data-n="${task.n}">
          <h2>№ ${task.n}</h2>
          <p>${escapeHtml(task.prompt || data.instruction || "")}</p>
          <ol>${options}</ol>
          <div class="task-actions">
            <label>Ответ ученика
              <input data-n="${task.n}" data-role="given" value="${escapeHtml(task.given || "")}" placeholder="245 или 2, 4, 5" />
            </label>
            <button class="primary-btn save-answer" type="button" data-n="${task.n}">Сохранить</button>
            ${keyField}
            ${isTeacherUi() ? `<button class="secondary-btn save-key" type="button" data-n="${task.n}">Сохранить ключ</button>` : ""}
          </div>
        </article>
      `;
    })
    .join("");

  els.practiceView.innerHTML = `
    <div class="practice-stats progress-${color}">
      Выполнено ${stats.done} / ${stats.total} (${stats.percent}%).
      ${stats.correct ? `Верно: ${stats.correct}.` : ""}
      Запишите номера рядов без пробелов, как в ЕГЭ: например 245.
    </div>
    <div class="task-list">${tasks}</div>
  `;
}

function initial(name) {
  const trimmed = String(name || "").trim();
  return trimmed ? trimmed[0].toUpperCase() : "?";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function afterLogin() {
  showApp();
  startPolling();
  if (isTeacherAccount()) {
    renderList();
  } else {
    state.currentId = state.me.studentId || (state.students[0] && state.students[0].id);
    renderTable();
  }
}

els.addStudentBtn.addEventListener("click", openModal);
if (els.previewBtn) {
  els.previewBtn.addEventListener("click", () => {
    if (state.currentId) enterStudentPreview(state.currentId);
  });
}
if (els.exitPreviewBtn) {
  els.exitPreviewBtn.addEventListener("click", exitStudentPreview);
}
els.cancelModal.addEventListener("click", closeModal);
els.modal.addEventListener("click", (event) => {
  if (event.target === els.modal) closeModal();
});
els.studentForm.addEventListener("change", (event) => {
  if (event.target.name === "template") toggleSecondSlot();
});
els.startDate.addEventListener("change", () => {
  if (!els.startDate.value) return;
  const date = new Date(`${els.startDate.value}T12:00:00`);
  if (!Number.isNaN(date.getTime())) {
    els.weekday0.value = String((date.getDay() + 6) % 7);
  }
});
els.backBtn.addEventListener("click", () => {
  if (state.view === "practice") {
    loadStudents().then(renderTable).catch((error) => setSaveStatus(error.message));
    return;
  }
  renderList();
});
els.templateSelect.addEventListener("change", () => {
  const student = currentStudent();
  if (!student || !isTeacherUi()) return;
  student.template = els.templateSelect.value;
  const second = document.getElementById("table-second-slot");
  if (second) second.classList.toggle("hidden", student.template !== "twice");
  scheduleSave();
});
els.addRowBtn.addEventListener("click", () => {
  const student = currentStudent();
  if (!student || !isTeacherUi()) return;
  student.rows.push(emptyRow());
  scheduleSave();
  renderTable();
});

els.studentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!els.createdBox.classList.contains("hidden")) {
    closeModal();
    return;
  }
  els.modalError.textContent = "";
  const name = els.studentName.value.trim();
  const { template, slots, startDate } = collectCreateSlots();
  try {
    const data = await api("/api/students", {
      method: "POST",
      body: JSON.stringify({ name, template, startDate, slots }),
    });
    state.students.push(data.student);
    els.createFields.classList.add("hidden");
    els.createdBox.classList.remove("hidden");
    els.createSubmit.textContent = "Закрыть";
    renderList();
  } catch (error) {
    els.modalError.textContent = error.message;
  }
});

els.listView.addEventListener("click", async (event) => {
  const card = event.target.closest(".card");
  if (!card) return;
  const id = card.dataset.id;
  if (event.target.closest(".delete-student")) {
    const student = state.students.find((item) => item.id === id);
    const label = student ? student.name : "этого ученика";
    if (!confirm(`Удалить таблицу ученика «${label}»?`)) return;
    try {
      await api("/api/students/delete", { method: "POST", body: JSON.stringify({ id }) });
      state.students = state.students.filter((item) => item.id !== id);
      renderList();
    } catch (error) {
      alert(error.message);
    }
    return;
  }
  if (event.target.closest(".preview-student")) {
    enterStudentPreview(id);
    return;
  }
  if (event.target.closest(".open-table")) {
    state.previewAsStudent = false;
    state.currentId = id;
    renderTable();
  }
});

els.tableView.addEventListener("input", (event) => {
  const area = event.target.closest("textarea");
  if (!area || area.readOnly) return;
  area.style.height = "auto";
  area.style.height = `${Math.max(88, area.scrollHeight)}px`;
  const student = currentStudent();
  if (!student) return;
  const row = student.rows[Number(area.dataset.row)];
  if (!row) return;
  row[area.dataset.key] = area.value;
  scheduleSave();
});

els.tableView.addEventListener("change", (event) => {
  const select = event.target.closest("select[data-role='bank']");
  if (!select || !isTeacherUi()) return;
  const student = currentStudent();
  if (!student) return;
  const row = student.rows[Number(select.dataset.row)];
  if (!row) return;
  row.bankId = select.value;
  persistCurrent()
    .then(() => renderTable())
    .catch((error) => setSaveStatus(error.message));
});

els.tableView.addEventListener("click", async (event) => {
  if (!event.target.closest("textarea, input, select, button, a, label")) {
    const cell = event.target.closest("td");
    const area = cell && cell.querySelector("textarea:not([readonly])");
    if (area) {
      area.focus();
      return;
    }
  }
  if (event.target.id === "save-schedule-btn") {
    const student = currentStudent();
    if (!student) return;
    const template = els.templateSelect.value === "twice" ? "twice" : "once";
    const slots = [
      {
        weekday: Number(document.getElementById("table-weekday-0").value),
        time: document.getElementById("table-time-0").value || "16:00",
      },
    ];
    if (template === "twice") {
      slots.push({
        weekday: Number(document.getElementById("table-weekday-1").value),
        time: document.getElementById("table-time-1").value || "16:00",
      });
    }
    try {
      setSaveStatus("Сохраняю расписание…");
      const data = await api("/api/schedule", {
        method: "POST",
        body: JSON.stringify({
          id: student.id,
          template,
          startDate: document.getElementById("table-start").value,
          slots,
          regenerate: false,
        }),
      });
      const index = state.students.findIndex((item) => item.id === student.id);
      if (index >= 0) state.students[index] = data.student;
      setSaveStatus("День и время сохранены");
      renderTable();
    } catch (error) {
      setSaveStatus(error.message);
      alert(error.message);
    }
    return;
  }
  const link = event.target.closest(".practice-link");
  if (link) {
    openPractice(link.dataset.bank).catch((error) => alert(error.message));
  }
});

els.practiceView.addEventListener("click", async (event) => {
  const student = currentStudent();
  const practice = state.practice;
  if (!student || !practice) return;
  const n = Number(event.target.dataset.n);
  if (event.target.closest(".save-answer")) {
    const input = els.practiceView.querySelector(`input[data-role='given'][data-n='${n}']`);
    try {
      const data = await api("/api/progress", {
        method: "POST",
        body: JSON.stringify({
          studentId: student.id,
          bankId: practice.id,
          n,
          answer: input ? input.value : "",
        }),
      });
      await openPractice(practice.id);
      setSaveStatus(`Сохранено, ${data.stats.done}/${data.stats.total}`);
    } catch (error) {
      alert(error.message);
    }
    return;
  }
  if (event.target.closest(".save-key")) {
    if (!isTeacherUi()) return;
    const input = els.practiceView.querySelector(`input[data-role='key'][data-n='${n}']`);
    try {
      await api("/api/bank-key", {
        method: "POST",
        body: JSON.stringify({
          bankId: practice.id,
          n,
          answer: input ? input.value : "",
        }),
      });
      await openPractice(practice.id);
      setSaveStatus("Ключ сохранён");
    } catch (error) {
      alert(error.message);
    }
  }
});

els.copyLinkBtn.addEventListener("click", async () => {
  const text = state.publicUrl;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    els.copyLinkBtn.textContent = "Скопировано";
    setTimeout(() => {
      els.copyLinkBtn.textContent = "Копировать интернет-ссылку";
    }, 1500);
  } catch (_error) {
    prompt("Скопируйте ссылку:", text);
  }
});

if (els.copyLanBtn) {
  els.copyLanBtn.addEventListener("click", async () => {
    const text = (state.lanUrls && state.lanUrls[0]) || state.lanUrl;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      els.copyLanBtn.textContent = "Скопировано";
      setTimeout(() => {
        els.copyLanBtn.textContent = "Копировать ссылку для телефона (Wi‑Fi)";
      }, 1500);
    } catch (_error) {
      prompt("Скопируйте ссылку. Должно быть http, не https:", text);
    }
  });
}

function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      await loadSession();
    } catch (_error) {
      /* окно запуска могли закрыть */
    }
  }, 3000);
}

async function start() {
  try {
    const session = await loadSession();
    state.me = session.user || { role: "teacher", name: "Учитель" };
    await loadStudents();
    await loadBanks();
    afterLogin();
  } catch (error) {
    els.listView.innerHTML = `
      <div class="empty-state">
        <p>Не получилось открыть журнал.</p>
        <p>Запустите файл «запустить.bat».</p>
      </div>
    `;
    setSaveStatus(error.message);
  }
}

start();
