// Ask before a form marked data-confirm is sent. A static file, because the
// Content-Security-Policy runs no inline script.
document.querySelectorAll("form[data-confirm]").forEach(function (form) {
  form.addEventListener("submit", function (event) {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
