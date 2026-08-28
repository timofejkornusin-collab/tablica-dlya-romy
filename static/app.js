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

const TABLE_CLIPBOARD_KEY = "journal-table-clipboard-v1";

function ensureTableCopyButtons() {
  const actions = document.getElementById("table-actions");
  if (!actions) return;
  const settings = document.getElementById("settings-btn");
  if (!document.getElementById("copy-table-btn")) {
    const button = document.createElement("button");
    button.id = "copy-table-btn";
    button.className = "secondary-btn hidden";
    button.type = "button";
    button.textContent = "Копировать таблицу";
    actions.insertBefore(button, settings || null);
  }
  if (!document.getElementById("paste-table-btn")) {
    const button = document.createElement("button");
    button.id = "paste-table-btn";
    button.className = "secondary-btn hidden";
    button.type = "button";
    button.disabled = true;
    button.textContent = "Вставить таблицу";
    actions.insertBefore(button, settings || null);
  }
}

ensureTableCopyButtons();

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
  revealedRowIndex: null,
  localTeacher: false,
  pendingNewStudent: false,
  tableClipboard: null,
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
  logoutConfirm: document.getElementById("logout-confirm"),
  logoutConfirmYes: document.getElementById("logout-confirm-yes"),
  logoutConfirmNo: document.getElementById("logout-confirm-no"),
  tableActions: document.getElementById("table-actions"),
  templateWrap: document.getElementById("template-wrap"),
  templateSelect: document.getElementById("template-select"),
  findWrap: document.getElementById("find-wrap"),
  findRowBtn: document.getElementById("find-row-btn"),
  copyTableBtn: document.getElementById("copy-table-btn"),
  pasteTableBtn: document.getElementById("paste-table-btn"),
  findDialog: document.getElementById("find-dialog"),
  findForm: document.getElementById("find-form"),
  findDate: document.getElementById("find-date"),
  findError: document.getElementById("find-error"),
  findCancel: document.getElementById("find-cancel"),
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
let skipTableDomSync = false;
const saveEpochByStudent = Object.create(null);

function bumpSaveEpoch(studentId) {
  const id = String(studentId || "");
  if (!id) return 0;
  saveEpochByStudent[id] = (saveEpochByStudent[id] || 0) + 1;
  return saveEpochByStudent[id];
}

function cloneTableData(value) {
  return JSON.parse(JSON.stringify(value));
}

function tableContentScore(student) {
  return (student && Array.isArray(student.rows) ? student.rows : []).reduce((sum, row) => {
    if (!row || typeof row !== "object") return sum;
    return (
      sum +
      ["date", "topic", "theory", "homework", "comment"].reduce(
        (part, key) => part + String(row[key] || "").trim().length,
        0
      )
    );
  }, 0);
}

function syncTableRowsFromDom(student) {
  if (!student || !els.tableView || els.tableView.classList.contains("hidden")) return;
  if (state.view !== "table" || state.currentId !== student.id) return;
  const wrap = els.tableView.querySelector(".table-wrap");
  if (!wrap || wrap.getAttribute("data-student-id") !== String(student.id)) return;
  if (!Array.isArray(student.rows)) student.rows = [];
  els.tableView.querySelectorAll("textarea[data-row][data-key]").forEach((area) => {
    const index = Number(area.dataset.row);
    if (!Number.isInteger(index) || index < 0) return;
    while (student.rows.length <= index) student.rows.push(emptyRow());
    const row = student.rows[index];
    if (!row) return;
    row[area.dataset.key] = area.value;
  });
  els.tableView.querySelectorAll("select[data-role='bank']").forEach((select) => {
    const index = Number(select.dataset.row);
    const row = student.rows[index];
    if (!row) return;
    row.bankId = select.value;
  });
}

function applyCopiedTable(target, copied) {
  const rows = Array.isArray(copied.rowData) ? copied.rowData : [];
  target.rows = cloneTableData(rows);
  target.template = copied.template === "twice" ? "twice" : "once";
  if (copied.schedule) {
    target.schedule = cloneTableData(copied.schedule);
  }
}

