import numpy as np


class Forecaster:
    name = "base"

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        raise NotImplementedError

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

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        history = np.asarray(history, dtype=float)
        best = None
        for alpha in self.ALPHAS:
            for beta in self.BETAS:
                for phi in self.PHIS:
                    level, trend, error = self._run(history, alpha, beta, phi)
                    if best is None or error < best[0]:
                        best = (error, level, trend, phi)
        _, level, trend, phi = best
        out = np.empty(horizon, dtype=float)
        cumulative = 0.0
        for step in range(horizon):
            cumulative += phi ** (step + 1)
            out[step] = level + cumulative * trend
        return out


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

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        import torch
        pipeline = self._load()
        series = torch.tensor(np.asarray(history, dtype=np.float32))
        levels = [0.1, 0.5, 0.9]
        try:
            _, mean = pipeline.predict_quantiles(
                inputs=series, prediction_length=horizon, quantile_levels=levels
            )
        except TypeError:
            _, mean = pipeline.predict_quantiles(
                context=series, prediction_length=horizon, quantile_levels=levels
            )
        if hasattr(mean, "detach"):
            mean = mean.detach().cpu().numpy()
        mean = np.asarray(mean, dtype=float)
        if mean.ndim > 1:
            mean = mean[0]
        return mean[:horizon]

class TimesFMForecaster(Forecaster):
    def __init__(self, context_length, horizon_length, backend="cpu"):
        self.context_length = context_length
        self.horizon_length = horizon_length
        self.backend = backend
        self.name = "timesfm"
        self._model = None

    def _load(self):
        raise NotImplementedError("TimesFM kurulumunda README'ye gore doldurulacak")

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        model = self._load()
        forecast, _ = model.forecast([np.asarray(history, dtype=float)], freq=[0])
        return np.asarray(forecast[0][:horizon], dtype=float)


class MoiraiForecaster(Forecaster):
    def __init__(self, model_name="Salesforce/moirai-1.1-R-small",
                 context_length=None, covariates=None):
        self.model_name = model_name
        self.context_length = context_length
        self.covariates = covariates
        suffix = "+cov" if covariates else ""
        self.name = f"moirai:{model_name.split('/')[-1]}{suffix}"
        self._model = None

    def _load(self, horizon):
        raise NotImplementedError("Moirai kurulumunda README'ye gore doldurulacak")

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        raise NotImplementedError

class DrivenDrying(Forecaster):
    def __init__(self, drivers=("vpd",)):
        self.drivers = tuple(drivers)
        self.name = "driven_drying(" + "+".join(self.drivers) + ")"

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        history = np.asarray(history, dtype=float)
        if not exog_past or not exog_future:
            return np.full(horizon, history[-1], dtype=float)

        delta = np.diff(history)
        past = [np.asarray(exog_past[d], dtype=float)[1:] for d in self.drivers]
        design = np.column_stack(past + [np.ones(len(delta))])
        coefficients, *_ = np.linalg.lstsq(design, delta, rcond=None)

        future = [np.asarray(exog_future[d], dtype=float) for d in self.drivers]
        design_future = np.column_stack(future + [np.ones(horizon)])
        rates = design_future @ coefficients
        return history[-1] + np.cumsum(rates)