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
  pdfImport: false,
  view: "list",
  practice: null,
  previewAsStudent: false,
  settingsStudentId: null,
  pendingDeleteRow: null,
  localTeacher: false,
  pendingNewStudent: false,
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
  rowConfirm: document.getElementById("row-confirm"),
  rowConfirmYes: document.getElementById("row-confirm-yes"),
  rowConfirmNo: document.getElementById("row-confirm-no"),
  tableActions: document.getElementById("table-actions"),
  templateWrap: document.getElementById("template-wrap"),
  templateSelect: document.getElementById("template-select"),
  addRowBtn: document.getElementById("add-row-btn"),
  settingsBtn: document.getElementById("settings-btn"),
  modalTitle: document.getElementById("modal-title"),
  saveStatus: document.getElementById("save-status"),
  shareBar: document.getElementById("share-bar"),
  shareUrl: document.getElementById("share-url"),
  shareHint: document.getElementById("share-hint"),
  copyLinkBtn: document.getElementById("copy-link-btn"),
  logoutBtn: document.getElementById("logout-btn"),
  loginScreen: document.getElementById("login-screen"),
  loginForm: document.getElementById("login-form"),
  loginName: document.getElementById("login-name"),
  loginPassword: document.getElementById("login-password"),
  loginError: document.getElementById("login-error"),
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
  createdLead: document.getElementById("created-lead"),
  createdCreds: document.getElementById("created-creds"),
  copyCredsBtn: document.getElementById("copy-creds-btn"),
  accessFields: document.getElementById("access-fields"),
  settingsLogin: document.getElementById("settings-login"),
  resetPasswordBtn: document.getElementById("reset-password-btn"),
  createSubmit: document.getElementById("create-submit"),
  modalError: document.getElementById("modal-error"),
};

let saveTimer = null;
let pollTimer = null;
let saveChain = Promise.resolve();

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
    theoryFileId: "",
    theoryFileName: "",
    homeworkFileId: "",
    homeworkFileName: "",
    practiceFileId: "",
    practiceFileName: "",
    importedSource: "",
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

function hideRowConfirm() {
  state.pendingDeleteRow = null;
  if (els.rowConfirm) els.rowConfirm.classList.add("hidden");
}

function showRowConfirm(rowIndex) {
  if (!els.rowConfirm) return;
  state.pendingDeleteRow = rowIndex;
  els.rowConfirm.classList.remove("hidden");
  if (els.rowConfirmNo) els.rowConfirmNo.focus();
}

function insertLessonAt(index) {
  const student = currentStudent();
  if (!student || !isTeacherUi()) return;
  hideRowConfirm();
  const at = Math.max(0, Math.min(Number(index) || 0, student.rows.length));
  student.rows.splice(at, 0, emptyRow());
  scheduleSave();
  renderTable();
  const dateArea = els.tableView.querySelector(`textarea[data-row='${at}'][data-key='date']`);
  if (dateArea) dateArea.focus();
}

async function deleteLessonAt(index) {
  const student = currentStudent();
  if (!student || !isTeacherUi()) return;
  const row = student.rows[index];
  if (!row) return;
  hideRowConfirm();
  for (const field of ["theory", "homework", "practice"]) {
    if (!row[`${field}FileId`]) continue;
    try {
      const data = await api("/api/file/delete", {
        method: "POST",
        body: JSON.stringify({ studentId: student.id, row: index, field }),
      });
      replaceStudent(data.student);
    } catch (_error) {
      /* строку всё равно убираем */
    }
  }
  const fresh = currentStudent();
  if (!fresh) return;
  fresh.rows.splice(index, 1);
  if (!fresh.rows.length) fresh.rows.push(emptyRow());
  setSaveStatus("Строка удалена");
  await persistCurrent();
  renderTable();
}

function enterStudentPreview(studentId) {
  if (!isTeacherAccount() || !studentId) return;
  hideRowConfirm();
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
  let response;
  try {
    response = await fetch(path, {
      cache: "no-store",
      credentials: "same-origin",
      ...options,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        ...(options.headers || {}),
      },
    });
  } catch (error) {
    throw friendlyNetworkError(error);
  }
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

