const CACHE='cinepi-shell-v24';
const SHELL=[
  '/static/css/cinemate-responsive.css',
  '/static/js/cinemate-app.js',
  '/static/js/cube-lut-engine.js',
  '/static/manifest.webmanifest',
  '/static/icons/cinepi-192.png',
  '/static/icons/cinepi-512.png'
];
self.addEventListener('install',function(event){
  event.waitUntil(caches.open(CACHE).then(function(c){return c.addAll(SHELL);}).then(function(){return self.skipWaiting();}));
});
self.addEventListener('activate',function(event){
  event.waitUntil(caches.keys().then(function(keys){
    return Promise.all(keys.filter(function(k){return k!==CACHE;}).map(function(k){return caches.delete(k);}));
  }).then(function(){return self.clients.claim();}));
});
self.addEventListener('fetch',function(event){
  var u=new URL(event.request.url);
  if(event.request.method!=='GET' || u.pathname==='/stream' || u.pathname==='/frame.jpg' || u.port==='8000') return;
  if(u.pathname.startsWith('/static/')){
    event.respondWith(caches.match(event.request).then(function(hit){
      return hit || fetch(event.request).then(function(r){
        var copy=r.clone();
        caches.open(CACHE).then(function(c){c.put(event.request,copy);});
        return r;
      });
    }));
  }
});
