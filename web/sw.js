const CACHE = 'repeaters-v1';
const SHELL = [
  './', './index.html', './style.css', './app.js', './manifest.webmanifest', './data/repeaters.json',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  // 数据包：先用缓存保证野外可用，同时后台更新
  if (req.url.includes('/data/repeaters.json')) {
    e.respondWith((async () => {
      const cache = await caches.open(CACHE);
      const cached = await cache.match(req);
      const network = fetch(req).then((res) => { cache.put(req, res.clone()); return res; }).catch(() => null);
      return cached || (await network) || new Response('{}', { headers: { 'content-type': 'application/json' } });
    })());
    return;
  }
  e.respondWith(caches.match(req).then((hit) => hit || fetch(req).catch(() => caches.match('./index.html'))));
});
