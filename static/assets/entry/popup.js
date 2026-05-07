(function () {
  const logEl = document.getElementById("log");

  const widgetLog = (label, payload) => {
    const ts = new Date().toISOString().replace("T", " ").replace("Z", "");
    const data = payload ? JSON.stringify(payload, null, 2) : "";
    const message = `[${ts}] ${label}\n${data}\n\n`;

    if (logEl) {
      logEl.textContent = message + logEl.textContent;
    } else {
      console.log(message);
    }
  };

  window.widgetLog = widgetLog;

  const sdkNamespace = window.WidgetSDK;
  const sdk = sdkNamespace ? sdkNamespace.create({ debug: true }) : null;

  if (sdk) {
    window.widgetSdk = sdk;
  }

  const parseMaybeJson = (value) => {
    if (value === undefined || value === null) {
      return undefined;
    }

    const trimmed = String(value).trim();

    if (!trimmed) {
      return undefined;
    }

    try {
      return JSON.parse(trimmed);
    } catch (_) {
      return trimmed;
    }
  };

  const sdkControlIds = ["btnSelectFolder", "btnNavigate", "btnDialog", "btnShowPopup", "btnClosePopup"];

  const setSdkControlsEnabled = (enabled) => {
    sdkControlIds.forEach((id) => {
      const el = document.getElementById(id);

      if (!el) {
        return;
      }

      el.disabled = !enabled;

      if (enabled) {
        el.removeAttribute("title");
        el.removeAttribute("aria-disabled");
      } else {
        el.setAttribute("title", "SDK недоступен");
        el.setAttribute("aria-disabled", "true");
      }
    });
  };

  const tabs = Array.from(document.querySelectorAll(".tab"));
  const panels = Array.from(document.querySelectorAll(".tab-panel"));

  const setActiveTab = (tabId) => {
    tabs.forEach((tab) => {
      const isActive = tab.dataset.tab === tabId;
      tab.classList.toggle("active", isActive);
      tab.setAttribute("aria-selected", isActive ? "true" : "false");
    });
    panels.forEach((panel) => {
      const isActive = panel.dataset.tabPanel === tabId;
      panel.classList.toggle("active", isActive);
    });
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => setActiveTab(tab.dataset.tab));
  });

  if (!sdk) {
    widgetLog("SDK init skipped", { reason: "WidgetSDK is not available" });
    setSdkControlsEnabled(false);
    return;
  }

  widgetLog("SDK initialized", { debug: true });
  setSdkControlsEnabled(true);

  sdk.onOpen((message) => widgetLog("Event: Open", message));
  sdk.onOpenPopup((message) => widgetLog("Event: OpenPopup", message));

  document.getElementById("btnSelectFolder").addEventListener("click", async () => {
    try {
      const res = await sdk.selectGoodFolder();
      widgetLog("selectGoodFolder response", res);
    } catch (e) {
      widgetLog("selectGoodFolder error", { message: e.message, name: e.name });
    }
  });

  document.getElementById("btnNavigate").addEventListener("click", async () => {
    const path = document.getElementById("navigatePath").value.trim() || "/";

    try {
      const res = await sdk.navigateTo(path, "blank");
      widgetLog("navigateTo response", res);
    } catch (e) {
      widgetLog("navigateTo error", { message: e.message, name: e.name });
    }
  });

  document.getElementById("btnDialog").addEventListener("click", async () => {
    const text = document.getElementById("dialogText").value.trim() || "Dialog";
    const buttonsPayload = parseMaybeJson(document.getElementById("dialogButtons").value);

    try {
      const normalizedButtons = Array.isArray(buttonsPayload)
        ? buttonsPayload
        : buttonsPayload && Array.isArray(buttonsPayload.buttons)
          ? buttonsPayload.buttons
          : undefined;
      const res = await sdk.showDialog(text, normalizedButtons);

      widgetLog("showDialog response", res);
    } catch (e) {
      widgetLog("showDialog error", { message: e.message, name: e.name });
    }
  });

  document.getElementById("btnShowPopup").addEventListener("click", async () => {
    const name = document.getElementById("popupName").value.trim() || "popup";
    const params = parseMaybeJson(document.getElementById("popupParams").value);

    try {
      const res = await sdk.showPopup(name, params);
      widgetLog("showPopup response", res);
    } catch (e) {
      widgetLog("showPopup error", { message: e.message, name: e.name });
    }
  });

  document.getElementById("btnClosePopup").addEventListener("click", () => {
    const res = sdk.closePopup({ ok: true });
    widgetLog("closePopup sent", res);
  });
}());
