# Figure review and corrections

Run `python rebuild_reviewed_figures.py` from the repository root to reproduce the
17 corrected PNG files in `outputs/figures/`. Numerical companions are
`outputs/reviewed_predictor_metrics.csv` and
`outputs/reviewed_scheduling_summary.csv`.

## Substantive problems found

| Figures | Problem in original charts | Correction |
| --- | --- | --- |
| 1–3 | Six hundred seconds compressed narrow state/current pulses. | Show the first 120 s and state units explicitly. |
| 4 | Title implied the configured 27 OCV points were verified raw CALCE measurements, although no raw measurements are in the repository. | Label them as an illustrative configured table. |
| 5–7 | Ten-minute battery changes were visually invisible; Figure 7 combined SOC-scaled nominal energy and terminal delivered energy as if they were complements. | State the short horizon, magnify remaining energy, and identify the SOC-derived quantity. |
| 8–11 | The 10 h run treated its final timestamp as battery death when it had not observed a cutoff. Predictor C used default low-current, short-active settings unrelated to the 20/8/2 s, 15 µA/500 mA/1 A load. Figures 9 and 11 were dominated by extreme values from short windows and instantaneous power. | Extend the same load until simulated cutoff; match C to actual state fractions and currents; use a log axis for A and readable complete-cycle windows for B. |
| 12–17 | The fixed runs stopped at 40 h without cutoff, while adaptive used a different current scaling that raised its TX current to about 1.85 A. Its 10 h duration was an artificial depletion from this mismatched path. Figures 16–17 presented 40 h and 10 h as measured runtime and a runtime–QoS trade-off. | Compare every mode on the same 40 h horizon with 15 µA/50 mA/200 mA state currents and one battery model. Mark all runtimes as right-censored (>40 h). Plot end SOC and mean power versus QoS instead. Adaptive overlaps fixed High QoS because the 1 h switch threshold is never reached. |

The original `outputs/predictor_metrics.csv`, `outputs/scheduling_summary.csv`,
`outputs/adaptive_simulation.csv`, and Part 3/4 reports were produced by the old
scripts and **must not be cited alongside the reviewed figures**. Use the reviewed
CSV files instead. The original script entry points also retain the old modeling
behavior; run `rebuild_reviewed_figures.py` to regenerate these figures.

## Interpretation limits

- The results are a digital prototype. The OCV points and state currents are
  configured assumptions, not validated raw battery and hardware measurements.
- The 1 s scheduler resolves each nominal 0.5 s TX event to one whole step.
  The reviewed Predictor C uses the corresponding discrete average current.
- In the 40 h comparison, no strategy reaches voltage or SOC cutoff. Its actual
  lifetime and any runtime extension cannot be estimated from that window.
- Figure 17 draws one compound marker labeled `High QoS = Adaptive` because both
  strategies have identical mean power and QoS during the 40 h observation.
- In the heavy-load predictor experiment, the first 30 s of the rolling-power
  predictor are a warm-up period and are excluded from the reviewed MAE values.