function emptyRow() {
  return {
    date: "",
    lessonStatus: "",
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

function hideFindDialog() {
  if (els.findDialog) els.findDialog.classList.add("hidden");
  if (els.findError) els.findError.textContent = "";
}

function showFindDialog() {
  hideRowConfirm();
  hideLogoutConfirm();
  if (!els.findDialog) return;
  if (els.findError) els.findError.textContent = "";
  els.findDialog.classList.remove("hidden");
  if (els.findDate) {
    els.findDate.value = "";
    els.findDate.focus();
  }
}

function parseDateParts(value) {
  const raw = String(value || "").trim();
  const iso = raw.match(/(\d{4})[./-](\d{1,2})[./-](\d{1,2})/);
  if (iso) {
    return { year: Number(iso[1]), month: Number(iso[2]), day: Number(iso[3]) };
  }
  const dmy = raw.match(/(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?/);
  if (!dmy) return null;
  let year = dmy[3] ? Number(dmy[3]) : null;
  if (year != null && year < 100) year += 2000;
  return { year, month: Number(dmy[2]), day: Number(dmy[1]) };
}

function rowMatchesDate(row, query) {
  const needle = String(query || "").trim();
  if (!needle) return false;
  const rowDate = String((row && row.date) || "");
  const wanted = parseDateParts(needle);
  const got = parseDateParts(rowDate);
  if (wanted && got) {
    if (wanted.day !== got.day || wanted.month !== got.month) return false;
    if (wanted.year != null && got.year != null && wanted.year !== got.year) return false;
    return true;
  }
  const compact = (text) => text.replace(/\s+/g, "").toLowerCase();
  return compact(rowDate).includes(compact(needle));
}

function scrollToLessonRow(index) {
  const row = els.tableView.querySelector(`tr[data-row="${index}"]`);
  if (!row) return false;
  document.querySelectorAll("tr.row-found").forEach((item) => item.classList.remove("row-found"));
  row.classList.add("row-found");
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  window.setTimeout(() => row.classList.remove("row-found"), 2600);
  return true;
}

function findLessonByDate(query) {
  const student = currentStudent();
  const rows = student && Array.isArray(student.rows) ? student.rows : [];
  if (!student || !rows.length) {
    return { ok: false, error: "Сначала откройте таблицу ученика." };
  }
  const index = rows.findIndex((row) => rowMatchesDate(row, query));
  if (index < 0) {
    return { ok: false, error: "Строка с такой датой не найдена." };
  }
  state.revealedRowIndex = index;
  renderTable();
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      if (!scrollToLessonRow(index) && els.findError) {
        els.findError.textContent = "Строка есть, но не получилось к ней перейти.";
      }
    });
  });
  setSaveStatus(`Открыта строка с датой ${rows[index].date || query}`);
  return { ok: true, index };
}

function hideLogoutConfirm() {
  if (els.logoutConfirm) els.logoutConfirm.classList.add("hidden");
}

function showLogoutConfirm() {
  hideRowConfirm();
  hideFindDialog();
  if (!els.logoutConfirm) return;
  els.logoutConfirm.classList.remove("hidden");
  if (els.logoutConfirmNo) els.logoutConfirmNo.focus();
}

async function performLogout() {
  hideLogoutConfirm();
  try {
    await api("/api/logout", { method: "POST", body: "{}" });
  } catch (_error) {
    /* всё равно выходим на экран входа */
  }
  state.me = null;
  state.students = [];
  state.currentId = null;
  state.localTeacher = false;
  state.previewAsStudent = false;
  showLoginScreen();
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
  updateTableCopyButtons();
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
    const error = new Error(data.error || "Ошибка запроса");
    error.status = response.status;
    throw error;
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
  if (els.logoutBtn) els.logoutBtn.classList.remove("hidden");
  updateModeChrome();
  updateShareBar();
}

