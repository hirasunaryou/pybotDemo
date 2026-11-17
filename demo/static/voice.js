"use strict";
/* Browser speech recognition is ONLY a text-entry convenience.
 * It never calls /api/ask and never records or uploads audio in this app.
 * Depending on the browser, recognition may use a vendor's cloud service.
 */
(function () {
  const button = document.getElementById("voiceBtn");
  const label = document.getElementById("voiceBtnText");
  const field = document.getElementById("questionInput");
  const status = document.getElementById("voiceStatus");
  const pulse = document.getElementById("voicePulse");
  const language = document.getElementById("voiceLang");
  if (!button || !field || !status || !language) return;

  const Engine = window.SpeechRecognition || window.webkitSpeechRecognition;
  const fallback = "このブラウザは音声認識に未対応です。Macの音声入力、Windowsの Win+H でも入力できます。";
  if (!Engine) {
    button.disabled = true;
    button.title = fallback;
    button.setAttribute("aria-label", fallback);
    status.textContent = fallback;
    return;
  }

  let recognizer = null;
  let recording = false;
  let base = "";
  let finalText = "";
  let latestInterim = "";
  let failed = false;

  function appendText(before, after) {
    const join = before && after ? (/[ \n]$/.test(before) ? "" : " ") : "";
    return (before + join + after).slice(0, field.maxLength > 0 ? field.maxLength : 1000);
  }
  function render(active, message) {
    recording = active;
    button.classList.toggle("listening", active);
    button.setAttribute("aria-pressed", String(active));
    button.setAttribute("aria-label", active ? "音声入力を停止" : "音声入力を開始");
    label.textContent = active ? "停止" : "音声";
    pulse.classList.toggle("hidden", !active);
    status.textContent = message;
  }

  button.addEventListener("click", () => {
    if (recording) {
      if (recognizer) {
        try { recognizer.stop(); }
        catch (error) { render(false, "停止しました。文字起こしを確認してください。"); }
      }
      return;
    }

    base = field.value.trim();
    finalText = "";
    latestInterim = "";
    failed = false;
    recognizer = new Engine();
    recognizer.lang = language.value;
    recognizer.continuous = false;
    recognizer.interimResults = true;
    recognizer.maxAlternatives = 1;
    recognizer.onstart = () => render(true, "聞き取り中です。話し終わるか「停止」を押してください。");
    recognizer.onresult = (event) => {
      const confirmed = [];
      const interim = [];
      for (let i = 0; i < event.results.length; i++) {
        const phrase = event.results[i] && event.results[i][0] && event.results[i][0].transcript;
        if (!phrase) continue;
        (event.results[i].isFinal ? confirmed : interim).push(phrase.trim());
      }
      finalText = confirmed.join(" ").trim();
      latestInterim = interim.join(" ").trim();
      field.value = appendText(base, [finalText, latestInterim].filter(Boolean).join(" "));
      status.textContent = latestInterim ? "文字起こし中（送信前に編集できます）" : "認識しました。内容を確認してください。";
    };
    recognizer.onerror = (event) => {
      failed = true;
      const messages = {
        "not-allowed":"マイクの許可がありません。ブラウザ設定を確認してください。",
        "service-not-allowed":"音声認識サービスを利用できません。",
        "audio-capture":"マイクが使えません。接続・設定を確認してください。",
        "network":"音声認識の通信に失敗しました（ブラウザ側サービスの場合があります）。",
        "no-speech":"声が検出されませんでした。もう一度試してください。",
        "aborted":"音声入力を取り消しました。",
        "language-not-supported":"選択した言語を認識できません。",
      };
      field.value = appendText(base, finalText);
      render(false, messages[event.error] || "音声認識に失敗しました。キーボード入力も利用できます。");
    };
    recognizer.onend = () => {
      // Only finalized words are kept. Interim hypotheses are not committed.
      field.value = appendText(base, finalText);
      if (!failed) render(false, finalText ?
        "文字起こしを入力しました。修正してから「送信」してください。" :
        "入力できませんでした。もう一度試すか、キーボードで入力してください。");
      else render(false, status.textContent);
      if (finalText) field.focus();
    };
    try {
      recognizer.start();
      render(true, "マイクを準備しています。アクセス許可が求められたら確認してください。");
    } catch (error) {
      render(false, "音声認識を開始できません。ブラウザのマイク設定を確認してください。");
    }
  });
})();
