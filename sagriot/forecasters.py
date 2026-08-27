from statistics import NormalDist

import numpy as np

# Levels used whenever a caller does not ask for something else. Five points
# give the advice layer a usable resolution on "how likely is this crossing"
# without making the rule engine run more often than it needs to.
QUANTILE_LEVELS = (0.1, 0.25, 0.5, 0.75, 0.9)


class Forecaster:
    name = "base"

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        raise NotImplementedError

    def warm_up(self, context_length, horizon):
        """One throwaway call so lazy loading happens before the first real use."""
        self.predict([0.0] * context_length, horizon)

    def predict_quantiles(self, history, horizon, exog_past=None, exog_future=None,
                          levels=QUANTILE_LEVELS):
        """Predictive quantiles. The default is a degenerate band.

        A method that overrides this is claiming to know something about its own
        error. A method that does not is stating honestly that it does not, and
        its band collapses onto the point forecast. Persistence is the extreme
        case: a flat forecast with zero spread can never cross a threshold under
        any scenario, which is the same fact its recall of 0.000 reports.
        """
        point = np.asarray(self.predict(history, horizon, exog_past, exog_future), dtype=float)
        return {level: point.copy() for level in levels}


class Persistence(Forecaster):
    name = "persistence"

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        return np.full(horizon, history[-1], dtype=float)


class SeasonalNaive(Forecaster):
    def __init__(self, season_length):
        self.season_length = season_length
        self.name = f"seasonal_naive({season_length})"

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        if len(history) < self.season_length:
            return np.full(horizon, history[-1], dtype=float)
        season = history[-self.season_length:]
        return np.array([season[i % self.season_length] for i in range(horizon)], dtype=float)


class DampedTrend(Forecaster):
    name = "damped_trend"

    ALPHAS = (0.1, 0.3, 0.5, 0.8)
    BETAS = (0.02, 0.1, 0.3)
    PHIS = (0.8, 0.9, 0.98)

    def _run(self, history, alpha, beta, phi):
        level = history[0]
        trend = history[1] - history[0] if len(history) > 1 else 0.0
        error = 0.0
        for value in history[1:]:
            forecast = level + phi * trend
            error += (value - forecast) ** 2
            previous = level
            level = alpha * value + (1 - alpha) * forecast
            trend = beta * (level - previous) + (1 - beta) * phi * trend
        return level, trend, error

    def _best(self, history):
        best = None
        for alpha in self.ALPHAS:
            for beta in self.BETAS:
                for phi in self.PHIS:
                    level, trend, error = self._run(history, alpha, beta, phi)
                    if best is None or error < best[0]:
                        best = (error, level, trend, phi)
        return best

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        history = np.asarray(history, dtype=float)
        _, level, trend, phi = self._best(history)
        out = np.empty(horizon, dtype=float)
        cumulative = 0.0
        for step in range(horizon):
            cumulative += phi ** (step + 1)
            out[step] = level + cumulative * trend
        return out

    def predict_quantiles(self, history, horizon, exog_past=None, exog_future=None,
                          levels=QUANTILE_LEVELS):
        history = np.asarray(history, dtype=float)
        error, level, trend, phi = self._best(history)
        point = self.predict(history, horizon)
        sigma = np.sqrt(error / max(1, len(history) - 1))
        steps = np.sqrt(np.arange(1, horizon + 1, dtype=float))
        return {q: point + NormalDist().inv_cdf(q) * sigma * steps for q in levels}


class ChronosForecaster(Forecaster):
    def __init__(self, model_name="amazon/chronos-bolt-small", device="cpu"):
        self.model_name = model_name
        self.device = device
        self.name = f"chronos:{model_name.split('/')[-1]}"
        self._pipeline = None

    def _load(self):
        if self._pipeline is None:
            import torch
            from chronos import BaseChronosPipeline
            self._pipeline = BaseChronosPipeline.from_pretrained(
                self.model_name, device_map=self.device, torch_dtype=torch.float32
            )
        return self._pipeline

    @staticmethod
    def _to_numpy(value):
        if hasattr(value, "detach"):
            value = value.detach().cpu().numpy()
        return np.asarray(value, dtype=float)

    def _raw(self, history, horizon, levels):
        import torch
        pipeline = self._load()
        series = torch.tensor(np.asarray(history, dtype=np.float32))
        try:
            quantiles, mean = pipeline.predict_quantiles(
                inputs=series, prediction_length=horizon, quantile_levels=list(levels)
            )
        except TypeError:
            quantiles, mean = pipeline.predict_quantiles(
                context=series, prediction_length=horizon, quantile_levels=list(levels)
            )
        return self._to_numpy(quantiles), self._to_numpy(mean)

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        _, mean = self._raw(history, horizon, QUANTILE_LEVELS)
        if mean.ndim > 1:
            mean = mean[0]
        return mean[:horizon]

    def predict_quantiles(self, history, horizon, exog_past=None, exog_future=None,
                          levels=QUANTILE_LEVELS):
        quantiles, _ = self._raw(history, horizon, levels)
        if quantiles.ndim == 3:
            quantiles = quantiles[0]
        return {level: quantiles[:horizon, index] for index, level in enumerate(levels)}


