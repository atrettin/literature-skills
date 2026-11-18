// Draw the TeX the reader left in .math elements. A macro KaTeX does not know
// shows as red source text instead of breaking the page.
document.querySelectorAll(".math").forEach(function (el) {
  katex.render(el.textContent, el, {
    displayMode: el.classList.contains("block"),
    throwOnError: false,
  });
});
