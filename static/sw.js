const CACHE_NAME = 'robo-pirate-hr-v12';
const STATIC_EXTENSIONS = ['.css', '.js', '.png', '.jpg', '.jpeg', '.webp', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.json'];
// No external CDNs — everything is self-hosted, so never put this origin's
// HTML behind cross-origin rules. (Old CDN_HOSTS + no-cors precache used to
// store opaque error pages as "cached" CSS, which made first load look slow
// or unstyled on school networks.)

// Assets to cache immediately on install so the next visit loads offline/instanly.
// All fonts/bootstrap are self-hosted now (no external CDN round-trips).
// NOTE: keep versioned portal.css/portal.js OUT of precache — they change per
// deploy via ?v=ASSET_VERSION and stale-while-revalidate below keeps them
// fresh without blocking install. Only tiny stable files are precached.
const PRECACHE_URLS = [
  '/static/js/main.js',
  '/static/manifest.json',
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      Promise.all(
        PRECACHE_URLS.map(url =>
          // Same-origin GET with credentials: only cache real 200 responses
          // so login HTML / error pages never poison the static cache.
          fetch(url, { credentials: 'same-origin' })
            .then(response => {
              if (response && response.ok) return cache.put(url, response);
            })
            .catch(() => {})
        )
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
  // Same-origin only; query strings (?v=11) are still static. Never treat
  // login HTML as a static asset.
  return extMatch && url.origin === self.location.origin;
}

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Never cache or intercept mutations (POST/PUT/DELETE).
  // Just let them hit the network directly so the app always talks to the server.
  if (request.method !== 'GET') {
    return;
  }

  // Static assets (same-origin only): stale-while-revalidate. Serve cache
  // instantly (fast repeat visits), refresh in background. Ignore query
  // strings when matching (?v=11 versioning) so deploys still hit cache.
  if (isStaticAsset(url)) {
    event.respondWith(
      caches.match(request, { ignoreSearch: true }).then(cached => {
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
  // Only cache real 200 HTML (never redirects/login-error pages).
  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response && response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match(request).then(cached => cached || caches.match('/portal/login')))
    );
    return;
  }

  // Everything else (GET): try network, then cache.
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});
