const CACHE_NAME = 'robo-pirate-hr-v3';
const STATIC_EXTENSIONS = ['.css', '.js', '.png', '.jpg', '.jpeg', '.webp', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.json'];
const CDN_HOSTS = ['cdn.jsdelivr.net', 'fonts.googleapis.com', 'fonts.gstatic.com'];

// Assets to cache immediately on install so the next visit loads offline/instanly.
const PRECACHE_URLS = [
  '/static/css/style.css',
  '/static/js/main.js',
  '/static/manifest.json',
  '/login',
  '/portal/login',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js',
  'https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700;800&family=Inter:wght@400;500;600&display=swap'
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      Promise.all(
        PRECACHE_URLS.map(url => {
          const isCors = url.startsWith(self.location.origin);
          return fetch(url, { mode: isCors ? 'cors' : 'no-cors' })
            .then(response => cache.put(url, response))
            .catch(() => {});
        })
      )
    )
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

function isStaticAsset(url) {
  const extMatch = STATIC_EXTENSIONS.some(ext => url.pathname.toLowerCase().endsWith(ext));
  return extMatch && (
    url.origin === self.location.origin || CDN_HOSTS.includes(url.hostname)
  );
}

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Static assets (same-origin + CDN): cache first, update in background.
  if (isStaticAsset(url)) {
    event.respondWith(
      caches.match(request).then(cached => {
        const networkFetch = fetch(request)
          .then(response => {
            if (response && response.ok) {
              const clone = response.clone();
              caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
            }
            return response;
          })
          .catch(() => cached);
        return cached || networkFetch;
      })
    );
    return;
  }

  // HTML pages / navigations: network first, fall back to cache if offline.
  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(
      fetch(request)
        .then(response => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
          return response;
        })
        .catch(() => caches.match(request).then(cached => cached || caches.match('/portal/login')))
    );
    return;
  }

  // Everything else: try network, then cache.
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});