class DrivenDrying(Forecaster):
    """Grey-box soil-moisture model: rate of change as a function of demand.

    decay < 1 applies exponentially decreasing weight to older samples, so the
    fit tracks a rate that changes with the room. decay=None keeps every sample
    equally weighted, which is the form the reported results were produced with.
    """

    def __init__(self, drivers=("vpd",), ridge=1e-3, non_increasing=True, decay=None):
        self.drivers = tuple(drivers)
        self.ridge = ridge
        self.non_increasing = non_increasing
        self.decay = decay
        suffix = f",decay={decay}" if decay else ""
        self.name = "driven_drying(" + "+".join(self.drivers) + suffix + ")"
        self._warned = False

    def _fit(self, design, target, weights=None):
        if weights is not None:
            root = np.sqrt(weights)
            design = design * root[:, None]
            target = target * root
        gram = design.T @ design
        penalty = np.eye(design.shape[1]) * self.ridge * np.trace(gram) / design.shape[1]
        penalty[-1, -1] = 0.0
        try:
            return np.linalg.solve(gram + penalty, design.T @ target)
        except np.linalg.LinAlgError:
            return np.linalg.lstsq(design, target, rcond=None)[0]

    def _missing(self, history, horizon):
        if not self._warned:
            print(f"[{self.name}] exogenous drivers missing - falling back to persistence")
            self._warned = True
        return np.full(horizon, history[-1], dtype=float)

    def _solve(self, history, horizon, exog_past, exog_future):
        """Returns (point forecast, per-step standard deviation)."""
        delta = np.diff(history)
        past = [np.asarray(exog_past[d], dtype=float)[1:] for d in self.drivers]
        design = np.column_stack(past + [np.ones(len(delta))])

        weights = None
        if self.decay:
            weights = self.decay ** np.arange(len(delta) - 1, -1, -1, dtype=float)

        coefficients = self._fit(design, delta, weights)

        residual = delta - design @ coefficients
        dof = max(1, len(delta) - design.shape[1])
        if weights is None:
            variance = float(residual @ residual) / dof
        else:
            variance = float(np.sum(weights * residual ** 2) / np.sum(weights))
            variance *= len(delta) / dof
        sigma = np.sqrt(max(variance, 0.0))

        future = [np.asarray(exog_future[d], dtype=float) for d in self.drivers]
        design_future = np.column_stack(future + [np.ones(horizon)])
        rates = design_future @ coefficients
        if self.non_increasing:
            rates = np.minimum(rates, 0.0)

        point = history[-1] + np.cumsum(rates)
        # Step errors accumulate through the integration, so the band widens as
        # the square root of the number of steps.
        spread = sigma * np.sqrt(np.arange(1, horizon + 1, dtype=float))
        return point, spread

    def warm_up(self, context_length, horizon):
        # Warming up without drivers would trip the fallback warning, which is
        # meant to report a real configuration problem.
        self.predict(np.zeros(context_length),
                     horizon,
                     {d: np.zeros(context_length) for d in self.drivers},
                     {d: np.zeros(horizon) for d in self.drivers})

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        history = np.asarray(history, dtype=float)
        if not exog_past or not exog_future:
            return self._missing(history, horizon)
        point, _ = self._solve(history, horizon, exog_past, exog_future)
        return point

    def predict_quantiles(self, history, horizon, exog_past=None, exog_future=None,
                          levels=QUANTILE_LEVELS):
        history = np.asarray(history, dtype=float)
        if not exog_past or not exog_future:
            flat = self._missing(history, horizon)
            return {level: flat.copy() for level in levels}

        point, spread = self._solve(history, horizon, exog_past, exog_future)
        bands = {}
        for level in levels:
            band = point + NormalDist().inv_cdf(level) * spread
            if self.non_increasing:
                # The model asserts the soil cannot gain water without input, so
                # no scenario may rise above the last observation.
                band = np.minimum(band, history[-1])
            bands[level] = band
        return bands


class Ensemble(Forecaster):
    """Average of several forecasters.

    Point forecasts are averaged directly; quantiles are averaged level by level
    (Vincentization), which keeps the band ordered and is exact when the members
    disagree about location more than about shape.
    """

    def __init__(self, members, weights=None, name=None):
        self.members = list(members)
        if weights is None:
            self.weights = None
        else:
            weights = np.asarray(weights, dtype=float)
            self.weights = weights / weights.sum()
        self.name = name or "ensemble(" + "+".join(m.name for m in self.members) + ")"

    def warm_up(self, context_length, horizon):
        for member in self.members:
            member.warm_up(context_length, horizon)

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        stack = np.vstack([
            np.asarray(m.predict(history, horizon, exog_past, exog_future), dtype=float)
            for m in self.members
        ])
        return np.average(stack, axis=0, weights=self.weights)

    def predict_quantiles(self, history, horizon, exog_past=None, exog_future=None,
                          levels=QUANTILE_LEVELS):
        bands = [m.predict_quantiles(history, horizon, exog_past, exog_future, levels)
                 for m in self.members]
        out = {}
        for level in levels:
            stack = np.vstack([np.asarray(b[level], dtype=float) for b in bands])
            out[level] = np.average(stack, axis=0, weights=self.weights)
        return out
