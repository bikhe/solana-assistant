"""Train the keyword classifier on embeddings and export it as an openWakeWord-style ONNX.

Same shape as openWakeWord models: (batch, 16, 96) embeddings in, (batch, 1) score out.
The network is tiny (two hidden layers), so it trains in plain numpy in a minute on CPU.
"""

from __future__ import annotations

import argparse
import itertools
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from solana_core.wake.assets import wake_models_dir

from wakeword.phrases import KEYWORD

log = logging.getLogger("wakeword.train")
F = NDArray[np.float32]


@dataclass
class Mlp:
    """in -> hidden -> hidden -> 1, ReLU, sigmoid on the output."""

    weights: list[F] = field(default_factory=list)
    biases: list[F] = field(default_factory=list)

    @classmethod
    def create(cls, n_in: int, hidden: int, rng: np.random.Generator) -> Mlp:
        sizes = [n_in, hidden, hidden, 1]
        mlp = cls()
        for a, b in itertools.pairwise(sizes):
            mlp.weights.append((rng.standard_normal((a, b)) * np.sqrt(2 / a)).astype(np.float32))
            mlp.biases.append(np.zeros(b, dtype=np.float32))
        return mlp

    def forward(self, x: F) -> tuple[F, list[F]]:
        acts = [x]
        for i, (w, b) in enumerate(zip(self.weights, self.biases, strict=True)):
            z = acts[-1] @ w + b
            acts.append(np.maximum(z, 0) if i < len(self.weights) - 1 else z)
        logits = acts[-1][:, 0]
        return logits, acts

    def predict(self, x: F) -> F:
        logits, _ = self.forward(x)
        return (1 / (1 + np.exp(-logits))).astype(np.float32)


class Adam:
    def __init__(self, params: list[F], lr: float) -> None:
        self.params, self.lr, self.t = params, lr, 0
        self.m = [np.zeros_like(p) for p in params]
        self.v = [np.zeros_like(p) for p in params]

    def step(self, grads: list[F]) -> None:
        self.t += 1
        for p, g, m, v in zip(self.params, grads, self.m, self.v, strict=True):
            m *= 0.9
            m += 0.1 * g
            v *= 0.999
            v += 0.001 * g * g
            m_hat = m / (1 - 0.9**self.t)
            v_hat = v / (1 - 0.999**self.t)
            p -= self.lr * m_hat / (np.sqrt(v_hat) + 1e-8)


def train_step(mlp: Mlp, opt: Adam, x: F, y: F, w: F, l2: float) -> float:
    logits, acts = mlp.forward(x)
    prob = 1 / (1 + np.exp(-logits))
    eps = 1e-7
    loss = float(-np.mean(w * (y * np.log(prob + eps) + (1 - y) * np.log(1 - prob + eps))))
    grad = ((prob - y) * w / len(y))[:, None].astype(np.float32)
    grads_w: list[F] = []
    grads_b: list[F] = []
    for i in reversed(range(len(mlp.weights))):
        grads_w.insert(0, acts[i].T @ grad + l2 * mlp.weights[i])
        grads_b.insert(0, grad.sum(axis=0))
        if i:
            grad = (grad @ mlp.weights[i].T) * (acts[i] > 0)
    opt.step(grads_w + grads_b)
    return loss


def evaluate(mlp: Mlp, x: F, y: NDArray[np.uint8], threshold: float = 0.5) -> tuple[float, float]:
    """(recall on positives, false accept rate on negatives) at ``threshold``."""
    p = mlp.predict(x)
    pos, neg = y == 1, y == 0
    recall = float((p[pos] >= threshold).mean()) if pos.any() else 0.0
    far = float((p[neg] >= threshold).mean()) if neg.any() else 0.0
    return recall, far


def export_onnx(mlp: Mlp, window: int, path: Path) -> None:
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    inits, nodes = [], [helper.make_node("Flatten", ["x"], ["h0"], axis=1)]
    for i, (w, b) in enumerate(zip(mlp.weights, mlp.biases, strict=True)):
        inits += [numpy_helper.from_array(w, f"w{i}"), numpy_helper.from_array(b, f"b{i}")]
        nodes.append(helper.make_node("Gemm", [f"h{i}", f"w{i}", f"b{i}"], [f"z{i}"]))
        last = i == len(mlp.weights) - 1
        nodes.append(
            helper.make_node(
                "Sigmoid" if last else "Relu", [f"z{i}"], ["score" if last else f"h{i + 1}"]
            )
        )
    graph = helper.make_graph(
        nodes,
        KEYWORD,
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, window, 96])],
        [helper.make_tensor_value_info("score", TensorProto.FLOAT, [1, 1])],
        inits,
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8  # readable by onnxruntime >= 1.10
    onnx.checker.check_model(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(path))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wakeword train", description=__doc__)
    parser.add_argument("features", type=Path, nargs="+", help=".npz files from `generate`")
    parser.add_argument("--out", type=Path, default=Path(f"work/{KEYWORD}.onnx"))
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--l2", type=float, default=1e-4)
    parser.add_argument(
        "--negative-weight",
        type=float,
        default=5.0,
        help="higher = fewer false wakes, a bit lower recall",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="copy the model to the folder Solana loads wake words from",
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    rng = np.random.default_rng(args.seed)
    xs, ys = zip(*((d["x"], d["y"]) for d in map(np.load, args.features)), strict=True)
    x = np.concatenate(xs).astype(np.float32)
    y = np.concatenate(ys).astype(np.uint8)
    window = x.shape[1]
    x = x.reshape(len(x), -1)
    order = rng.permutation(len(x))
    n_val = max(len(x) // 10, 1)
    val, tr = order[:n_val], order[n_val:]
    log.info("%d train / %d val, %d positive", len(tr), len(val), int(y.sum()))

    mlp = Mlp.create(x.shape[1], args.hidden, rng)
    opt = Adam(mlp.weights + mlp.biases, args.lr)
    weights = np.where(y == 1, 1.0, args.negative_weight).astype(np.float32)
    best: tuple[float, Mlp] | None = None
    for epoch in range(args.epochs):
        rng.shuffle(tr)
        losses = [
            train_step(mlp, opt, x[b], y[b].astype(np.float32), weights[b], args.l2)
            for b in np.array_split(tr, max(len(tr) // 256, 1))
        ]
        recall, far = evaluate(mlp, x[val], y[val])
        score = recall - 20 * far  # a false wake costs much more than a miss
        if best is None or score > best[0]:
            best = (score, Mlp([w.copy() for w in mlp.weights], [b.copy() for b in mlp.biases]))
        if epoch % 10 == 0 or epoch == args.epochs - 1:
            log.info(
                "epoch %3d  loss %.4f  val recall %.3f  false accepts %.4f",
                epoch,
                float(np.mean(losses)),
                recall,
                far,
            )
    assert best is not None
    recall, far = evaluate(best[1], x[val], y[val])
    log.info("best: val recall %.3f, false accepts %.4f", recall, far)
    export_onnx(best[1], window, args.out)
    log.info("saved %s", args.out)
    if args.install:
        dest = wake_models_dir() / f"{KEYWORD}.onnx"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.out, dest)
        log.info("installed to %s", dest)
