import { mountChat } from "./chat/index.js";

function mountSelectOnFocus(root) {
  root.querySelectorAll("[data-select-on-focus]").forEach((element) => {
    if (!(element instanceof HTMLInputElement) || element.dataset.selectOnFocusMounted === "true") {
      return;
    }

    element.dataset.selectOnFocusMounted = "true";
    element.addEventListener("focus", () => {
      element.select();
    });
  });
}

function mountThreadTitleEdit(root) {
  root.querySelectorAll("[data-thread-title-edit]").forEach((form) => {
    if (!(form instanceof HTMLFormElement) || form.dataset.threadTitleEditMounted === "true") {
      return;
    }

    form.dataset.threadTitleEditMounted = "true";
    form.addEventListener("focusout", (event) => {
      const nextTarget = event.relatedTarget;
      if (nextTarget instanceof Node && form.contains(nextTarget)) {
        return;
      }

      const cancelUrl = form.dataset.threadTitleCancelUrl;
      if (!cancelUrl) {
        return;
      }

      window.htmx.ajax("GET", cancelUrl, {
        target: "#thread-title",
        swap: "outerHTML",
        select: "#thread-title",
      });
    });
  });
}

function boot(documentRoot) {
  mountChat(documentRoot);
  mountSelectOnFocus(documentRoot);
  mountThreadTitleEdit(documentRoot);

  documentRoot.body.addEventListener("htmx:afterSwap", (event) => {
    mountChat(event.target);
    if (event.target instanceof Element) {
      mountSelectOnFocus(event.target);
      mountThreadTitleEdit(event.target);
    }
  });
}

boot(document);