function friendlyNetworkError(error) {
  const message = String((error && error.message) || error || "");
  if (/failed to fetch|networkerror|load failed|network request failed/i.test(message)) {
    return new Error(
      "Журнал не отвечает. Закройте все чёрные окна запуска, откройте «запустить.bat» и обновите страницу."
    );
  }
  return error instanceof Error ? error : new Error(message);
}

async function loadSession() {
  const data = await api("/api/session");
  state.me = data.user;
  state.localTeacher = Boolean(data.localTeacher);
  state.publicUrl = data.publicUrl || "";
  state.lanUrl = data.lanUrl || "";
  state.lanUrls = Array.isArray(data.lanUrls) && data.lanUrls.length ? data.lanUrls : data.lanUrl ? [data.lanUrl] : [];
  state.wifiName = data.wifiName || "";
  state.tunnelError = data.tunnelError || "";
  state.pdfImport = Boolean(data.pdfImport);
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
  if (state.publicUrl) {
    els.shareUrl.textContent = state.publicUrl;
    els.shareHint.textContent = "Эту ссылку можно открыть с телефона из любой сети. Вводите http://, не https://.";
  } else if (state.tunnelError) {
    els.shareUrl.textContent = state.tunnelError;
    els.shareHint.textContent = "Интернет-ссылка пока не готова. Не закрывайте окно запуска и обновите страницу через минуту.";
  } else {
    els.shareUrl.textContent = "Готовится… подождите 10–20 секунд, окно запуска не закрывайте";
    els.shareHint.textContent = "Сначала появится интернет-ссылка. Вводите http://, не https://.";
  }
}

function showApp() {
  if (els.loginScreen) els.loginScreen.classList.add("hidden");
  els.app.classList.remove("hidden");
  els.addStudentBtn.classList.toggle("hidden", !isTeacherUi());
  if (els.logoutBtn) els.logoutBtn.classList.toggle("hidden", state.localTeacher);
  updateModeChrome();
  updateShareBar();
}

function showLoginScreen() {
  if (els.app) els.app.classList.add("hidden");
  if (els.loginScreen) els.loginScreen.classList.remove("hidden");
  if (els.loginError) els.loginError.textContent = "";
  if (els.loginPassword) els.loginPassword.value = "";
  if (els.loginName) els.loginName.focus();
}

function accessMessage(name, login, password) {
  const lines = [`Журнал русского языка — кабинет ученика${name ? ` (${name})` : ""}`];
  if (state.publicUrl) {
    lines.push(`Ссылка: ${state.publicUrl}`);
  }
  lines.push(`Логин: ${login}`, `Пароль: ${password}`, "");
  lines.push(
    state.publicUrl
      ? "Откройте ссылку, введите логин и пароль — откроется только ваша таблица."
      : "Введите логин и пароль на странице входа — откроется только ваша таблица."
  );
  return lines.join("\n");
}

function showCreatedAccess(name, login, password, lead) {
  const text = accessMessage(name, login, password);
  if (els.createdLead) els.createdLead.textContent = lead;
  if (els.createdCreds) els.createdCreds.textContent = text;
  els.createdBox.classList.remove("hidden");
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
  const run = async () => {
    const student = currentStudent();
    if (!student || !isTeacherUi()) return;
    setSaveStatus("Сохранение…");
    await api("/api/table", {
      method: "POST",
      body: JSON.stringify({
        id: student.id,
        rows: student.rows,
        template: student.template,
      }),
    });
    setSaveStatus("Сохранено");
  };
  saveChain = saveChain.then(run, run);
  return saveChain;
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    persistCurrent()
      .then(() => importHomeworkPdfs(currentStudent()))
      .then((changed) => {
        if (changed && state.view === "table") renderTable();
      })
      .catch((error) => setSaveStatus(friendlyNetworkError(error).message));
  }, 1200);
}

function toggleSecondSlot() {
  const twice = els.studentForm.template.value === "twice";
  els.secondSlot.classList.toggle("hidden", !twice);
}

