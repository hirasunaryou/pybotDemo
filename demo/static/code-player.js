"use strict";
/* A time-seekable film of OBSERVED replay events. No animation is fabricated
 * from static code paths. Only the two clearly marked source-inspection frames
 * at the end come from static, exact-answer source matching. */
(function () {
  const $ = id => document.getElementById(id);
  const wrap = $("filmPlayer"), seek = $("filmSeek");
  if (!wrap || !seek) return;
  const speeds = [0.5, 1, 2, 4, 8];
  const stages = [
    ["runtime", "開始"],
    ["observe", "観察・記憶"],
    ["respond", "候補生成"],
    ["choose", "選択"],
    ["after", "後処理"],
    ["source", "回答の定義"]
  ];
  const descriptions = {
    runtime: "PyBotのruntimeが各モジュールの処理を順に進めます。",
    observe: "入力を観察して会話メモリを更新する段階です（元PyBotのhook）。",
    respond: "複数のモジュールが返信案を提案します。採択前の候補を作っている段階です。",
    choose: "回答選択器の規則により、採用する候補を決める段階です。",
    after: "採択後の処理や会話履歴の更新を行う段階です。",
    source: "ここからは実行時刻の外です。回答文の定義を後から静的検索で調べます。"
  };
  const film = {
    rows: [], data: null, turn: null, index: 0, timer: null, speed: 1,
    cache: new Map(), revision: 0, token: 0, loading: false, expanded: false
  };
  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g,
      c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }
  function setText(id, value) { $(id).textContent = String(value == null ? "" : value); }
  function errorText(msg) {
    $("filmTrust").textContent = msg;
    $("filmTrust").className = "film-trust warning";
  }
  function stop() {
    if (film.timer) window.clearInterval(film.timer);
    film.timer = null;
    $("filmPlay").textContent = "▶ 再生";
    $("filmPlay").setAttribute("aria-label", "再生する");
  }
  function getStage(row) {
    return row.appendix ? "source" : (row.phase || "runtime");
  }
  function fileArea(path) {
    if (path.startsWith("bot/knowledge/")) return ["知識・計算", "知識辞書・数値処理のコード領域です（所属フォルダによる分類）。"];
    if (path.startsWith("bot/memory/")) return ["会話の記憶", "過去の話や現在の文脈を扱うコード領域です（所属フォルダによる分類）。"];
    if (path.startsWith("bot/understanding/")) return ["発話の理解", "入力文の読み取り・解釈に関わるコード領域です（所属フォルダによる分類）。"];
    if (path.startsWith("bot/compose/")) return ["回答の組立", "文章の組み立て・表現の調整に関わる領域です（所属フォルダによる分類）。"];
    if (path === "bot/modules/arbiter.py") return ["回答選択", "回答候補を選ぶarbiterのソースです（PyBot公式）。"];
    if (path.startsWith("bot/modules/")) return ["回答候補", "個別の回答案を提出するモジュールの領域です（PyBot公式）。"];
    if (path === "bot/runtime.py") return ["実行の制御", "observe / respond / choose / after を呼び出す元の実行エンジンです。"];
    return ["処理の内部", "実際に呼び出されたPythonの関数です。役割は原文を確認してください。"];
  }
  function stepsFromSource(data) {
    const steps = [];
    const locations = (data.source_matches || []).filter(x => x.verified_equal);
    if (!locations.length) return steps;
    const best = locations[0];
    const observed = data.executed_return_sites || [];
    if ((best.references || []).length) {
      const hit = best.references.find(loc =>
        observed.some(x => x.path === loc.path && x.line === loc.line));
      const ref = hit || best.references[0];
      steps.push({
        appendix:true, kind:"source_reference", phase:"source",
        path:ref.path, line:ref.line, fn:"return " + best.symbol,
        note:hit ? "返却を通過した行を、再生後に確認（観測済み）" :
          "回答定数への静的参照。通過は未確認（ソース照合）",
        evidence:hit ? "実行行として観測済み・今は再生後の参考表示" : "静的検索による参考候補"
      });
    }
    steps.push({
      appendix:true, kind:"source_literal", phase:"source",
      path:best.path, line:best.line, fn:best.symbol || "answer",
      note:"元の回答と完全一致する文字列定義（実行後の静的照合）",
      evidence:"元の回答文字列と静的ソースの完全一致",
    });
    return steps;
  }

  function renderStages() {
    const first = new Map();
    film.rows.forEach((row, i) => {
      const ph = getStage(row);
      if (!first.has(ph)) first.set(ph,i);
    });
    $("filmStages").innerHTML = stages.filter(x => first.has(x[0])).map(([key,label]) =>
      '<button type="button" class="film-stage" data-stage="' + escapeHtml(key) +
      '" data-index="' + first.get(key) + '">' + escapeHtml(label) + '</button>').join("");
    $("filmStages").querySelectorAll("[data-stage]").forEach(btn => btn.addEventListener("click", () => {
      stop();
      show(Number(btn.dataset.index), true);
    }));
  }

  function highlightSource(code) {
    const escaped = escapeHtml(code);
    if (/^\s*#/.test(code)) return '<span class="film-comment">' + escaped + '</span>';
    return escaped.replace(/\b(def|class|return|import|from|if|elif|else|try|except|for|in|not|None|True|False|continue|break|and|or|with|lambda|yield)\b/g,
      '<span class="film-keyword">$1</span>');
  }

  function updateCode(src, focusLine) {
    const display = $("filmCode");
    const lines = src.lines || [];
    display.innerHTML = lines.map(row => '<div class="film-line' +
      (row.n === focusLine ? ' focused' : '') + '" data-line="' + Number(row.n) + '">' +
      '<span class="film-line-no">' + Number(row.n) + '</span>' +
      '<span class="film-line-text">' + highlightSource(row.code) + '</span></div>').join("");
    const selected = display.querySelector(".film-line.focused");
    if (selected) display.scrollTop = Math.max(0, selected.offsetTop - display.offsetTop - display.clientHeight * 0.38);
  }

  async function fetchSource(path, line, withDoc) {
    if (!/^bot\/[a-zA-Z0-9_/]+\.py$/.test(path)) throw Error("不正なソースファイル");
    const start = Math.max(1, Math.floor((Math.max(1,line)-1)/70)*70+1);
    const key = path + ":" + start + ":" + (withDoc ? line : "source");
    if (film.cache.has(key)) return film.cache.get(key);
    const query = "?path=" + encodeURIComponent(path) + "&start=" + start +
      (withDoc ? "&focus=" + line : "");
    const promise = fetch("/api/source" + query).then(async response => {
      const data = await response.json();
      if (!response.ok || data.error) throw Error(data.error || "HTTP " + response.status);
      return data;
    });
    film.cache.set(key, promise);
    if (film.cache.size > 150) film.cache.delete(film.cache.keys().next().value);
    try { return await promise; }
    catch (err) { film.cache.delete(key); throw err; }
  }

  async function drawSource(row, requestDoc) {
    const token = ++film.token;
    const line = Math.max(1, Number(row.line) || 1);
    $("filmCode").textContent = "Pythonソースを読み込んでいます…";
    $("filmGithub").href = "https://github.com/huggingface/pybot/blob/" +
      "7d63c7fbebb44c7e466e5c8b5c1f341ab767929e/" + row.path + "#L" + line;
    setText("filmFile", row.path + " : L" + line);
    try {
      const source = await fetchSource(row.path,line,false);
      if (token !== film.token) return;
      updateCode(source,line);
      if (requestDoc && !row.appendix) {
        const doc = await fetchSource(row.path,line,true);
        if (token !== film.token) return;
        const help = doc.function_info;
        setText("filmFunctionDoc", help && help.docstring ?
          "原文docstring（PyBot純正）: " + help.docstring : "");
      }
    } catch (err) {
      if (token === film.token) {
        setText("filmCode","ソースを開けませんでした: " + err.message);
      }
    }
  }

  function show(index, requestDoc) {
    if (!film.rows.length) return;
    const i = Math.max(0,Math.min(film.rows.length-1,Math.round(index)));
    film.index=i;
    seek.value=String(i);
    const row=film.rows[i];
    const phase=getStage(row);
    const [label,desc]=fileArea(row.path||"");
    const appendix=!!row.appendix;
    const type=row.kind==="candidate_return"?"採択候補の生成を観測":
      row.kind==="arbiter_return"?"回答候補の選択を観測":
      row.kind==="return_site"?"実際に通った返却行":
      row.kind==="final"?"PyBot最終応答":
      appendix?"後から調べたソース（再実行の時刻外）":"再実行での関数/行を観測";
    setText("filmEventType", type);
    setText("filmCounter", (i+1)+" / "+film.rows.length);
    setText("filmPhase",label+" · "+(row.fn||"unknown")+"()");
    const role=appendix ? descriptions.source :
      (descriptions[phase]||descriptions.runtime);
    const comment=row.note || "";
    const observation=appendix ? "（静的照合）" : "（再実行で観測）";
    setText("filmPurpose",role+" "+desc+" "+comment+" "+observation);
    setText("filmTime", "再生位置 "+(i+1)+" / "+film.rows.length+"（代表的なイベント）");
    setText("filmElapsed", appendix ? "実行後のソース調査・時刻ではありません" :
      "再実行中の計測位置：+"+Number(row.at_ms||0).toFixed(1)+" ms");
    $("filmEventType").classList.toggle("appendix", appendix);
    $("filmElapsed").classList.toggle("appendix", appendix);
    $("filmStages").querySelectorAll("[data-stage]").forEach(button => {
      button.classList.toggle("active", button.dataset.stage === phase);
    });
    if(i===film.rows.length-1) stop();
    setText("filmFunctionDoc","");
    drawSource(row,!!requestDoc);
  }

  function play() {
    if(!film.rows.length || film.timer) return;
    if(film.index >= film.rows.length-1) show(0,false);
    $("filmPlay").textContent="Ⅱ 一時停止";
    $("filmPlay").setAttribute("aria-label","一時停止する");
    film.timer=window.setInterval(() => {
      if(film.index >= film.rows.length-1) {stop();return;}
      show(film.index+1,false);
    }, Math.max(35,170/film.speed));
  }

  async function load(args) {
    if(film.loading || !args || !Number.isInteger(args.turn_index)) return;
    reset();
    film.loading = true;
    const revision = film.revision;
    wrap.classList.remove("hidden");
    setText("filmTrust","PyBotの会話を別メモリで再実行して、実際の関数呼び出しを調べています…");
    $("filmTrust").className = "film-trust";
    setText("filmCode","解析中…");
    try {
      const response = await fetch("/api/playback",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({session:args.session,turn_index:args.turn_index})
      });
      const data = await response.json();
      if(!response.ok || data.error) throw Error(data.error||"処理に失敗しました");
      if(revision!==film.revision)return;
      film.data=data;film.turn=args.turn;
      film.rows=(data.frames||[]).concat(stepsFromSource(data));
      if(!film.rows.length)throw Error("観測した再生コマがありません");
      seek.min="0";seek.max=String(film.rows.length-1);
      setText("filmAnswer",args.turn.reply||"");
      const observed=Number(data.call_count||0).toLocaleString("ja-JP");
      const retained=Number(data.sampled_frames||0).toLocaleString("ja-JP");
      $("filmTrust").className="film-trust "+(data.replay_equal?"good":"warning");
      setText("filmTrust",(data.replay_equal ?
        "✓ 再実行の回答・選択結果は元と一致" :
        "⚠ 元と再実行が不一致。元の確定経路として扱わないでください")+
        " · "+observed+" 関数呼出し中 "+retained+" コマを抜粋"+(data.source_matches?.some(s=>s.verified_equal) ?
        " · 末尾に回答文の完全一致ソースあり" : " · 回答文の静的定義は未特定"));
      renderStages();
      show(0,true);
      wrap.scrollIntoView({block:"start",behavior:"smooth"});
    }catch(err){
      if(revision===film.revision)errorText("再生データを取得できません: "+err.message);
    }finally{
      if(revision===film.revision)film.loading=false;
    }
  }

  function reset() {
    stop();
    film.revision++;
    film.token++;
    film.loading=false;
    film.rows=[];film.turn=null;film.data=null;film.index=0;
    film.cache.clear();
    wrap.classList.add("hidden");
    if(film.expanded)expand(false);
  }
  function expand(force) {
    film.expanded=force;
    wrap.classList.toggle("expanded",force);
    document.body.classList.toggle("film-expanded",force);
    $("filmExpand").textContent=force?"⤡ 戻す":"⤢ 拡大";
    $("filmExpand").setAttribute("aria-pressed",String(force));
    if(force)wrap.focus({preventScroll:true});
  }

  $("filmPlay").addEventListener("click",()=>film.timer?stop():play());
  $("filmPrevious").addEventListener("click",()=>{stop();show(film.index-1,true);});
  $("filmNext").addEventListener("click",()=>{stop();show(film.index+1,true);});
  $("filmFirst").addEventListener("click",()=>{stop();show(0,true);});
  $("filmLast").addEventListener("click",()=>{stop();show(film.rows.length-1,true);});
  $("filmSpeed").addEventListener("click",()=>{
    const next=speeds[(speeds.indexOf(film.speed)+1)%speeds.length];
    film.speed=next;
    $("filmSpeed").textContent="×"+next;
    if(film.timer){stop();play();}
  });
  seek.addEventListener("input",()=>{stop();show(Number(seek.value),false);});
  seek.addEventListener("change",()=>{show(Number(seek.value),true);});
  $("filmExpand").addEventListener("click",()=>expand(!film.expanded));
  document.addEventListener("keydown",event=>{
    if(!film.rows.length)return;
    if(event.key==="Escape"&&film.expanded){expand(false);return;}
    const active=document.activeElement;
    if(!film.expanded&&!wrap.contains(active))return;
    if(["INPUT","TEXTAREA","SELECT"].includes(active?.tagName) && active!==seek)return;
    if(event.key===" "){event.preventDefault();film.timer?stop():play();}
    else if(event.key==="ArrowLeft"&&active!==seek){event.preventDefault();stop();show(film.index-1,true);}
    else if(event.key==="ArrowRight"&&active!==seek){event.preventDefault();stop();show(film.index+1,true);}
    else if(event.key==="Home"&&active!==seek){event.preventDefault();stop();show(0,true);}
    else if(event.key==="End"&&active!==seek){event.preventDefault();stop();show(film.rows.length-1,true);}
  });
  window.PyBotLabCodePlayer={load,reset,isReady:()=>film.rows.length>0,getPosition:()=>film.index};
})();
