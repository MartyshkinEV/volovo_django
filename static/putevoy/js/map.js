(function () {
  console.log("map.js loaded");
  if (typeof L === "undefined") {
    console.error("Leaflet (L) not loaded");
    return;
  }
  const el = document.getElementById("map");
  if (!el) {
    console.error("#map not found");
    return;
  }
  const map = L.map("map").setView([52.036282, 37.887833], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap"
  }).addTo(map);
})();
