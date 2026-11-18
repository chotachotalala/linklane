"use strict";

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
let toastTimer;
function toast(message) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.remove("visible"), 3500);
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin", ...options,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": $("meta[name=csrf-token]").content, ...options.headers },
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && $("#workspace")) location.assign("/login");
    throw new Error(data.error || "Не удалось выполнить запрос.");
  }
  return data;
}
function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function errorMessage(error) { return error instanceof TypeError ? "Нет связи с сервером. Проверьте, что он запущен." : error.message; }

const auth = $("#auth-form");
if (auth) auth.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = $("button[type=submit]", auth);
  const error = $("#auth-error");
  error.textContent = "";
  if (auth.dataset.mode === "setup" && $("#password").value !== $("#confirm-password").value) {
    error.textContent = "Пароли не совпадают.";
    return;
  }
  submit.disabled = true;
  try {
    await api(`/api/${auth.dataset.mode}`, { method: "POST", body: JSON.stringify({ password: $("#password").value }) });
    location.assign("/app");
  } catch (failure) { error.textContent = errorMessage(failure); }
  finally { submit.disabled = false; }
});

const workspace = $("#workspace");
if (workspace) {
  let links = [], filter = "all", editing = null, deleting = null;
  const format = new Intl.NumberFormat("ru-RU");
  const labels = { active: "Активна", paused: "На паузе", expired: "Истекла" };
  const dialog = $("#link-dialog");
  let lastFocused;
  function openModal(modal) { lastFocused = document.activeElement; modal.showModal(); }
  $$(".close-modal").forEach((element) => element.addEventListener("click", () => element.closest("dialog").close()));
  $$("dialog").forEach((modal) => modal.addEventListener("close", () => lastFocused?.focus()));

  async function load() {
    const data = await api("/api/overview");
    links = data.links;
    $("#stat-total").textContent = format.format(links.length);
    $("#stat-clicks").textContent = format.format(data.analytics.total_clicks);
    $("#stat-active").textContent = format.format(links.filter((link) => link.status === "active").length);
    $("#nav-count").textContent = links.length;
    $("#collection-count").textContent = links.length;
    render();
    renderAnalytics(data.analytics);
  }
  function rowButton(symbol, title, action) {
    const control = node("button", "icon-button", symbol);
    control.type = "button";
    control.title = title;
    control.setAttribute("aria-label", title);
    control.addEventListener("click", action);
    return control;
  }
  function render() {
    const query = $("#search").value.toLocaleLowerCase("ru").trim();
    const visible = links.filter((link) => (filter === "all" || link.status === filter) &&
      `${link.title} ${link.destination} ${link.slug} ${link.tag}`.toLocaleLowerCase("ru").includes(query));
    const body = $("#links-body");
    body.replaceChildren();
    visible.forEach((link, index) => {
      const row = node("tr");
      const titleCell = node("td");
      const cell = node("div", "link-cell");
      cell.append(node("span", `link-monogram color-${index % 5}`, link.title[0]?.toUpperCase() || "L"));
      const info = node("div", "link-info");
      const title = node("strong", "", link.title);
      title.title = link.destination;
      const address = node("a", "short-address", new URL(link.short_url).host + "/s/" + link.slug + " ↗");
      address.href = "/p/" + encodeURIComponent(link.slug);
      address.target = "_blank";
      address.rel = "noopener";
      address.title = "Предпросмотр: " + link.destination;
      info.append(title, address);
      cell.append(info);
      titleCell.append(cell);
      const tagCell = node("td");
      tagCell.append(node("span", link.tag ? "tag" : "muted", link.tag || "—"));
      const clicks = node("td", "clicks", format.format(link.clicks));
      const status = node("td");
      status.append(node("span", "status-pill " + link.status, labels[link.status]));
      const actionsCell = node("td");
      const actions = node("div", "row-actions");
      actions.append(
        rowButton("⧉", "Скопировать ссылку", () => copy(link.short_url)),
        rowButton("▦", "QR-код", () => showQR(link)),
        rowButton("✎", "Изменить ссылку", () => edit(link)),
        rowButton(link.active ? "Ⅱ" : "▷", link.active ? "Приостановить ссылку" : "Включить ссылку", () => toggle(link)),
        rowButton("×", "Удалить ссылку", () => askDelete(link)),
      );
      actionsCell.append(actions);
      row.append(titleCell, tagCell, clicks, status, actionsCell);
      body.append(row);
    });
    $("#empty-state").hidden = visible.length > 0;
    $("#visible-count").textContent = `Показано ${visible.length} из ${links.length}`;
  }
  function renderAnalytics(analytics) {
    const chart = $("#activity-chart");
    chart.replaceChildren();
    const max = Math.max(1, ...analytics.days.map((day) => day.count));
    analytics.days.forEach((day) => {
      const col = node("div", "chart-column");
      const bar = node("div", "chart-bar");
      bar.style.height = `${Math.max(2, day.count / max * 77)}%`;
      bar.title = `${day.date}: ${day.count}`;
      col.append(node("span", "chart-count", String(day.count)), bar, node("span", "chart-label", day.date.slice(8, 10) + "." + day.date.slice(5, 7)));
      chart.append(col);
    });
    [["#source-list", analytics.sources], ["#browser-list", analytics.browsers]].forEach(([selector, data]) => {
      const parent = $(selector);
      parent.replaceChildren();
      if (!data.length) parent.append(node("p", "muted", "Первые переходы появятся здесь."));
      data.forEach((item) => {
        const row = node("div", "metric-row");
        row.append(node("span", "", item.name), node("strong", "", format.format(item.count)));
        parent.append(row);
      });
    });
  }
  async function copy(value) {
    try { await navigator.clipboard.writeText(value); toast("Ссылка скопирована"); }
    catch { toast("Не удалось скопировать. Откройте предпросмотр и скопируйте адрес вручную."); }
  }
  function edit(link = null) {
    editing = link;
    $("#link-form").reset();
    $("#link-error").textContent = "";
    $("#dialog-title").textContent = link ? "Изменить ссылку" : "Создать ссылку";
    $("#save-link").textContent = link ? "Сохранить изменения" : "Создать ссылку ↗";
    $("#link-title").value = link?.title || "";
    $("#destination").value = link?.destination || "";
    $("#slug").value = link?.slug || "";
    $("#slug").disabled = !!link;
    $("#slug-hint").textContent = link ? "Адрес сохраняется, чтобы ранее отправленные ссылки продолжали работать." : "Оставьте пустым — подберём автоматически. От 3 до 40 символов.";
    $("#tag").value = link?.tag || "";
    $("#link-active").checked = link ? !!link.active : true;
    if (link?.expires_at) {
      const date = new Date(link.expires_at * 1000);
      const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
      $("#expires").value = local.toISOString().slice(0, 16);
    }
    openModal(dialog);
    $("#link-title").focus();
  }
  ["#create-link", "#sidebar-create", "#empty-create"].forEach((selector) => $(selector).addEventListener("click", () => edit()));
  $("#link-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = $("#save-link");
    submit.disabled = true;
    const payload = { title: $("#link-title").value.trim(), destination: $("#destination").value.trim(),
      slug: $("#slug").value.trim(), tag: $("#tag").value.trim(), active: $("#link-active").checked,
      expires_at: $("#expires").value ? new Date($("#expires").value).getTime() / 1000 : null };
    try {
      await api(editing ? `/api/links/${encodeURIComponent(editing.slug)}` : "/api/links", { method: editing ? "PUT" : "POST", body: JSON.stringify(payload) });
      dialog.close();
      await load();
      toast(editing ? "Изменения сохранены" : "Ссылка создана. Можно делиться!");
    } catch (error) { if (dialog.open) $("#link-error").textContent = errorMessage(error); else toast(errorMessage(error)); }
    finally { submit.disabled = false; }
  });
  async function toggle(link) {
    try {
      await api(`/api/links/${encodeURIComponent(link.slug)}`, { method: "PUT", body: JSON.stringify({ ...link, active: !link.active }) });
      await load(); toast(link.active ? "Ссылка на паузе" : "Ссылка включена");
    } catch (error) { toast(errorMessage(error)); }
  }
  function showQR(link) {
    $("#qr-image").src = `/api/links/${encodeURIComponent(link.slug)}/qr.svg`;
    $("#qr-download").href = $("#qr-image").src;
    $("#qr-address").textContent = link.short_url;
    openModal($("#qr-dialog"));
  }
  function askDelete(link) {
    deleting = link;
    $("#delete-description").textContent = `«${link.title}» — /s/${link.slug}`;
    openModal($("#delete-dialog"));
  }
  $("#confirm-delete").addEventListener("click", async () => {
    const control = $("#confirm-delete");
    control.disabled = true;
    try { await api(`/api/links/${encodeURIComponent(deleting.slug)}`, { method: "DELETE" }); $("#delete-dialog").close(); await load(); toast("Ссылка удалена"); }
    catch (error) { toast(errorMessage(error)); }
    finally { control.disabled = false; }
  });
  $("#search").addEventListener("input", render);
  $$(".tab").forEach((tab) => tab.addEventListener("click", () => {
    $$(".tab").forEach((item) => item.classList.toggle("active", item === tab));
    filter = tab.dataset.filter;
    render();
  }));
  $$(".nav-item").forEach((item) => item.addEventListener("click", () => {
    $$(".nav-item").forEach((other) => other.classList.toggle("active", other === item));
    ["links", "analytics", "settings"].forEach((view) => $("#view-" + view).hidden = view !== item.dataset.view);
    $("#breadcrumb").textContent = { links: "Все ссылки", analytics: "Аналитика", settings: "Настройки" }[item.dataset.view];
    if (item.dataset.view === "analytics") load().catch((error) => toast(errorMessage(error)));
  }));
  $("#logout").addEventListener("click", async () => {
    try { await api("/api/logout", { method: "POST" }); location.assign("/login"); }
    catch (error) { toast(errorMessage(error)); }
  });
  $("#password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = $("button[type=submit]", event.currentTarget);
    submit.disabled = true;
    try {
      await api("/api/password", { method: "POST", body: JSON.stringify({ current_password: $("#current-password").value, password: $("#new-password").value }) });
      location.assign("/login");
    } catch (error) { $("#password-error").textContent = errorMessage(error); }
    finally { submit.disabled = false; }
  });
  load().catch((error) => { $("#visible-count").textContent = errorMessage(error); toast(errorMessage(error)); });
}
