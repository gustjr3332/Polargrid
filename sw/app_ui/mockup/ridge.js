// AI (3) in the browser: StandardScaler + Ridge, the same maths as polagrid/ai.py fit_preference (sklearn).
// The phone page learns from the saved corrections and posts {mean, scale, coef, intercept, n} to the demo server;
// tools/real_cell.py ai --pref web aims the cell with it. Checked against sklearn by tests/test_ridge_js.py.
function fitRidge(X, y, alpha = 1) {
  const n = X.length, d = X[0].length, eps = Number.EPSILON;
  const mean = [], scale = [];
  for (let j = 0; j < d; j++) {
    const m = X.reduce((a, r) => a + r[j], 0) / n;
    const v = X.reduce((a, r) => a + (r[j] - m) ** 2, 0) / n;
    mean.push(m);
    scale.push(v <= n * eps * v + (n * m * eps) ** 2 ? 1 : Math.sqrt(v));   // sklearn: a constant column keeps scale 1
  }
  const Z = X.map(r => r.map((v, j) => (v - mean[j]) / scale[j]));
  const ybar = y.reduce((a, v) => a + v, 0) / n;
  // (ZtZ + alpha I) w = Zt (y - ybar), Gauss elimination with partial pivoting
  const A = Array.from({length: d}, (_, i) => Array.from({length: d}, (_, j) => Z.reduce((a, r) => a + r[i] * r[j], 0) + (i === j ? alpha : 0)));
  const b = Array.from({length: d}, (_, i) => Z.reduce((a, r, k) => a + r[i] * (y[k] - ybar), 0));
  for (let c = 0; c < d; c++) {
    let p = c;
    for (let r = c + 1; r < d; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    [A[c], A[p]] = [A[p], A[c]]; [b[c], b[p]] = [b[p], b[c]];
    for (let r = c + 1; r < d; r++) {
      const f = A[r][c] / A[c][c];
      for (let k = c; k < d; k++) A[r][k] -= f * A[c][k];
      b[r] -= f * b[c];
    }
  }
  const coef = new Array(d).fill(0);
  for (let i = d - 1; i >= 0; i--) coef[i] = (b[i] - A[i].slice(i + 1).reduce((a, v, k) => a + v * coef[i + 1 + k], 0)) / A[i][i];
  return {mean, scale, coef, intercept: ybar, n};
}
// Wanted change of the desk light (lux) for the model input x; the controller clips it to +-1000 like prefs.run_day.
// zmax: a standardised input is held within +-zmax of what the corrections covered. Presses made within minutes of each
// other leave a tiny spread, and a plain Ridge then swings wildly an hour later (live_learning.LinearModel does the same).
const predictRidge = (p, x, zmax = 3) => x.reduce((a, v, j) => a + Math.max(-zmax, Math.min(zmax, (v - p.mean[j]) / p.scale[j])) * p.coef[j], p.intercept);
if (typeof module !== "undefined") module.exports = {fitRidge, predictRidge};
