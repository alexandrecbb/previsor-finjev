"""Estimadores, seleção de atributos e ajuste temporal dos modelos."""

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin, clone
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier
from sklearn.utils.validation import check_is_fitted
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit
from sklearn.metrics import accuracy_score
from xgboost import XGBClassifier

from .config import FEATURE_IMPORTANCE_THRESHOLD, RANDOM_STATE, HORIZON_DAYS, PARAM_GRID


class TreeFeatureSelector(TransformerMixin, BaseEstimator):
    """Aprende a seleção exclusivamente no treino de cada divisão temporal."""

    def __init__(self, threshold=FEATURE_IMPORTANCE_THRESHOLD, random_state=RANDOM_STATE):
        self.threshold = threshold
        self.random_state = random_state

    def fit(self, X, y):
        tree = DecisionTreeClassifier(random_state=self.random_state)
        tree.fit(X, y)
        importances = pd.Series(tree.feature_importances_, index=X.columns)
        self.selected_features_ = importances[importances > self.threshold].index.tolist()
        if not self.selected_features_:
            self.selected_features_ = importances.nlargest(5).index.tolist()
        return self

    def transform(self, X):
        check_is_fitted(self, "selected_features_")
        return X.loc[:, self.selected_features_]


class TemporalEarlyStoppingPipeline(Pipeline):
    """Escolhe o número de árvores em validação interna, depois reajusta o treino.

    Inclusive o seletor é ajustado sem acesso à validação interna. O teste externo
    nunca é passado ao XGBoost como eval_set.
    """

    def __init__(self, steps, *, horizon=HORIZON_DAYS, early_stopping=True):
        super().__init__(steps)
        self.horizon = horizon
        self.early_stopping = early_stopping

    def fit(self, X, y, **params):
        original_n_estimators = self.named_steps["xgb"].n_estimators
        if self.early_stopping:
            split = int(len(X) * 0.8)
            end = split - self.horizon
            if end < 20 or y.iloc[:end].nunique() < 2:
                raise ValueError("Histórico insuficiente para parada antecipada temporal.")
            selector = self.named_steps["select"]
            internal_selector = clone(selector) if selector != "passthrough" else None
            train, validation = X.iloc[:end], X.iloc[split:]
            if internal_selector is not None:
                train = internal_selector.fit_transform(train, y.iloc[:end])
                validation = internal_selector.transform(validation)
            internal = clone(self.named_steps["xgb"])
            internal.set_params(early_stopping_rounds=30)
            internal.fit(train, y.iloc[:end], eval_set=[(validation, y.iloc[split:])], verbose=False)
            self.best_n_estimators_ = internal.best_iteration + 1
            self.named_steps["xgb"].set_params(n_estimators=self.best_n_estimators_)
        fitted = super().fit(X, y, **params)
        # Preserva o limite de busca ao clonar/reajustar, sem alterar o booster treinado.
        self.named_steps["xgb"].set_params(n_estimators=original_n_estimators)
        return fitted


def fit_temporal_model(X, y, *, horizon, n_iter, n_jobs, select_features=False,
                       model_type="xgb", tune_threshold=True, early_stopping=True,
                       max_train_size=None):
    """Busca e limiar usam somente o treino recebido, com divisões cronológicas."""
    folds = list(TimeSeriesSplit(n_splits=3, gap=horizon,
                                max_train_size=max_train_size).split(X))
    for train, validation in folds:
        if y.iloc[train].nunique() < 2 or y.iloc[validation].nunique() < 2:
            raise ValueError("Cada treino e validação precisa conter altas e não altas.")
    if model_type == "xgb":
        model = TemporalEarlyStoppingPipeline([
            ("select", TreeFeatureSelector() if select_features else "passthrough"),
            ("xgb", XGBClassifier(random_state=RANDOM_STATE, n_jobs=1, eval_metric="logloss")),
        ], horizon=horizon, early_stopping=early_stopping)
        grid = {f"xgb__{key}": values for key, values in PARAM_GRID.items()}
    elif model_type == "logistic":
        model = Pipeline([("scale", StandardScaler()),
                          ("logistic", LogisticRegression(max_iter=2000, random_state=RANDOM_STATE))])
        grid = {"logistic__C": [0.01, 0.1, 1, 10]}
    else:
        raise ValueError("model_type deve ser xgb ou logistic.")
    combinations = int(np.prod([len(values) for values in grid.values()]))
    search = RandomizedSearchCV(model, grid, n_iter=min(n_iter, combinations), cv=folds,
                                scoring="accuracy", random_state=RANDOM_STATE,
                                n_jobs=n_jobs, error_score="raise")
    search.fit(X, y)
    threshold = 0.5
    if tune_threshold:
        probabilities, targets = [], []
        for train, validation in folds:
            candidate = clone(search.best_estimator_).fit(X.iloc[train], y.iloc[train])
            probabilities.extend(candidate.predict_proba(X.iloc[validation])[:, 1])
            targets.extend(y.iloc[validation])
        probabilities, targets = np.asarray(probabilities), np.asarray(targets)
        thresholds = np.linspace(0.3, 0.7, 41)
        scores = [accuracy_score(targets, probabilities >= value) for value in thresholds]
        # Em empates, prefere o limiar mais próximo de 0,5.
        threshold = min(zip(scores, thresholds), key=lambda pair: (-pair[0], abs(pair[1] - 0.5)))[1]
    return search.best_estimator_, float(threshold), search.best_params_
