// Comment affordances for the doc view: 💬 on every heading, badges for
// sections with open comments, selection capture into the composer quote.
(function () {
  var article = document.querySelector("article.doc[data-doc-id]");
  if (!article || typeof htmx === "undefined") return;
  var docId = article.dataset.docId;

  var counts = {};
  try {
    counts = JSON.parse(document.getElementById("comment-counts").textContent) || {};
  } catch (e) {}

  function threadUrl(kind, heading, quote) {
    var params = new URLSearchParams({ anchor_kind: kind, doc_id: docId });
    if (heading) params.set("heading", heading);
    if (quote) params.set("quote", quote.slice(0, 1000));
    return "/partial/comments?" + params.toString();
  }

  function toggleThread(container, kind, heading, quote) {
    if (!container.hidden && container.innerHTML.trim() !== "") {
      container.hidden = true;
      container.innerHTML = "";
      return;
    }
    container.hidden = false;
    htmx.ajax("GET", threadUrl(kind, heading, quote), { target: container, swap: "innerHTML" });
  }

  // Whole-doc comments.
  var docBtn = article.querySelector(".doc-comment-btn");
  var docThread = article.querySelector('.comment-thread[data-anchor-kind="doc"]');
  if (docBtn && docThread) {
    if (counts[""]) docBtn.textContent = "💬 " + counts[""];
    docBtn.addEventListener("click", function () {
      toggleThread(docThread, "doc", null, "");
    });
  }

  // Per-section comments.
  article.querySelectorAll(".doc-body h1[id], .doc-body h2[id], .doc-body h3[id], .doc-body h4[id]")
    .forEach(function (heading) {
      var slug = heading.id;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "comment-btn heading-comment-btn";
      btn.title = "Comment on this section";
      btn.textContent = counts[slug] ? "💬 " + counts[slug] : "💬";
      if (counts[slug]) btn.classList.add("has-comments");

      var container = document.createElement("div");
      container.className = "comment-thread";
      container.hidden = true;
      heading.insertAdjacentElement("afterend", container);

      btn.addEventListener("click", function (e) {
        e.preventDefault();
        var selection = "";
        try { selection = String(window.getSelection() || "").trim(); } catch (err) {}
        toggleThread(container, "doc-section", slug, selection);
      });
      heading.appendChild(btn);
    });
})();
