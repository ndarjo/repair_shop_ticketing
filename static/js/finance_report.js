// ========================================
// REPAIR SHOP TICKETING SYSTEM
// Financial Reporting Chart Logic
// ========================================

document.addEventListener('DOMContentLoaded', function() {
    const ctx = document.getElementById('financeChart');
    if (ctx && typeof Chart !== 'undefined' && Chart !== null) {
        // Integrity: Prevent "Canvas is already in use" errors by destroying existing instance
        const existingChart = Chart.getChart(ctx);
        if (existingChart) {
            existingChart.destroy();
        }

        // Integrity: Safe JSON parsing
        const parseJsonData = (attr) => {
            try {
                const val = ctx.getAttribute(attr);
                return (val && val !== 'None') ? JSON.parse(val) : [];
            } catch (e) {
                return [];
            }
        };

        const labels = parseJsonData('data-labels');
        const revenue = parseJsonData('data-revenue');
        const costs = parseJsonData('data-costs');
        const profit = parseJsonData('data-profit');

        if (labels.length === 0) return;

        const labelRevenue = ctx.getAttribute('data-label-revenue') || 'Revenue';
        const labelCosts = ctx.getAttribute('data-label-costs') || 'Costs';
        const labelProfit = ctx.getAttribute('data-label-profit') || 'Net Profit';
        
        const symbolAttr = ctx.getAttribute('data-currency-symbol');
        const currencySymbol = (symbolAttr && symbolAttr !== 'None') ? symbolAttr : '';
        
        const decimalsAttr = ctx.getAttribute('data-currency-decimals');
        const parsedDecimals = parseInt(decimalsAttr, 10);
        const currencyDecimals = isNaN(parsedDecimals) ? 2 : parsedDecimals;
        
        // Dependable Localization: Convert Python locale (en_US) to JS BCP 47 (en-US)
        const localeAttr = ctx.getAttribute('data-locale');
        const locale = (localeAttr && localeAttr !== 'None') ? localeAttr.replace(/_/g, '-') : undefined;

        // UI Consistency: Match active theme and dark mode states
        const bodyStyle = getComputedStyle(document.body);
        const isDarkMode = document.body.classList.contains('theme-dark');
        
        // Fetch theme-specific colors
        const primaryColor = bodyStyle.getPropertyValue('--primary').trim() || '#0d6efd';
        const successColor = bodyStyle.getPropertyValue('--bs-success').trim() || '#198754';
        const dangerColor = bodyStyle.getPropertyValue('--bs-danger').trim() || '#dc3545';
        const textColor = isDarkMode ? '#ffffff' : '#212529';
        const gridColor = isDarkMode ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';

        /**
         * Helper to ensure consistent transparency for backgrounds across all browsers.
         * Handles Hex, RGB, and RGBA computed styles safely.
         */
        const getTransColor = (color) => {
            if (color.startsWith('#')) return color + '1a';
            if (color.startsWith('rgba')) return color.replace(/[^,)]+\)$/, '0.1)');
            if (color.startsWith('rgb')) return color.replace('rgb', 'rgba').replace(')', ', 0.1)');
            return color;
        };

        new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: labelRevenue,
                        data: revenue,
                        borderColor: successColor,
                        backgroundColor: getTransColor(successColor),
                        fill: true,
                        tension: 0.3
                    },
                    {
                        label: labelCosts,
                        data: costs,
                        borderColor: dangerColor,
                        backgroundColor: getTransColor(dangerColor),
                        fill: true,
                        tension: 0.3
                    },
                    {
                        label: labelProfit,
                        data: profit,
                        borderColor: primaryColor,
                        backgroundColor: getTransColor(primaryColor),
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
                plugins: {
                    legend: {
                        labels: { 
                            color: textColor,
                            font: { family: bodyStyle.fontFamily }
                        }
                    },
                    tooltip: {
                        backgroundColor: isDarkMode ? '#2d2d2d' : '#fff',
                        titleColor: isDarkMode ? '#fff' : '#000',
                        bodyColor: isDarkMode ? '#eee' : '#666',
                        borderColor: gridColor,
                        borderWidth: 1,
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) label += ': ';
                                if (context.parsed.y !== null) {
                                    label += currencySymbol + context.parsed.y.toLocaleString(locale, {
                                        minimumFractionDigits: currencyDecimals,
                                        maximumFractionDigits: currencyDecimals
                                    });
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { 
                            color: textColor,
                            font: { family: bodyStyle.fontFamily }
                        },
                        grid: { display: false }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: gridColor },
                        ticks: {
                            color: textColor,
                            font: { family: bodyStyle.fontFamily },
                            callback: function(value) {
                                return currencySymbol + value.toLocaleString(locale, {
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
