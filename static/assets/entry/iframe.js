(function () {
  const sdkNamespace = window.WidgetSDK;
  const sdk = sdkNamespace ? sdkNamespace.create({ debug: true }) : null;

  if (sdk) {
    window.widgetSdk = sdk;
    sdk.autoResizeIframe();
  }

  const bootstrapPanel = document.getElementById("bootstrapPanel");
  const bootstrapStatus = document.getElementById("bootstrapStatus");
  const userPanel = document.getElementById("userPanel");
  const settingsPanel = document.getElementById("settingsPanel");
  const adminSettings = document.getElementById("adminSettings");
  const settingsRestricted = document.getElementById("settingsRestricted");
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

  function showBootstrapError(message) {
    if (bootstrapStatus) {
      bootstrapStatus.textContent = message;
      bootstrapStatus.classList.remove("muted");
      bootstrapStatus.classList.add("is-error");
    }
  }

  async function initializeUserContext() {
    if (!sdk || typeof sdk.requestUserContextToken !== "function") {
      showBootstrapError("JS Widget SDK не загружен, контекст пользователя недоступен.");
      return;
    }

    let token = null;
    try {
      token = await sdk.requestUserContextToken();
    } catch (error) {
      const details = error && error.message ? error.message : String(error);
      showBootstrapError(`Не удалось запросить контекст пользователя у хоста: ${details}`);
      return;
    }

    const request = new Request("/entry/user-context", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, page: "iframe" }),
      credentials: "same-origin",
    });
    token = null;

    let response;
    let payload = null;
    try {
      response = await fetch(request);
      payload = await response.json().catch(() => null);
    } catch (_error) {
      showBootstrapError("Не удалось отправить контекст на сервер приложения.");
      return;
    }

    if (!response.ok || !payload || !payload.pageData) {
      const code = payload && payload.code ? ` (код ${payload.code})` : "";
      showBootstrapError(`Не удалось получить контекст пользователя: HTTP ${response.status}${code}.`);
      return;
    }

    renderPage(payload.pageData);
  }

  function renderPage(pageData) {
    document.getElementById("userUid").textContent = pageData.fio ? `${pageData.uid} (${pageData.fio})` : pageData.uid;
    document.getElementById("userAccountId").textContent = pageData.accountId;
    document.getElementById("userAccessLevel").textContent = pageData.accessLevel;
    updateStatus(pageData.status);

    if (pageData.isAdmin) {
      const storeSelect = document.getElementById("store");
      storeSelect.innerHTML = "";
      const currentStore = pageData.status ? pageData.status.store : "";
      const stores = Array.isArray(pageData.storesValues) ? pageData.storesValues.slice() : [];
      if (currentStore && !stores.includes(currentStore)) {
        stores.unshift(currentStore);
      }
      stores.forEach(function (value) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        option.selected = value === currentStore;
        storeSelect.append(option);
      });
      document.getElementById("infoMessage").value = pageData.status ? pageData.status.infoMessage : "";
      document.querySelectorAll('input[name="contextNonce"]').forEach(function (input) {
        input.value = pageData.contextNonce;
      });
      adminSettings.hidden = false;
    } else {
      settingsRestricted.hidden = false;
    }

    bootstrapPanel.hidden = true;
    userPanel.hidden = false;
    settingsPanel.hidden = false;
  }

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
        const staggerMs = 30;
        await Promise.all(Array.from({ length: requestCount }, async function (_unused, index) {
          if (index > 0) {
            await new Promise(function (resolve) {
              window.setTimeout(resolve, index * staggerMs);
            });
          }
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

  initializeUserContext();
})();
