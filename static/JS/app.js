(function () {
  // Mobile nav
  const toggle = document.getElementById('navToggle'), nav = document.getElementById('nav');
  if (toggle) toggle.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    toggle.setAttribute('aria-expanded', open);
  });

  // Toasts: dismiss button + auto-hide
  document.querySelectorAll('.toast').forEach(t => {
    t.querySelector('[data-dismiss]').addEventListener('click', () => t.remove());
    setTimeout(() => t.remove(), 6000);
  });

  // Password visibility
  document.querySelectorAll('[data-toggle-pw]').forEach(b => b.addEventListener('click', () => {
    const i = document.getElementById(b.dataset.togglePw);
    const show = i.type === 'password';
    i.type = show ? 'text' : 'password';
    b.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  }));

  // Before / after sliders
  document.querySelectorAll('[data-compare]').forEach(el => {
    const range = el.querySelector('input[type=range]');
    const set = () => el.style.setProperty('--pos', range.value + '%');
    range.addEventListener('input', set); set();
  });
})();
