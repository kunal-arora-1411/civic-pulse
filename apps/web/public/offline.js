// External rather than inline so offline.html works under script-src 'self'.
document.getElementById("retry").addEventListener("click", () => {
  location.reload();
});
window.addEventListener("online", () => location.reload());
