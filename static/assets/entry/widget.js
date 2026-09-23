(function () {
  const root = document.body;
  const logEl = document.getElementById("log");
  const getObjectUrl = root ? root.dataset.getObjectUrl || "" : "";
  const objectEl = document.getElementById("object");
  const AUTO_OPEN_FEEDBACK_DELAY_MS = 1000;

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

  const sdkControlIds = [
    "btnSelectFolder",
    "btnNavigate",
    "btnDialog",
    "btnSetDirty",
    "btnClearDirty",
    "btnValidation",
    "btnUpdate",
    "btnShowPopup",
    "btnClosePopup"
  ];

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

  let objectState = {};

  const valuesEqual = (left, right) => {
    if (left === right) {
      return true;
    }

    if (left && right && typeof left === "object" && typeof right === "object") {
      try {
        return JSON.stringify(left) === JSON.stringify(right);
      } catch (_) {
        return false;
      }
    }

    return false;
  };

  const diffs = (oldState, newState) => {
    const result = new Map();

    if (!newState || typeof newState !== "object") {
      return result;
    }

    for (const key in newState) {
      if (Object.prototype.hasOwnProperty.call(newState, key)) {
        const oldValue = oldState && Object.prototype.hasOwnProperty.call(oldState, key) ? oldState[key] : undefined;

        if (!oldState || !Object.prototype.hasOwnProperty.call(oldState, key) || !valuesEqual(newState[key], oldValue)) {
          result.set(key, newState[key]);
        }
      }
    }

    if (oldState && typeof oldState === "object") {
      for (const key in oldState) {
        if (Object.prototype.hasOwnProperty.call(oldState, key) && (!newState || !Object.prototype.hasOwnProperty.call(newState, key))) {
          result.set(key, "<deleted>");
        }
      }
    }

    return result;
  };

  const formatDiffs = (map) => {
    if (!map || map.size === 0) {
      return "objectState: no changes";
    }

    const lines = [];

    map.forEach((value, key) => {
      if (value && typeof value === "object") {
        lines.push(`${key} = {...}`);
      } else {
        lines.push(`${key} = ${value}`);
      }
    });

    return `objectState changes:\n${lines.join("\n")}`;
  };

  if (!sdk) {
    widgetLog("SDK init skipped", { reason: "WidgetSDK is not available" });
    setSdkControlsEnabled(false);
    return;
  }

  widgetLog("SDK initialized", { debug: true });
  setSdkControlsEnabled(true);

  sdk.autoResizeIframe();

  const userEl = document.getElementById("user");
  let contextNonce = "";
  let pendingObjectId = null;

  // Open может прийти раньше, чем сессия поднимется, поэтому objectId ждет контекст.
  async function initializeUserContext() {
    let token = null;
    try {
      token = await sdk.requestUserContextToken();
    } catch (error) {
      widgetLog("requestUserContextToken error", { message: error.message || String(error), name: error.name });
      if (userEl) {
        userEl.textContent = "Контекст пользователя недоступен";
      }
      return;
    }

    const request = new Request("/entry/user-context", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      credentials: "same-origin"
    });
    token = null;

    try {
      const response = await fetch(request);
      const payload = await response.json().catch(() => null);

      if (!response.ok || !payload || !payload.user) {
        widgetLog("user context exchange failed", { status: response.status, code: payload && payload.code });
        if (userEl) {
          userEl.textContent = "Контекст пользователя недоступен";
        }
        return;
      }

      contextNonce = payload.contextNonce || "";
      if (userEl) {
        userEl.textContent = `${payload.user.userUid} (${payload.user.role})`;
      }
      widgetLog("user context ready", payload.user);

      if (pendingObjectId) {
        const objectId = pendingObjectId;
        pendingObjectId = null;
        loadObject(objectId);
      }
    } catch (error) {
      widgetLog("user context exchange error", { message: error.message || String(error) });
      if (userEl) {
        userEl.textContent = "Контекст пользователя недоступен";
      }
    }
  }

  function loadObject(objectId) {
    if (!objectEl || !getObjectUrl) {
      return;
    }

    if (!contextNonce) {
      pendingObjectId = objectId;
      widgetLog("object fetch deferred", { reason: "waiting for user context" });
      return;
    }

    fetch(getObjectUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        contextNonce,
        objectId
      })
    })
      .then(async (response) => {
        const text = await response.text();

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${text}`);
        }

        return text;
      })
      .then((text) => {
        objectEl.textContent = text;
      })
      .catch((error) => {
        widgetLog("object fetch error", { message: error.message || String(error) });
      });
  }

  const maybeAutoOpenFeedback = (openMessage) => {
    const resolvedId = openMessage == null ? undefined : openMessage.messageId;

    setTimeout(() => {
      const res = sdk.openFeedback(resolvedId);
      widgetLog("auto openFeedback sent", res);
    }, AUTO_OPEN_FEEDBACK_DELAY_MS);
  };

  sdk.onOpen((message) => {
    widgetLog("Event: Open", message);
    maybeAutoOpenFeedback(message);

    if (message && message.objectId) {
      loadObject(message.objectId);
    } else {
      widgetLog("object fetch skipped", { reason: "missing objectId" });
    }
  });

  sdk.onOpenPopup((message) => widgetLog("Event: OpenPopup", message));
  sdk.onChange((message) => {
    widgetLog("Event: Change", message);

    if (!message || !message.objectState) {
      widgetLog("Change ignored", { reason: "missing objectState" });
      return;
    }

    const diffMap = diffs(objectState, message.objectState);

    widgetLog("Event: Change (diff)", formatDiffs(diffMap));

    objectState = message.objectState;
  });
  sdk.onSave((message) => widgetLog("Event: Save", message));

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

  document.getElementById("btnSetDirty").addEventListener("click", () => {
    const res = sdk.setDirty();
    widgetLog("setDirty sent", res);
  });

  document.getElementById("btnClearDirty").addEventListener("click", () => {
    const res = sdk.clearDirty();
    widgetLog("clearDirty sent", res);
  });

  document.getElementById("btnValidation").addEventListener("click", () => {
    const payload = parseMaybeJson(document.getElementById("validationPayload").value);

    let valid = false;
    let message = undefined;
    let changeMessageId = undefined;

    if (payload && typeof payload === "object" && !Array.isArray(payload)) {
      if (payload.valid !== undefined) {
        valid = payload.valid;
      }

      if (payload.message !== undefined) {
        message = payload.message;
      }

      if (payload.changeMessageId !== undefined) {
        changeMessageId = payload.changeMessageId;
      }

      if (payload.correlationId !== undefined) {
        changeMessageId = payload.correlationId;
      }
    } else if (payload !== undefined) {
      message = String(payload);
    }

    const res = sdk.validationFeedback(valid, message, changeMessageId);
    widgetLog("validationFeedback sent", res);
  });

  document.getElementById("btnUpdate").addEventListener("click", async () => {
    const payload = parseMaybeJson(document.getElementById("updatePayload").value);

    try {
      const res = await sdk.update(payload);
      widgetLog("update response", res);
    } catch (e) {
      widgetLog("update error", { message: e.message, name: e.name });
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

  initializeUserContext();
}());
