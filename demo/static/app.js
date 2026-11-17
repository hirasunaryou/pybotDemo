"use strict";
/* This viewer never generates simulated PyBot answers. All observations are from /api/ask. */
const $ = (id) => document.getElementById(id);
const state = {
  session: "lab_" + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2),
  seed: 42, turns: [], active: -1, module: null, source: null, trace: null,
  busy: false, scenario: -1, step: 0
};
const scenarios = [
  {name:"名前と記憶", desc:"名前を伝え、会話内の情報が取り出せるかを観察します。", prompts:["Hi, I'm Sam.","What's my name?","Actually, my name is Alex.","What's my name now?"]},
  {name:"日常知識", desc:"知識の取り出しと、続く質問への応答を観察します。", prompts:["My kettle is full of limescale. How do I remove it?","How long does that take?"]},
  {name:"言い換え", desc:"同じ意図を違う表現で質問し、候補を比較します。", prompts:["How long should I boil an egg?","What's the best way to cook eggs in water?"]},
  {name:"未知の概念", desc:"未定義の架空概念に対する応答を検討します。", prompts:["Explain Quantum Banana Regression.","Can you give me a concrete example?"]},
  {name:"日本語", desc:"英語中心の仕組みの言語依存性を試します。", prompts:["こんにちは。私の名前は太郎です。","私の名前は何ですか？"]}
];
function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, ch =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}
async function request(path, data) {
  const options = data === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)};
  let result;
  try {
    const response = await fetch(path, options);
    result = await response.json();
    if (!response.ok || result.error) throw new Error(result.error || "HTTP " + response.status);
    return result;
  } catch (err) {
    throw new Error("通信・処理エラー: " + err.message);
  }
}
function toast(message, isError) {
  const box = $("toast");
  box.textContent = message;
  box.classList.remove("hidden");
  box.style.borderColor = isError ? "#ff9c9c" : "#61dfc8";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => box.classList.add("hidden"), 4700);
}
function toggleBusy(busy, label) {
  state.busy = busy;
  $("sendBtn").disabled = busy;
  $("resetBtn").disabled = busy;
  $("traceBtn").disabled = busy || !state.module || state.active < 0;
  $("busyText").textContent = busy ? (label || "PyBotが実際に処理しています…") : "Enterで送信 / Shift+Enterで改行";
}
function tab(id) {
  for (const button of document.querySelectorAll("[data-tab]")) {
    const active = button.dataset.tab === id;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    $("tab-" + button.dataset.tab).classList.toggle("hidden", !active);
  }
}
function renderScenarios() {
  $("scenarioChips").innerHTML = scenarios.map((s,i) => '<button class="' +
    (state.scenario === i ? "active" : "") + '" data-scenario="' + i +
    '">' + esc(s.name) + '</button>').join("");
  document.querySelectorAll("[data-scenario]").forEach(b => b.onclick = () => {
    state.scenario = Number(b.dataset.scenario);
    state.step = 0;
    prepareNext();
    renderScenarios();
  });
}
function prepareNext() {
  const s = scenarios[state.scenario];
  if (!s || state.step >= s.prompts.length) {
    $("scenarioNote").textContent = s ? "シナリオ完了。質問を自由に変えて、反応を比べてみましょう。" : "試したいテーマを選んでください。自由な質問もできます。";
    return;
  }
  $("questionInput").value = s.prompts[state.step];
  $("scenarioNote").textContent = s.desc + " (" + (state.step+1) + "/" + s.prompts.length + ")";
  $("questionInput").focus();
}
function updateNext(input) {
  const s = scenarios[state.scenario];
  if (!s || s.prompts[state.step] !== input) return;
  state.step += 1;
  prepareNext();
}
function renderConversation() {
  const area = $("conversation");
  if (state.turns.length === 0) {
    area.innerHTML = '<div class="empty-chat"><div class="empty-orb">◎</div><h3>まずは、話しかけてみましょう。</h3><p>例えば「Hi, I&#39;m Sam.」と伝えて、名前を覚えているか確かめます。</p><button class="example-link" id="exampleBtn">この質問を使う ↗</button></div>';
    $("exampleBtn").onclick = () => { $("questionInput").value = "Hi, I'm Sam."; $("questionInput").focus(); };
    return;
  }
  area.innerHTML = state.turns.map((t,i) =>
    '<div class="bubble-row user"><div class="bubble-main"><div class="bubble">' + esc(t.text) + '</div></div></div>' +
    '<div class="bubble-row bot"><div class="speaker">P</div><div class="bubble-main"><div class="bubble">' + esc(t.reply) +
    '</div><div class="bubble-meta"><span class="mini-tag">' + esc(t.module || "fallback") +
    '</span><span>' + esc(t.elapsed_ms) + ' ms · ' + esc(t.candidate_count) +
    ' candidates</span><button data-turn="' + i + '">内部を見る ↗</button></div></div></div>'
  ).join("");
  area.querySelectorAll("[data-turn]").forEach(b => b.onclick = () => selectTurn(Number(b.dataset.turn)));
  area.scrollTop = area.scrollHeight;
}
function selectTurn(i) {
  state.active = i;
  const t = state.turns[i];
  state.module = t.module || (t.candidates[0] && t.candidates[0].module) || null;
  state.trace = null;
  renderCandidateList();
  tab("candidates");
}
function renderTurnComparison(t) {
  const box = $("turnComparison");
  if (!t || state.active < 1) { box.classList.add("hidden"); return; }
  const prev = state.turns[state.active - 1];
  const a = new Set(prev.candidates.map(c => c.module));
  const b = new Set(t.candidates.map(c => c.module));
  const common = [...a].filter(x => b.has(x)).length;
  const total = new Set([...a,...b]).size;
  const share = total ? Math.round(100 * common / total) : 100;
  const switched = (prev.module || "fallback") !== (t.module || "fallback");
  box.classList.remove("hidden");
  box.innerHTML = '<div class="compare-heading">↔ 直前の質問と比較（観測結果）</div>' +
    '<div class="compare-pair"><span>' + esc(prev.module || "fallback") +
    '</span><span class="compare-arrow">→</span><span>' + esc(t.module || "fallback") + '</span></div>' +
    '<div class="compare-bar"><div id="compareFill"></div></div>' +
    '<div class="compare-caption">回答候補のモジュール一致率 ' + share + '% (' + common + '/' + total +
    ' 種類) · 採択モジュール ' + (switched ? "変化あり" : "変化なし") +
    '<br>※ 類似性の指標は候補の集合であり、質問の意味や回答品質の評価ではありません。</div>';
  $("compareFill").style.width = share + "%";
}

