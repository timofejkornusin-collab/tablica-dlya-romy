(function () {
  var style = document.createElement("style");
  style.textContent =
    ".material-tools{z-index:4;pointer-events:auto}" +
    ".file-remove{position:relative;z-index:5;background:rgba(255,255,255,.92);border:1px solid var(--line,#ded4c2);border-radius:6px;min-width:24px;min-height:24px;padding:0 6px;font-size:0;line-height:1;cursor:pointer}" +
    ".file-remove::after{content:\"×\";font-size:1.1rem;line-height:1;color:inherit}" +
    ".bank-picker.is-open,.bank-picker-menu{position:relative;z-index:40;overflow:visible}" +
    ".col-practice,.col-theory,.col-homework{overflow:visible}";
  document.head.appendChild(style);
  function stripBank(id) {
    var wanted = String(id || "").toLowerCase();
    if (!wanted || typeof state !== "object" || !state) return;
    state.banks = (state.banks || []).filter(function (bank) {
      return String(bank.id || "").toLowerCase() !== wanted;
    });
    (state.students || []).forEach(function (student) {
      (student.rows || []).forEach(function (row) {
        if (String(row.bankId || "").toLowerCase() !== wanted) return;
        var source = String(row.importedSource || "");
        row.bankId = "";
        if (source.indexOf("file:") === 0 || source.indexOf("manual:") === 0) row.importedSource = "";
        if (source.indexOf("file:") === 0 || wanted.indexOf("pdf-") === 0) {
          row.practiceFileId = "";
          row.practiceFileName = "";
        }
      });
    });
  }
  window.deleteBankAt = async function (bankId) {
    if (typeof hideRowConfirm === "function") hideRowConfirm();
    var id = String(bankId || "").trim();
    if (!id) return;
    if (typeof isTeacherUi === "function" && !isTeacherUi()) return;
    if (typeof saveTimer !== "undefined") clearTimeout(saveTimer);
    if (typeof saveEpoch === "number") saveEpoch += 1;
    if (typeof saveChain !== "undefined" && saveChain && saveChain.catch) {
      await saveChain.catch(function () {});
      await saveChain.catch(function () {});
    }
    if (typeof saveEpoch === "number") saveEpoch += 1;
    if (typeof saveChain !== "undefined") saveChain = Promise.resolve();
    stripBank(id);
    if (state && state.view === "table" && typeof renderTable === "function") renderTable();
    if (typeof setSaveStatus === "function") setSaveStatus("Удаляю набор…");
    var data = await api("/api/banks/delete", { method: "POST", body: JSON.stringify({ bankId: id }) });
    if (typeof saveEpoch === "number") saveEpoch += 1;
    if (typeof saveChain !== "undefined") saveChain = Promise.resolve();
    if (data && Array.isArray(data.banks)) state.banks = data.banks;
    if (data && Array.isArray(data.students)) state.students = data.students;
    else stripBank(id);
    if (state && state.view === "table" && typeof renderTable === "function") renderTable();
    if (typeof setSaveStatus === "function") setSaveStatus("Набор удалён из списка");
  };
  function removeFile(btn) {
    if (typeof removeAttachedFile === "function") { removeAttachedFile(btn); return; }
    if (typeof currentStudent !== "function" || typeof api !== "function") return;
    var student = currentStudent();
    if (!student) return;
    api("/api/file/delete", {
      method: "POST",
      body: JSON.stringify({
        studentId: student.id,
        row: Number(btn.getAttribute("data-row")),
        field: btn.getAttribute("data-field")
      })
    }).then(function (data) {
      if (typeof replaceStudent === "function") replaceStudent(data.student);
      if (typeof renderTable === "function") renderTable();
      if (typeof setSaveStatus === "function") setSaveStatus("Файл убран");
    }).catch(function (error) {
      if (typeof setSaveStatus === "function") setSaveStatus(error.message);
      alert(error.message);
    });
  }
  document.addEventListener("click", function (event) {
    var bankDelete = event.target.closest(".bank-delete");
    if (bankDelete) {
      event.preventDefault();
      event.stopPropagation();
      if (typeof showBankDeleteConfirm === "function") showBankDeleteConfirm(bankDelete.getAttribute("data-bank"));
      return;
    }
    var remove = event.target.closest(".file-remove");
    if (remove) {
      event.preventDefault();
      event.stopPropagation();
      removeFile(remove);
    }
  }, true);
})();
