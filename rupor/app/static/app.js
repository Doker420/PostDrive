// Рупор — небольшой клиентский скрипт
document.addEventListener('DOMContentLoaded', () => {
  // Автоскрытие флеш-сообщений
  document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity .6s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 700);
    }, 5000);
  });

  // Сумма пополнения — только цифры/запятая
  const amount = document.querySelector('input[name="amount"]');
  if (amount) {
    amount.addEventListener('input', () => {
      amount.value = amount.value.replace(/[^\d.,]/g, '');
    });
  }
});
