"use strict";

// Shared helpers for all pages. Everything user-supplied is rendered with
// textContent / DOM nodes (never innerHTML), so task text cannot inject markup.

function getToken() {
    return localStorage.getItem("token");
}

function isAdmin() {
    return localStorage.getItem("role") === "admin";
}

function logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("role");
    window.location.href = "/";
}

// Call at the top of a protected page. The API enforces auth either way.
function requireLogin() {
    if (!getToken()) {
        window.location.href = "/";
        return false;
    }
    return true;
}

function errorMessage(detail) {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
    return "Something went wrong";
}

async function api(path, { method = "GET", json } = {}) {
    const headers = { Authorization: `Bearer ${getToken()}` };
    const options = { method, headers };
    if (json !== undefined) {
        headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(json);
    }

    const response = await fetch(path, options);
    if (response.status === 401) {
        logout();
        throw new Error("Session expired. Please log in again.");
    }
    if (!response.ok) {
        let detail;
        try {
            detail = (await response.json()).detail;
        } catch (_) {
            /* body was not JSON */
        }
        throw new Error(errorMessage(detail));
    }
    return response.status === 204 ? null : response.json();
}

function showMessage(text) {
    const el = document.getElementById("message");
    if (el) el.textContent = text || "";
}

function cell(text) {
    const td = document.createElement("td");
    td.textContent = text;
    return td;
}

function actionButton(label, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
}

// actionsFor(task) returns an array of buttons for the last column.
function renderTasks(tbody, tasks, actionsFor) {
    tbody.replaceChildren();
    for (const task of tasks) {
        const row = document.createElement("tr");
        const assignee = task.assignee ? `${task.assignee.username}, ${task.assignee.id}` : "Unassigned";
        const actions = document.createElement("td");
        actions.append(...actionsFor(task));
        row.append(cell(task.id), cell(task.description), cell(task.priority), cell(task.status), cell(assignee), actions);
        tbody.append(row);
    }
}
