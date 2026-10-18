# ETH causal PRICE/MARKET replay — 15.10.2026

Один ранее выбранный ETH/follow/z2.5/h120. Binance USD-M, просмотренный период, не OOS, не WEEX и не maker replay. Исходные174сигнала независимо восстановлены точно; стопы/цели/выходы пересчитаны от новых входов.

| Сценарий | N | Net USDT | Mean net % | PF | 95% monthly block CI % | DD liquidation USDT | Без3лучших net USDT |
|---|---:|---:|---:|---:|---|---:|---:|
| static_all_in_4bp | 174 | +56.586161 | +0.032520782 | 1.100359 | [-0.06266520646084828, 0.14227491568994147] | 76.523112 | +3.786161 |
| static_all_in_8bp | 174 | -13.013839 | -0.007479218 | 0.978323 | [-0.10266520646084827, 0.10227491568994142] | 105.875297 | -64.613839 |
| decomposed_fee1bp_slip1bp | 174 | +52.131555 | +0.029960664 | 1.091654 | [-0.0740113107942369, 0.14618251050232214] | 86.152417 | -1.039210 |
| decomposed_fee1bp_slip3bp | 174 | -31.218836 | -0.017941860 | 0.948480 | [-0.11703578568097175, 0.09230580704465803] | 118.813546 | -83.800355 |

Static all-in4/8bp: новые raw-price пути, плоский круг от entry notional без дополнительного funding/fees/slip. Decomposed: fee1bp за каждое исполнение + adverse slip1bp/3bp на сторону + signed Binance funding, без плоского круга. В каждом сценарии геометрия стопа0.9%/цели1.8% строится заново от его фактического входа, срок — точный t0+120min.

Размер — continuous diagnostic: R10USDT, entry notional≤1000USDT, без проверенной исторической contract step/tick и без сложного процента. Суммы не доходность реального депозита. DD учитывает начальную точку, minute-close liquidation и immediate-entry friction; OHLC не показывает полный внутриминутный floating worst-case.

Исключение трёх лучших — заранее заданный adversarial diagnostic, не оценка вероятности maker no-fill. Ранее просмотренные данные и месячный CI не подтверждают новую прибыльную систему. Макс.убыток, funding bounds, причины выходов, полный ledger/equity — REPORT.json и CSV.

Файлы источников неизменны; хеши/допущения зафиксированы до расчёта в INPUT_MANIFEST.json и README_ASSUMPTIONS.md. Никаких private API, ключей, счёта, Mac, Claude или сетевых вызовов. Воспроизведение: сначала `python -m unittest test_replay -v`, затем `python run_replay.py` из этой папки с исходными соседними research-файлами.
