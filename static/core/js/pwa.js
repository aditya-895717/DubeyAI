(() => {
    "use strict";

    // ------------------------------------------------------------------
    // Service worker registration (every page)
    // ------------------------------------------------------------------
    if ("serviceWorker" in navigator) {
        window.addEventListener("load", () => {
            navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch((err) => {
                console.warn("Service worker registration failed:", err);
            });
        });
    }

    // ------------------------------------------------------------------
    // Custom "Install DubeyAI" button (beforeinstallprompt)
    // ------------------------------------------------------------------
    const installButton = document.getElementById("pwaInstallButton");
    let deferredInstallPrompt = null;

    window.addEventListener("beforeinstallprompt", (event) => {
        event.preventDefault();
        deferredInstallPrompt = event;
        if (installButton) installButton.hidden = false;
    });

    if (installButton) {
        installButton.addEventListener("click", async () => {
            if (!deferredInstallPrompt) return;
            installButton.hidden = true;
            deferredInstallPrompt.prompt();
            await deferredInstallPrompt.userChoice;
            deferredInstallPrompt = null;
        });
    }

    window.addEventListener("appinstalled", () => {
        if (installButton) installButton.hidden = true;
        deferredInstallPrompt = null;
    });

    // ------------------------------------------------------------------
    // Push notification subscription (called from a page-level button,
    // e.g. the chat page's "Enable notifications" control — see chat.js)
    // ------------------------------------------------------------------
    function urlBase64ToUint8Array(base64String) {
        const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
        const rawData = window.atob(base64);
        return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
    }

    window.DubeyAIPush = {
        async subscribe(vapidPublicKey, csrfToken) {
            if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
                return { success: false, reason: "Push notifications aren't supported in this browser." };
            }
            const permission = await Notification.requestPermission();
            if (permission !== "granted") {
                return { success: false, reason: "Notification permission was not granted." };
            }
            const registration = await navigator.serviceWorker.ready;
            const subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
            });
            const response = await fetch("/api/push/subscribe/", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
                body: JSON.stringify(subscription.toJSON()),
            });
            if (!response.ok) {
                return { success: false, reason: "Could not save the subscription on the server." };
            }
            return { success: true };
        },
    };
})();
