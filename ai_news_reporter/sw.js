// BUG FIX: bump CACHE_NAME whenever you deploy — old cache is then discarded.
// Deliberately NOT caching index.html so browser always fetches the latest version.
const CACHE_NAME = 'newsdesk-v2';
const STATIC_ASSETS = [
  // Only cache truly static assets (fonts, icons etc.)
  // Do NOT cache index.html — you want the freshest markup on every load.
];

self.addEventListener('install', (event) => {
  // Skip waiting so the new SW activates immediately
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return STATIC_ASSETS.length ? cache.addAll(STATIC_ASSETS) : Promise.resolve();
    })
  );
});

self.addEventListener('activate', (event) => {
  // Delete all old caches on activation
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Never intercept non-GET, API calls, or HTML documents
  if (
    event.request.method !== 'GET' ||
    event.request.url.includes('/query') ||
    event.request.url.includes('/confirm') ||
    event.request.url.includes('/health') ||
    event.request.destination === 'document'   // ← never cache HTML
  ) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});