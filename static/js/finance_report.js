
document.addEventListener('DOMContentLoaded', function() {
    const ctx = document.getElementById('financeChart');
    if (ctx) {
        const labels = JSON.parse(ctx.getAttribute('data-labels') || '[]');
        const revenue = JSON.parse(ctx.getAttribute('data-revenue') || '[]');
        const costs = JSON.parse(ctx.getAttribute('data-costs') || '[]');
        const profit = JSON.parse(ctx.getAttribute('data-profit') || '[]');

        const labelRevenue = ctx.getAttribute('data-label-revenue') || 'Revenue';
        const labelCosts = ctx.getAttribute('data-label-costs') || 'Costs';
        const labelProfit = ctx.getAttribute('data-label-profit') || 'Net Profit';
        const currencySymbol = ctx.getAttribute('data-currency-symbol') || '';
        const currencyDecimals = parseInt(ctx.getAttribute('data-currency-decimals') || '2');

        new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: labelRevenue,
                        data: revenue,
                        borderColor: '#198754',
                        backgroundColor: 'rgba(25, 135, 84, 0.1)',
                        fill: true,
                        tension: 0.3
                    },
                    {
                        label: labelCosts,
                        data: costs,
                        borderColor: '#dc3545',
                        backgroundColor: 'rgba(220, 53, 69, 0.1)',
                        fill: true,
                        tension: 0.3
                    },
                    {
                        label: labelProfit,
                        data: profit,
                        borderColor: '#0d6efd',
                        backgroundColor: 'rgba(13, 110, 253, 0.1)',
                        fill: true,
                        tension: 0.3
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    intersect: false,
                    mode: 'index'
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return currencySymbol + value.toLocaleString(undefined, {
                                    minimumFractionDigits: currencyDecimals,
                                    maximumFractionDigits: currencyDecimals
                                });
                            }
                        }
                    }
                }
            }
        });
    }
});
