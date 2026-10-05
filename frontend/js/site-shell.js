const sitePages = [
  { file: "index.html", label: "Home", icon: "M3 11 12 3l9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" },
  { file: "about.html", label: "About", icon: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-8 9a8 8 0 0 1 16 0" },
  { file: "people.html", label: "People", icon: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-6 9a6 6 0 0 1 12 0m1-13a3 3 0 1 1 0 6m1 2a5 5 0 0 1 4 5" },
  { file: "instruments.html", label: "Instruments", icon: "M4 4h16v16H4zM8 8h8v8H8zM2 9h2m16 0h2M2 15h2m16 0h2M9 2v2m6-2v2m-6 16v2m6-2v2" },
  { file: "booking.html", label: "Book a slot", icon: "M3 5h18v16H3zM7 3v4m10-4v4M3 10h18m5 3 5 3-5 3z" },
  { file: "workshops.html", label: "Events & Workshop", icon: "M3 5h18v16H3zM7 3v4m10-4v4M3 10h18m5 3 5 3-5 3z" },
  { file: "forms-resources.html", label: "Forms & Resources", icon: "M6 3h8l4 4v14H6zM14 3v5h5m-9 4h6m-6 4h6" },
  { file: "data-analysis.html", label: "Data Analysis", icon: "M4 19V5m0 14h17m-14-4 4-4 3 2 5-6" },
  { file: "contact.html", label: "Contact", icon: "M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Zm-5 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" }
];

const currentFile = window.location.pathname.split("/").pop() || "index.html";
const activePage = sitePages.find(page => page.file === currentFile) || sitePages[0];
const main = document.querySelector("main");
const sidebar = document.createElement("aside");
sidebar.className = "site-sidebar";
sidebar.innerHTML = `
  <a class="sidebar-brand" href="index.html" aria-label="Divisional FACS Facility home">
    <span class="brand-logo"><img class="brand-seal" src="assets/images/site/iisc-seal.jpg" alt="Indian Institute of Science seal"></span>
    <span class="sidebar-brand-copy"><strong>IISc</strong><small>Divisional FACS<br>Facility</small></span>
  </a>
  <button class="menu-toggle" aria-label="Open navigation" aria-expanded="false" aria-controls="site-navigation"><span></span><span></span><span></span></button>
  <nav class="nav" id="site-navigation" aria-label="Main navigation">
    ${sitePages.map(page => `<a href="${page.file}"${page.file === activePage.file ? ' class="active" aria-current="page"' : ""}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${page.icon}"/></svg><span>${page.label}</span></a>`).join("")}
  </nav>
  <a class="sidebar-admin-link${currentFile === "admin.html" ? " active" : ""}" href="admin.html"${currentFile === "admin.html" ? ' aria-current="page"' : ""}>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 6v5c0 5 3.4 8.5 8 10 4.6-1.5 8-5 8-10V6zm-3 9 2 2 4-4"/></svg><span>Staff admin login</span>
  </a>
  <div class="sidebar-campus" aria-hidden="true">
    <img src="assets/images/site/iis-campus.jpg" alt="">
    <span>Indian Institute<br>of Science<br><small>Bengaluru</small></span>
  </div>
  <div class="sidebar-footer"><span class="sidebar-dot"></span><span>Facility Online</span></div>
`;

const siteMain = document.createElement("div");
siteMain.className = "site-main";
main.before(sidebar);
main.before(siteMain);
siteMain.append(main);
sidebar.addEventListener("mouseenter", () => document.body.classList.add("sidebar-expanded"));
sidebar.addEventListener("mouseleave", () => {
  if (!sidebar.matches(":focus-within")) document.body.classList.remove("sidebar-expanded");
});
sidebar.addEventListener("focusin", () => document.body.classList.add("sidebar-expanded"));
sidebar.addEventListener("focusout", () => {
  if (!sidebar.matches(":focus-within") && !sidebar.matches(":hover")) {
    document.body.classList.remove("sidebar-expanded");
  }
});
siteMain.insertAdjacentHTML("beforeend", `
  <footer>
    <div class="container footer-top">
      <a class="footer-brand" href="index.html"><span class="brand-logo">IISc</span><span><strong>Indian Institute of Science</strong><small>Bengaluru</small></span></a>
      <nav class="footer-links" aria-label="Footer navigation">
        <a href="about.html">About</a><a href="people.html">People</a><a href="instruments.html">Instruments</a><a href="booking.html">Book a slot</a><a href="workshops.html">Events &amp; Workshop</a><a href="forms-resources.html">Forms &amp; Resources</a><a href="data-analysis.html">Data Analysis</a><a href="contact.html">Contact</a><a href="admin.html">Staff admin login</a>
      </nav>
    </div>
    <div class="container footer-bottom"><span>© 2026 Divisional FACS Facility, IISc</span><a href="https://www.iisc.ac.in/" target="_blank" rel="noreferrer">Indian Institute of Science ↗</a></div>
  </footer>  `);
