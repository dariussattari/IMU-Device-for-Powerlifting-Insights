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
              NN on windowed IMU time-series counts squat / bench / deadlift reps given a
              user-specified exercise type.
            </div>
            <div className="tgt">
              target <b>≥ 95% accuracy</b>
            </div>
          </div>
          <div className="hyp-row">
            <div className="k">H2 · Bar path</div>
            <div className="v">
              EKF fusing accelerometer &amp; gyroscope reconstructs bar trajectories suitable
              for sagittal / lateral path analysis.
            </div>
            <div className="tgt">
              target <b>low drift across rep window</b>
            </div>
          </div>
          <div className="hyp-row">
            <div className="k">H3 · 1RM prediction</div>
            <div className="v">
              IMU-derived velocity metrics predict 1RM better than Epley / Brzycki rep-based
              formulas.
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
            <div className="tgt">
              target <b>ICC ≥ 0.8 across sessions</b>
            </div>
          </div>
        </div>

        <div className="panel contact">
          <div className="panel-h">
            <span className="tit">Author · research contact</span>
          </div>
          <div className="contact-body">
            <div className="name">Darius Sattari</div>
            <div className="aff">Barbell Lab · Harvard SEAS</div>
            <a className="mail" href="mailto:dariussattari@g.harvard.edu">
              dariussattari@g.harvard.edu
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
