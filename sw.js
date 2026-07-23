// Offline cache for the GitHub Pages app. The app shell is self-contained;
// navigating while online always refreshes it, with the last copy as fallback.
const CACHE = 'draft-day-v4';
const SHELL = './index.html';
const STUDY = './study/index.html';
const ASSETS = [SHELL, STUDY];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  if (event.request.mode === 'navigate') {
    const target = /\/study(\/(index\.html)?)?$/.test(new URL(event.request.url).pathname) ? STUDY : SHELL;
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(target, copy)).catch(() => {});
          return response;
        })
        .catch(() => caches.match(target))
    );
    return;
  }

  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});