function fillStudentForm(student) {
  const schedule = (student && student.schedule) || {};
  const slots = Array.isArray(schedule.slots) ? schedule.slots : [];
  els.studentName.value = student ? student.name : "";
  els.studentForm.template.value = student && student.template === "twice" ? "twice" : "once";
  els.startDate.value = schedule.startDate || "2026-09-03";
  els.weekday0.value = String(slots[0] ? slots[0].weekday : 3);
  els.time0.value = (slots[0] && slots[0].time) || "16:00";
  els.weekday1.value = String(slots[1] ? slots[1].weekday : 1);
  els.time1.value = (slots[1] && slots[1].time) || "16:00";
  toggleSecondSlot();
}

function openModal() {
  state.settingsStudentId = null;
  state.pendingNewStudent = false;
  if (els.modalTitle) els.modalTitle.textContent = "Новый ученик";
  els.modal.classList.remove("hidden");
  els.createFields.classList.remove("hidden");
  if (els.accessFields) els.accessFields.classList.add("hidden");
  els.createdBox.classList.add("hidden");
  els.createSubmit.classList.remove("hidden");
  els.createSubmit.textContent = "Создать таблицу";
  els.cancelModal.textContent = "Отмена";
  els.modalError.textContent = "";
  els.studentForm.reset();
  fillStudentForm(null);
  els.studentName.focus();
}

function openSettings(studentId) {
  const student = state.students.find((item) => item.id === studentId) || currentStudent();
  if (!student || !isTeacherUi()) return;
  state.settingsStudentId = student.id;
  state.pendingNewStudent = false;
  if (els.modalTitle) els.modalTitle.textContent = "Настройки ученика";
  els.modal.classList.remove("hidden");
  els.createFields.classList.remove("hidden");
  if (els.accessFields) els.accessFields.classList.remove("hidden");
  if (els.settingsLogin) els.settingsLogin.textContent = student.login || "ещё не задан";
  els.createdBox.classList.add("hidden");
  els.createSubmit.classList.remove("hidden");
  els.createSubmit.textContent = "Сохранить";
  els.cancelModal.textContent = "Отмена";
  els.modalError.textContent = "";
  fillStudentForm(student);
  els.studentName.focus();
}

function closeModal(goToTable) {
  const pending = state.pendingNewStudent;
  const id = state.currentId;
  els.modal.classList.add("hidden");
  state.settingsStudentId = null;
  state.pendingNewStudent = false;
  els.cancelModal.textContent = "Отмена";
  if (!pending || !id) return;
  if (goToTable) {
    renderTable();
    return;
  }
  renderList();
}

function renderList() {
  hideRowConfirm();
  state.view = "list";
  state.currentId = null;
  state.previewAsStudent = false;
  els.listView.classList.remove("hidden");
  els.tableView.classList.add("hidden");
  els.practiceView.classList.add("hidden");
  els.backBtn.classList.add("hidden");
  els.tableActions.classList.add("hidden");
  if (els.settingsBtn) els.settingsBtn.classList.add("hidden");
  if (isTeacherUi()) els.addStudentBtn.classList.remove("hidden");
  els.pageTitle.textContent = "Журнал занятий";
  els.pageSubtitle.textContent = "Русский язык · 10–11 классы · Подготовка к экзаменам и уроки";
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

  els.listView.innerHTML = `
    <div class="cards">${state.students
      .map(
        (student) => `
        <article class="card" data-id="${student.id}">
          <div class="card-top">
            <div class="avatar">${escapeHtml(initial(student.name))}</div>
            <div>
              <h2>${escapeHtml(student.name)}</h2>
              <span class="badge">${TEMPLATE_LABELS[student.template] || TEMPLATE_LABELS.once}</span>
              ${student.login ? `<p class="card-login">логин: ${escapeHtml(student.login)}</p>` : ""}
            </div>
          </div>
          <div class="card-actions">
            <button class="primary-btn open-table" type="button">Открыть таблицу</button>
            <button class="secondary-btn preview-student" type="button">Как видит ученик</button>
            <button class="secondary-btn open-settings" type="button">Настройки</button>
            <button class="danger-btn delete-student" type="button">Удалить</button>
          </div>
        </article>
      `
      )
      .join("")}</div>`;
}

