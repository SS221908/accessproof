"use strict";
const scenario = location.pathname.split("/").filter(Boolean).pop();
const form = document.getElementById("booking");
const slot = document.getElementById("action-slot");
const register = document.createElement(scenario === "unreachable" ? "div" : "button");
register.id = "register";
register.textContent = "Reserve appointment";
register.className = "submit-control";
if (scenario === "unreachable") { register.setAttribute("role", "button"); register.tabIndex = -1; }
else register.type = "submit";
slot.append(register);
if (scenario === "variant") {
  form.insertBefore(document.getElementById("topic-field"), document.getElementById("name-field"));
  form.insertBefore(document.getElementById("email-field"), document.getElementById("name-field"));
}
function book() {
  const name = document.getElementById("name").value.trim();
  const email = document.getElementById("email").value.trim();
  const topic = document.getElementById("topic").value;
  if (!name || !email.includes("@") || !topic) {
    document.getElementById("form-message").textContent = "Please enter your name, a valid email address, and a tutoring topic.";
    return;
  }
  form.hidden = true;
  document.getElementById("form-title").hidden = true;
  const confirmation = document.getElementById("confirmation");
  document.getElementById("confirmation-details").textContent = `${name} · ${email} · ${topic}`;
  confirmation.hidden = false;
  confirmation.dataset.apSuccess = "true";
}
form.addEventListener("submit", event => {
  event.preventDefault();
  if (scenario !== "unreachable") book();
});
if (scenario === "unreachable") register.addEventListener("click", book);
if (scenario === "trap") {
  const layer = document.getElementById("notice-layer");
  layer.hidden = false;
  const buttons = [...document.querySelectorAll("#notice button")];
  buttons[0].focus();
  document.getElementById("dismiss-notice").addEventListener("click", () => {layer.hidden = true; document.getElementById("name").focus();});
  document.getElementById("notice-details").addEventListener("click", () => {document.getElementById("notice-message").textContent = "We use your booking details only for this session.";});
  document.getElementById("notice-access").addEventListener("click", () => {document.getElementById("notice-message").textContent = "Contact your tutoring center for help with this booking form.";});
  document.getElementById("notice").addEventListener("keydown", event => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); }
    if (event.key === "Tab") {
      event.preventDefault();
      const current = buttons.indexOf(document.activeElement);
      buttons[(current + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length].focus();
    }
  });
}