function renderCandidateList() {
  const t = state.turns[state.active];
  $("selectedModule").textContent = t ? (t.module || "runtime fallback") : "まだ会話がありません";
  $("latency").textContent = t ? t.elapsed_ms + " ms" : "— ms";
  $("candidateCount").textContent = t ? String(t.candidate_count) : "0";
  $("resultMessage").textContent = t ? "実測された候補から arbiter が " +
    (t.module || "fallback") + " を選択しました。" +
    (t.chosen_index > 0 ? " 優先度順の先頭以外が採択されています。" : "") +
    " 候補をクリックしてコードを確認できます。" :
    "質問を送信すると、本物のPyBotが生成した候補を表示します。";
  renderTurnComparison(t);
  if (!t) return;
  $("candidatesList").innerHTML = t.candidates.length ? t.candidates.map((c, i) => {
    const picked = i === t.chosen_index;
    return '<button class="candidate-item ' + (picked ? "picked " : "") + (state.module === c.module ? "current" : "") +
      '" data-choice="' + i + '"><div class="candidate-header"><span class="candidate-name">' +
      (picked ? '<span class="selected-label">採択</span>' : "") + esc(c.module) +
      '</span><span class="candidate-priority">PRIORITY ' + esc(c.priority) +
      '</span></div><div class="candidate-response">' + esc(c.reply) + '</div></button>';
  }).join("") : '<div class="placeholder-card">候補はありません。PyBotの既定応答が使われました。</div>';
  $("candidatesList").querySelectorAll("[data-choice]").forEach(b => b.onclick = async () => {
    const c = t.candidates[Number(b.dataset.choice)];
    state.module = c.module;
    state.trace = null;
    renderCandidateList();
    await openSource("bot/modules/" + c.module + ".py", null, c.module);
    tab("code");
  });
  $("memoryView").innerHTML = '<div class="memory-grid"><div class="memory-column"><b>処理前</b>' +
    memoryEntries(t.memory_before) + '</div><div class="memory-column"><b>処理後</b>' +
    memoryEntries(t.memory_after) + '</div></div>';
}
function memoryEntries(entries) {
  return entries && entries.length ? entries.map(v => '<div class="memory-entry"><strong>' + esc(v.name) +
    '</strong>: ' + esc(v.summary) + '</div>').join("") : '<div class="memory-entry">まだ情報がありません</div>';
}
function highlightSyntax(code) {
  // Escape before adding highlighting; upstream source is never inserted as executable HTML.
  let s = esc(code);
  if (/^\s*#/.test(code)) return '<span class="comment">' + s + '</span>';
  return s.replace(/\b(def|class|return|import|from|if|elif|else|try|except|for|in|not|None|True|False|continue|break|and|or|with|lambda)\b/g,
    '<span class="kw">$1</span>');
}
async function openSource(path, start, module) {
  if (state.busy) return;
  try {
    const query = module && start == null ? "module=" + encodeURIComponent(module) :
      "path=" + encodeURIComponent(path) + "&start=" + Math.max(1, start || 1);
    const data = await request("/api/source?" + query);
    state.source = data;
    $("codeTitle").textContent = data.path;
    $("traceBtn").disabled = !state.module || state.active < 0;
    renderSource();
  } catch (err) { toast(err.message, true); }
}
function renderSource() {
  const d = state.source;
  if (!d) return;
  $("codeRange").textContent = "L" + d.start + "–" + (d.start + d.lines.length - 1) + " / " + d.total;
  $("githubFileLink").href = "https://github.com/huggingface/pybot/blob/" + ($("sourceCommit").textContent === "—" ? "main" : "7d63c7fbebb44c7e466e5c8b5c1f341ab767929e") +
    "/" + d.path + "#L" + d.start;
  const traced = (state.trace && state.trace.hits && state.trace.hits[d.path]) || [];
  const hitNums = new Set(traced.map(h => h.line));
  $("codeView").innerHTML = d.lines.map(row => '<div class="code-line ' +
    (hitNums.has(row.n) ? "hit" : "") + '"><span class="number">' + row.n +
    '</span><span class="code">' + highlightSyntax(row.code) + '</span></div>').join("");
  $("traceCount").textContent = state.trace ? traced.length + " 個の行を通過 (" + (state.trace.replay_equal ? "再実行一致" : "再実行不一致") + ")" : "実行追跡前";
  $("prevPage").disabled = d.start <= 1;
  $("nextPage").disabled = d.start + d.lines.length - 1 >= d.total;
  $("traceBtn").disabled = state.busy || !state.module || state.active < 0;
  $("moduleBtn").disabled = !state.module;
}
async function traceSource() {
  if (!state.module || state.active < 0 || state.busy) return;
  const module = state.module, turnIndex = state.active;
  toggleBusy(true, "会話を再実行し、Pythonの実行行を取得しています…");
  try {
    state.trace = await request("/api/trace", {session:state.session,turn_index:turnIndex,module});
    const data = state.trace;
    $("traceNote").textContent = data.warning ||
      "再実行と元の回答が一致しました。色付きの行は、対象モジュールまたはarbiterで実際に通過した行です。";
    $("traceNote").className = "trace-note " + (data.replay_equal ? "good" : "warn");
    $("functionCalls").innerHTML = data.calls.length ?
      data.calls.map(c => '<div class="call-row"><span>' + esc(c.file) + ' · ' + esc(c.fn) +
        '()</span><span>' + esc(c.count) + ' 回</span></div>').join("") :
      "対象の関数呼び出しは観測されませんでした。";
    // Keep whichever source (module or arbiter) is currently open and highlight its observed lines.
    if (state.source) renderSource();
    toast(data.replay_equal ? "実行行を記録しました（再実行結果も一致）" : "実行行を記録しましたが、再実行結果に差がありました", !data.replay_equal);
  } catch (err) { toast(err.message, true); }
  finally { toggleBusy(false); }
}
async function searchCode() {
  const query = $("searchInput").value.trim();
  if (query.length < 2) return toast("2文字以上の検索語を入力してください", true);
  $("searchResults").textContent = "コードを検索中…";
  try {
    const r = await request("/api/search", {query,scope:$("searchScope").value});
    $("searchResults").innerHTML = r.results.length ? r.results.map((f,i) =>
      '<button class="search-result" data-result="' + i + '"><b>' + esc(f.path) + ':' +
      esc(f.line) + '</b><small>' + esc(f.snippet) + '</small></button>').join("") :
      '<div class="placeholder-card">一致する行は見つかりませんでした。</div>';
    $("searchResults").querySelectorAll("[data-result]").forEach(b => b.onclick = () => {
      const f = r.results[Number(b.dataset.result)];
      state.module = null;
      state.trace = null;
      openSource(f.path, Math.max(1, f.line-15));
    });
  } catch (err) { toast(err.message, true); }
}
async function sendQuestion() {
  const input = $("questionInput").value.trim();
  if (!input || state.busy) return;
  toggleBusy(true, "PyBotが候補を生成しています。初回は本体の読み込みにも時間がかかります…");
  $("questionInput").value = "";
  const pending = document.createElement("div");
  pending.className = "thinking";
  pending.textContent = "PyBot がルールを評価しています";
  $("conversation").appendChild(pending);
  $("conversation").scrollTop = $("conversation").scrollHeight;
  try {
    const response = await request("/api/ask", {session:state.session,seed:state.seed,text:input});
    state.turns.push(response);
    selectTurn(state.turns.length-1);
    renderConversation();
    updateNext(input);
  } catch (err) {
    pending.remove();
    $("questionInput").value = input;
    toast(err.message, true);
  } finally {
    toggleBusy(false);
    $("questionInput").focus();
  }
}
async function resetConversation() {
  if (state.busy) return;
  if (state.turns.length && !confirm("会話とメモリをリセットしますか？（保存していない結果は失われます）")) return;
  try {
    if (state.turns.length) await request("/api/reset", {session:state.session});
    state.turns = []; state.active = -1; state.module = null; state.trace = null; state.source = null;
    renderConversation();
    renderCandidateList();
    $("codeView").innerHTML = '<div class="placeholder-code"># ここにPyBotの実際のコードが表示されます</div>';
    $("codeTitle").textContent = "候補を選ぶとコードを開きます";
    $("traceCount").textContent = "実行追跡前";
    toast("会話をリセットしました", false);
  } catch (err) { toast(err.message, true); }
}
function exportSession() {
  if (state.turns.length === 0) return toast("保存する会話がまだありません", true);
  const report = {app:"PyBot Live Lab", source_commit:"7d63c7fbebb44c7e466e5c8b5c1f341ab767929e",
    seed:state.seed, notice:"Observations from upstream bot.runtime.turn(). Trace is a separately replayed session.",
    turns:state.turns};
  const blob = new Blob([JSON.stringify(report,null,2)],{type:"application/json"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "pybot-live-lab-" + new Date().toISOString().slice(0,10) + ".json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 500);
}
async function loadStatus() {
  try {
    const r = await request("/api/status");
    $("codeLines").textContent = Number(r.stats.total.lines).toLocaleString("en-US");
    $("moduleCount").textContent = Number(r.stats.modules.files).toLocaleString("en-US");
    $("sourceCommit").textContent = r.source_commit.slice(0,8);
    $("statusDot").classList.add("ready");
    $("statusDot").innerHTML = "<i></i> PyBot取得済み";
    $("architectureStats").innerHTML = ["understanding","memory","knowledge","compose","modules"].map(name =>
      '<div class="arch-stat"><strong>' + Number(r.stats[name].lines).toLocaleString("en-US") +
      '</strong><span>' + esc(name) + " / " + r.stats[name].files + " files</span></div>").join("");
  } catch (err) {
    $("statusDot").classList.add("error");
    $("statusDot").innerHTML = "<i></i> 読込エラー";
    toast(err.message,true);
  }
}
function init() {
  renderScenarios();
  renderCandidateList();
  renderConversation();
  document.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => tab(b.dataset.tab));
  document.querySelectorAll("[data-ask]").forEach(b => b.onclick = () => {
    $("questionInput").value = b.dataset.ask; $("questionInput").focus(); tab("candidates");
  });
  $("sendBtn").onclick = sendQuestion;
  $("questionInput").onkeydown = event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault(); sendQuestion();
    }
  };
  $("traceBtn").onclick = traceSource;
  $("moduleBtn").onclick = () => state.module && openSource("bot/modules/" + state.module + ".py", null, state.module);
  $("arbiterBtn").onclick = () => openSource("bot/modules/arbiter.py", 200);
  $("resetBtn").onclick = resetConversation;
  $("exportBtn").onclick = exportSession;
  $("prevPage").onclick = () => state.source && openSource(state.source.path, state.source.start - 110);
  $("nextPage").onclick = () => state.source && openSource(state.source.path, state.source.start + 110);
  $("searchBtn").onclick = searchCode;
  $("searchInput").onkeydown = e => { if (e.key === "Enter") searchCode(); };
  loadStatus();
}
document.addEventListener("DOMContentLoaded", init);
