"use strict";
// ======================================================================== //
// Academy — renders the curated learning library from /api/academy.
// Loaded after app.js; shares $, esc, getJSON. Single source of truth is
// academy.py on the server (also generates the portable academy/*.md files).
// ======================================================================== //

const AC_TYPE = {
  book: "📕 book", site: "🌐 site", doc: "📄 doc", video: "▶️ video",
  course: "🎓 course", community: "👥 community", tool: "🛠 tool", hotline: "☎ hotline",
};

function acResource(r) {
  const tag = AC_TYPE[r.type] || r.type;
  const costCls = r.cost === "free" ? "free" : (r.cost === "paid" ? "paid" : "freemium");
  const titleHtml = r.url
    ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)} <span class="ac-ext">↗</span></a>`
    : `<span class="ac-booktitle">${esc(r.title)}</span>`;
  return `<li class="ac-res">
    <div class="ac-res-head">
      <span class="ac-res-title">${titleHtml}</span>
      <span class="ac-badges"><span class="ac-badge type">${esc(tag)}</span><span class="ac-badge cost ${costCls}">${esc(r.cost)}</span></span>
    </div>
    <div class="ac-res-src">${esc(r.source)}</div>
    <div class="ac-res-why">${esc(r.why)}</div>
  </li>`;
}

function acTopic(t) {
  return `<div class="ac-topic">
    <h4>${esc(t.title)}</h4>
    <ul class="ac-res-list">${t.resources.map(acResource).join("")}</ul>
  </div>`;
}

function acCourse(c) {
  const tools = (c.tools && c.tools.length)
    ? `<div class="ac-maps"><b>In Money Lab:</b> ${esc(c.tools.join(" · "))}</div>` : "";
  const note = c.note ? `<div class="ac-note">${esc(c.note)}</div>` : "";
  return `<section class="ac-course" id="ac-course-${esc(c.id)}">
    <div class="ac-course-head">
      <span class="ac-emoji">${esc(c.emoji)}</span>
      <div>
        <h3>${esc(c.title)}</h3>
        <p class="ac-blurb">${esc(c.blurb)}</p>
        ${tools}
      </div>
    </div>
    ${note}
    ${c.topics.map(acTopic).join("")}
  </section>`;
}

let acLoaded = false;
async function loadAcademy() {
  if (acLoaded) return;
  acLoaded = true;
  let d;
  try {
    d = await getJSON("/api/academy");
  } catch (e) {
    acLoaded = false;
    $("acCourses").innerHTML = `<div class="empty-note">Couldn't load the Academy. Is the server running?</div>`;
    return;
  }
  $("acTagline").textContent = d.tagline || "";
  $("acDisclaimer").textContent = d.disclaimer || "";
  $("acToc").innerHTML = d.courses.map((c) =>
    `<a href="#ac-course-${esc(c.id)}" class="ac-toc-link"><span>${esc(c.emoji)}</span> ${esc(c.title)}</a>`
  ).join("");
  $("acCourses").innerHTML = d.courses.map(acCourse).join("");

  // smooth-scroll the in-section TOC without touching the URL hash
  $("acToc").addEventListener("click", (e) => {
    const a = e.target.closest(".ac-toc-link");
    if (!a) return;
    e.preventDefault();
    const el = document.getElementById(a.getAttribute("href").slice(1));
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

// Lazy-load the first time the Academy nav button is clicked.
$("mainNav").addEventListener("click", (e) => {
  const b = e.target.closest('.nav-btn[data-section="academy"]');
  if (b) loadAcademy();
});
