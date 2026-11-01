"use strict";

// Show only the fields of the selected entry type. Hidden inputs are disabled so they aren't submitted.
function syncType(form) {
  const checked = form.querySelector('input[name="type"]:checked');
  const type = checked ? checked.value : "expense";
  form.querySelectorAll("[data-show-for]").forEach((el) => {
    const on = el.dataset.showFor.split(" ").includes(type);
    el.hidden = !on;
    el.querySelectorAll("input, select, textarea").forEach((i) => (i.disabled = !on));
  });
}

// A main category tile reveals its subcategory row; a selected sub keeps its main tile highlighted.
function syncSubrows(form) {
  const sel = form.querySelector('input[name="category_id"]:checked:not(:disabled)');
  const main = sel ? sel.dataset.parent || sel.value : null;
  form.querySelectorAll(".subrow").forEach((row) => (row.hidden = row.dataset.parent !== main));
  form.querySelectorAll(".tile[data-main]").forEach((tile) =>
    tile.classList.toggle("parent-selected", !!sel && !!sel.dataset.parent && tile.dataset.main === main),
  );
}

// Recurring template form: show the day field matching the selected frequency.
function syncFrequency(form) {
  const select = form.querySelector("select[data-frequency]");
  if (!select) return;
  form.querySelectorAll("[data-freq-for]").forEach((el) => {
    el.hidden = !el.dataset.freqFor.split(" ").includes(select.value);
  });
}

function initEntryForm(form) {
  syncType(form);
  syncSubrows(form);
  syncFrequency(form);
}

document.addEventListener("change", (e) => {
  const form = e.target.form;
  if (!form || !form.matches("[data-entry-form]")) return;
  if (e.target.name === "type") syncType(form);
  if (e.target.name === "type" || e.target.name === "category_id") syncSubrows(form);
  if (e.target.name === "frequency") syncFrequency(form);
});

// Forms with data-autosubmit reload on every change (statistics filters).
document.addEventListener("change", (e) => {
  const form = e.target.form;
  if (form && form.hasAttribute("data-autosubmit")) form.requestSubmit();
});

// Forms with data-confirm ask before submitting (deletes).
document.addEventListener("submit", (e) => {
  const msg = e.target.dataset && e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) e.preventDefault();
});

// Toast hides itself after 5 seconds (this also ends the undo window in the UI).
let toastTimer;
function armToast(toast) {
  clearTimeout(toastTimer);
  if (!toast.children.length) return;
  toastTimer = setTimeout(() => toast.replaceChildren(), 5000);
}

// Drag to reorder: <ul data-sortable data-reorder-url="…"> with <li data-id>.
function initSortable(list) {
  if (!window.Sortable || list.sortable) return;
  list.sortable = window.Sortable.create(list, {
    handle: list.dataset.handle || ".handle",
    animation: 150,
    onEnd() {
      const body = new URLSearchParams();
      for (const li of list.children) if (li.dataset.id) body.append("ids", li.dataset.id);
      fetch(list.dataset.reorderUrl, { method: "POST", body });
    },
  });
}

function init(root) {
  const scope = root.querySelectorAll ? root : document;
  if (scope.matches && scope.matches("[data-entry-form]")) initEntryForm(scope);
  scope.querySelectorAll("[data-entry-form]").forEach(initEntryForm);
  scope.querySelectorAll("[data-sortable]").forEach(initSortable);
  if (scope.id === "toast") armToast(scope);
  // After a quick-add save the fresh form comes back: focus the amount again.
  if (scope.id === "entry-form" && scope.hasAttribute("hx-post")) {
    const amount = scope.querySelector('input[name="amount"]');
    if (amount) amount.focus();
  }
}

htmx.onLoad(init);
