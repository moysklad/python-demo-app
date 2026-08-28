(function () {
  const sdkNamespace = window.WidgetSDK;
  const sdk = sdkNamespace ? sdkNamespace.create({ debug: true }) : null;

  if (sdk) {
    window.widgetSdk = sdk;
    sdk.autoResizeIframe();
  }

  const form = document.getElementById("settingsForm");
  const result = document.getElementById("settingsResult");
  const statusBox = document.getElementById("appStatus");
  const statusTitle = document.getElementById("appStatusTitle");
  const statusDetails = document.getElementById("appStatusDetails");
  const retryTestForm = document.getElementById("retryTestForm");
  const retryTestResult = document.getElementById("retryTestResult");

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

  if (retryTestForm && retryTestResult) {
    const retryButton = retryTestForm.querySelector('button[type="submit"]');
    const defaultRetryButtonText = retryButton ? retryButton.textContent : "";

    retryTestForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      retryTestResult.textContent = "";
      retryTestResult.classList.remove("is-success", "is-error");

      const requestCountInput = retryTestForm.elements.namedItem("requestCount");
      const requestCount = Number(requestCountInput ? requestCountInput.value : 0);
      const maxRequestCount = Number(requestCountInput ? requestCountInput.max : 0) || 100;
      if (!Number.isInteger(requestCount) || requestCount < 1 || requestCount > maxRequestCount) {
        retryTestResult.textContent = `Количество запросов должно быть от 1 до ${maxRequestCount}`;
        retryTestResult.classList.add("is-error");
        return;
      }

      if (retryButton) {
        retryButton.disabled = true;
        retryButton.textContent = "Выполнение...";
      }

      let completed = 0;
      let successful = 0;
      let failed = 0;
      let retries = 0;

      function showProgress() {
        retryTestResult.textContent = `Выполнено: ${completed} из ${requestCount}. Успешно: ${successful}, ошибок: ${failed}, ретраев: ${retries}.`;
      }

      try {
        showProgress();
        await Promise.all(Array.from({ length: requestCount }, async function () {
          const body = new FormData(retryTestForm);
          body.delete("requestCount");

          try {
            const response = await fetch(retryTestForm.dataset.testUrl || retryTestForm.action, {
              method: "POST",
              body,
              credentials: "same-origin",
            });
            const contentType = response.headers.get("content-type") || "";
            const payload = contentType.includes("application/json") ? await response.json() : null;

            retries += payload && Number.isInteger(payload.retries) ? payload.retries : 0;
            if (response.ok && payload && payload.success) {
              successful += 1;
            } else {
              failed += 1;
            }
          } catch (_error) {
            failed += 1;
          } finally {
            completed += 1;
            showProgress();
          }
        }));
        retryTestResult.classList.add(failed === 0 ? "is-success" : "is-error");
      } catch (_error) {
        retryTestResult.textContent = "Не удалось выполнить проверку";
        retryTestResult.classList.add("is-error");
      } finally {
        if (retryButton) {
          retryButton.disabled = false;
          retryButton.textContent = defaultRetryButtonText;
        }
      }
    });
  }
})();
