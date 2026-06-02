// Header scroll effect
const header = document.getElementById('header');
window.addEventListener('scroll', () => {
  header.classList.toggle('scrolled', window.scrollY > 20);
});

// Mobile hamburger
const hamburger = document.getElementById('hamburger');
const nav = document.getElementById('nav');
hamburger.addEventListener('click', () => {
  nav.classList.toggle('open');
  hamburger.classList.toggle('active');
});

// Close nav on link click
document.querySelectorAll('.nav__link').forEach(link => {
  link.addEventListener('click', () => {
    nav.classList.remove('open');
    hamburger.classList.remove('active');
  });
});

// Product filter
const filtros = document.querySelectorAll('.filtro');
const cards = document.querySelectorAll('.producto-card');
filtros.forEach(btn => {
  btn.addEventListener('click', () => {
    filtros.forEach(f => f.classList.remove('active'));
    btn.classList.add('active');
    const filter = btn.dataset.filter;
    cards.forEach(card => {
      const show = filter === 'all' || card.dataset.category === filter;
      card.classList.toggle('hidden', !show);
    });
  });
});

// FAQ accordion
document.querySelectorAll('.faq__q').forEach(btn => {
  btn.addEventListener('click', () => {
    const item = btn.parentElement;
    const isOpen = item.classList.contains('open');
    document.querySelectorAll('.faq__item.open').forEach(i => i.classList.remove('open'));
    if (!isOpen) item.classList.add('open');
  });
});

// Contact form (basic validation + UX)
const form = document.getElementById('contactForm');
form.addEventListener('submit', (e) => {
  e.preventDefault();
  const nombre = form.nombre.value.trim();
  const telefono = form.telefono.value.trim();
  const email = form.email.value.trim();
  if (!nombre || !telefono || !email) {
    alert('Por favor rellena los campos obligatorios: nombre, teléfono y email.');
    return;
  }
  const btn = form.querySelector('button[type="submit"]');
  btn.textContent = '✓ Solicitud enviada — Te contactaremos pronto';
  btn.disabled = true;
  btn.style.background = '#2d6a4f';
});

// Smooth scroll offset for fixed header
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', (e) => {
    const target = document.querySelector(anchor.getAttribute('href'));
    if (!target) return;
    e.preventDefault();
    const offset = 80;
    const top = target.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo({ top, behavior: 'smooth' });
  });
});
