"use strict";
/* Optional experiment wrapper, NOT Hugging Face PyBot.
   On-device Web Translator API: user explicitly turns it on.
   PyBot always receives the English text shown under "PyBotに渡した英文".
   Never silently send content to a remote translation endpoint. */
(function () {
  const button = document.getElementById("jaBridgeBtn");
  const stateText = document.getElementById("jaBridgeStatus");
  const details = document.getElementById("jaBridgeDetails");
  if (!button || !stateText) return;
  const NativeTranslator = window.Translator;
  const pairOptions = [
    {sourceLanguage: "ja", targetLanguage: "en"},
    {sourceLanguage: "en", targetLanguage: "ja"}
  ];
  const store = {active:false, preparing:false, jaEn:null, enJa:null};

  function status(message) {
    stateText.textContent = message;
  }
  function paint() {
    button.disabled = store.preparing || !NativeTranslator || typeof NativeTranslator.create !== "function";
    button.setAttribute("aria-pressed", String(store.active));
    button.classList.toggle("is-on", store.active);
    button.textContent = store.preparing ? "準備中…" : store.active ? "日本語ブリッジ ON" : "日本語ブリッジ OFF";
  }
  function release() {
    for (const translator of [store.jaEn, store.enJa]) {
      try { if (translator && typeof translator.destroy === "function") translator.destroy(); }
      catch (_) {}
    }
    store.jaEn = null;
    store.enJa = null;
  }
  paint();
  if (!NativeTranslator || typeof NativeTranslator.create !== "function") {
    status("このブラウザでは翻訳補助は未対応。Chrome 138以降または対応Edge（PC）で試せます。");
  } else {
    status("初期状態は純正モード。ONにすると翻訳を追加します（初回は言語パック取得が必要な場合あり）。");
  }

  button.addEventListener("click", async function () {
    if (store.preparing || !NativeTranslator) return;
    if (store.active) {
      store.active = false;
      release();
      status("純正モード：翻訳しません。日本語をそのまま送るとPyBotの英語主体の規則で処理されます。");
      paint();
      return;
    }
    store.preparing = true;
    paint();
    status("日本語 ↔ 英語のローカル翻訳を準備中。最初だけ言語パックの取得が必要な場合があります。");
    try {
      // MUST call create() directly in the gesture. The browser may reject
      // downloading new language packs after a preceding await.
      const tasks = pairOptions.map(options => NativeTranslator.create({
        ...options,
        monitor(m) {
          if (m && typeof m.addEventListener === "function") {
            m.addEventListener("downloadprogress", event => {
              const percent = Math.round(Math.max(0, Math.min(1, event.loaded || 0)) * 100);
              status("ブラウザの翻訳言語パックを準備中… " + percent + "%");
            });
          }
        }
      }));
      const [jaEn, enJa] = await Promise.all(tasks);
      if (!jaEn || !enJa || typeof jaEn.translate !== "function" || typeof enJa.translate !== "function") {
        throw new Error("翻訳器を初期化できませんでした");
      }
      store.jaEn = jaEn;
      store.enJa = enJa;
      store.active = true;
      status("翻訳補助ON：日本語→英語をPyBotへ。回答は英語の原文と日本語訳を併記します。");
    } catch (error) {
      release();
      store.active = false;
      status("翻訳を利用できません：" + (error.message || error.name || "対応環境・空き容量・ブラウザ設定を確認してください"));
    } finally {
      store.preparing = false;
      paint();
    }
  });

  window.PyBotLabTranslation = {
    active: () => store.active,
    async prepare(text) {
      const source = String(text || "").trim();
      if (!store.active || !/[一-龯ぁ-ゖァ-ヿ]/.test(source)) {
        return {inputOriginal:source, sentToPyBot:source, inputTranslated:false,
                bridge:store.active ? "browser-translator-enabled" : "pure"};
      }
      if (!store.jaEn) throw new Error("翻訳補助がまだ準備できていません");
      let english;
      try { english = String(await store.jaEn.translate(source)).trim(); }
      catch (error) { throw new Error("日本語から英語への翻訳に失敗したため、PyBotには送信していません: " + error.message); }
      if (!english || english.length > 1000 || english === source) {
        throw new Error("英訳を確認できませんでした。PyBotへの送信を中止しました。");
      }
      return {inputOriginal:source, sentToPyBot:english, inputTranslated:true,
              bridge:"browser-on-device"};
    },
    async translateReply(rawReply) {
      if (!store.active || !store.enJa) return {outputJapanese:"", outputTranslated:false};
      try {
        const translated = String(await store.enJa.translate(String(rawReply || ""))).trim();
        if (!translated) throw new Error("空の翻訳結果");
        return {outputJapanese:translated, outputTranslated:true};
      } catch (error) {
        // PyBot's real turn ALREADY succeeded. Do not make the user resubmit.
        return {outputJapanese:"", outputTranslated:false,
                translationWarning:"回答の和訳だけ失敗しました。PyBot純正の英語回答は保存されています: " + error.message};
      }
    }
  };
})();
