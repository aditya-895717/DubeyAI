/**
 * DubeyAI — browser voice layer.
 *
 * Three independent pieces, all browser-native (no paid API):
 *   1. Speech-to-text  — SpeechRecognition / webkitSpeechRecognition
 *   2. Text-to-speech  — speechSynthesis
 *   3. Voice commands  — a phrase -> URL matcher that runs BEFORE the AI call
 *
 * IMPORTANT (voice commands): a web page can only navigate to URLs. It CANNOT
 * launch a native desktop or mobile application — browsers sandbox that away.
 * "open whatsapp" therefore opens https://web.whatsapp.com in a new tab. When a
 * command defines a custom scheme (e.g. whatsapp://send) we make a best-effort
 * attempt at it first: that usually works on mobile, is unreliable on desktop,
 * and we always fall back to the web URL after a short timeout if nothing
 * intercepted it.
 */
(() => {
    "use strict";

    const SpeechRecognitionClass =
        window.SpeechRecognition || window.webkitSpeechRecognition || null;

    // Fallback map used if /api/voice-commands/ is unreachable. The live list
    // comes from the VoiceCommand model so it is editable from Django admin.
    const FALLBACK_COMMANDS = [
        { phrase: "open whatsapp", url: "https://web.whatsapp.com", native: "whatsapp://send", label: "WhatsApp" },
        { phrase: "whatsapp khol do", url: "https://web.whatsapp.com", native: "whatsapp://send", label: "WhatsApp" },
        { phrase: "open youtube", url: "https://www.youtube.com", native: "", label: "YouTube" },
        { phrase: "youtube khol do", url: "https://www.youtube.com", native: "", label: "YouTube" },
        { phrase: "open gmail", url: "https://mail.google.com", native: "", label: "Gmail" },
        { phrase: "open google", url: "https://www.google.com", native: "", label: "Google" },
    ];

    let commands = FALLBACK_COMMANDS.slice();

    /** Replace the command list with the admin-managed one from the server. */
    async function loadCommands(url) {
        if (!url) return commands;
        try {
            const response = await fetch(url, {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
            });
            const data = await response.json();
            if (data && data.success && Array.isArray(data.commands) && data.commands.length) {
                commands = data.commands;
            }
        } catch (error) {
            // Keep the fallback list — voice commands are a convenience, not
            // something worth breaking the chat over.
            console.warn("DubeyAI: using fallback voice commands", error);
        }
        return commands;
    }

    function normalize(text) {
        return (text || "")
            .toLowerCase()
            .replace(/[.,!?।]/g, " ")
            .replace(/\s+/g, " ")
            .trim();
    }

    /**
     * Return the matching command for `text`, or null.
     *
     * Longest phrase wins, so "open google maps" is not swallowed by
     * "open google" when both are configured.
     */
    function matchCommand(text, list = commands) {
        const spoken = normalize(text);
        if (!spoken) return null;

        let best = null;
        for (const command of list) {
            const phrase = normalize(command.phrase);
            if (!phrase) continue;
            if (spoken === phrase || spoken.includes(phrase)) {
                if (!best || phrase.length > normalize(best.phrase).length) best = command;
            }
        }
        return best;
    }

    /**
     * Execute a matched command. Tries the native scheme first when one is
     * configured, then falls back to the web URL in a new tab.
     */
    function runCommand(command) {
        if (!command) return false;

        if (command.native) {
            // Best-effort native app launch. If the OS hands the URL to an app,
            // this page loses focus/visibility; if nothing handles it, nothing
            // visible happens and the timeout below opens the web version.
            const frame = document.createElement("iframe");
            frame.style.display = "none";
            frame.src = command.native;
            document.body.appendChild(frame);

            window.setTimeout(() => {
                frame.remove();
                if (!document.hidden) {
                    window.open(command.url, "_blank", "noopener");
                }
            }, 1200);
            return true;
        }

        window.open(command.url, "_blank", "noopener");
        return true;
    }

    // ------------------------------------------------------------------
    // Speech-to-text
    // ------------------------------------------------------------------

    let recognition = null;
    let isListening = false;

    /**
     * Start listening. Calls `onResult(transcript)` once with the final text,
     * `onError(message)` on failure, and `onEnd()` whenever listening stops.
     */
    function startListening({ lang = "en-IN", onResult, onError, onEnd } = {}) {
        if (!SpeechRecognitionClass) {
            onError?.("Voice input needs Chrome or Edge — this browser doesn't support it.");
            return false;
        }
        if (isListening) {
            stopListening();
            return false;
        }

        recognition = new SpeechRecognitionClass();
        recognition.lang = lang;
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;
        recognition.continuous = false;

        recognition.onresult = (event) => {
            const transcript = event.results?.[0]?.[0]?.transcript || "";
            if (transcript.trim()) onResult?.(transcript.trim());
        };

        recognition.onerror = (event) => {
            const messages = {
                "not-allowed": "Microphone access was blocked. Allow it in your browser's site settings to use voice input.",
                "service-not-allowed": "Microphone access was blocked by your browser or OS settings.",
                "no-speech": "I didn't catch anything. Try speaking again.",
                "audio-capture": "No microphone was found. Check that one is connected.",
                network: "Speech recognition needs an internet connection.",
            };
            onError?.(messages[event.error] || "Voice input failed. Please try again.");
        };

        recognition.onend = () => {
            isListening = false;
            onEnd?.();
        };

        try {
            recognition.start();
            isListening = true;
            return true;
        } catch (error) {
            isListening = false;
            onError?.("Could not start voice input. Please try again.");
            return false;
        }
    }

    function stopListening() {
        if (recognition && isListening) {
            try {
                recognition.stop();
            } catch (error) {
                /* already stopped */
            }
        }
        isListening = false;
    }

    // ------------------------------------------------------------------
    // Text-to-speech
    // ------------------------------------------------------------------

    const synth = window.speechSynthesis || null;

    function speak(text, lang = "en-IN") {
        if (!synth || !text) return false;
        synth.cancel(); // never stack two replies on top of each other
        const utterance = new SpeechSynthesisUtterance(text.slice(0, 4000));
        utterance.lang = lang;
        utterance.rate = 1;
        utterance.pitch = 1;
        synth.speak(utterance);
        return true;
    }

    function stopSpeaking() {
        if (synth) synth.cancel();
    }

    window.DubeyAIVoice = {
        isRecognitionSupported: Boolean(SpeechRecognitionClass),
        isSynthesisSupported: Boolean(synth),
        loadCommands,
        matchCommand,
        runCommand,
        startListening,
        stopListening,
        speak,
        stopSpeaking,
        get isListening() {
            return isListening;
        },
    };
})();
