(() => {
    "use strict";

    const form = document.getElementById("chatForm");
    if (!form) return;

    const appShell = document.getElementById("appShell");
    const messagesArea = document.getElementById("messagesArea");
    const conversation = document.getElementById("conversation");
    const welcomePanel = document.getElementById("welcomePanel");
    const messageInput = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    const alertBox = document.getElementById("appAlert");
    const historyList = document.getElementById("historyList");
    const historySearch = document.getElementById("historySearch");
    const newChatButton = document.getElementById("newChatButton");
    const clearHistoryButton = document.getElementById("clearHistoryButton");
    const mobileMenuButton = document.getElementById("mobileMenuButton");
    const sidebarBackdrop = document.getElementById("sidebarBackdrop");
    const maxLength = Number(form.dataset.maxLength || 12000);
    let isLoading = false;

    const csrfToken = form.querySelector("[name=csrfmiddlewaretoken]").value;

    function setAlert(message) {
        alertBox.textContent = message;
        alertBox.hidden = !message;
    }

    function setLoading(loading) {
        isLoading = loading;
        messageInput.disabled = loading;
        sendButton.disabled = loading;
        sendButton.querySelector("span").textContent = loading ? "Working" : "Send";
    }

    function resizeInput() {
        messageInput.style.height = "auto";
        messageInput.style.height = `${Math.min(messageInput.scrollHeight, 160)}px`;
    }

    function scrollToBottom(behavior = "smooth") {
        messagesArea.scrollTo({ top: messagesArea.scrollHeight, behavior });
    }

    function formatTime(date = new Date()) {
        return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    }

    function createMessage(role, text, chatId = "") {
        const row = document.createElement("article");
        row.className = `message-row message-${role}`;
        if (chatId) row.dataset.chatId = String(chatId);

        const avatar = document.createElement("div");
        avatar.className = "message-avatar";
        avatar.textContent = role === "user"
            ? document.querySelector(".avatar")?.textContent.trim() || "U"
            : "D";

        const stack = document.createElement("div");
        stack.className = "message-stack";

        const meta = document.createElement("div");
        meta.className = "message-meta";
        const name = document.createElement("strong");
        name.textContent = role === "user" ? "You" : "DubeyAI";
        const time = document.createElement("span");
        time.textContent = formatTime();
        meta.append(name, time);

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        bubble.textContent = text;

        stack.append(meta, bubble);
        row.append(avatar, stack);
        conversation.appendChild(row);
        return row;
    }

    function createLoadingMessage() {
        const row = createMessage("assistant", "");
        row.classList.add("message-loading");
        const bubble = row.querySelector(".message-bubble");
        bubble.replaceChildren();
        for (let index = 0; index < 3; index += 1) {
            const dot = document.createElement("span");
            dot.className = "typing-dot";
            bubble.appendChild(dot);
        }
        return row;
    }

    function addHistoryItem(chat) {
        document.getElementById("historyEmpty")?.remove();
        const button = document.createElement("button");
        button.className = "history-item active";
        button.type = "button";
        button.dataset.chatId = String(chat.id);
        button.dataset.message = chat.message;
        button.dataset.response = chat.response;
        button.dataset.created = chat.created_at;

        const icon = document.createElement("span");
        icon.className = "history-icon";
        icon.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M20 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h9a4 4 0 0 1 4 4z"/></svg>';

        const copy = document.createElement("span");
        copy.className = "history-copy";
        const title = document.createElement("strong");
        title.textContent = chat.message.length > 34 ? `${chat.message.slice(0, 34)}...` : chat.message;
        const date = document.createElement("small");
        date.textContent = "Just now";
        copy.append(title, date);
        button.append(icon, copy);

        historyList.querySelectorAll(".history-item").forEach((item) => item.classList.remove("active"));
        historyList.prepend(button);
    }

    async function parseResponse(response) {
        const contentType = response.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) {
            throw new Error("The server returned an unexpected response.");
        }
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || "The request could not be completed.");
        }
        return data;
    }

    async function sendMessage(message) {
        setLoading(true);
        setAlert("");
        welcomePanel.hidden = true;
        createMessage("user", message);
        const loadingRow = createLoadingMessage();
        scrollToBottom();

        try {
            const response = await fetch(form.dataset.chatUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                    "Accept": "application/json",
                },
                body: JSON.stringify({ message }),
            });
            const data = await parseResponse(response);
            loadingRow.remove();
            createMessage("assistant", data.chat.response, data.chat.id);
            const userRows = conversation.querySelectorAll(".message-user");
            userRows[userRows.length - 1].dataset.chatId = String(data.chat.id);
            addHistoryItem(data.chat);
        } catch (error) {
            loadingRow.remove();
            setAlert(error.message || "Unable to reach the server. Please try again.");
        } finally {
            setLoading(false);
            messageInput.focus();
            scrollToBottom();
        }
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (isLoading) return;
        const message = messageInput.value.trim();
        if (!message) {
            setAlert("Please enter a message.");
            messageInput.focus();
            return;
        }
        if (message.length > maxLength) {
            setAlert(`Message must be ${maxLength.toLocaleString()} characters or fewer.`);
            return;
        }
        messageInput.value = "";
        resizeInput();
        sendMessage(message);
    });

    messageInput.addEventListener("input", resizeInput);
    messageInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    document.querySelectorAll("[data-prompt]").forEach((button) => {
        button.addEventListener("click", () => {
            messageInput.value = button.dataset.prompt;
            resizeInput();
            messageInput.focus();
        });
    });

    newChatButton.addEventListener("click", () => {
        conversation.replaceChildren();
        welcomePanel.hidden = false;
        historyList.querySelectorAll(".history-item").forEach((item) => item.classList.remove("active"));
        setAlert("");
        appShell.classList.remove("sidebar-open");
        messageInput.focus();
    });

    historyList.addEventListener("click", (event) => {
        const item = event.target.closest(".history-item");
        if (!item) return;
        conversation.replaceChildren();
        welcomePanel.hidden = true;
        createMessage("user", item.dataset.message, item.dataset.chatId);
        createMessage("assistant", item.dataset.response, item.dataset.chatId);
        historyList.querySelectorAll(".history-item").forEach((entry) => entry.classList.remove("active"));
        item.classList.add("active");
        appShell.classList.remove("sidebar-open");
        scrollToBottom("auto");
    });

    historySearch.addEventListener("input", () => {
        const query = historySearch.value.trim().toLowerCase();
        historyList.querySelectorAll(".history-item").forEach((item) => {
            const haystack = `${item.dataset.message} ${item.dataset.response}`.toLowerCase();
            item.hidden = Boolean(query) && !haystack.includes(query);
        });
    });

    clearHistoryButton.addEventListener("click", async () => {
        if (!window.confirm("Clear all saved conversations? This cannot be undone.")) return;
        clearHistoryButton.disabled = true;
        setAlert("");
        try {
            const response = await fetch(form.dataset.clearUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: { "X-CSRFToken": csrfToken, "Accept": "application/json" },
            });
            await parseResponse(response);
            historyList.replaceChildren();
            const empty = document.createElement("p");
            empty.className = "history-empty";
            empty.id = "historyEmpty";
            empty.textContent = "Your conversations will appear here.";
            historyList.appendChild(empty);
            conversation.replaceChildren();
            welcomePanel.hidden = false;
        } catch (error) {
            setAlert(error.message || "Could not clear chat history.");
        } finally {
            clearHistoryButton.disabled = false;
        }
    });

    mobileMenuButton.addEventListener("click", () => appShell.classList.add("sidebar-open"));
    sidebarBackdrop.addEventListener("click", () => appShell.classList.remove("sidebar-open"));

    if (conversation.children.length > 0) {
        welcomePanel.hidden = true;
        scrollToBottom("auto");
    }
    resizeInput();
})();
