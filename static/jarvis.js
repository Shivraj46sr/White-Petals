(() => {
  const root = document.querySelector("[data-assistant-root]");
  if (!root) return;

  const form = root.querySelector("[data-assistant-form]");
  const input = root.querySelector("[data-chat-input]");
  const log = root.querySelector("[data-chat-log]");
  const status = root.querySelector("[data-chat-status]");
  const stateLabel = root.querySelector("[data-core-state]");
  const providerLabel = root.querySelector("[data-provider-state]");
  const voiceNote = root.querySelector("[data-voice-note]");
  const voiceButton = root.querySelector("[data-voice]");
  const stopListeningButton = root.querySelector("[data-stop-listening]");
  const cancelButton = root.querySelector("[data-cancel]");
  const speakToggle = root.querySelector("[data-speak]");
  const freshness = root.querySelector("[data-freshness]");
  const initialMessage = log.querySelector(".system-message")?.textContent || "";
  const storageKey = "whitepetals.jarvis.conversation.v1";
  const quickCommands = {
    pipeline: "Summarize the current sales pipeline.",
    follow_ups: "Which follow-ups are due?",
    research: "How many active leads need research?",
  };
  let controller = null;
  let recognition = null;

  if (freshness) {
    const renderedAt = Number(freshness.dataset.renderedAt);
    const staleAfterMs = 5 * 60 * 1000;
    if (Number.isFinite(renderedAt) && renderedAt > 0) {
      const markStaleIfNeeded = () => {
        const remaining = staleAfterMs - (Date.now() - renderedAt);
        if (remaining <= 0) {
          freshness.textContent = "This CRM snapshot may be stale · refresh to load current records.";
          freshness.classList.add("stale");
        } else {
          window.setTimeout(markStaleIfNeeded, remaining);
        }
      };
      markStaleIfNeeded();
    }
  }

  function setState(state, message) {
    root.dataset.state = state.toLowerCase();
    document.body.dataset.state = state.toLowerCase();
    stateLabel.textContent = state.toUpperCase();
    status.textContent = message;
  }

  function saveConversation() {
    const entries = Array.from(log.querySelectorAll("[data-message]")).slice(-40);
    const conversation = entries.map((entry) => ({
      role: entry.dataset.message,
      text: entry.querySelector(".message-content").textContent,
    }));
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(conversation));
    } catch {
      status.textContent = "Conversation storage is unavailable; this session will not persist after closing the tab.";
    }
  }

  function addMessage(role, text, action) {
    const article = document.createElement("article");
    article.className = `chat-message ${role}`;
    article.dataset.message = role;
    const label = document.createElement("span");
    label.className = "message-label";
    label.textContent = role === "user" ? "YOU" : "JARVIS";
    const content = document.createElement("p");
    content.className = "message-content";
    content.textContent = text;
    article.append(label, content);
    if (action && action.url && action.label && action.url.startsWith("/") && !action.url.startsWith("//")) {
      const link = document.createElement("a");
      link.className = "message-action";
      link.href = action.url;
      link.textContent = action.label;
      article.append(link);
    }
    log.append(article);
    log.scrollTop = log.scrollHeight;
    saveConversation();
    return content;
  }

  function getRecentConversation() {
    return Array.from(log.querySelectorAll("[data-message]"))
      .filter((entry) => !entry.classList.contains("error"))
      .map((entry) => ({
        role: entry.dataset.message,
        text: entry.querySelector(".message-content").textContent,
      }))
      .filter((entry) => entry.text && entry.text !== "Working…")
      .slice(-8)
      .map((entry) => ({ role: entry.role, text: entry.text.slice(0, 800) }));
  }

  function restoreConversation() {
    let saved;
    try {
      saved = JSON.parse(sessionStorage.getItem(storageKey) || "[]");
    } catch {
      return;
    }
    if (!Array.isArray(saved)) return;
    for (const item of saved.slice(-40)) {
      if (item && (item.role === "user" || item.role === "assistant") && typeof item.text === "string") {
        addMessage(item.role, item.text);
      }
    }
  }

  async function submit(message, command = "") {
    if (controller) return;
    const text = message.trim();
    if (!text) {
      input.focus();
      return;
    }
    recognition?.stop();
    const history = command ? [] : getRecentConversation();
    addMessage("user", text);
    const assistantMessage = addMessage("assistant", "Working…");
    const activeController = new AbortController();
    controller = activeController;
    cancelButton.disabled = false;
    form.querySelector('[type="submit"]').disabled = true;
    setState(command ? "Executing" : "Thinking", command
      ? "Executing · Reading current CRM records…"
      : "Thinking · Sending your question, recent chat context, and aggregate CRM metrics to the configured provider…");

    const formData = new URLSearchParams();
    formData.set("csrf_token", form.querySelector('[name="csrf_token"]').value);
    formData.set("message", text);
    if (command) formData.set("command", command);
    if (history.length) formData.set("history", JSON.stringify(history));

    try {
      const response = await fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
        body: formData,
        signal: activeController.signal,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `Request failed with status ${response.status}.`);
      assistantMessage.textContent = payload.answer;
      providerLabel.textContent = payload.provider;
      const article = assistantMessage.closest("[data-message]");
      if (payload.action_url && payload.action_label && payload.action_url.startsWith("/") && !payload.action_url.startsWith("//")) {
        const link = document.createElement("a");
        link.className = "message-action";
        link.href = payload.action_url;
        link.textContent = payload.action_label;
        article.append(link);
      }
      saveConversation();
      if (speakToggle.checked && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(payload.answer);
        utterance.onstart = () => setState("Speaking", "Speaking · Text remains available in the conversation.");
        utterance.onend = () => setState("Ready", `Ready · Response from ${payload.provider}.`);
        utterance.onerror = () => setState("Error", "Speech playback failed. The text response is still available.");
        setState("Speaking", "Speaking · Text remains available in the conversation.");
        window.speechSynthesis.speak(utterance);
      } else {
        setState("Ready", `Ready · Response from ${payload.provider}.`);
      }
    } catch (error) {
      assistantMessage.textContent = error.name === "AbortError"
        ? "Response cancelled in this view. The server may have completed processing."
        : error.message;
      assistantMessage.closest("[data-message]")?.classList.add("error");
      saveConversation();
      setState(error.name === "AbortError" ? "Ready" : "Error",
        error.name === "AbortError" ? "Ready · Response wait cancelled." : `Error · ${error.message}`);
    } finally {
      if (controller === activeController) controller = null;
      cancelButton.disabled = true;
      form.querySelector('[type="submit"]').disabled = false;
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = input.value;
    input.value = "";
    submit(message);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  root.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", () => {
      const command = button.dataset.command;
      submit(quickCommands[command] || "", command);
    });
  });

  cancelButton.addEventListener("click", () => controller?.abort());
  root.querySelector("[data-clear]").addEventListener("click", () => {
    controller?.abort();
    recognition?.stop();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    let storageCleared = true;
    try {
      sessionStorage.removeItem(storageKey);
    } catch {
      storageCleared = false;
    }
    log.replaceChildren();
    if (initialMessage) {
      const intro = document.createElement("p");
      intro.className = "system-message";
      intro.textContent = initialMessage;
      log.append(intro);
    }
    setState("Ready", storageCleared
      ? "Ready · Conversation cleared from this browser tab."
      : "Ready · Conversation cleared from view, but browser storage could not be cleared.");
  });

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    voiceButton.disabled = true;
    voiceNote.textContent = "Voice input is not supported by this browser. Text input is available.";
  } else {
    voiceButton.addEventListener("click", () => {
      recognition = new SpeechRecognition();
      recognition.lang = navigator.language || "en-IN";
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.onstart = () => {
        voiceButton.disabled = true;
        stopListeningButton.hidden = false;
        setState("Listening", "Listening · Speak your command, then review the recognized text before sending.");
      };
      recognition.onresult = (event) => {
        let transcript = "";
        let finalTranscript = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const phrase = event.results[index][0].transcript;
          transcript += phrase;
          if (event.results[index].isFinal) finalTranscript += phrase;
        }
        if (transcript) {
          input.value = transcript.trim();
          voiceNote.textContent = finalTranscript
            ? "Recognized speech is in the text field. Review or edit it, then choose Send."
            : `Recognizing: ${transcript}`;
        }
      };
      recognition.onerror = (event) => {
        const denied = event.error === "not-allowed" || event.error === "service-not-allowed";
        voiceNote.textContent = denied
          ? "Microphone permission was denied. Allow microphone access in browser settings or use text input."
          : `Voice input failed (${event.error}). Text input is available.`;
        setState("Error", voiceNote.textContent);
      };
      recognition.onend = () => {
        voiceButton.disabled = false;
        stopListeningButton.hidden = true;
        recognition = null;
        if (root.dataset.state === "listening") setState("Ready", "Ready · Review recognized text before sending.");
      };
      try {
        recognition.start();
      } catch (error) {
        voiceNote.textContent = "Voice input could not start. Check browser microphone permissions or use text input.";
        setState("Error", voiceNote.textContent);
        recognition = null;
      }
    });
    stopListeningButton.addEventListener("click", () => recognition?.stop());
  }

  if (!("speechSynthesis" in window)) {
    speakToggle.disabled = true;
    voiceNote.textContent = "Spoken replies are not supported by this browser. Text replies remain available.";
  }

  restoreConversation();
})();
