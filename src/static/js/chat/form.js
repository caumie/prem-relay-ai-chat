/*
 * チャット送信フォームの振る舞いを扱うファイル。
 *
 * 永続化はサーバー、差し替えは HTMX が担うため、この module はブラウザ側の操作性に
 * 限って責務を持つ。具体的には textarea の高さ調整、キーボード送信、
 * 二重送信防止、添付プレビューの表示と削除を扱う。
 */

import { scrollChatToBottom } from "./scroll.js";

const debounceMsDefault = 400;

export function mountChatForm(root) {
  const form = root.querySelector("[data-chat-form]");
  if (!form || form.dataset.chatMounted === "true") {
    return;
  }

  const textarea = form.querySelector("[data-chat-input]");
  if (!textarea) {
    return;
  }

  const button = form.querySelector("[data-chat-send-button]");
  const assistantSelect = form.querySelector("[name=\"assistant_id\"]");
  const composer = form.querySelector("[data-chat-composer]");
  const fileInput = form.querySelector("[data-chat-file-input]");
  const fileLabel = form.querySelector("[data-chat-file-label]");
  const fileList = form.querySelector("[data-chat-attachment-list]");
  const dropExtensions = form.querySelector("[data-chat-drop-extensions]");
  const previewUrls = [];
  let selectedFiles = fileInput ? Array.from(fileInput.files || []) : [];
  let activeProcessingCount = form.dataset.chatProcessing === "true" ? 1 : 0;
  form.dataset.chatMounted = "true";

  function resize() {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 240) + "px";
  }

  function setBusy(busy) {
    form.dataset.chatSubmitting = busy ? "true" : "false";
    refreshSubmitState();
  }

  function setProcessing(processing) {
    form.dataset.chatProcessing = processing ? "true" : "false";
    refreshSubmitState();
  }

  function refreshSubmitState() {
    if (button) {
      button.disabled =
        form.dataset.chatSubmitting === "true" ||
        form.dataset.chatProcessing === "true";
    }
  }

  function fileUploadAllowed() {
    const option = assistantSelect?.selectedOptions?.[0];
    return option?.dataset.allowFileUpload === "true";
  }

  function allowedFileExtensions() {
    const option = assistantSelect?.selectedOptions?.[0];
    return (option?.dataset.allowedFileExtensions || "")
      .split(",")
      .map((extension) => extension.trim().toLowerCase().replace(/^\.+/, ""))
      .filter(Boolean);
  }

  function fileExtensionAllowed(file) {
    const extensions = allowedFileExtensions();
    const filenameParts = file.name.toLowerCase().split(".");
    const extension = filenameParts.length > 1
      ? filenameParts.at(-1)
      : extensionFromMimeType(file.type);
    return Boolean(extension && extensions.includes(extension));
  }

  function extensionFromMimeType(type) {
    return {
      "image/jpeg": "jpg",
      "image/png": "png",
      "image/gif": "gif",
      "image/webp": "webp",
    }[type] || "";
  }

  function clipboardImageFiles(dataTransfer) {
    if (!dataTransfer) {
      return [];
    }
    return Array.from(dataTransfer.items || [])
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((file) => file instanceof File);
  }

  function filterAllowedFiles(files) {
    if (!fileUploadAllowed()) {
      return [];
    }
    return files.filter(fileExtensionAllowed);
  }

  function fileAcceptValue() {
    return allowedFileExtensions().map((extension) => `.${extension}`).join(",");
  }

  function refreshDropExtensions() {
    if (!dropExtensions) {
      return;
    }
    dropExtensions.textContent = allowedFileExtensions()
      .map((extension) => `.${extension}`)
      .join(", ");
  }

  function refreshFileState() {
    const allowed = fileUploadAllowed();
    if (fileInput) {
      fileInput.disabled = !allowed;
      fileInput.accept = allowed ? fileAcceptValue() : "";
      if (!allowed) {
        replaceFiles([]);
      } else {
        replaceFiles(selectedFiles.filter(fileExtensionAllowed));
      }
    }
    composer?.classList.remove("dropActive");
    fileLabel?.classList.toggle("disabled", !allowed);
    fileLabel?.setAttribute(
      "title",
      allowed ? "Attach file" : "File upload is unavailable for this model",
    );
    refreshDropExtensions();
    renderFileList();
  }

  function renderFileList() {
    if (!fileList) {
      return;
    }

    clearPreviewUrls();
    fileList.replaceChildren();
    const files = selectedFiles;
    fileList.hidden = files.length === 0;
    files.forEach((file, index) => {
      const card = document.createElement("div");
      card.className = "attachmentCard";

      const preview = file.type.startsWith("image/")
        ? buildImagePreview(file)
        : buildFileIcon();
      preview.classList.add("attachmentPreview");

      const name = document.createElement("div");
      name.className = "attachmentName";
      name.textContent = file.name;

      const meta = document.createElement("div");
      meta.className = "attachmentMeta";
      meta.textContent = file.type.startsWith("image/")
        ? "Image"
        : file.type || "File";

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "attachmentRemoveButton iconButton";
      removeButton.dataset.fileIndex = String(index);
      removeButton.setAttribute("aria-label", `Remove ${file.name}`);
      removeButton.innerHTML = '<i class="fas fa-xmark" aria-hidden="true"></i>';

      card.append(preview, name, meta, removeButton);
      fileList.appendChild(card);
    });
  }

  function buildImagePreview(file) {
    const image = document.createElement("img");
    const objectUrl = URL.createObjectURL(file);
    previewUrls.push(objectUrl);
    image.src = objectUrl;
    image.alt = file.name;
    return image;
  }

  function buildFileIcon() {
    const icon = document.createElement("span");
    icon.className = "attachmentIcon";
    icon.innerHTML = '<i class="fas fa-file" aria-hidden="true"></i>';
    return icon;
  }

  function clearPreviewUrls() {
    previewUrls.splice(0).forEach((objectUrl) => {
      URL.revokeObjectURL(objectUrl);
    });
  }

  function replaceFiles(files) {
    if (!fileInput) {
      return;
    }
    selectedFiles = files;
    const dataTransfer = new DataTransfer();
    files.forEach((file) => {
      dataTransfer.items.add(file);
    });
    fileInput.files = dataTransfer.files;
    renderFileList();
  }

  textarea.addEventListener("input", resize);
  assistantSelect?.addEventListener("change", refreshFileState);
  fileInput?.addEventListener("change", () => {
    if (!fileInput) {
      return;
    }
    const incomingFiles = Array.from(fileInput.files || []);
    replaceFiles([...selectedFiles, ...filterAllowedFiles(incomingFiles)]);
  });
  composer?.addEventListener("dragover", (event) => {
    if (!fileUploadAllowed() || !event.dataTransfer?.types.includes("Files")) {
      return;
    }
    event.preventDefault();
    composer.classList.add("dropActive");
  });
  composer?.addEventListener("dragleave", (event) => {
    if (event.relatedTarget instanceof Node && composer.contains(event.relatedTarget)) {
      return;
    }
    composer.classList.remove("dropActive");
  });
  composer?.addEventListener("drop", (event) => {
    event.preventDefault();
    composer.classList.remove("dropActive");
    const droppedFiles = Array.from(event.dataTransfer?.files || []);
    replaceFiles([...selectedFiles, ...filterAllowedFiles(droppedFiles)]);
  });
  textarea.addEventListener("paste", (event) => {
    const pastedFiles = clipboardImageFiles(event.clipboardData);
    const allowedFiles = filterAllowedFiles(pastedFiles);
    if (allowedFiles.length === 0) {
      return;
    }
    event.preventDefault();
    replaceFiles([...selectedFiles, ...allowedFiles]);
  });
  fileList?.addEventListener("click", (event) => {
    const target = event.target instanceof Element
      ? event.target.closest("[data-file-index]")
      : null;
    if (!(target instanceof HTMLButtonElement) || !fileInput) {
      return;
    }

    const removeIndex = Number.parseInt(target.dataset.fileIndex || "", 10);
    if (Number.isNaN(removeIndex)) {
      return;
    }

    const files = Array.from(fileInput.files || []);
    replaceFiles(files.filter((_, index) => index !== removeIndex));
  });
  fileLabel?.addEventListener("click", (event) => {
    if (fileInput?.disabled) {
      event.preventDefault();
      return;
    }
    if (fileInput) {
      fileInput.value = "";
    }
    fileInput?.click();
  });
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", (event) => {
    const now = Date.now();
    const last = Number.parseInt(form.dataset.chatLastSubmittedAt || "0", 10);
    const debounceMs =
      Number.parseInt(form.dataset.chatSubmitDebounceMs || "", 10) ||
      debounceMsDefault;

    if (
      form.dataset.chatSubmitting === "true" ||
      form.dataset.chatProcessing === "true" ||
      now - last < debounceMs ||
      (!textarea.value.trim() && (!fileInput || fileInput.files.length === 0))
    ) {
      event.preventDefault();
      return;
    }

    form.dataset.chatLastSubmittedAt = String(now);
    setBusy(true);
    scrollChatToBottom();
  });

  form.addEventListener("htmx:afterRequest", (event) => {
    setBusy(false);
    if (!event.detail.successful) {
      return;
    }
    textarea.value = "";
    if (fileInput) {
      replaceFiles([]);
    }
    resize();
  });

  document.addEventListener("chat:stream-start", () => {
    if (!document.contains(form)) {
      return;
    }
    activeProcessingCount += 1;
    setProcessing(true);
  });

  document.addEventListener("chat:stream-end", () => {
    if (!document.contains(form)) {
      return;
    }
    activeProcessingCount = Math.max(0, activeProcessingCount - 1);
    setProcessing(activeProcessingCount > 0);
  });

  refreshFileState();
  refreshSubmitState();
  resize();
}