function showLoginScreen() {
  hideLogoutConfirm();
  hideRowConfirm();
  hideFindDialog();
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
  syncStartDateWeekday();
  const template = els.studentForm.template.value === "twice" ? "twice" : "once";
  const slots = [
    { weekday: Number(els.weekday0.value), time: els.time0.value || "16:00" },
  ];
  if (template === "twice") {
    slots.push({ weekday: Number(els.weekday1.value), time: els.time1.value || "16:00" });
  }
  return { template, slots, startDate: els.startDate ? els.startDate.value : "" };
}

function syncStartDateWeekday() {
  if (!els.startDate || !els.startDate.value || !els.weekday0) return;
  const date = new Date(`${els.startDate.value}T12:00:00`);
  if (Number.isNaN(date.getTime())) return;
  els.weekday0.value = String((date.getDay() + 6) % 7);
}

async function persistCurrent() {
  const student = currentStudent();
  if (!student || !isTeacherUi()) return saveChain;
  syncTableRowsFromDom(student);
  const id = student.id;
  const epoch = saveEpochByStudent[id] || 0;
  const payload = {
    id,
    rows: cloneTableData(Array.isArray(student.rows) ? student.rows : []),
    template: student.template === "twice" ? "twice" : "once",
  };
  const run = async () => {
    if ((saveEpochByStudent[id] || 0) !== epoch) return;
    setSaveStatus("Сохранение…");
    await api("/api/table", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if ((saveEpochByStudent[id] || 0) !== epoch) return;
    setSaveStatus("Сохранено");
  };
  saveChain = saveChain.then(run, run);
  return saveChain;
}

function loadTableClipboard() {
  try {
    const stored = JSON.parse(sessionStorage.getItem(TABLE_CLIPBOARD_KEY) || "null");
    if (stored && stored.sourceId && stored.sourceName) {
      state.tableClipboard = stored;
    }
  } catch (_error) {
    state.tableClipboard = null;
  }
}

function updateTableCopyButtons() {
  const teacherTable = isTeacherUi() && state.view === "table" && Boolean(currentStudent());
  if (els.copyTableBtn) {
    els.copyTableBtn.classList.toggle("hidden", !teacherTable);
  }
  if (els.pasteTableBtn) {
    els.pasteTableBtn.classList.toggle("hidden", !teacherTable);
    const sameStudent =
      state.tableClipboard && currentStudent() && state.tableClipboard.sourceId === currentStudent().id;
    els.pasteTableBtn.disabled = !state.tableClipboard || Boolean(sameStudent);
    els.pasteTableBtn.title = state.tableClipboard
      ? sameStudent
        ? "Откройте таблицу другого ученика"
        : `Вставить таблицу ученика «${state.tableClipboard.sourceName}»`
      : "Сначала скопируйте таблицу ученика";
  }
}

async function copyCurrentTable() {
  const student = currentStudent();
  if (!student || !isTeacherUi()) return;
  clearTimeout(saveTimer);
  syncTableRowsFromDom(student);
  await persistCurrent();
  state.tableClipboard = {
    sourceId: student.id,
    sourceName: student.name,
    rows: Array.isArray(student.rows) ? student.rows.length : 0,
    rowData: cloneTableData(Array.isArray(student.rows) ? student.rows : []),
    template: student.template === "twice" ? "twice" : "once",
    schedule: student.schedule ? cloneTableData(student.schedule) : null,
  };
  try {
    sessionStorage.setItem(TABLE_CLIPBOARD_KEY, JSON.stringify(state.tableClipboard));
  } catch (_error) {
    /* Буфер всё равно действует, пока открыта эта страница. */
  }
  updateTableCopyButtons();
  setSaveStatus(`Таблица «${student.name}» скопирована: ${state.tableClipboard.rows} строк`);
}

async function pasteCopiedTable() {
  const target = currentStudent();
  const copied = state.tableClipboard;
  if (!target || !copied || !isTeacherUi() || target.id === copied.sourceId) return;
  if (!Array.isArray(copied.rowData) || !copied.rowData.length) {
    const source = state.students.find((item) => item.id === copied.sourceId);
    if (source && Array.isArray(source.rows)) {
      copied.rowData = cloneTableData(source.rows);
      copied.template = source.template === "twice" ? "twice" : copied.template;
      copied.schedule = source.schedule ? cloneTableData(source.schedule) : copied.schedule;
    }
  }
  if (!Array.isArray(copied.rowData)) {
    throw new Error("Сначала скопируйте таблицу ещё раз — буфер оказался пустым.");
  }
  const approved = confirm(
    `Заменить таблицу ученика «${target.name}» таблицей ученика «${copied.sourceName}»?\n\n` +
      "Даты, темы, материалы, задания и отметки занятий будут скопированы полностью. " +
      "Личные ответы и прогресс учеников не копируются."
  );
  if (!approved) return;
  clearTimeout(saveTimer);
  await saveChain.catch(() => {});
  bumpSaveEpoch(target.id);
  applyCopiedTable(target, copied);
  skipTableDomSync = true;
  renderTable();
  setSaveStatus("Вставляю таблицу…");
  let data = { student: target };
  try {
    data = await api("/api/table/copy", {
      method: "POST",
      body: JSON.stringify({ sourceId: copied.sourceId, targetId: target.id }),
    });
  } catch (error) {
    if (error.status !== 404 && error.status !== 405) throw error;
    const schedule = copied.schedule;
    if (schedule && schedule.startDate && Array.isArray(schedule.slots) && schedule.slots.length) {
      try {
        await api("/api/schedule", {
          method: "POST",
          body: JSON.stringify({
            id: target.id,
            name: target.name,
            template: copied.template,
            startDate: schedule.startDate,
            slots: schedule.slots,
            regenerate: false,
          }),
        });
      } catch (_scheduleError) {
        /* строки всё равно сохраняем через /api/table */
      }
    }
    data = await api("/api/table", {
      method: "POST",
      body: JSON.stringify({
        id: target.id,
        rows: cloneTableData(target.rows),
        template: target.template,
      }),
    });
  }
    if (data && data.student) {
      replaceStudent(data.student, { keepRicher: true });
    }
  await persistCurrent();
  skipTableDomSync = true;
  renderTable();
  setSaveStatus(`Таблица «${copied.sourceName}» вставлена ученику «${target.name}»`);
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    persistCurrent().catch((error) => setSaveStatus(friendlyNetworkError(error).message));
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
  hideFindDialog();
  document.body.classList.remove("practice-open");
  state.view = "list";
  state.currentId = null;
  state.previewAsStudent = false;
  state.revealedRowIndex = null;
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
  if (["held", "missed"].includes(row.lessonStatus)) return true;
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
  if (!rows.length) return [];
  const filled = [];
  rows.forEach((row, index) => {
    if (rowHasLessonContent(row)) filled.push(index);
  });
  const visible = !filled.length ? [0] : filled.slice();
  if (filled.length) {
    const next = filled[filled.length - 1] + 1;
    if (next < rows.length && !visible.includes(next)) {
      visible.push(next);
    }
  }
  const revealed = state.revealedRowIndex;
  if (Number.isInteger(revealed) && revealed >= 0 && revealed < rows.length && !visible.includes(revealed)) {
    visible.push(revealed);
    visible.sort((a, b) => a - b);
  }
  return visible;
}

function renderTable() {
  const student = currentStudent();
  if (!student) {
    if (isTeacherAccount()) renderList();
    return;
  }
  if (!skipTableDomSync) syncTableRowsFromDom(student);
  skipTableDomSync = false;
  if (!isTeacherUi()) hideRowConfirm();
  document.body.classList.remove("practice-open");

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
  els.tableActions.classList.remove("hidden");
  els.addStudentBtn.classList.add("hidden");
  els.templateWrap.classList.add("hidden");
  if (els.findWrap) els.findWrap.classList.remove("hidden");
  if (els.settingsBtn) {
    els.settingsBtn.classList.toggle("hidden", !isTeacherUi());
  }
  updateTableCopyButtons();
  els.pageTitle.textContent = student.name;
  els.pageSubtitle.textContent = isStudentView()
    ? "Та же таблица, что у педагога: сначала первая строка, затем следующая после заполнения."
    : "Между уроками нажмите «+». «Найти» открывает строку по дате.";
  updateModeChrome();
  updateShareBar();

  const rowIndexes = visibleRowIndexes(student);
  if (isStudentView() && rowIndexes.length === 0) {
    els.tableView.innerHTML = `
      <div class="empty-state">
        <p>Таблица пока пустая.</p>
        <p>Когда педагог добавит расписание, здесь появится первая строка занятия.</p>
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
        if (column.key === "date") {
          const status = ["held", "missed"].includes(row.lessonStatus) ? row.lessonStatus : "";
          const readonly = isStudentView() ? "readonly" : "";
          const controls = isTeacherUi()
            ? `<div class="lesson-status-controls" role="group" aria-label="Состоялось ли занятие">
                <button class="lesson-status-btn status-held" type="button" data-row="${rowIndex}" data-status="held" aria-pressed="${
                  status === "held"
                }">Было</button>
                <button class="lesson-status-btn status-missed" type="button" data-row="${rowIndex}" data-status="missed" aria-pressed="${
                  status === "missed"
                }">Не было</button>
              </div>`
            : status
              ? `<span class="lesson-status-badge status-${status}">${
                  status === "held" ? "✓ Было занятие" : "× Занятия не было"
                }</span>`
              : "";
          return `<td class="col-date" data-label="${escapeHtml(column.label)}">
            <div class="date-cell">
              <textarea class="cell-fill" data-row="${rowIndex}" data-key="date" rows="1" spellcheck="false" placeholder="например 10.09.2026, 17:00" ${readonly}>${escapeHtml(
                String(row.date || "")
              )}</textarea>
              ${controls}
            </div>
          </td>`;
        }
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
        return `<td class="${column.className}" data-label="${escapeHtml(column.label)}">
          <textarea class="cell-fill" data-row="${rowIndex}" data-key="${column.key}" rows="1" spellcheck="false" ${readonly}>${escapeHtml(
            String(value)
          )}</textarea>
        </td>`;
      }).join("");
      const tools = isTeacherUi()
        ? `<td class="col-row-tools" data-label="Урок">
            <button class="row-delete" type="button" data-row="${rowIndex}" title="Удалить этот урок">×</button>
          </td>`
        : "";
      const classes = [];
      if (upcoming) classes.push("lesson-upcoming");
      if (row.lessonStatus === "held") classes.push("lesson-held");
      if (row.lessonStatus === "missed") classes.push("lesson-missed");
      const classAttr = classes.length ? ` class="${classes.join(" ")}"` : "";
      return `<tr${classAttr} data-row="${rowIndex}">${tools}${cells}</tr>${
        isTeacherUi() ? insertGap(rowIndex + 1) : ""
      }`;
  };
  const body = isTeacherUi()
    ? insertGap(0) + rowIndexes.map(renderLessonRow).join("")
    : rowIndexes.map(renderLessonRow).join("");

  els.tableView.innerHTML = `
    <div class="table-wrap" data-student-id="${escapeHtml(String(student.id || ""))}">
      <table>
        <thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

function closePractice() {
  document.body.classList.remove("practice-open");
  loadStudents().then(renderTable).catch((error) => setSaveStatus(error.message));
}

function capturePracticeScroll(taskN) {
  const view = els.practiceView;
  const card =
    taskN != null && view ? view.querySelector(`.task-card[data-n="${taskN}"]`) : null;
  return {
    windowY: window.scrollY || window.pageYOffset || 0,
    viewY: view ? view.scrollTop : 0,
    cardTop: card ? card.getBoundingClientRect().top : null,
    taskN,
  };
}

function restorePracticeScroll(snapshot, taskN, role) {
  const n = taskN != null ? taskN : snapshot && snapshot.taskN;
  const apply = () => {
    const view = els.practiceView;
    if (!view) return;
    const card = n != null ? view.querySelector(`.task-card[data-n="${n}"]`) : null;
    if (card && snapshot && snapshot.cardTop != null) {
      const delta = card.getBoundingClientRect().top - snapshot.cardTop;
      if (Math.abs(delta) >= 1) {
        view.scrollTop += delta;
      }
      const still = card.getBoundingClientRect().top - snapshot.cardTop;
      if (Math.abs(still) >= 1) {
        window.scrollBy(0, still);
      }
    } else if (snapshot) {
      window.scrollTo(0, snapshot.windowY);
      view.scrollTop = snapshot.viewY;
    }
    const input =
      role && n != null
        ? view.querySelector(`input[data-role="${role}"][data-n="${n}"]`)
        : null;
    if (input && !input.readOnly) {
      try {
        input.focus({ preventScroll: true });
      } catch (_error) {
        /* не вызываем focus() без preventScroll — это снова уводит вверх */
      }
    }
  };
  apply();
  queueMicrotask(apply);
  requestAnimationFrame(() => {
    apply();
    requestAnimationFrame(apply);
  });
  setTimeout(apply, 0);
  setTimeout(apply, 32);
}

async function openPractice(bankId, options = {}) {
  const student = currentStudent();
  if (!student || !bankId) return;
  const keepScroll = Boolean(options.keepScroll);
  const snapshot = keepScroll ? capturePracticeScroll(options.focusN) : null;
  hideRowConfirm();
  hideFindDialog();
  const asStudent = isStudentView() ? "&asStudent=1" : "";
  const data = await api(
    `/api/practice?studentId=${encodeURIComponent(student.id)}&bankId=${encodeURIComponent(bankId)}${asStudent}`
  );
  state.view = "practice";
  state.practice = data;
  document.body.classList.add("practice-open");
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
  if (keepScroll) {
    restorePracticeScroll(snapshot, options.focusN, options.focusRole);
  } else {
    window.scrollTo(0, 0);
    els.practiceView.scrollTop = 0;
  }
}

function renderPractice() {
  const data = state.practice;
  if (!data) return;
  const stats = data.stats || { done: 0, total: 0, percent: 0, correct: 0 };
  const total = Number(stats.total) || 0;
  const done = Number(stats.done) || 0;
  const correct = Number(stats.correct) || 0;
  const percent = Number(stats.percent) || 0;
  const color = data.statsColor || "red";
  const wordBank =
    (data.tasks || []).length > 0 &&
    (data.tasks || []).every((task) => task.kind === "phrases" || task.kind === "word" || task.word);
  const statsHint = wordBank
    ? "Запишите слово, как в бланке ЕГЭ."
    : "Запишите номера рядов без пробелов, как в бланке ЕГЭ: например 245.";
  const tasks = (data.tasks || [])
    .map((task) => {
      const optionItems = (task.options || []).filter(Boolean);
      const isPhrases = task.kind === "phrases";
      const isWord = Boolean(task.word) || task.kind === "word" || isPhrases;
      const listTag = isPhrases ? "ul" : "ol";
      const skip = `<div class="task-skip" style="height:64px;min-height:64px;line-height:64px;font-size:32px;margin:0;padding:0;">&nbsp;</div>`;
      const options = optionItems.length
        ? `${skip}<${listTag} class="task-options${isPhrases ? " task-phrases" : ""}">${optionItems
            .map((option) => `<li>${escapeHtml(option)}</li>`)
            .join("")}</${listTag}>`
        : "";
      const answerPlaceholder = isWord ? "слово" : "245 или 2, 4, 5";
      const keyPlaceholder = isWord ? "например слово" : "например 245";
      const keyField = isTeacherUi()
        ? `<label class="task-field-label">Ключ <input class="key-input" data-n="${task.n}" data-role="key" value="${escapeHtml(
            task.answer || ""
          )}" placeholder="${keyPlaceholder}" /></label>`
        : "";
      const correctAnswer = task.correctAnswer || "";
      const correctReveal =
        task.status === "bad" && correctAnswer
          ? `<p class="task-correct">Правильный ответ: <strong>${escapeHtml(correctAnswer)}</strong></p>`
          : "";
      const locked = Boolean(task.locked) || (!isTeacherUi() && Boolean(String(task.given || "").trim()));
      const saveControl = locked
        ? `<p class="task-locked">Ответ сохранён. Изменить его нельзя.</p>`
        : `<button class="primary-btn save-answer" type="button" data-n="${task.n}">Сохранить</button>`;
      return `
        <article class="task-card ${task.status || ""} ${locked ? "locked" : ""}" data-n="${task.n}">
          <div class="task-card-top">
            <span class="task-badge">№ ${task.n}</span>
            <span class="task-tag">Задание ЕГЭ</span>
          </div>
          ${renderTaskPrompt(task.prompt || data.instruction || "")}
          ${options}
          <div class="task-actions">
            <label class="task-field-label">Ответ ученика
              <input data-n="${task.n}" data-role="given" value="${escapeHtml(task.given || "")}" placeholder="${answerPlaceholder}" ${locked ? "readonly" : ""} />
            </label>
            ${saveControl}
            ${keyField}
            ${isTeacherUi() ? `<button class="secondary-btn save-key" type="button" data-n="${task.n}">Сохранить ключ</button>` : ""}
          </div>
          ${correctReveal}
        </article>
      `;
    })
    .join("");

  els.practiceView.innerHTML = `
    <div class="practice-screen">
      <div class="practice-toolbar">
        <button class="primary-btn practice-back" type="button">← К таблице</button>
        <h2>${escapeHtml(data.title || "Задания")}</h2>
      </div>
      <div class="practice-summary progress-${escapeHtml(color)}">
        <div class="stats-text">Выполнено: ${done} из ${total}. Верно: ${correct} из ${total} (${percent}%).</div>
        <div class="stats-hint">${escapeHtml(statsHint)}</div>
      </div>
      <div class="task-list">${tasks}</div>
    </div>
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

function formatTaskPrompt(text) {
  let raw = String(text || "").replace(/\r/g, "");
  raw = raw.replace(
    /(Запишите номера этих предложений|Запишите номера ответов|запишите слово правильно|Запишите это слово)\.?\s*(?=[1-5][.)]|\(\d+\)[А-ЯЁA-Z«"])/gi,
    "$1.\n\n"
  );
  raw = raw.replace(/\n{3,}/g, "\n\n");
  return raw;
}

function renderTaskPrompt(text) {
  const raw = formatTaskPrompt(text).trim();
  const parts = raw.split(/\n\s*\n/).map((part) => part.trim()).filter(Boolean);
  const skip = `<div class="task-skip" style="height:64px;min-height:64px;line-height:64px;font-size:32px;margin:0;padding:0;">&nbsp;</div>`;
  const blocks = (parts.length ? parts : [raw]).map(
    (part) => `<p class="task-prompt">${escapeHtml(part).replaceAll("\n", "<br>")}</p>`
  );
  return blocks.join(skip);
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

function replaceStudent(student, options = {}) {
  if (!student || !student.id) return;
  const index = state.students.findIndex((item) => item.id === student.id);
  if (index < 0) return;
  const current = state.students[index];
  if (options.keepRicher && current && tableContentScore(current) > tableContentScore(student)) {
    student = {
      ...student,
      rows: cloneTableData(current.rows || []),
      template: current.template || student.template,
      schedule: current.schedule || student.schedule,
    };
  }
  state.students[index] = student;
  skipTableDomSync = true;
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
if (els.copyTableBtn) {
  els.copyTableBtn.addEventListener("click", () => {
    copyCurrentTable().catch((error) => {
      setSaveStatus(error.message);
      alert(error.message);
    });
  });
}
if (els.pasteTableBtn) {
  els.pasteTableBtn.addEventListener("click", () => {
    pasteCopiedTable().catch((error) => {
      setSaveStatus(error.message);
      alert(error.message);
    });
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
if (els.startDate) {
  const onStartDateChange = () => syncStartDateWeekday();
  els.startDate.addEventListener("change", onStartDateChange);
  els.startDate.addEventListener("input", onStartDateChange);
}
els.backBtn.addEventListener("click", () => {
  if (state.view === "practice") {
    closePractice();
    return;
  }
  renderList();
});
if (els.templateSelect) {
  els.templateSelect.addEventListener("change", () => {
    const student = currentStudent();
    if (!student || !isTeacherUi()) return;
    student.template = els.templateSelect.value;
    const second = document.getElementById("table-second-slot");
    if (second) second.classList.toggle("hidden", student.template !== "twice");
    scheduleSave();
  });
}
if (els.findRowBtn) {
  els.findRowBtn.addEventListener("click", () => {
    if (!currentStudent()) {
      setSaveStatus("Сначала откройте таблицу ученика.");
      return;
    }
    showFindDialog();
  });
}
if (els.findCancel) {
  els.findCancel.addEventListener("click", hideFindDialog);
}
if (els.findDialog) {
  els.findDialog.addEventListener("click", (event) => {
    if (event.target === els.findDialog) hideFindDialog();
  });
}
if (els.findForm) {
  els.findForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = els.findDate ? els.findDate.value.trim() : "";
    if (!query) {
      if (els.findError) els.findError.textContent = "Введите дату, например 10.09.2026";
      return;
    }
    const result = findLessonByDate(query);
    if (!result.ok) {
      if (els.findError) els.findError.textContent = result.error;
      return;
    }
    hideFindDialog();
  });
}
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
      clearTimeout(saveTimer);
      await saveChain.catch(() => {});
      bumpSaveEpoch(state.settingsStudentId);
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
  const statusBtn = event.target.closest(".lesson-status-btn");
  if (statusBtn) {
    const student = currentStudent();
    const row = student && student.rows[Number(statusBtn.dataset.row)];
    if (!row || !isTeacherUi()) return;
    const selected = statusBtn.dataset.status;
    row.lessonStatus = row.lessonStatus === selected ? "" : selected;
    scheduleSave();
    renderTable();
    return;
  }
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
  if (event.target.closest(".practice-back")) {
    closePractice();
    return;
  }
  const student = currentStudent();
  const practice = state.practice;
  if (!student || !practice) return;
  const saveAnswer = event.target.closest(".save-answer");
  if (saveAnswer) {
    const n = Number(saveAnswer.dataset.n);
    if (!isTeacherUi()) {
      const task = (practice.tasks || []).find((item) => Number(item.n) === n);
      if (task && String(task.given || "").trim()) {
        alert("Ответ уже сохранён. Изменить его нельзя.");
        return;
      }
    }
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
      await openPractice(practice.id, { keepScroll: true, focusN: n, focusRole: "given" });
      setSaveStatus(`Сохранено, ${data.stats.done}/${data.stats.total}`);
    } catch (error) {
      alert(error.message);
    }
    return;
  }
  const saveKey = event.target.closest(".save-key");
  if (saveKey) {
    if (!isTeacherUi()) return;
    const n = Number(saveKey.dataset.n);
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
      await openPractice(practice.id, { keepScroll: true, focusN: n, focusRole: "key" });
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
  els.logoutBtn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    showLogoutConfirm();
  });
}
document.addEventListener(
  "click",
  (event) => {
    const logoutBtn = event.target.closest("#logout-btn");
    if (logoutBtn) {
      event.preventDefault();
      event.stopPropagation();
      showLogoutConfirm();
    }
  },
  true
);
if (els.logoutConfirmYes) {
  els.logoutConfirmYes.addEventListener("click", () => {
    performLogout();
  });
}
if (els.logoutConfirmNo) {
  els.logoutConfirmNo.addEventListener("click", hideLogoutConfirm);
}
if (els.logoutConfirm) {
  els.logoutConfirm.addEventListener("click", (event) => {
    if (event.target === els.logoutConfirm) hideLogoutConfirm();
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
  loadTableClipboard();
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
