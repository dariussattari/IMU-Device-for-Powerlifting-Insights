export default function ResearchTab() {
  return (
    <section className="tabview">
      <div className="hyp-wrap">
        <div className="panel hyp">
          <div className="panel-h">
            <span className="tit">Research hypotheses</span>
            <span className="r">
              <span className="chip">open dataset</span>
            </span>
          </div>
          <div className="hyp-row">
            <div className="k">H1 · Rep counting</div>
            <div className="v">
              A signal-processing pipeline can count squat / bench / deadlift reps from a
              single barbell-mounted IMU without per-lifter training.
            </div>
            <div className="meth">
              <b>Method</b>
              Schmitt-trigger hysteresis on vertical velocity (vy ±0.25&nbsp;m/s).
              Pipeline: gravity-removed a<sub>y</sub> → 5&nbsp;Hz Butterworth low-pass →
              cumulative integration → 0.3&nbsp;Hz high-pass to suppress integrator drift.
              Two post-rep gates filter out false reps: a global-gyro rerack check (drops
              candidates whose peak gyro &gt; 1.5× the per-rep median) and a 2.0&nbsp;s
              post-motion test (≥ 0.7&nbsp;rad/s must follow the last candidate, else
              the bar is settled on the rack).
            </div>
            <div className="tgt">
              target <b>≥ 95% accuracy vs. rep counts logged at collection time</b>
            </div>
          </div>
          <div className="hyp-row">
            <div className="k">H2 · Bar path</div>
            <div className="v">
              A single 6-DoF IMU can recover per-rep 2-D bar trajectory with bounded drift,
              despite no magnetometer, by exploiting stationary endpoints at lockout.
            </div>
            <div className="meth">
              <b>Method</b>
              Calibration-only orientation: gravity vector fitted from a 1&nbsp;s pre-lift
              stillness window defines a static body-to-world rotation (no AHRS across
              the session — gyro integration through unrack events flips world-Z). World
              linear accel = R·a<sub>body</sub> − g, low-passed at 15&nbsp;Hz. Each rep is
              integrated once over its full lockout→chest→lockout cycle with linear
              endpoint anchoring on velocity AND position across all three axes — both
              endpoints share the same stationary pose, so drift is bounded inside the
              rep window. Output resampled to 120 points.
            </div>
            <div className="tgt">
              target <b>per-rep drift &lt; 5&nbsp;cm; consistent ROM within session</b>
            </div>
          </div>
          <div className="hyp-row">
            <div className="k">H3 · 1RM prediction</div>
            <div className="v">
              IMU-derived velocity metrics predict 1RM better than Epley / Brzycki
              rep-based formulas.
            </div>
            <div className="meth">
              <b>Method</b>
              <b style={{ color: "var(--ink-700)" }}>Primary</b>
              Linear load–velocity profile (LVP) across <b>≥ 2 loads</b>. For each
              load the best mean propulsive velocity (MPV) is taken; OLS regresses
              MPV on load and extrapolates to a literature minimum velocity threshold
              (MVT = 0.17&nbsp;m/s for bench). Consensus is an R²-weighted mean of
              three MPV / MCV / top-2-MPV variants (each requiring R² ≥ 0.50 and
              negative slope). 95% CI from 2000-iteration bootstrap over the per-rep
              pool.
              <br />
              <b style={{ color: "var(--ink-700)" }}>Single-set fallback</b>
              When only one set is selected the LVP cannot be fit, so the consensus
              switches to the mean of two heuristic estimators: (a) González-Badillo
              2011 population equation %1RM&nbsp;= 8.43·MPV² − 73.5·MPV + 112.3
              applied to the heaviest set's best MPV, and (b) within-set velocity
              loss → reps-in-reserve → %1RM via the Baechle rep table. No
              bootstrap CI in this mode.
            </div>
            <div className="tgt">
              target <b>within 5% of tested 1RM</b>
            </div>
          </div>
          <div className="hyp-row">
            <div className="k">H4 · Sticking region</div>
            <div className="v">
              Phase-anchored sticking points are reproducible per lifter-exercise and
              predictive of proximity to failure.
            </div>
            <div className="meth">
              <b>Method</b>
              Per-rep concentric velocity is scanned with scipy.signal.find_peaks for the
              initial drive peak (first local max, prominence ≥ 0.02&nbsp;m/s) and the
              deepest valley after it. A sticking point is accepted if velocity depth
              (peak − valley) ≥ 0.04&nbsp;m/s, post-valley resurgence ≥ 0.02&nbsp;m/s
              (lifter recovers before lockout), and the valley sits within 10–90% of
              concentric duration. Reps without a clear double-peak signature return
              NaN; otherwise the output is time, depth, and fractional position.
            </div>
            <div className="tgt">
              target <b>same lifter · same load → sticking time within ±10% across sessions</b>
            </div>
          </div>
        </div>

        <div className="panel contact">
          <div className="panel-h">
            <span className="tit">Authors · research contact</span>
          </div>
          <div className="contact-body">
            <div className="name">Darius Sattari</div>
            <div className="aff">Barbell Lab · Harvard SEAS</div>
            <a className="mail" href="mailto:dariussattari@g.harvard.edu">
              dariussattari@g.harvard.edu
            </a>
            <div className="name" style={{ marginTop: 14 }}>Mashruf Mahin</div>
            <div className="aff">Barbell Lab · Harvard SEAS</div>
            <a className="mail" href="mailto:mmahin@college.harvard.edu">
              mmahin@college.harvard.edu
            </a>
            <div className="note">
              For dataset access, hardware schematics, and collaboration inquiries on the
              open IMU-lifting platform.
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
