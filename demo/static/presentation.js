"use strict";
/* Live Lab presentation aids. Pure CSS typography; does not alter PyBot. */
(function () {
  const sizes = [100,125,150,175];
  const key = "pybot-live-lab:font-size";
  const btnMinus=document.getElementById("fontMinus");
  const btnPlus=document.getElementById("fontPlus");
  const output=document.getElementById("fontScale");
  const present=document.getElementById("presentationToggle");
  if(!btnMinus||!btnPlus||!output||!present)return;
  let value=100;
  try {
    const stored=Number(localStorage.getItem(key));
    if(sizes.includes(stored))value=stored;
  }catch(_){}
  let presenting=false;

  function render() {
    document.documentElement.style.setProperty("--lab-font-scale",String(value/100));
    document.documentElement.dataset.font = String(value);
    document.documentElement.dataset.presentation=presenting?"on":"off";
    output.textContent=value+"%";
    btnMinus.disabled=value===sizes[0];
    btnPlus.disabled=value===sizes[sizes.length-1];
    present.setAttribute("aria-pressed",String(presenting));
    present.textContent=presenting?"発表終了":"発表";
    try { localStorage.setItem(key,String(value)); }catch(_){}
  }
  btnMinus.addEventListener("click",()=>{
    const index=sizes.indexOf(value);
    value=sizes[Math.max(0,index-1)];
    render();
  });
  btnPlus.addEventListener("click",()=>{
    const index=sizes.indexOf(value);
    value=sizes[Math.min(sizes.length-1,index+1)];
    render();
  });
  present.addEventListener("click",()=>{
    presenting=!presenting;
    if(presenting&&value<125)value=125;
    render();
  });
  render();
  window.PyBotLabDisplay={getFontSize:()=>value,isPresenting:()=>presenting};
})();
