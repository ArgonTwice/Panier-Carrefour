// Service worker : seulement pour afficher les notifications (panier prêt, bons qui expirent)
self.addEventListener("push", (e) => {
  const { titre, texte } = e.data ? e.data.json() : { titre: "Panier Carrefour", texte: "" };
  e.waitUntil(self.registration.showNotification(titre, { body: texte, icon: "icone-192.png", badge: "icone-192.png" }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(clients.matchAll({ type: "window" }).then((fenetres) =>
    fenetres.length ? fenetres[0].focus() : clients.openWindow("/")));
});
