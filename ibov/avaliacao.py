"""Divisões cronológicas, métricas e gráficos de avaliação."""

import warnings
import numpy as np
import matplotlib.pyplot as plt
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, precision_recall_curve, roc_curve, auc,
)


def temporal_partitions(X, y, horizon, max_train_size=None):
    """Separa teste e CV com uma lacuna que impede sobreposição dos alvos."""
    split = int(len(X) * (2 / 3))
    train_end = split - horizon
    if train_end < 50 or split >= len(X):
        raise ValueError("Histórico insuficiente para treino, lacuna temporal e teste.")
    train_start = 0 if max_train_size is None else max(0, train_end - max_train_size)
    X_train, X_test = X.iloc[train_start:train_end], X.iloc[split:]
    y_train, y_test = y.iloc[train_start:train_end], y.iloc[split:]
    try:
        folds = list(TimeSeriesSplit(n_splits=3, gap=horizon, max_train_size=max_train_size).split(X_train))
    except ValueError as exc:
        raise ValueError("Histórico insuficiente para validação temporal com lacuna.") from exc
    for train_idx, val_idx in folds:
        if y_train.iloc[train_idx].nunique() < 2 or y_train.iloc[val_idx].nunique() < 2:
            raise ValueError(
                "Cada treino e validação precisa conter altas e não altas para calcular ROC AUC. "
                "Use um histórico maior ou revise o horizonte."
            )
    return X_train, X_test, y_train, y_test, folds


def calculate_metrics(y_train, y_test, y_pred, y_prob, threshold):
    """Avalia o teste histórico e a referência aprendida no treino."""
    y_test_bin = y_test.astype(int)

    metrics = {
        "accuracy": accuracy_score(y_test, y_pred),
        "precision": precision_score(y_test, y_pred, zero_division=0),
        "recall": recall_score(y_test, y_pred, zero_division=0),
        "f1": f1_score(y_test, y_pred, zero_division=0),
        "roc_auc": float("nan"),
        "pr_auc": float("nan"),
    }
    if y_test_bin.nunique() == 2:
        prec, rec, _ = precision_recall_curve(y_test_bin, y_prob)
        metrics["roc_auc"] = roc_auc_score(y_test_bin, y_prob)
        metrics["pr_auc"] = auc(rec, prec)
    else:
        warnings.warn("O teste contém uma única classe; as AUCs não serão calculadas.", stacklevel=2)

    majority = int(y_train.mean() > 0.5)
    metrics["baseline_accuracy"] = accuracy_score(y_test, np.full(len(y_test), majority))
    metrics["threshold"] = threshold
    return metrics


def plot_evaluation(y_test, y_prob, metrics):
    """Exibe as curvas do teste quando as duas classes estão presentes."""
    y_test_bin = y_test.astype(int)
    if y_test_bin.nunique() == 2:
        prec, rec, _ = precision_recall_curve(y_test_bin, y_prob)
        fpr, tpr, _ = roc_curve(y_test_bin, y_prob)
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        axes[0].plot(fpr, tpr, label=f"ROC AUC={metrics['roc_auc']:.2f}", color="darkorange")
        axes[0].plot([0, 1], [0, 1], "k--")
        axes[0].set(title="ROC - IBOV (XGBoost)", xlabel="Taxa de falsos positivos", ylabel="Taxa de verdadeiros positivos")
        axes[1].plot(rec, prec, label=f"PR AUC={metrics['pr_auc']:.2f}", color="blue")
        axes[1].set(title="Precisão-Recall - IBOV (XGBoost)", xlabel="Recall", ylabel="Precisão")
        for ax in axes:
            ax.legend()
        fig.tight_layout()
        plt.show()
        plt.close(fig)
