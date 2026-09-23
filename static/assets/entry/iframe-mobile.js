(function () {
  const root = document.querySelector(".mobile-page");
  const state = {
    imageUrl: "",
    videoUrl: "",
    downloadUrl: "",
    cameraStream: null,
    microphoneStream: null,
    audioContext: null,
    microphoneAnimationFrame: 0,
  };

  function $(selector) {
    return document.querySelector(selector);
  }

  function setStatus(id, message, kind) {
    const element = document.getElementById(id);
    if (!element) {
      return;
    }
    element.textContent = message;
    element.classList.remove("is-success", "is-error");
    if (kind) {
      element.classList.add(kind);
    }
  }

  function setBadge(name, supported) {
    const badge = document.querySelector(`[data-support="${name}"]`);
    if (!badge) {
      return;
    }
    badge.textContent = supported ? "Доступно" : "Недоступно";
    badge.classList.toggle("is-supported", supported);
    badge.classList.toggle("is-unsupported", !supported);
  }

  function errorMessage(error) {
    if (!error) {
      return "Неизвестная ошибка";
    }
    if (error.name && error.message) {
      return `${error.name}: ${error.message}`;
    }
    return String(error);
  }

  function revokeUrl(key) {
    if (state[key]) {
      URL.revokeObjectURL(state[key]);
      state[key] = "";
    }
  }

  function formatFileSize(size) {
    if (size < 1024) {
      return `${size} Б`;
    }
    if (size < 1024 * 1024) {
      return `${(size / 1024).toFixed(1)} КБ`;
    }
    return `${(size / 1024 / 1024).toFixed(1)} МБ`;
  }

  function getMediaDevices() {
    return navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === "function";
  }

  function stopStream(stream) {
    if (!stream) {
      return;
    }
    stream.getTracks().forEach((track) => track.stop());
  }

  async function copyText() {
    const input = $("#textInput");
    const area = $("#textArea");
    const text = (input && input.value) || (area && area.value) || "Тестовый текст из мобильного WebView";

    if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
      throw new Error("Clipboard write API недоступен");
    }

    await navigator.clipboard.writeText(text);
    setStatus("clipboardStatus", `Скопировано: ${text}`, "is-success");
  }

  async function readClipboard() {
    const area = $("#textArea");
    if (!navigator.clipboard || typeof navigator.clipboard.readText !== "function") {
      throw new Error("Clipboard read API недоступен");
    }

    const text = await navigator.clipboard.readText();
    if (area) {
      area.value = text;
    }
    setStatus("clipboardStatus", text ? "Текст прочитан из буфера" : "Буфер пуст", "is-success");
  }

  function showImage(file) {
    const preview = $("#imagePreview");
    if (!preview || !file) {
      return;
    }

    revokeUrl("imageUrl");
    state.imageUrl = URL.createObjectURL(file);
    preview.src = state.imageUrl;
    preview.hidden = false;
    setStatus("fileStatus", `Изображение выбрано: ${file.name}`, "is-success");
  }

  function showVideo(file) {
    const preview = $("#videoPreview");
    if (!preview || !file) {
      return;
    }

    revokeUrl("videoUrl");
    state.videoUrl = URL.createObjectURL(file);
    preview.src = state.videoUrl;
    preview.hidden = false;
    preview.load();
    setStatus("fileStatus", `Видео выбрано: ${file.name}`, "is-success");
  }

  function showFiles(files) {
    const list = $("#fileList");
    if (!list) {
      return;
    }

    list.innerHTML = "";
    Array.from(files).forEach((file) => {
      const item = document.createElement("li");
      item.textContent = `${file.name} (${formatFileSize(file.size)}, ${file.type || "тип не указан"})`;
      list.appendChild(item);
    });
    setStatus("fileStatus", files.length ? `Файлы доступны в WebView: ${files.length}` : "Файлы не выбраны", files.length ? "is-success" : "");
  }

  function downloadFile() {
    revokeUrl("downloadUrl");
    const payload = [
      "Python Demo App mobile WebView check",
      `time=${new Date().toISOString()}`,
      `userAgent=${navigator.userAgent}`,
      `sessionNoncePresent=${root && root.dataset.contextNonce ? "yes" : "no"}`,
      "",
    ].join("\n");
    const blob = new Blob([payload], { type: "text/plain;charset=utf-8" });
    state.downloadUrl = URL.createObjectURL(blob);

    const link = document.createElement("a");
    link.href = state.downloadUrl;
    link.download = "webview-check.txt";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setStatus("fileStatus", "Скачивание тестового файла запущено", "is-success");
  }

  async function startCamera() {
    if (!getMediaDevices()) {
      throw new Error("getUserMedia недоступен");
    }

    const preview = $("#cameraPreview");
    stopCamera();
    state.cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });

    if (preview) {
      preview.srcObject = state.cameraStream;
      preview.hidden = false;
      await preview.play();
    }
    setStatus("cameraStatus", "Камера включена", "is-success");
  }

  function stopCamera() {
    const preview = $("#cameraPreview");
    stopStream(state.cameraStream);
    state.cameraStream = null;
    if (preview) {
      preview.pause();
      preview.srcObject = null;
      preview.hidden = true;
    }
    setStatus("cameraStatus", "Камера остановлена", "");
  }

  async function startMicrophone() {
    if (!getMediaDevices()) {
      throw new Error("getUserMedia недоступен");
    }

    stopMicrophone();
    state.microphoneStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      setStatus("microphoneStatus", "Доступ к микрофону получен, AudioContext недоступен для уровня сигнала", "is-success");
      return;
    }

    state.audioContext = new AudioContextClass();
    const source = state.audioContext.createMediaStreamSource(state.microphoneStream);
    const analyser = state.audioContext.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);

    const data = new Uint8Array(analyser.frequencyBinCount);
    const level = $("#microphoneLevel");

    function updateLevel() {
      analyser.getByteFrequencyData(data);
      const average = data.reduce((sum, value) => sum + value, 0) / data.length;
      if (level) {
        level.style.width = `${Math.min(100, Math.round((average / 255) * 140))}%`;
      }
      state.microphoneAnimationFrame = window.requestAnimationFrame(updateLevel);
    }

    updateLevel();
    setStatus("microphoneStatus", "Микрофон включен", "is-success");
  }

  function stopMicrophone() {
    const level = $("#microphoneLevel");
    if (state.microphoneAnimationFrame) {
      window.cancelAnimationFrame(state.microphoneAnimationFrame);
      state.microphoneAnimationFrame = 0;
    }
    if (state.audioContext) {
      state.audioContext.close();
      state.audioContext = null;
    }
    stopStream(state.microphoneStream);
    state.microphoneStream = null;
    if (level) {
      level.style.width = "0";
    }
    setStatus("microphoneStatus", "Микрофон остановлен", "");
  }

  function getLocation() {
    if (!navigator.geolocation) {
      setStatus("locationStatus", "Geolocation API недоступен", "is-error");
      return;
    }

    const output = $("#locationOutput");
    setStatus("locationStatus", "Запрашиваем координаты...", "");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const payload = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy: position.coords.accuracy,
          timestamp: new Date(position.timestamp).toISOString(),
        };
        if (output) {
          output.textContent = JSON.stringify(payload, null, 2);
        }
        setStatus("locationStatus", "Координаты получены", "is-success");
      },
      (error) => {
        setStatus("locationStatus", errorMessage(error), "is-error");
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 },
    );
  }

  function bindActions() {
    document.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-action]");
      if (!button) {
        return;
      }

      const action = button.dataset.action;
      button.disabled = true;
      try {
        if (action === "copy-text") {
          await copyText();
        } else if (action === "read-clipboard") {
          await readClipboard();
        } else if (action === "download-file") {
          downloadFile();
        } else if (action === "start-camera") {
          await startCamera();
        } else if (action === "stop-camera") {
          stopCamera();
        } else if (action === "start-microphone") {
          await startMicrophone();
        } else if (action === "stop-microphone") {
          stopMicrophone();
        } else if (action === "get-location") {
          getLocation();
        }
      } catch (error) {
        if (action.includes("clipboard")) {
          setStatus("clipboardStatus", errorMessage(error), "is-error");
        } else if (action.includes("camera")) {
          setStatus("cameraStatus", errorMessage(error), "is-error");
        } else if (action.includes("microphone")) {
          setStatus("microphoneStatus", errorMessage(error), "is-error");
        } else {
          setStatus("fileStatus", errorMessage(error), "is-error");
        }
      } finally {
        button.disabled = false;
      }
    });

    const imagePicker = $("#imagePicker");
    if (imagePicker) {
      imagePicker.addEventListener("change", () => showImage(imagePicker.files[0]));
    }

    const videoPicker = $("#videoPicker");
    if (videoPicker) {
      videoPicker.addEventListener("change", () => showVideo(videoPicker.files[0]));
    }

    const filePicker = $("#filePicker");
    if (filePicker) {
      filePicker.addEventListener("change", () => showFiles(filePicker.files));
    }
  }

  function initSupportBadges() {
    setBadge("clipboard", Boolean(navigator.clipboard));
    setBadge("file", Boolean(window.File && window.URL && URL.createObjectURL));
    setBadge("camera", getMediaDevices());
    setBadge("microphone", getMediaDevices());
    setBadge("geolocation", Boolean(navigator.geolocation));
  }

  window.addEventListener("pagehide", () => {
    stopCamera();
    stopMicrophone();
    revokeUrl("imageUrl");
    revokeUrl("videoUrl");
    revokeUrl("downloadUrl");
  });

  initSupportBadges();
  bindActions();
})();