function bankOptions(selected) {
  const items = state.banks.length ? state.banks.slice() : [{ id: "ege-10", title: "Задание 10 ЕГЭ" }];
  if (selected && !items.some((bank) => bank.id === selected)) {
    const student = currentStudent();
    const row = student && (student.rows || []).find((item) => item.bankId === selected);
    items.push({ id: selected, title: (row && row.bankTitle) || "Задания из PDF" });
  }
  return `<option value="">— нет —</option>${items
    .map((bank) => {
      const extra = bank.total ? ` · ${bank.total}` : "";
      const label = bank.id === "ege-10" ? bank.title : `${bank.title}${extra}`;
      return `<option value="${escapeHtml(bank.id)}" ${bank.id === selected ? "selected" : ""}>${escapeHtml(
        label
      )}</option>`;
    })
    .join("")}`;
}

function rowHasLessonContent(row) {
  if (!row || typeof row !== "object") return false;
  if (["topic", "theory", "homework", "comment"].some((key) => String(row[key] || "").trim())) {
    return true;
  }
  if (String(row.bankId || "").trim()) return true;
  if (String(row.theoryFileId || "").trim()) return true;
  if (String(row.homeworkFileId || "").trim()) return true;
  return false;
}

function visibleRowIndexes(student) {
  const rows = Array.isArray(student.rows) ? student.rows : [];
  if (!isStudentView()) {
    return rows.map((_, index) => index);
  }
  const filled = [];
  rows.forEach((row, index) => {
    if (rowHasLessonContent(row)) filled.push(index);
  });
  if (!filled.length) return [];
  const next = filled[filled.length - 1] + 1;
  if (next < rows.length && !filled.includes(next)) {
    filled.push(next);
  }
  return filled;
}

