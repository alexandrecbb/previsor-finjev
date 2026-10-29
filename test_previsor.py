"""Testes de regressão sem acesso ao Yahoo Finance."""

import importlib
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd
from sklearn.base import clone
from xgboost import XGBClassifier
from ibov import atributos, dados
from ibov.avaliacao import plt

previsor = importlib.import_module("previsor_ibovespa_versão_xgboost_pynb")


def historical_data(size=600):
    rng = np.random.default_rng(42)
    days = np.arange(size)
    close = 100 + 10 * np.sin(days / 8) + rng.normal(0, 0.2, size)
    return pd.DataFrame({
        "open": close + 0.1,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": rng.integers(1000, 10000, size).astype(float),
    }, index=pd.bdate_range("2020-01-01", periods=size))


class TargetTests(unittest.TestCase):
    def test_unknown_future_is_not_a_negative_label(self):
        frame = pd.DataFrame({"close": [10, 12, 11, 12, 11]})
        actual = previsor.make_target(frame, 2)
        np.testing.assert_equal(actual.to_numpy(), [1, 0, 0, np.nan, np.nan])
        self.assertTrue(actual.index.equals(frame.index))

    def test_invalid_horizon_is_rejected(self):
        for horizon in [0, -1, 1.5, True]:
            with self.subTest(horizon=horizon), self.assertRaises(ValueError):
                previsor.make_target(historical_data(), horizon)


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.expected = historical_data(60)
        self.yahoo = self.expected.rename(columns=str.title)
        self.yahoo["Adj Close"] = np.nan  # Coluna opcional não invalida OHLCV.

    def test_flat_and_multilevel_columns(self):
        multi = self.yahoo.copy()
        multi.columns = pd.MultiIndex.from_product([multi.columns, ["^BVSP"]])
        for downloaded in [self.yahoo, multi, multi.swaplevel(axis=1)]:
            with self.subTest(columns=downloaded.columns), patch.object(
                dados.yf, "download", return_value=downloaded
            ):
                actual = previsor.fetch_data("^BVSP", "2020-01-01", "2021-01-01")
                pd.testing.assert_frame_equal(actual, self.expected)
                self.assertIsInstance(actual["close"], pd.Series)

    def test_empty_or_incomplete_download(self):
        for downloaded in [None, pd.DataFrame(), self.yahoo.drop(columns="Volume")]:
            with self.subTest(downloaded=type(downloaded)), patch.object(
                dados.yf, "download", return_value=downloaded
            ), self.assertRaises(ValueError):
                previsor.fetch_data("^BVSP", "2020-01-01", "2021-01-01")

    def test_dates_are_sorted_and_deduplicated(self):
        downloaded = pd.concat([self.yahoo.iloc[::-1], self.yahoo.iloc[[0]]])
        with patch.object(dados.yf, "download", return_value=downloaded):
            actual = previsor.fetch_data("^BVSP", "2020-01-01", "2021-01-01")
        pd.testing.assert_frame_equal(actual, self.expected, check_freq=False)


class TemporalTests(unittest.TestCase):
    def test_no_training_target_reaches_validation_or_test(self):
        raw = historical_data()
        y = previsor.make_target(raw, previsor.HORIZON_DAYS).dropna()
        X = raw.loc[y.index]
        X_train, X_test, _, _, folds = previsor.temporal_partitions(
            X, y, previsor.HORIZON_DAYS
        )
        positions = pd.Series(np.arange(len(raw)), index=raw.index)

        def assert_separated(train, validation):
            last_target = positions.loc[train.index[-1]] + previsor.HORIZON_DAYS
            self.assertLess(last_target, positions.loc[validation.index[0]])

        assert_separated(X_train, X_test)
        for train_idx, validation_idx in folds:
            assert_separated(X_train.iloc[train_idx], X_train.iloc[validation_idx])

    def test_small_history_and_single_class_fail_clearly(self):
        raw = historical_data()
        for X, y in [(raw.iloc[:30], pd.Series([0, 1] * 15)),
                     (raw, pd.Series(1, index=raw.index))]:
            with self.subTest(size=len(X)), self.assertRaises(ValueError):
                previsor.temporal_partitions(X, y, previsor.HORIZON_DAYS)

    def test_indicators_do_not_depend_on_future_prices(self):
        raw = historical_data()
        full = previsor.compute_indicators(previsor.apply_smoothing(raw, 0.7))
        prefix = previsor.compute_indicators(previsor.apply_smoothing(raw.iloc[:300], 0.7))
        pd.testing.assert_frame_equal(full.iloc[:300], prefix)


