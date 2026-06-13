const CACHE_NAME = 'robo-pirate-hr-v1';
const urlsToCache = [
  '/',
  '/portal/login',
  '/portal/dashboard',
  '/portal/punch',
  '/portal/attendance',
  '/portal/leaves',
  '/portal/payslips'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        if (response) return response;
        return fetch(event.request);
      })
  );
});
