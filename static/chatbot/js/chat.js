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
    const enableNotificationsButton = document.getElementById("enableNotificationsButton");
    const offlineBanner = document.getElementById("offlineBanner");
    const fileInput = document.getElementById("fileInput");
    const attachButton = document.getElementById("attachButton");
    const attachmentTray = document.getElementById("attachmentTray");
    const micButton = document.getElementById("micButton");
    const voiceLang = document.getElementById("voiceLang");
    const listeningIndicator = document.getElementById("listeningIndicator");
    const ttsToggleButton = document.getElementById("ttsToggleButton");
    const toastStack = document.getElementById("toastStack");
    const maxLength = Number(form.dataset.maxLength || 12000);
    const uploadMaxBytes = Number(form.dataset.uploadMaxBytes || 15 * 1024 * 1024);
    const OFFLINE_QUEUE_KEY = "dubeyai_offline_queue";
    const TTS_PREF_KEY = "dubeyai_tts_enabled";
    const voice = window.DubeyAIVoice || null;
    let isLoading = false;
    let ttsEnabled = localStorage.getItem(TTS_PREF_KEY) === "1";

    const csrfToken = form.querySelector("[name=csrfmiddlewaretoken]").value;

    function setAlert(message) {
        alertBox.textContent = message;
        alertBox.hidden = !message;
    }

    function showToast(message) {
        if (!toastStack) return;
        const toast = document.createElement("div");
        toast.className = "toast";
        toast.textContent = message;
        toastStack.appendChild(toast);
        setTimeout(() => toast.classList.add("is-leaving"), 2600);
        setTimeout(() => toast.remove(), 3200);
    }

    /** Add a replay button to an assistant bubble so any reply can be heard again. */
    function attachSpeakButton(stack, text) {
        if (!voice || !voice.isSynthesisSupported || !text) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "speak-button";
        button.title = "Read this reply aloud";
        button.setAttribute("aria-label", "Read this reply aloud");
        button.innerHTML =
            '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M11 5 6 9H2v6h4l5 4z"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>';
        button.addEventListener("click", () => voice.speak(text, voiceLang ? voiceLang.value : "en-IN"));
        stack.appendChild(button);
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
        if (role === "assistant") attachSpeakButton(stack, text);
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
        if (data.fallback) return data;   // AI fallback — always 200, safe to display
        if (!response.ok || !data.success) {
            throw new Error(data.error || "The request could not be completed.");
        }
        return data;
    }

    // ------------------------------------------------------------------
    // Offline queueing — messages sent while offline are queued in
    // localStorage, shown locally with a "will send once back online" note,
    // and flushed automatically when connectivity returns.
    // ------------------------------------------------------------------

    function getOfflineQueue() {
        try {
            return JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || "[]");
        } catch (err) {
            return [];
        }
    }

    function setOfflineQueue(queue) {
        localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue));
    }

    function updateOfflineBanner() {
        if (offlineBanner) offlineBanner.hidden = navigator.onLine;
    }

    function queueMessageOffline(message) {
        const queue = getOfflineQueue();
        queue.push(message);
        setOfflineQueue(queue);

        welcomePanel.hidden = true;
        createMessage("user", message);
        createMessage("assistant", "You're offline — this message will send once you're back online.");
        scrollToBottom();
        messageInput.value = "";
        resizeInput();
    }

    let isFlushingQueue = false;

    async function flushOfflineQueue() {
        if (isFlushingQueue || !navigator.onLine) return;
        const queue = getOfflineQueue();
        if (!queue.length) return;

        isFlushingQueue = true;
        setOfflineQueue([]);
        for (const queuedMessage of queue) {
            // eslint-disable-next-line no-await-in-loop
            await sendMessage(queuedMessage);
        }
        isFlushingQueue = false;
    }

    async function sendMessage(message) {
        setLoading(true);
        setAlert("");
        welcomePanel.hidden = true;
        createMessage("user", message);
        const loadingRow = createLoadingMessage();
        scrollToBottom();

        // Hard abort after 95 s — prevents the browser hanging indefinitely
        // if Gunicorn is restarting or the network stalls past the server timeout.
        const controller = new AbortController();
        const hardTimeout = setTimeout(() => controller.abort(), 95000);

        // Soft indicator after 5 s — reassures the user Nemotron is still working.
        const slowTimer = setTimeout(() => {
            const bubble = loadingRow.querySelector(".message-bubble");
            if (bubble) bubble.textContent = "Nemotron is thinking deeply… this may take up to 60 seconds.";
        }, 5000);

        try {
            const response = await fetch(form.dataset.chatUrl, {
                method: "POST",
                credentials: "same-origin",
                signal: controller.signal,
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                    "Accept": "application/json",
                },
                body: JSON.stringify({ message }),
            });
            const data = await parseResponse(response);
            loadingRow.remove();
            if (data.fallback) {
                // AI error path — display the server's user-friendly message as a bot reply.
                createMessage("assistant", data.response);
            } else if (data.intent === "open_app") {
                // Command intent — no AI call, no chat history entry. Confirm, then
                // also attempt the web-based fallback (e.g. wa.me) in a new tab.
                createMessage("assistant", data.message);
                if (data.web_fallback_url) {
                    window.open(data.web_fallback_url, "_blank", "noopener");
                }
            } else if (data.intent === "set_alarm") {
                // Reminder intent — confirmation only, handled locally by the
                // companion script (Phase 5), not added to chat history.
                createMessage("assistant", data.message);
            } else {
                createMessage("assistant", data.chat.response, data.chat.id);
                if (ttsEnabled && voice) {
                    voice.speak(data.chat.response, voiceLang ? voiceLang.value : "en-IN");
                }
                const userRows = conversation.querySelectorAll(".message-user");
                userRows[userRows.length - 1].dataset.chatId = String(data.chat.id);
                addHistoryItem(data.chat);
            }
        } catch (error) {
            loadingRow.remove();
            if (error.name === "AbortError") {
                createMessage("assistant", "Response took too long. Please try a shorter question.");
            } else {
                setAlert(error.message || "Unable to reach the server. Please try again.");
            }
        } finally {
            clearTimeout(slowTimer);
            clearTimeout(hardTimeout);
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
        if (!navigator.onLine) {
            queueMessageOffline(message);
            return;
        }
        messageInput.value = "";
        resizeInput();
        sendMessage(message);
    });

    window.addEventListener("online", () => {
        updateOfflineBanner();
        flushOfflineQueue();
    });
    window.addEventListener("offline", updateOfflineBanner);
    updateOfflineBanner();
    flushOfflineQueue();

    if (navigator.serviceWorker) {
        navigator.serviceWorker.addEventListener("message", (event) => {
            if (event.data && event.data.type === "flush-offline-queue") flushOfflineQueue();
        });
    }

    if (enableNotificationsButton && window.DubeyAIPush) {
        enableNotificationsButton.addEventListener("click", async () => {
            const vapidKey = enableNotificationsButton.dataset.vapidPublicKey;
            if (!vapidKey) {
                setAlert("Push notifications aren't configured yet.");
                return;
            }
            enableNotificationsButton.disabled = true;
            const result = await window.DubeyAIPush.subscribe(vapidKey, csrfToken);
            enableNotificationsButton.disabled = false;
            setAlert(result.success ? "Notifications enabled." : result.reason || "Could not enable notifications.");
        });
    }

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
        voice?.stopSpeaking();
        // Detach uploaded documents so an old file is never injected as context
        // into an unrelated new conversation.
        if (attachmentTray) {
            attachmentTray.replaceChildren();
            attachmentTray.hidden = true;
        }
        fetch(form.dataset.clearDocumentsUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: { "X-CSRFToken": csrfToken, Accept: "application/json" },
        }).catch(() => {});
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

    // ------------------------------------------------------------------
    // File attachments
    // ------------------------------------------------------------------

    function renderChip(document_) {
        const chip = document.createElement("span");
        chip.className = `attachment-chip is-${document_.status}`;
        if (document_.id) chip.dataset.documentId = String(document_.id);

        const icon = document.createElement("span");
        icon.innerHTML =
            '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>';

        const name = document.createElement("span");
        name.className = "attachment-name";
        name.textContent = document_.filename;

        const state = document.createElement("span");
        state.className = "attachment-state";
        state.textContent = document_.stateText;

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "attachment-remove";
        remove.setAttribute("aria-label", "Remove attachment");
        remove.textContent = "×";

        chip.append(icon.firstChild, name, state, remove);
        attachmentTray.appendChild(chip);
        attachmentTray.hidden = false;
        return chip;
    }

    async function uploadFile(file) {
        if (file.size > uploadMaxBytes) {
            setAlert(`"${file.name}" is too large. The limit is ${Math.round(uploadMaxBytes / 1048576)} MB.`);
            return;
        }

        setAlert("");
        const chip = renderChip({ filename: file.name, status: "processing", stateText: "Processing..." });
        const state = chip.querySelector(".attachment-state");

        const body = new FormData();
        body.append("file", file);

        try {
            const response = await fetch(form.dataset.uploadUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: { "X-CSRFToken": csrfToken, Accept: "application/json" },
                body,
            });
            const data = await response.json();

            if (!response.ok || !data.success) {
                chip.className = "attachment-chip is-failed";
                state.textContent = "Failed";
                setAlert(data.error || "That file could not be processed.");
                return;
            }

            chip.className = "attachment-chip is-ready";
            chip.dataset.documentId = String(data.document.id);
            state.textContent = "Ready";
            showToast(`"${data.document.filename}" is ready — ask me about it.`);
        } catch (error) {
            chip.className = "attachment-chip is-failed";
            state.textContent = "Failed";
            setAlert("Upload failed. Please check your connection and try again.");
        }
    }

    if (attachButton && fileInput) {
        attachButton.addEventListener("click", () => fileInput.click());
        fileInput.addEventListener("change", () => {
            const [file] = fileInput.files || [];
            if (file) uploadFile(file);
            fileInput.value = ""; // allow re-picking the same file
        });
    }

    if (attachmentTray) {
        attachmentTray.addEventListener("click", async (event) => {
            const button = event.target.closest(".attachment-remove");
            if (!button) return;
            const chip = button.closest(".attachment-chip");
            const documentId = chip?.dataset.documentId;
            chip?.remove();
            if (!attachmentTray.querySelector(".attachment-chip")) attachmentTray.hidden = true;
            if (!documentId) return;
            try {
                await fetch(`/api/documents/${documentId}/remove/`, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "X-CSRFToken": csrfToken, Accept: "application/json" },
                });
            } catch (error) {
                /* the chip is already gone from the UI; nothing useful to say */
            }
        });
    }

    // ------------------------------------------------------------------
    // Voice input / output
    // ------------------------------------------------------------------

    if (voice) {
        voice.loadCommands(form.dataset.voiceCommandsUrl);
    }

    function setListening(listening) {
        if (listeningIndicator) listeningIndicator.hidden = !listening;
        if (micButton) {
            micButton.classList.toggle("is-listening", listening);
            micButton.setAttribute("aria-pressed", String(listening));
        }
    }

    /**
     * Handle a finished transcript. A matched voice command is executed in the
     * browser and never reaches the AI; anything else becomes a normal message.
     */
    function handleTranscript(transcript) {
        const command = voice.matchCommand(transcript);
        if (command) {
            showToast(`Opening ${command.label || command.phrase}...`);
            voice.runCommand(command);
            messageInput.value = "";
            resizeInput();
            return;
        }
        messageInput.value = transcript;
        resizeInput();
        messageInput.focus();
    }

    if (micButton) {
        if (!voice || !voice.isRecognitionSupported) {
            micButton.disabled = true;
            micButton.title = "Voice input needs Chrome or Edge — this browser doesn't support it.";
        } else {
            micButton.addEventListener("click", () => {
                if (voice.isListening) {
                    voice.stopListening();
                    setListening(false);
                    return;
                }
                setAlert("");
                // Flip the indicator on *before* starting: onEnd can fire during
                // startListening() for very short utterances, and setting the
                // state afterwards would leave "Listening..." stuck on screen.
                setListening(true);
                const started = voice.startListening({
                    lang: voiceLang ? voiceLang.value : "en-IN",
                    onResult: handleTranscript,
                    onError: (message) => {
                        setListening(false);
                        setAlert(message);
                    },
                    onEnd: () => setListening(false),
                });
                if (!started) setListening(false);
            });
        }
    }

    if (ttsToggleButton) {
        if (!voice || !voice.isSynthesisSupported) {
            ttsToggleButton.disabled = true;
            ttsToggleButton.title = "This browser can't read replies aloud.";
        } else {
            const syncTts = () => {
                ttsToggleButton.classList.toggle("is-on", ttsEnabled);
                ttsToggleButton.setAttribute("aria-pressed", String(ttsEnabled));
                ttsToggleButton.title = ttsEnabled ? "Stop reading replies aloud" : "Read replies aloud";
            };
            syncTts();
            ttsToggleButton.addEventListener("click", () => {
                ttsEnabled = !ttsEnabled;
                localStorage.setItem(TTS_PREF_KEY, ttsEnabled ? "1" : "0");
                if (!ttsEnabled) voice.stopSpeaking();
                syncTts();
                showToast(ttsEnabled ? "Replies will be read aloud." : "Voice replies off.");
            });
        }
    }

    mobileMenuButton.addEventListener("click", () => appShell.classList.add("sidebar-open"));
    sidebarBackdrop.addEventListener("click", () => appShell.classList.remove("sidebar-open"));

    // Server-rendered history is built by the template, so its assistant bubbles
    // need replay buttons added here rather than in createMessage().
    conversation.querySelectorAll(".message-assistant .message-stack").forEach((stack) => {
        if (stack.querySelector(".speak-button")) return;
        attachSpeakButton(stack, stack.querySelector(".message-bubble")?.innerText || "");
    });

    if (conversation.children.length > 0) {
        welcomePanel.hidden = true;
        scrollToBottom("auto");
    }
    resizeInput();
})();
