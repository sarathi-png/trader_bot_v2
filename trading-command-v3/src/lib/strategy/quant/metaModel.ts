/**
 * Meta-model inference — port of trader_bot_v2/ml4t/nblogistic.py.
 * Pure logistic: p = sigmoid(((x-mu)/sd)·w + b). Weights ship as JSON.
 *
 * meta_model.json holds the weights exported by
 * trader_bot_v2\Scripts\train_meta_model.py after purged-CV training on the
 * Python bot's cached 15m history. Keep the 18 columns in FEATURE_COLUMNS
 * order: predictProba maps by position, so a reordered export would silently
 * feed the model scrambled features.
 */
import { FEATURE_COLUMNS, toArray, type FeatureVector } from "./features";
import modelJson from "./meta_model.json";

export interface MetaWeights { w: number[]; b: number; mu: number[]; sd: number[] }

const sigmoid = (z: number) => 1 / (1 + Math.exp(-z));

export function predictProba(weights: MetaWeights, v: FeatureVector): number {
  const x = toArray(v);
  let z = weights.b;
  for (let i = 0; i < x.length; i++) z += ((x[i] - weights.mu[i]) / weights.sd[i]) * weights.w[i];
  return sigmoid(z);
}

export function gateWithMeta(prob: number, minProb = 0.5): { passed: boolean; reason: string } {
  if (!(prob >= 0)) return { passed: true, reason: "meta model absent" };
  if (prob < minProb)
    return { passed: false, reason: `META_VETO: meta p=${prob.toFixed(3)} < min ${minProb.toFixed(2)}` };
  return { passed: true, reason: `meta ok (p=${prob.toFixed(3)} >= min ${minProb.toFixed(2)})` };
}

/** Trained weights, exported from the Python bot. */
export const META_MODEL: MetaWeights = {
  w: modelJson.w,
  b: modelJson.b,
  mu: modelJson.mu,
  sd: modelJson.sd,
};

/** Training provenance, surfaced in the UI so numbers are traceable. */
export const META_MODEL_INFO = {
  kind: modelJson.kind,
  cvAuc: modelJson.cv_auc,
  rows: modelJson.rows,
  posRate: modelJson.pos_rate,
  ltf: modelJson.ltf,
  barrier: modelJson.barrier,
  source: modelJson.source,
  features: modelJson.features as string[],
};

/** True when a trained model is present and matches the feature layout. */
export function modelAvailable(): boolean {
  const n = FEATURE_COLUMNS.length;
  return (
    Array.isArray(META_MODEL.w) && META_MODEL.w.length === n &&
    META_MODEL.mu.length === n && META_MODEL.sd.length === n
  );
}

/** Demo weights so the UI works before real training export lands. */
export const DEMO_WEIGHTS: MetaWeights = {
  w: FEATURE_COLUMNS.map(() => 0), b: 0,
  mu: FEATURE_COLUMNS.map(() => 0), sd: FEATURE_COLUMNS.map(() => 1),
};
