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
    """Holt's linear trend with damping.

    Two states are carried: where the signal is (level) and how fast it is
    moving (trend). Each new observation updates both. To forecast, the trend
    is added repeatedly but multiplied by phi < 1 at every step, so the
    extrapolation bends flat instead of running away over a three-hour horizon.
    Three parameters -- alpha, beta, phi -- chosen by grid search on the
    context.

    Dropped from the production benchmark: with driven drying at two fitted
    coefficients and TTM at about a million pretrained ones, its three
    parameters sat in a place on the ladder that produced no distinct
    behaviour. Kept here so the choice can be re-measured rather than
    re-argued.
    """

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

    @staticmethod
    def _extrapolate(level, trend, phi, horizon):
        out = np.empty(horizon, dtype=float)
        cumulative = 0.0
        for step in range(horizon):
            cumulative += phi ** (step + 1)
            out[step] = level + cumulative * trend
        return out

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        history = np.asarray(history, dtype=float)
        _, level, trend, phi = self._best(history)
        return self._extrapolate(level, trend, phi, horizon)

    def predict_quantiles(self, history, horizon, exog_past=None, exog_future=None,
                          levels=QUANTILE_LEVELS):
        history = np.asarray(history, dtype=float)
        # The grid search is the whole cost of this method, so it is run once
        # and the point forecast is built from the same fit.
        error, level, trend, phi = self._best(history)
        point = self._extrapolate(level, trend, phi, horizon)
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


class TTMForecaster(Forecaster):
    """IBM Granite Tiny Time Mixer — a pretrained model of about one million
    parameters.

    It sits between the two extremes this project compares. Driven drying fits
    two coefficients on site; Chronos-Bolt holds nine to forty-eight million
    pretrained ones. TTM is pretrained like Chronos but three orders of
    magnitude smaller, so it tests the claim directly: if a one-million
    parameter model cannot beat a two-coefficient physical model on the
    irrigation decision, that is evidence about the decision, not about size.

    One constraint is not negotiable. TTM only accepts a fixed input length
    (512, 1024 or 1536 steps), while every other method here is given the same
    288-step context. Rather than give TTM more history than the others -- which
    would make the comparison meaningless -- the 288 steps are left-padded with
    the oldest value up to 512. The padding carries no information, so all five
    methods still see exactly the same twenty-four hours.

    The model produces a point forecast only, so its predictive band stays
    degenerate. That is reported rather than hidden: it means TTM cannot take
    part in the scenario-based early warning.
    """

    CONTEXT = 512

    def __init__(self, model_path="ibm-granite/granite-timeseries-ttm-r2", device="cpu"):
        self.model_path = model_path
        self.device = device
        self.name = "ttm"
        self._models = {}

    def _load(self, horizon):
        if horizon not in self._models:
            import torch
            from tsfm_public.toolkit.get_model import get_model
            model = get_model(self.model_path,
                              context_length=self.CONTEXT,
                              prediction_length=horizon)
            model.eval()
            self._models[horizon] = model.to(torch.device(self.device))
        return self._models[horizon]

    def predict(self, history, horizon, exog_past=None, exog_future=None):
        import torch
        history = np.asarray(history, dtype=float)

        # Left-pad with the oldest observation. Repeating a value adds no
        # information; it only satisfies the fixed input width.
        if len(history) < self.CONTEXT:
            pad = np.full(self.CONTEXT - len(history), history[0], dtype=float)
            window = np.concatenate([pad, history])
        else:
            window = history[-self.CONTEXT:]

        # Standardise on the context. A pretrained model has no idea what units
        # soil moisture is in, and the scale of these channels is nothing like
        # its training data.
        centre = window.mean()
        scale = window.std()
        if scale < 1e-8:
            return np.full(horizon, history[-1], dtype=float)
        normalised = (window - centre) / scale

        tensor = torch.tensor(normalised, dtype=torch.float32).reshape(1, self.CONTEXT, 1)
        with torch.no_grad():
            output = self._load(horizon)(past_values=tensor.to(self.device))

        prediction = getattr(output, "prediction_outputs", None)
        if prediction is None:
            prediction = output[0]
        prediction = prediction.detach().cpu().numpy().reshape(-1)

        return prediction[:horizon] * scale + centre

    def warm_up(self, context_length, horizon):
        self.predict(np.zeros(context_length) + np.arange(context_length) * 1e-3, horizon)


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