class PipelineTests(unittest.TestCase):
    def test_cv_selection_and_latest_forecast_use_correct_dates(self):
        raw = historical_data()
        fit_dates, probability_dates = [], []
        original_fit = previsor.TreeFeatureSelector.fit
        original_proba = XGBClassifier.predict_proba

        def record_fit(selector, X, y):
            fit_dates.append(X.index.copy())
            return original_fit(selector, X, y)

        def record_proba(model, X, *args, **kwargs):
            probability_dates.append(X.index.copy())
            return original_proba(model, X, *args, **kwargs)

        with patch.object(previsor.TreeFeatureSelector, "fit", record_fit), patch.object(
            XGBClassifier, "predict_proba", record_proba
        ), redirect_stdout(io.StringIO()):
            metrics, prediction, probability = previsor.run_ibov_pipeline(
                raw_data=raw, n_iter=1, show_plots=True, n_jobs=1,
                select_features=True, early_stopping=False, tune_threshold=False
            )

        self.assertEqual(len(fit_dates), 5)  # 3 folds, refit do treino, refit final.
        X = previsor.prepare_features(raw).join(previsor.make_target(raw, 3)).dropna()
        train, test, _, _, folds = previsor.temporal_partitions(X.drop(columns="target"), X.target, 3)
        for fit_index, (_, validation) in zip(fit_dates[:3], folds):
            target_end = raw.index.get_loc(fit_index[-1]) + 3
            self.assertLess(target_end, raw.index.get_loc(train.index[validation[0]]))
        self.assertLess(fit_dates[3][-1], test.index[0])
        self.assertEqual(fit_dates[-1][-1], raw.index[-previsor.HORIZON_DAYS - 1])
        self.assertEqual(probability_dates[-1].tolist(), [raw.index[-1]])
        self.assertEqual(prediction.shape, (1,))
        self.assertEqual(probability.shape, (1, 2))
        np.testing.assert_allclose(probability.sum(axis=1), 1)
        self.assertTrue(all(np.isfinite(value) for value in metrics.values()))
        self.assertEqual(plt.get_fignums(), [])

    def test_relative_features_are_causal(self):
        raw = historical_data()
        for alpha in [None, 0.7]:
            full = previsor.prepare_features(raw, alpha=alpha)
            prefix = previsor.prepare_features(raw.iloc[:300], alpha=alpha)
            pd.testing.assert_frame_equal(full.iloc[:300], prefix)

    def test_early_stopping_preserves_internal_gap(self):
        raw = historical_data()
        records = []
        original = XGBClassifier.fit

        def record(model, X, y, **kwargs):
            if "eval_set" in kwargs:
                records.append((X.index, kwargs["eval_set"][0][0].index))
            return original(model, X, y, **kwargs)

        with patch.object(XGBClassifier, "fit", record), redirect_stdout(io.StringIO()):
            metrics, prediction, probability = previsor.run_ibov_pipeline(
                raw_data=raw, horizon=3, n_iter=1, n_jobs=1, show_plots=False)
        self.assertTrue(records)
        for train, validation in records:
            self.assertLess(raw.index.get_loc(train[-1]) + 3,
                            raw.index.get_loc(validation[0]))
        np.testing.assert_array_equal(prediction, (probability[:, 1] >= metrics["threshold"]).astype(int))

    def test_single_class_holdout_does_not_crash(self):
        raw = historical_data()
        close = np.linspace(100, 400, 230)
        raw.loc[raw.index[-230:], ["open", "high", "low", "close"]] = np.column_stack(
            [close + 0.1, close + 1, close - 1, close]
        )
        with self.assertWarnsRegex(UserWarning, "única classe"), redirect_stdout(io.StringIO()):
            metrics, _, _ = previsor.run_ibov_pipeline(
                raw_data=raw, n_iter=1, show_plots=False, n_jobs=1
            )
        self.assertTrue(np.isnan(metrics["roc_auc"]))
        self.assertTrue(np.isnan(metrics["pr_auc"]))

    def test_no_silent_forecast_from_an_older_date(self):
        raw = historical_data()
        indicators = previsor.compute_indicators(previsor.apply_smoothing(raw, 0.7))
        indicators.loc[raw.index[-1], "rsi"] = np.inf
        with patch.object(atributos, "compute_indicators", return_value=indicators):
            with self.assertRaisesRegex(ValueError, "último pregão"):
                previsor.run_ibov_pipeline(raw_data=raw, n_iter=1, show_plots=False)


