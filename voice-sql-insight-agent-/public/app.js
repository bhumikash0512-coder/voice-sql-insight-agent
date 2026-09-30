const voiceButton = document.getElementById("voiceButton");
const speakToggle = document.getElementById("speakToggle");
const queryForm = document.getElementById("queryForm");
const queryInput = document.getElementById("queryInput");
const transcript = document.getElementById("transcript");
const statusPill = document.getElementById("statusPill");
const resultTitle = document.getElementById("resultTitle");
const summary = document.getElementById("summary");
const insights = document.getElementById("insights");
const sqlBox = document.getElementById("sqlBox");
const tableWrap = document.getElementById("tableWrap");
const chartWrap = document.getElementById("chart");

const sessionId = localStorage.getItem("voice-sql-session") || crypto.randomUUID();
localStorage.setItem("voice-sql-session", sessionId);

let voiceReplyEnabled = true;
let recognition = null;
let listening = false;

function setStatus(text) {
    statusPill.textContent = text;
}

function addBubble(role, text) {
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role}`;
    bubble.textContent = text;
    transcript.appendChild(bubble);
    transcript.scrollTop = transcript.scrollHeight;
}

function renderInsights(items) {
    insights.innerHTML = "";
    (items || []).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        insights.appendChild(li);
    });
}

function renderTable(rows) {
    if (!rows || !rows.length) {
        tableWrap.innerHTML = "<p class='summary'>No rows returned.</p>";
        return;
    }

    const columns = Object.keys(rows[0]);
    const thead = `<thead><tr>${columns.map((column) => `<th>${column}</th>`).join("")}</tr></thead>`;
    const tbody = rows
        .map((row) => `<tr>${columns.map((column) => `<td>${row[column]}</td>`).join("")}</tr>`)
        .join("");
    tableWrap.innerHTML = `<table>${thead}<tbody>${tbody}</tbody></table>`;
}

function renderChart(rows, chart) {
    if (!rows || !rows.length) {
        chartWrap.innerHTML = "<p class='summary'>No chart data available.</p>";
        return;
    }

    const maxValue = Math.max(...rows.map((row) => Number(row[chart.value_key]) || 0), 1);
    chartWrap.innerHTML = rows
        .map((row) => {
            const value = Number(row[chart.value_key]) || 0;
            const width = Math.max((value / maxValue) * 100, 4);
            return `
                <div class="bar-row">
                    <span>${row[chart.label_key]}</span>
                    <div class="bar" style="width:${width}%"></div>
                    <strong>${value}</strong>
                </div>
            `;
        })
        .join("");
}

function formatPlannerLabel(planner) {
    return planner === "llm" ? "LLM planner" : "Rule planner";
}

function pickVoiceForLang(langCode) {
    const voices = window.speechSynthesis.getVoices();
    if (!voices.length) {
        return null;
    }
    // Try exact match first (e.g. "hi-IN"), then prefix match (e.g. "hi")
    return (
        voices.find((v) => v.lang.toLowerCase() === langCode.toLowerCase()) ||
        voices.find((v) => v.lang.toLowerCase().startsWith(langCode.split("-")[0].toLowerCase())) ||
        null
    );
}

function speak(text, language) {
    if (!voiceReplyEnabled || !("speechSynthesis" in window)) {
        return;
    }

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1;
    utterance.pitch = 1;

    const langCode = language === "hi" ? "hi-IN" : "en-US";
    utterance.lang = langCode;

    const matchedVoice = pickVoiceForLang(langCode);
    if (matchedVoice) {
        utterance.voice = matchedVoice;
    }

    window.speechSynthesis.speak(utterance);
}

async function runQuery(question) {
    addBubble("user", question);
    setStatus("Analyzing");

    const response = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, sessionId }),
    });

    const payload = await response.json();
    if (!response.ok || !payload.success) {
        throw new Error((payload && payload.error) || "Request failed.");
    }

    // Backend wraps the actual result inside { success, data: {...} }
    const result = payload.data;

    resultTitle.textContent = result.title;
    summary.textContent = result.summary;
    renderInsights(result.insights);
    sqlBox.textContent = `[${formatPlannerLabel(result.planner)}]\n${result.sql}`;
    renderTable(result.table);
    renderChart(result.table, result.chart);
    addBubble("agent", result.summary);
    const detectedLanguage = (result.context && result.context.language) || "en";
    speak(result.spoken_response, detectedLanguage);
    setStatus("Ready");
}

queryForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = queryInput.value.trim();
    if (!question) {
        return;
    }

    queryInput.disabled = true;
    try {
        await runQuery(question);
        queryInput.value = "";
    } catch (error) {
        addBubble("agent", error.message);
        setStatus("Error");
    } finally {
        queryInput.disabled = false;
        queryInput.focus();
    }
});

speakToggle.addEventListener("click", () => {
    voiceReplyEnabled = !voiceReplyEnabled;
    speakToggle.textContent = voiceReplyEnabled ? "Voice reply on" : "Voice reply off";
    speakToggle.setAttribute("aria-pressed", String(voiceReplyEnabled));
    if (!voiceReplyEnabled) {
        window.speechSynthesis.cancel();
    }
});

if ("speechSynthesis" in window) {
    // Voices load asynchronously in some browsers; this warms the cache.
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => {
        window.speechSynthesis.getVoices();
    };
}

function setupRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        voiceButton.disabled = true;
        voiceButton.textContent = "Speech unavailable";
        setStatus("Browser STT unavailable");
        return;
    }

    recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
        listening = true;
        setStatus("Listening");
        voiceButton.textContent = "Stop listening";
    };

    recognition.onend = () => {
        listening = false;
        voiceButton.textContent = "Start listening";
        setStatus("Idle");
    };

    recognition.onerror = () => {
        setStatus("Voice error");
    };

    recognition.onresult = async (event) => {
        const transcriptText = event.results[0][0].transcript;
        queryInput.value = transcriptText;
        queryForm.requestSubmit();
    };
}

voiceButton.addEventListener("click", () => {
    if (!recognition) {
        return;
    }
    if (listening) {
        recognition.stop();
    } else {
        recognition.start();
    }
});

setupRecognition();