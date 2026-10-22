"use strict";

const form = document.getElementById("search-form");
const input = document.getElementById("query");
const region = document.getElementById("results-region");
const status = document.getElementById("status");
const results = document.getElementById("results");
const message = document.getElementById("message");
const messageTitle = document.getElementById("message-title");
const messageBody = document.getElementById("message-body");
let activeController = null;
let requestSequence = 0;

function showMessage(title, body) {
  messageTitle.textContent = title;
  messageBody.textContent = body;
  message.hidden = false;
}

function setBusy(busy) {
  region.setAttribute("aria-busy", String(busy));
}

function updateAddress(query) {
  const url = new URL(window.location.href);
  if (query) url.searchParams.set("q", query);
  else url.searchParams.delete("q");
  window.history.replaceState(null, "", url);
}

function appendHighlightedText(parent, text, ranges) {
  const characters = Array.from(text);
  let cursor = 0;
  const validRanges = Array.isArray(ranges)
    ? ranges.filter((range) => (
      range && Number.isInteger(range.start) && Number.isInteger(range.end) &&
      range.start >= 0 && range.end > range.start && range.end <= characters.length
    )).sort((a, b) => a.start - b.start || a.end - b.end) : [];
  for (const range of validRanges) {
    if (range.start < cursor) continue;
    parent.appendChild(document.createTextNode(characters.slice(cursor, range.start).join("")));
    const mark = document.createElement("mark");
    mark.className = "bg-yellow-200 text-gray-900 rounded px-1";
    mark.textContent = characters.slice(range.start, range.end).join("");
    parent.appendChild(mark);
    cursor = range.end;
  }
  parent.appendChild(document.createTextNode(characters.slice(cursor).join("")));
}

function safeDocumentUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
    return url;
  } catch { return null; }
}

function renderResult(result) {
  const item = document.createElement("li");
  item.className = "rounded-2xl border border-gray-700 bg-gray-800 p-6";
  const article = document.createElement("article");
  const heading = document.createElement("h3");
  heading.className = "text-xl font-semibold";
  const url = safeDocumentUrl(result.url);
  const title = document.createElement(url ? "a" : "span");
  if (url) {
    title.href = url.href;
    title.target = "_blank";
    title.rel = "noopener noreferrer";
    title.className = "text-indigo-300 hover:text-indigo-200 focus:outline-none focus:ring-2 focus:ring-indigo-400 rounded";
  }
  appendHighlightedText(title, result.title, result.title_highlights);
  heading.appendChild(title);
  const address = document.createElement("p");
  address.className = "mt-2 text-xs text-gray-400 break-all";
  address.textContent = url ? url.href : "Document URL unavailable";
  const snippet = document.createElement("p");
  snippet.className = "mt-3 text-gray-300 leading-relaxed";
  appendHighlightedText(snippet, result.snippet, result.snippet_highlights);
  article.append(heading, address, snippet);
  item.appendChild(article);
  return item;
}

function isValidResponse(data) {
  return data && Number.isInteger(data.total) && data.total >= 0 &&
    Number.isInteger(data.returned) && data.returned >= 0 && data.returned <= data.total &&
    Number.isFinite(data.took_ms) && data.took_ms >= 0 &&
    Array.isArray(data.results) && data.results.length === data.returned &&
    data.results.every((result) => result && typeof result.id === "string" &&
      typeof result.title === "string" && typeof result.url === "string" &&
      typeof result.snippet === "string");
}

async function runSearch() {
  const sequence = ++requestSequence;
  if (activeController) activeController.abort();
  activeController = null;
  const query = input.value.trim().replace(/\s+/gu, " ");
  results.replaceChildren();
  setBusy(false);
  input.removeAttribute("aria-invalid");
  updateAddress(query);
  if (!query) {
    status.textContent = "Enter a query to search.";
    showMessage("What would you like to find?", "Type one or more words in the search box.");
    input.focus();
    return;
  }
  if (Array.from(query).length > 200) {
    input.setAttribute("aria-invalid", "true");
    status.textContent = "The query is too long.";
    showMessage("Shorten your search", "Use no more than 200 characters.");
    return;
  }
  const controller = new AbortController();
  activeController = controller;
  let timedOut = false;
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 15000);
  setBusy(true);
  message.hidden = true;
  status.textContent = `Searching for “${query}”…`;
  try {
    const parameters = new URLSearchParams({ q: query, limit: "10" });
    const response = await fetch(`/api/search?${parameters}`, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
      cache: "no-store"
    });
    let data;
    try { data = await response.json(); }
    catch { throw new Error("The server returned an unreadable response."); }
    if (sequence !== requestSequence) return;
    if (!response.ok) {
      if (response.status === 400 || response.status === 422) input.setAttribute("aria-invalid", "true");
      throw new Error(typeof data?.error?.message === "string"
        ? data.error.message : `Search failed with HTTP ${response.status}.`);
    }
    if (!isValidResponse(data)) throw new Error("The server returned an unexpected response.");
    if (data.total === 0) {
      status.textContent = `No matches for “${query}”.`;
      showMessage("No documents found", "Try a different word or a broader query. Search matches words in the documents.");
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const result of data.results) fragment.appendChild(renderResult(result));
    results.appendChild(fragment);
    status.textContent = `${data.total} ${data.total === 1 ? "match" : "matches"} · Showing ${data.returned} · ${data.took_ms.toFixed(2)} ms`;
  } catch (error) {
    if (sequence !== requestSequence) return;
    if (error.name === "AbortError" && !timedOut) return;
    results.replaceChildren();
    status.textContent = "Search could not be completed.";
    showMessage(timedOut ? "The server took too long" : "Something went wrong",
      timedOut ? "Check that the local server is running, then search again."
        : error instanceof TypeError ? "Cannot reach the local server. Check your connection and try again."
          : error.message || "Please try your search again.");
  } finally {
    window.clearTimeout(timeout);
    if (sequence === requestSequence) {
      activeController = null;
      setBusy(false);
    }
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  runSearch();
});
document.querySelectorAll("[data-query]").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.dataset.query;
    runSearch();
  });
});
const initialQuery = new URL(window.location.href).searchParams.get("q");
if (initialQuery !== null) {
  input.value = initialQuery;
  runSearch();
}
