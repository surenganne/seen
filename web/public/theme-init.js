// Set the stored theme before first paint (external file: CSP forbids inline scripts).
try {
  var t = localStorage.getItem("seen-theme");
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch (e) {}
