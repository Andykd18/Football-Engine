const CACHE_NAME = 'accademy-v1';
const ASSETS = [
  '/Football-Engine/',
  '/Football-Engine/index.html',
  '/Football-Engine/manifest.json',
  '/Football-Engine/icons/icon-192x192.png',
  '/Football-Engine/icons/icon-512x512.png',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  // Network first for API calls, cache first for static assets
  if (event.request.url.includes('railway.app') || event.request.url.includes('odds-api')) {
    event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
  } else {
    event.respondWith(
      caches.match(event.request).then(cached => cached || fetch(event.request))
    );
  }
});
