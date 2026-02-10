// table.js — таблица и расчёты

function updateTotals(data) {
  let km = 0;
  let tons = 0;

  data.forEach(row => {
    km += Number(row.km || 0);
    tons += Number(row.tons || 0);
  });

  document.getElementById('total_km').textContent = km.toFixed(2);
  document.getElementById('total_tons').textContent = tons.toFixed(2);
}
