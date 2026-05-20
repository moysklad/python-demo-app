(function () {
  const form = document.getElementById("settingsForm");
  const result = document.getElementById("settingsResult");
  const statusBox = document.getElementById("appStatus");
  const statusTitle = document.getElementById("appStatusTitle");
  const statusDetails = document.getElementById("appStatusDetails");

  if (!form || !result) {
    return;
  }

  const submitButton = form.querySelector('button[type="submit"]');
  const defaultButtonText = submitButton ? submitButton.textContent : "";

  function setResult(message, kind) {
    result.textContent = message;
    result.classList.remove("is-success", "is-error");
    if (kind) {
      result.classList.add(kind);
    }
  }

  function updateStatus(status) {
    if (!status || !statusBox || !statusTitle || !statusDetails) {
      return;
    }

    statusBox.classList.remove("status-required", "status-ready");
    if (status.className) {
      statusBox.classList.add(status.className);
    }

    statusTitle.textContent = status.title || "";
    if (status.showDetails) {
      statusDetails.hidden = false;
      statusDetails.innerHTML = "";
      statusDetails.append("Сообщение: ", status.infoMessage || "", document.createElement("br"), "Выбран склад: ", status.store || "");
    } else {
      statusDetails.hidden = true;
      statusDetails.textContent = "";
    }
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    setResult("", "");

    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Сохранение...";
    }

    try {
      const response = await fetch(form.dataset.updateUrl || form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
      });
      const contentType = response.headers.get("content-type") || "";
      const payload = contentType.includes("application/json") ? await response.json() : await response.text();
      const message = typeof payload === "string" ? payload : payload.message;

      if (response.ok) {
        setResult(message || "Настройки обновлены", "is-success");
        updateStatus(typeof payload === "string" ? null : payload.status);
      } else {
        setResult(message || "Не удалось сохранить настройки", "is-error");
      }
    } catch (_error) {
      setResult("Не удалось сохранить настройки", "is-error");
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = defaultButtonText;
      }
    }
  });
})();