class ExternalTests(unittest.TestCase):
    def test_external_same_day_and_future_are_unavailable(self):
        raw = historical_data()
        source = raw["close"].copy()
        before = previsor.external_features(raw.index, {"vix": source})
        changed = source.copy()
        changed.iloc[300:] *= 2
        after = previsor.external_features(raw.index, {"vix": changed})
        pd.testing.assert_frame_equal(before.iloc[:301], after.iloc[:301])
        self.assertEqual(before.iloc[300]["ext_vix_level"], source.iloc[299])

    def test_holiday_alignment_and_staleness(self):
        source = historical_data(60)["close"]
        date = source.index[-1]
        dates = pd.DatetimeIndex([date + pd.Timedelta(days=1), date + pd.Timedelta(days=8)])
        actual = previsor.external_features(dates, {"vix": source})
        self.assertEqual(actual.iloc[0]["ext_vix_level"], source.iloc[-1])
        self.assertTrue(actual.iloc[1].isna().all())

    def test_selic_is_causal_and_uses_percentage_points(self):
        dates = pd.date_range("2020-01-01", periods=70)
        source = pd.Series(2.0, index=dates)
        source.iloc[40:] = 3.0
        before = previsor.external_features(dates, {"selic": source})
        changed = source.copy()
        changed.iloc[40:] = 8.0
        after = previsor.external_features(dates, {"selic": changed})
        pd.testing.assert_frame_equal(before.iloc[:41], after.iloc[:41])
        self.assertEqual(before.iloc[41]["ext_selic_level"], 3.0)
        self.assertEqual(before.iloc[41]["ext_selic_change_1"], 1.0)
        self.assertEqual(before.iloc[41]["ext_selic_change_30"], 1.0)

    def test_selic_download_has_exclusive_end_and_annual_chunks(self):
        import json
        payloads = [
            [{"data": "01/01/2020", "valor": "4.5"}],
            [{"data": "01/01/2021", "valor": "2.0"},
             {"data": "02/01/2021", "valor": "2.0"}],
        ]
        responses = [io.BytesIO(json.dumps(p).encode()) for p in payloads]
        with patch.object(dados, "urlopen", side_effect=responses) as download:
            actual = dados.fetch_interest_data("2020-01-01", "2021-01-02")
        self.assertEqual(download.call_count, 2)
        self.assertEqual(len(actual), 2)
        self.assertEqual(actual.iloc[-1], 2.0)
        self.assertLess(actual.index[-1], pd.Timestamp("2021-01-02"))
        with patch.object(dados, "urlopen", return_value=io.BytesIO(b"[]")):
            with self.assertRaisesRegex(ValueError, "Banco Central"):
                dados.fetch_interest_data("2020-01-01", "2020-01-02")

    def test_selic_retries_transient_download_failure(self):
        from urllib.error import HTTPError
        response = io.BytesIO(b'[{"data":"01/01/2020","valor":"4.5"}]')
        failure = HTTPError("https://api.bcb.gov.br", 502, "Bad Gateway", {}, None)
        with patch.object(dados, "urlopen", side_effect=[failure, response]) as download:
            actual = dados.fetch_interest_data("2020-01-01", "2020-01-02")
        self.assertEqual(download.call_count, 2)
        self.assertEqual(actual.iloc[0], 4.5)

    def test_external_subset_excludes_selic(self):
        import avaliar_configuracoes as evaluation
        raw = historical_data()
        frames = evaluation.prepare_datasets(raw, {"vix": raw["close"], "selic": raw["close"]}, {
            "four": {"external": True, "external_names": ["vix"]},
            "five": {"external": True},
        })
        self.assertFalse(any("selic" in c for c in frames["four"]))
        self.assertIn("ext_selic_level", frames["five"])
        pd.testing.assert_index_equal(frames["four"].index, frames["five"].index)

    def test_external_download_is_mockable(self):
        with patch.object(dados, "fetch_data", return_value=historical_data()) as fetch:
            external = previsor.fetch_external_data("2020-01-01", "2023-01-01")
        self.assertEqual(set(external), set(previsor.EXTERNAL_TICKERS))
        self.assertEqual(fetch.call_count, 4)

    def test_external_pipeline_and_stale_latest(self):
        raw = historical_data()
        external = {"vix": raw["close"]}
        with redirect_stdout(io.StringIO()):
            metrics, prediction, probability = previsor.run_ibov_pipeline(
                raw_data=raw, external_data=external, horizon=3,
                n_iter=1, n_jobs=1, show_plots=False)
        self.assertTrue(np.isfinite(metrics["accuracy"]))
        self.assertEqual(probability.shape, (1, 2))
        with self.assertRaisesRegex(ValueError, "último pregão"):
            previsor.run_ibov_pipeline(raw_data=raw,
                external_data={"vix": raw["close"].iloc[:-20]}, show_plots=False)

    def test_early_stopping_preserves_tree_budget_when_cloned(self):
        raw = historical_data()
        X = previsor.prepare_features(raw).dropna().iloc[:-3]
        y = previsor.make_target(raw, 3).loc[X.index].astype(int)
        model = previsor.TemporalEarlyStoppingPipeline([
            ("select", "passthrough"),
            ("xgb", XGBClassifier(n_estimators=100, n_jobs=1,
                random_state=42, eval_metric="logloss")),
        ], horizon=3).fit(X, y)
        copied = clone(model)
        self.assertEqual(copied.named_steps["xgb"].n_estimators, 100)
        self.assertLessEqual(model.best_n_estimators_, 100)

    def test_evaluation_keeps_holdout_out_of_selection(self):
        import avaliar_configuracoes as evaluation
        raw = historical_data(1000)
        calls = []

        class DummyModel:
            def predict_proba(self, X):
                calls.append(("predict", X.index))
                return np.tile([0.4, 0.6], (len(X), 1))

        def fit(X, y, **kwargs):
            calls.append(("fit", X.index))
            return DummyModel(), 0.5, {}

        with patch.object(evaluation, "fit_temporal_model", side_effect=fit), redirect_stdout(io.StringIO()):
            report = evaluation.evaluate(raw, {"vix": raw["close"]},
                configurations={"relativos": {}, "externos": {"external": True}})
        test_start = pd.Timestamp(report["test_start"])
        for kind, dates in calls:
            if kind == "fit":
                self.assertLess(dates[-1], test_start)
        for (kind, train), (next_kind, validation) in zip(calls[::2], calls[1::2]):
            self.assertEqual((kind, next_kind), ("fit", "predict"))
            self.assertLess(raw.index.get_loc(train[-1]) + 3, raw.index.get_loc(validation[0]))


