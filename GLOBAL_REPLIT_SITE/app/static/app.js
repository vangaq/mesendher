const messagesEl = document.getElementById("messages");
const sendForm = document.getElementById("sendForm");
const textInput = document.getElementById("textInput");
const fileInput = document.getElementById("fileInput");
const preview = document.getElementById("preview");
const previewImg = document.getElementById("previewImg");
const clearImageBtn = document.getElementById("clearImageBtn");
const refreshBtn = document.getElementById("refreshBtn");
const statusEl = document.getElementById("status");

let selectedImageFile = null;
let lastRenderedCount = 0;

function setStatus(text) {
  statusEl.textContent = text || "";
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderMessages(messages) {
  if (!Array.isArray(messages)) return;

  messagesEl.innerHTML = messages.map((msg) => {
    const role = msg.role === "system" ? "system" : msg.role === "assistant" ? "assistant" : "user";
    const text = msg.text ? `<div class="text">${escapeHtml(msg.text)}</div>` : "";
    const image = msg.image_url
      ? `<img src="${msg.image_url}" alt="uploaded image">`
      : "";
    const download = msg.download_url
      ? `<a class="download" href="${msg.download_url}" download>Скачать фото</a>`
      : "";
    const date = msg.created_at ? new Date(msg.created_at).toLocaleString() : "";
    return `
      <div class="msg ${role}">
        <div class="meta">#${msg.id || ""} · ${role} · ${escapeHtml(date)}</div>
        ${text}
        ${image}
        ${download}
      </div>
    `;
  }).join("");

  if (messages.length !== lastRenderedCount) {
    messagesEl.scrollTop = messagesEl.scrollHeight;
    lastRenderedCount = messages.length;
  }
}

async function loadMessages() {
  try {
    const res = await fetch("/api/messages", { cache: "no-store" });
    const data = await res.json();
    renderMessages(data.messages);
  } catch (err) {
    console.error(err);
    setStatus("Ошибка загрузки сообщений.");
  }
}

function setSelectedImage(file) {
  if (!file) return;

  if (!file.type.startsWith("image/")) {
    setStatus("Можно вставлять только изображения.");
    return;
  }

  selectedImageFile = file;

  const url = URL.createObjectURL(file);
  previewImg.src = url;
  preview.classList.remove("hidden");
  setStatus("Фото добавлено. Нажмите “Отправить”.");
}

function clearSelectedImage() {
  selectedImageFile = null;
  fileInput.value = "";
  previewImg.removeAttribute("src");
  preview.classList.add("hidden");
}

fileInput.addEventListener("change", () => {
  const file = fileInput.files && fileInput.files[0];
  if (file) setSelectedImage(file);
});

clearImageBtn.addEventListener("click", (event) => {
  event.preventDefault();
  clearSelectedImage();
});

document.addEventListener("paste", (event) => {
  const items = event.clipboardData && event.clipboardData.items;
  if (!items) return;

  for (const item of items) {
    if (item.type && item.type.startsWith("image/")) {
      const file = item.getAsFile();
      if (file) {
        event.preventDefault();
        const ext = file.type.includes("png") ? "png" : file.type.includes("webp") ? "webp" : "jpg";
        const renamed = new File([file], `clipboard_${Date.now()}.${ext}`, { type: file.type });
        setSelectedImage(renamed);
        return;
      }
    }
  }
});

sendForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const text = textInput.value.trim();
  if (!text && !selectedImageFile) {
    setStatus("Введите текст или добавьте фото.");
    return;
  }

  const form = new FormData();
  form.append("text", text);
  if (selectedImageFile) {
    form.append("file", selectedImageFile);
  }

  setStatus("Отправка...");

  try {
    const res = await fetch("/api/messages", {
      method: "POST",
      body: form,
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Ошибка отправки.");
    }

    textInput.value = "";
    clearSelectedImage();
    setStatus("Отправлено. Задача создана для агента.");
    await loadMessages();
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Ошибка отправки.");
  }
});

refreshBtn.addEventListener("click", loadMessages);

loadMessages();
setInterval(loadMessages, 1500);
