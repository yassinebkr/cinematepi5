(function(){
'use strict';

var root=document.documentElement;
var body=document.body;
var isiOS=/iphone|ipad|ipod/i.test(navigator.userAgent) ||
          (navigator.platform==='MacIntel' && navigator.maxTouchPoints>1);

function standalone(){
  return window.matchMedia('(display-mode: standalone)').matches ||
         window.matchMedia('(display-mode: fullscreen)').matches ||
         navigator.standalone===true;
}
function fullElement(){
  return document.fullscreenElement || document.webkitFullscreenElement || null;
}
function requestCapable(){
  return !!(root.requestFullscreen || root.webkitRequestFullscreen);
}
function setRootState(){
  root.classList.toggle('is-standalone',standalone());
  root.classList.toggle('is-fullscreen',!!fullElement());
}
function showInstallHint(){
  var hint=document.getElementById('install-hint');
  if(!hint){
    hint=document.createElement('div');
    hint.id='install-hint';
    hint.className='install-hint';
    hint.appendChild(document.createTextNode(
      isiOS
        ? 'iPhone/iPad: Safari and other iOS browsers cannot reliably fullscreen an arbitrary web page. Use Share → Add to Home Screen, then launch CinePi from its Home Screen icon.'
        : 'This browser refused fullscreen. Use its Add to Home Screen / Install app command for a browserless camera UI.'
    ));
    var close=document.createElement('button');
    close.type='button'; close.textContent='Close';
    close.onclick=function(){hint.classList.remove('show');};
    hint.appendChild(close);
    document.body.appendChild(hint);
  }
  hint.classList.add('show');
}
function ensureExitFab(){
  var b=document.getElementById('fullscreen-exit-fab');
  if(!b){
    b=document.createElement('button');
    b.id='fullscreen-exit-fab';
    b.type='button';
    b.textContent='Exit Fullscreen';
    b.addEventListener('click',function(ev){
      ev.preventDefault();
      if(document.exitFullscreen) document.exitFullscreen().catch(function(){});
      else if(document.webkitExitFullscreen) document.webkitExitFullscreen();
    });
    document.body.appendChild(b);
  }
  return b;
}
function updateFullscreen(){
  setRootState();
  ensureExitFab();
  var b=document.getElementById('fullscreen-btn');
  if(!b) return;
  if(standalone()){
    b.style.display='none';
    return;
  }
  b.style.display='';
  if(fullElement()){
    b.textContent='Exit Fullscreen';
    b.disabled=false;
  }else if(isiOS || !requestCapable()){
    b.textContent='Home Screen Fullscreen';
    b.disabled=false;
  }else{
    b.textContent='Enter Fullscreen';
    b.disabled=false;
  }
}
async function fullscreenGesture(ev){
  ev.preventDefault();
  ev.stopPropagation();
  if(standalone()) return;
  if(isiOS || !requestCapable()){
    showInstallHint();
    return;
  }
  try{
    if(fullElement()){
      if(document.exitFullscreen) await document.exitFullscreen();
      else if(document.webkitExitFullscreen) document.webkitExitFullscreen();
    }else if(root.requestFullscreen){
      await root.requestFullscreen({navigationUI:'hide'});
    }else{
      root.webkitRequestFullscreen();
    }
  }catch(e){
    showInstallHint();
  }
  updateFullscreen();
}
function bindFullscreen(){
  var b=document.getElementById('fullscreen-btn');
  if(b) b.addEventListener('click',fullscreenGesture,{passive:false});
  document.addEventListener('fullscreenchange',updateFullscreen);
  document.addEventListener('webkitfullscreenchange',updateFullscreen);
  updateFullscreen();
}

function placeResponsiveCameraControls(){
  if(!body || !body.classList.contains('page-live')) return;

  var lut=document.getElementById('lutsel');
  var slot=document.getElementById('mobile-look-slot');
  var expo=document.getElementById('expo-tools');
  var tag=document.getElementById('btn-tag');
  var tool=document.getElementById('tool-side');
  var tagPanel=document.getElementById('tag-panel');
  var scopes=document.getElementById('scopes');
  var cont=document.getElementById('stream-container');
  var clips=document.getElementById('clips-link');
  var top=document.querySelector('.top-bar');
  if(!lut||!slot||!expo||!tag||!tool||!cont||!clips||!top) return;

  var portrait=window.matchMedia('(orientation: portrait)').matches;
  var compactLandscape=landscapeCompact();

  if(portrait){
    if(lut.parentNode!==slot) slot.appendChild(lut);
    if(tag.parentNode!==expo) expo.insertBefore(tag,expo.firstChild);
    if(scopes && scopes.parentNode!==tool) tool.appendChild(scopes);
    if(clips.parentNode!==top) top.appendChild(clips);
  }else{
    if(lut.parentNode!==expo) expo.insertBefore(lut,expo.firstChild);
    if(tag.parentNode!==tool){
      if(tagPanel && tagPanel.parentNode===tool) tool.insertBefore(tag,tagPanel);
      else tool.appendChild(tag);
    }
    if(compactLandscape){
      if(scopes && scopes.parentNode!==cont) cont.appendChild(scopes);
      if(scopes) scopes.classList.add('landscape-scope-overlay');
      if(clips.parentNode!==cont) cont.appendChild(clips);
    }else{
      if(scopes && scopes.parentNode!==tool) tool.appendChild(scopes);
      if(scopes) scopes.classList.remove('landscape-scope-overlay');
      if(clips.parentNode!==top) top.appendChild(clips);
    }
  }
}

function landscapeCompact(){
  return window.matchMedia('(orientation: landscape) and (max-width: 1180px)').matches;
}
function portraitCompact(){
  return window.matchMedia('(orientation: portrait)').matches;
}
var userControlsChoice=null;
function applyControls(){
  if(!body || !body.classList.contains('page-live')) return;
  var open;
  if(userControlsChoice!==null) open=userControlsChoice;
  else open=!landscapeCompact();
  body.classList.toggle('controls-open',open);
  body.classList.toggle('controls-closed',!open && portraitCompact());
  var b=document.getElementById('ui-toggle');
  if(b){
    b.textContent=open?'×':'☰';
    b.setAttribute('aria-label',open?'Hide camera controls':'Show camera controls');
  }
}
function bindControls(){
  var b=document.getElementById('ui-toggle');
  if(!b) return;
  b.addEventListener('click',function(ev){
    ev.preventDefault();ev.stopPropagation();
    userControlsChoice=!body.classList.contains('controls-open');
    applyControls();
    syncLandscapeChrome();
  });
  applyControls();
}

function liveStreamUrl(){
  var host=window.location.hostname;
  var port='8000';
  var stream=document.getElementById('stream');
  if(stream && stream.dataset.streamPort) port=stream.dataset.streamPort;
  return 'http://'+host+':'+port+'/stream';
}

function connectLiveStream(force){
  if(!body || !body.classList.contains('page-live')) return;
  var stream=document.getElementById('stream');
  if(!stream) return;
  if(document.hidden && !force) return;

  var hasSrc=!!stream.getAttribute('src');
  if(!force && hasSrc && stream.dataset.streamFailed!=='1') return;

  stream.dataset.streamFailed='0';
  stream.dataset.streamLoaded='0';
  stream.src=liveStreamUrl();
}

function markLiveStreamLoaded(){
  var stream=document.getElementById('stream');
  if(!stream) return;
  stream.dataset.streamLoaded='1';
  stream.dataset.streamFailed='0';
  syncStreamGeometry();
}

function noteLiveStreamError(){
  /* Safari/WebKit can emit a transient error for a still-useful multipart
     MJPEG image. Never restart the stream from this event itself. */
  var stream=document.getElementById('stream');
  if(stream) stream.dataset.streamFailed='1';
}

function positionRecIndicator(){
  if(!body || !body.classList.contains('page-live')) return;
  var dot=document.getElementById('live-rec-indicator');
  var stream=document.getElementById('stream');
  var cont=document.getElementById('stream-container');
  if(!dot||!stream||!cont||dot.hidden) return;

  var compactLandscape=window.matchMedia(
    '(orientation: landscape) and (max-width: 1180px)'
  ).matches;
  var compactPortrait=window.matchMedia(
    '(orientation: portrait)'
  ).matches;

  if(compactPortrait){
    var crp=cont.getBoundingClientRect();
    var srp=stream.getBoundingClientRect();
    var sizep=dot.offsetWidth || 15;
    dot.style.left=Math.round(srp.right-crp.left-sizep-10)+'px';
    dot.style.top=Math.round(srp.top-crp.top+10)+'px';
    dot.style.right='auto';
    dot.style.bottom='auto';
    dot.style.transform='none';
    return;
  }

  if(compactLandscape){
    var crl=cont.getBoundingClientRect();
    var nwl=stream.naturalWidth || 1446;
    var nhl=stream.naturalHeight || 800;
    var sizel=dot.offsetWidth || 15;
    if(crl.width>0 && crl.height>0 && nwl>0 && nhl>0){
      var scalel=Math.min(crl.width/nwl,crl.height/nhl);
      var iwl=nwl*scalel, ihl=nhl*scalel;
      var ixl=(crl.width-iwl)/2, iyl=(crl.height-ihl)/2;
      dot.style.left=Math.round(ixl+iwl-sizel-14)+'px';
      dot.style.top=Math.round(iyl+14)+'px';
    }else{
      dot.style.left='auto';
      dot.style.top='14px';
      dot.style.right='64px';
    }
    dot.style.bottom='auto';
    dot.style.transform='none';
    return;
  }

  var cr=cont.getBoundingClientRect();
  var nw=stream.naturalWidth || 1446;
  var nh=stream.naturalHeight || 800;
  if(!(cr.width>0 && cr.height>0 && nw>0 && nh>0)) return;

  var scale=Math.min(cr.width/nw,cr.height/nh);
  var iw=nw*scale;
  var ih=nh*scale;
  var ix=(cr.width-iw)/2;
  var iy=(cr.height-ih)/2;
  var imageRight=ix+iw;
  var gutter=Math.max(0,cr.width-imageRight);
  var size=dot.offsetWidth || 18;

  var x;
  if(gutter>=size+14){
    x=imageRight+(gutter-size)/2;
  }else{
    x=Math.max(ix+8,imageRight-size-14);
  }
  var y=iy+ih/2-size/2;

  dot.style.left=Math.round(x)+'px';
  dot.style.top=Math.round(y)+'px';
  dot.style.right='auto';
  dot.style.bottom='auto';
  dot.style.transform='none';
}
window.CinePiPositionRecIndicator=positionRecIndicator;

function syncStreamGeometry(){
  if(!body || !body.classList.contains('page-live')) return;
  var stream=document.getElementById('stream');
  var cont=document.getElementById('stream-container');
  if(!stream||!cont) return;
  var r=stream.getBoundingClientRect(), c=cont.getBoundingClientRect();
  var lv=document.getElementById('level-ov');
  if(lv){
    lv.style.left=(r.left-c.left+r.width/2)+'px';
    lv.style.top=(r.top-c.top+r.height/2)+'px';
  }
  positionRecIndicator();
}
function syncLandscapeChrome(){
  if(!body || !body.classList.contains('page-live')) return;
  if(!landscapeCompact()){
    body.style.removeProperty('--landscape-topbar-right');
    body.style.removeProperty('--landscape-scopes-bottom');
    return;
  }
  requestAnimationFrame(function(){
    var clips=document.getElementById('clips-link');
    var close=document.getElementById('ui-toggle');
    if(clips && close){
      var lr=clips.getBoundingClientRect();
      var xr=close.getBoundingClientRect();
      if(lr.width>0 && xr.width>0){
        var gap=Math.max(0,Math.round(xr.left-lr.right));
        var reserve=Math.max(0,Math.ceil(window.innerWidth-lr.left+gap));
        body.style.setProperty('--landscape-topbar-right',reserve+'px');
      }
    }
    var bottom=document.querySelector('.bottom-bar');
    if(bottom && body.classList.contains('controls-open')){
      var br=bottom.getBoundingClientRect();
      if(br.height>0){
        body.style.setProperty('--landscape-scopes-bottom',
          Math.max(0,Math.ceil(window.innerHeight-br.top+6))+'px');
      }
    }else{
      body.style.removeProperty('--landscape-scopes-bottom');
    }
  });
}

function viewportChanged(){
  placeResponsiveCameraControls();
  var vv=window.visualViewport;
  if(vv){
    root.style.setProperty('--visual-height',vv.height+'px');
    root.style.setProperty('--visual-width',vv.width+'px');
  }
  root.dataset.orientation=innerWidth>=innerHeight?'landscape':'portrait';
  if(userControlsChoice===null) applyControls();
  syncLandscapeChrome();
  requestAnimationFrame(syncStreamGeometry);
}

function registerPWA(){
  if('serviceWorker' in navigator){
    navigator.serviceWorker.register('/sw.js',{scope:'/'}).catch(function(){});
  }
}

document.addEventListener('DOMContentLoaded',function(){
  bindFullscreen();
  bindControls();
  placeResponsiveCameraControls();
  viewportChanged();
  registerPWA();
  var st=document.getElementById('stream');
  if(st){
    st.addEventListener('load',markLiveStreamLoaded);
    st.addEventListener('error',noteLiveStreamError);
    if('ResizeObserver' in window) new ResizeObserver(syncStreamGeometry).observe(st);
    connectLiveStream(true);
  }
  window.addEventListener('resize',viewportChanged,{passive:true});
  window.addEventListener('orientationchange',function(){
    userControlsChoice=null;
    setTimeout(viewportChanged,120);
  },{passive:true});
  window.addEventListener('pageshow',function(ev){
    /* A BFCache restore can revive the DOM with a dead network stream. */
    if(ev.persisted) connectLiveStream(true);
  },{passive:true});
  window.addEventListener('online',function(){connectLiveStream(true);},{passive:true});
  document.addEventListener('visibilitychange',function(){
    if(!document.hidden) connectLiveStream(false);
  });
  if(window.visualViewport) window.visualViewport.addEventListener('resize',viewportChanged,{passive:true});
});
})();