function renderTable() {
  const student = currentStudent();
  if (!student) {
    if (isTeacherAccount()) renderList();
    return;
  }
  if (!isTeacherUi()) hideRowConfirm();

  if (!Array.isArray(student.rows)) {
    student.rows = [];
  }
  if (student.rows.length === 0 && isTeacherUi()) {
    student.rows = [emptyRow()];
  }

  state.view = "table";
  els.listView.classList.add("hidden");
  els.practiceView.classList.add("hidden");
  els.tableView.classList.remove("hidden");
  els.backBtn.classList.toggle("hidden", isStudentView());
  els.backBtn.textContent = "← К списку";
  els.tableActions.classList.toggle("hidden", isStudentView());
  els.addStudentBtn.classList.add("hidden");
  els.templateWrap.classList.add("hidden");
  els.addRowBtn.classList.toggle("hidden", !isTeacherUi());
  if (els.settingsBtn) {
    els.settingsBtn.classList.toggle("hidden", !isTeacherUi());
  }
  els.pageTitle.textContent = student.name;
  els.pageSubtitle.textContent = isStudentView()
    ? "Заполненные уроки и дата следующего занятия."
    : "Между уроками нажмите «+». Крестик удаляет строку. В конец таблицы — отдельная кнопка.";
  updateModeChrome();
  updateShareBar();

  const rowIndexes = visibleRowIndexes(student);
  if (isStudentView() && rowIndexes.length === 0) {
    els.tableView.innerHTML = `
      <div class="empty-state">
        <p>Педагог ещё не заполнил занятия.</p>
        <p>Когда появятся тема, материалы или домашнее задание, урок откроется здесь. Следом будет видна дата следующего занятия.</p>
      </div>
    `;
    return;
  }

  const toolsHead = isTeacherUi() ? `<th class="col-row-tools"></th>` : "";
  const colCount = COLUMNS.length + (isTeacherUi() ? 1 : 0);
  const insertGap = (index) =>
    isTeacherUi()
      ? `<tr class="insert-gap"><td colspan="${colCount}">
          <button class="insert-lesson" type="button" data-insert="${index}" title="Вставить урок между этими строками">+</button>
        </td></tr>`
      : "";
  const head = `${toolsHead}${COLUMNS.map((column) => `<th class="${column.className}">${column.label}</th>`).join("")}`;
  const renderLessonRow = (rowIndex) => {
      const row = student.rows[rowIndex];
      const upcoming = isStudentView() && !rowHasLessonContent(row);
      const cells = COLUMNS.map((column) => {
        if (column.key === "practice") {
          const fraction = row.bankId ? row.practice || "0/0" : "—";
          const teacherSelect = isTeacherUi()
            ? `<select data-row="${rowIndex}" data-role="bank">${bankOptions(row.bankId || "")}</select>`
            : "";
          const attach = isTeacherUi()
            ? `<label class="file-corner" title="Загрузить PDF с заданиями">
                <span class="file-corner-mark" aria-hidden="true">+</span>
                <input type="file" class="visually-hidden" accept="application/pdf,.pdf" data-row="${rowIndex}" data-field="practice" />
              </label>`
            : "";
          const openBtn = row.bankId
            ? `<button class="practice-link" type="button" data-row="${rowIndex}" data-bank="${escapeHtml(
                row.bankId
              )}">${escapeHtml(fraction)}</button>`
            : `<span class="hint">${isTeacherUi() ? "PDF или набор" : "пока нет заданий"}</span>`;
          return `<td class="col-practice practice-cell" data-label="${escapeHtml(column.label)}"><div class="practice-box">${attach}${teacherSelect}${
            isTeacherUi() || row.bankId ? openBtn : "—"
          }</div></td>`;
        }
        if (column.key === "progress") {
          if (!row.bankId) {
            return `<td class="col-progress progress-cell" data-label="${escapeHtml(column.label)}"></td>`;
          }
          const color = row.progressColor || "red";
          return `<td class="col-progress progress-cell" data-label="${escapeHtml(column.label)}"><div class="progress-swatch progress-${color}">${escapeHtml(
            row.progress || "0%"
          )}</div></td>`;
        }
        if (column.key === "theory" || column.key === "homework") {
          return renderMaterialCell(row, rowIndex, column);
        }
        const value = row[column.key] ?? "";
        const locked = isStudentView();
        const readonly = locked ? "readonly" : "";
        const placeholder = column.key === "date" ? 'placeholder="например 10.09.2026, 17:00"' : "";
        return `<td class="${column.className}" data-label="${escapeHtml(column.label)}">
          <textarea class="cell-fill" data-row="${rowIndex}" data-key="${column.key}" rows="1" spellcheck="false" ${placeholder} ${readonly}>${escapeHtml(
            String(value)
          )}</textarea>
        </td>`;
      }).join("");
      const tools = isTeacherUi()
        ? `<td class="col-row-tools" data-label="Урок">
            <button class="row-delete" type="button" data-row="${rowIndex}" title="Удалить этот урок">×</button>
          </td>`
        : "";
      const rowClass = upcoming ? ' class="lesson-upcoming"' : "";
      return `${tools ? `<tr${rowClass}>${tools}${cells}</tr>` : `<tr${rowClass}>${cells}</tr>`}${
        isTeacherUi() ? insertGap(rowIndex + 1) : ""
      }`;
  };
  const body = isTeacherUi()
    ? insertGap(0) + rowIndexes.map(renderLessonRow).join("")
    : rowIndexes.map(renderLessonRow).join("");

  els.tableView.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

async function openPractice(bankId) {
  const student = currentStudent();
  if (!student || !bankId) return;
  hideRowConfirm();
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
  if (els.settingsBtn) els.settingsBtn.classList.add("hidden");
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
      const optionItems = (task.options || []).filter(Boolean);
      const options = optionItems.length
        ? `<ol class="task-options">${optionItems.map((option) => `<li>${escapeHtml(option)}</li>`).join("")}</ol>`
        : "";
      const keyField = isTeacherUi()
        ? `<label class="task-field-label">Ключ <input class="key-input" data-n="${task.n}" data-role="key" value="${escapeHtml(
            task.answer || ""
          )}" placeholder="например 245" /></label>`
        : "";
      return `
        <article class="task-card ${task.status || ""}" data-n="${task.n}">
          <div class="task-card-top">
            <span class="task-badge">№ ${task.n}</span>
            <span class="task-tag">Задание ЕГЭ</span>
          </div>
          <p class="task-prompt">${escapeHtml(task.prompt || data.instruction || "")}</p>
          ${options}
          <div class="task-actions">
            <label class="task-field-label">Ответ ученика
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
      <div class="stats-text">
        <strong>Выполнено:</strong> ${stats.done} из ${stats.total} (${stats.percent}%).
        ${stats.correct ? ` · <strong>Верно:</strong> ${stats.correct}.` : ""}
      </div>
      <div class="stats-hint">Запишите номера рядов без пробелов, как в бланке ЕГЭ: например 245.</div>
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

function linkifyText(text) {
  const raw = String(text || "");
  if (!raw.trim()) {
    return "";
  }
  return raw.split(/(https?:\/\/[^\s]+)/g).map((part, index) => {
    if (index % 2 === 1) {
      const href = part.replaceAll('"', "%22");
      return `<a href="${href}" target="_blank" rel="noopener noreferrer">${escapeHtml(part)}</a>`;
    }
    return escapeHtml(part).replaceAll("\n", "<br>");
  }).join("");
}

function fileUrl(id, name) {
  return `/api/file?id=${encodeURIComponent(id)}&name=${encodeURIComponent(name || id)}`;
}

function firstPdfUrl(text) {
  const matches = String(text || "").match(/https?:\/\/[^\s<>"]+/gi) || [];
  return matches.map((item) => item.replace(/[),.;]+$/g, "")).find((item) => isPdfUrl(item)) || "";
}

function isPdfUrl(url) {
  const raw = String(url || "").trim();
  const lowered = raw.toLowerCase();
  if (lowered.endsWith(".pdf")) return true;
  if (/drive\.google\.com\/file\/d\/[a-zA-Z0-9_-]{20,}/i.test(raw)) return true;
  if (lowered.includes("drive.google.com") && lowered.includes("id=")) return true;
  if (lowered.includes("dropbox.com") && (lowered.endsWith(".pdf") || lowered.includes("dl="))) return true;
  return false;
}

const importFailed = new Set();
let importInFlight = false;

async function importHomeworkPdfs(student) {
  if (!student || !isTeacherUi() || !state.pdfImport || importInFlight) return false;
  let changed = false;
  for (let index = 0; index < (student.rows || []).length; index += 1) {
    const row = student.rows[index];
    const url = firstPdfUrl(row.homework);
    if (!url || url === row.importedSource) continue;
    if (String(row.importedSource || "").startsWith("manual:")) continue;
    const key = `${student.id}:${index}:${url}`;
    if (importFailed.has(key)) continue;
    importInFlight = true;
    setSaveStatus("Разбираю PDF…");
    try {
      const data = await api("/api/import-pdf", {
        method: "POST",
        body: JSON.stringify({ studentId: student.id, row: index, url }),
      });
      replaceStudent(data.student);
      await loadBanks();
      changed = true;
      setSaveStatus(data.total ? `Готово: ${data.total} заданий из PDF` : "Задания из PDF готовы");
    } catch (error) {
      importFailed.add(key);
      setSaveStatus(error.message);
    } finally {
      importInFlight = false;
    }
  }
  return changed;
}

function renderMaterialCell(row, rowIndex, column) {
  const field = column.key;
  const value = String(row[field] ?? "");
  const fileId = row[`${field}FileId`] || "";
  const fileName = row[`${field}FileName`] || "";
  const fileLink = fileId
    ? `<a class="file-open" href="${escapeHtml(fileUrl(fileId, fileName || fileId))}" target="_blank" rel="noopener noreferrer">${escapeHtml(
        fileName || "открыть"
      )}</a>`
    : "";
  if (isStudentView()) {
    const text = linkifyText(value);
    const body = text || fileLink ? `${text ? `<div class="material-text">${text}</div>` : ""}${fileLink}` : "—";
    return `<td class="${column.className}" data-label="${escapeHtml(column.label)}"><div class="material-cell student-material">${body}</div></td>`;
  }
  const placeholder =
    field === "theory"
      ? 'placeholder="заметка или ссылка на документ"'
      : 'placeholder="домашнее задание, ссылка на PDF или файл"';
  const attach = `<label class="file-corner" title="Прикрепить документ">
      <span class="file-corner-mark" aria-hidden="true">+</span>
      <input type="file" class="visually-hidden" data-row="${rowIndex}" data-field="${field}" />
    </label>`;
  const remove = fileId
    ? `<button class="file-remove" type="button" data-row="${rowIndex}" data-field="${field}">Убрать</button>`
    : "";
  const tools = fileId ? `<div class="material-tools">${fileLink}${remove}</div>` : "";
  return `<td class="${column.className}" data-label="${escapeHtml(column.label)}">
    <div class="material-cell">
      <textarea class="cell-fill" data-row="${rowIndex}" data-key="${field}" rows="1" spellcheck="false" ${placeholder}>${escapeHtml(value)}</textarea>
      ${attach}
      ${tools}
    </div>
  </td>`;
}

function replaceStudent(student) {
  if (!student || !student.id) return;
  const index = state.students.findIndex((item) => item.id === student.id);
  if (index >= 0) state.students[index] = student;
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
if (els.settingsBtn) {
  els.settingsBtn.addEventListener("click", () => {
    if (state.currentId) openSettings(state.currentId);
  });
}
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
  hideRowConfirm();
  student.rows.push(emptyRow());
  scheduleSave();
  renderTable();
});
if (els.rowConfirmYes) {
  els.rowConfirmYes.addEventListener("click", () => {
    const index = state.pendingDeleteRow;
    if (index == null) {
      hideRowConfirm();
      return;
    }
    deleteLessonAt(index).catch((error) => {
      setSaveStatus(error.message);
      alert(error.message);
    });
  });
}
if (els.rowConfirmNo) {
  els.rowConfirmNo.addEventListener("click", hideRowConfirm);
}
if (els.rowConfirm) {
  els.rowConfirm.addEventListener("click", (event) => {
    if (event.target === els.rowConfirm) hideRowConfirm();
  });
}

els.studentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!els.createdBox.classList.contains("hidden") && state.pendingNewStudent) {
    closeModal(true);
    return;
  }
  els.modalError.textContent = "";
  const name = els.studentName.value.trim();
  if (!name) {
    els.modalError.textContent = "Нужно имя ученика";
    return;
  }
  const { template, slots, startDate } = collectCreateSlots();
  try {
    if (state.settingsStudentId) {
      const data = await api("/api/schedule", {
        method: "POST",
        body: JSON.stringify({
          id: state.settingsStudentId,
          name,
          template,
          startDate,
          slots,
          regenerate: true,
        }),
      });
      replaceStudent(data.student);
      state.currentId = data.student.id;
      closeModal();
      setSaveStatus("Настройки сохранены");
      renderTable();
      return;
    }
    const data = await api("/api/students", {
      method: "POST",
      body: JSON.stringify({ name, template, startDate, slots }),
    });
    state.students.push(data.student);
    state.currentId = data.student.id;
    state.pendingNewStudent = true;
    els.createFields.classList.add("hidden");
    els.createSubmit.textContent = "Открыть таблицу";
    els.cancelModal.textContent = "К списку";
    showCreatedAccess(
      data.student.name,
      data.login || data.student.login,
      data.password,
      "Сохраните эти данные и отправьте ученику. Пароль больше не покажется."
    );
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
  if (event.target.closest(".open-settings")) {
    openSettings(id);
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
  const student = currentStudent();
  if (!student) return;
  const row = student.rows[Number(area.dataset.row)];
  if (!row) return;
  row[area.dataset.key] = area.value;
  scheduleSave();
});

els.tableView.addEventListener("change", (event) => {
  const fileInput = event.target.closest("input[type='file'][data-field]");
  if (fileInput) {
    const file = fileInput.files && fileInput.files[0];
    fileInput.value = "";
    if (!file || !isTeacherUi()) return;
    const student = currentStudent();
    if (!student) return;
    const body = new FormData();
    body.append("studentId", student.id);
    body.append("row", fileInput.dataset.row);
    body.append("field", fileInput.dataset.field);
    body.append("file", file);
    setSaveStatus("Загружаю файл…");
    persistCurrent()
      .then(() =>
        fetch("/api/upload", { method: "POST", body, credentials: "same-origin", cache: "no-store" })
      )
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "Не удалось загрузить файл");
        replaceStudent(data.student);
        await loadBanks();
        renderTable();
        if (data.importError) {
          setSaveStatus(data.importError);
          alert(data.importError);
        } else if (data.total) {
          setSaveStatus(`Готово: ${data.total} заданий из PDF`);
        } else {
          setSaveStatus("Файл прикреплён");
        }
      })
      .catch((error) => {
        const friendly = friendlyNetworkError(error);
        setSaveStatus(friendly.message);
        alert(friendly.message);
      });
    return;
  }
  const select = event.target.closest("select[data-role='bank']");
  if (!select || !isTeacherUi()) return;
  const student = currentStudent();
  if (!student) return;
  const row = student.rows[Number(select.dataset.row)];
  if (!row) return;
  row.bankId = select.value;
  row.importedSource = select.value ? `manual:${select.value}` : "";
  persistCurrent()
    .then(() => renderTable())
    .catch((error) => setSaveStatus(error.message));
});

els.tableView.addEventListener("click", async (event) => {
  const insertBtn = event.target.closest(".insert-lesson");
  if (insertBtn) {
    insertLessonAt(Number(insertBtn.dataset.insert));
    return;
  }
  const deleteBtn = event.target.closest(".row-delete");
  if (deleteBtn) {
    showRowConfirm(Number(deleteBtn.dataset.row));
    return;
  }
  if (!event.target.closest("textarea, input, select, button, a, label")) {
    const cell = event.target.closest("td");
    const area = cell && cell.querySelector("textarea:not([readonly])");
    if (area) {
      area.focus();
      return;
    }
  }
  const remove = event.target.closest(".file-remove");
  if (remove) {
    const student = currentStudent();
    if (!student || !isTeacherUi()) return;
    api("/api/file/delete", {
      method: "POST",
      body: JSON.stringify({
        studentId: student.id,
        row: Number(remove.dataset.row),
        field: remove.dataset.field,
      }),
    })
      .then((data) => {
        replaceStudent(data.student);
        renderTable();
        setSaveStatus("Файл убран");
      })
      .catch((error) => {
        setSaveStatus(error.message);
        alert(error.message);
      });
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

if (els.copyCredsBtn) {
  els.copyCredsBtn.addEventListener("click", async () => {
    const text = els.createdCreds ? els.createdCreds.textContent : "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      els.copyCredsBtn.textContent = "Скопировано";
      setTimeout(() => {
        els.copyCredsBtn.textContent = "Скопировать для отправки";
      }, 1500);
    } catch (_error) {
      prompt("Скопируйте сообщение ученику:", text);
    }
  });
}

if (els.resetPasswordBtn) {
  els.resetPasswordBtn.addEventListener("click", async () => {
    const studentId = state.settingsStudentId;
    if (!studentId) return;
    els.modalError.textContent = "";
    try {
      const data = await api("/api/students/password", {
        method: "POST",
        body: JSON.stringify({ id: studentId, reset: true }),
      });
      const student = state.students.find((item) => item.id === studentId);
      showCreatedAccess(
        student ? student.name : "",
        data.login,
        data.password,
        "Новый пароль. Старый больше не работает. Отправьте ученику это сообщение."
      );
    } catch (error) {
      els.modalError.textContent = error.message;
    }
  });
}

if (els.loginForm) {
  els.loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (els.loginError) els.loginError.textContent = "";
    try {
      const data = await api("/api/login", {
        method: "POST",
        body: JSON.stringify({
          login: els.loginName.value.trim(),
          password: els.loginPassword.value,
        }),
      });
      state.me = data.user;
      state.localTeacher = Boolean(data.localTeacher);
      state.publicUrl = data.publicUrl || state.publicUrl;
      await enterApp();
    } catch (error) {
      if (els.loginError) els.loginError.textContent = error.message;
    }
  });
}

if (els.logoutBtn) {
  els.logoutBtn.addEventListener("click", async () => {
    try {
      await api("/api/logout", { method: "POST", body: "{}" });
    } catch (_error) {
      /* всё равно выходим на экран входа */
    }
    state.me = null;
    state.students = [];
    state.currentId = null;
    state.localTeacher = false;
    showLoginScreen();
  });
}

function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (state.publicUrl) {
      clearInterval(pollTimer);
      return;
    }
    try {
      await loadSession();
    } catch (_error) {
      /* окно запуска могли закрыть */
    }
  }, 8000);
}

async function enterApp() {
  await loadStudents();
  await loadBanks();
  afterLogin();
}

async function start() {
  try {
    const session = await loadSession();
    if (!session.user) {
      showLoginScreen();
      return;
    }
    await enterApp();
  } catch (error) {
    if (els.app) els.app.classList.remove("hidden");
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