class DualSmoothingTests(unittest.TestCase):
    def test_combination_preserves_both_versions_without_duplicate_returns(self):
        raw = historical_data()
        combined = previsor.prepare_features(raw, feature_set="dual_smoothing")
        smooth = previsor.prepare_features(raw)
        original = previsor.prepare_features(raw, alpha=None)
        pd.testing.assert_frame_equal(combined[smooth.columns], smooth)
        extra = combined.filter(regex="_unsmoothed$")
        pd.testing.assert_frame_equal(extra.rename(columns=lambda c: c.removesuffix("_unsmoothed")),
                                      original[[c.removesuffix("_unsmoothed") for c in extra]])
        self.assertEqual(len(extra.columns), 15)
        self.assertNotIn("return_1_unsmoothed", combined)
        changed = raw.copy()
        changed.iloc[300:] *= 2
        after = previsor.prepare_features(changed, feature_set="dual_smoothing")
        pd.testing.assert_frame_equal(combined.iloc[:300], after.iloc[:300])
        with self.assertRaisesRegex(ValueError, "exige alpha"):
            previsor.prepare_features(raw, alpha=None, feature_set="dual_smoothing")

    def test_comparison_needs_no_external_data_and_uses_common_dates(self):
        import avaliar_configuracoes as evaluation
        raw = historical_data()
        with patch.object(evaluation, "external_features", side_effect=AssertionError("externos")):
            frames = evaluation.prepare_datasets(raw, None, {
                "smooth": {}, "original": {"alpha": None},
                "dual": {"feature_set": "dual_smoothing"},
            })
        for frame in frames.values():
            pd.testing.assert_index_equal(frame.index, frames["smooth"].index)
            self.assertFalse(frame.isna().any().any())


if __name__ == "__main__":
    unittest.main()
