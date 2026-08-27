"""Frame geometry for the gun-barrel intro — pure numpy, no ``xy``, no Reflex.

The whole title sequence is a **point cloud**: a gun barrel whose rifling
spirals around a lit interior, a walking silhouette, a muzzle flash, and blood
running down the frame. Every frame is a pure function of one float — the cycle
clock — so the Reflex data var that publishes it stays a pure function of state
(the adapter's rebuild contract), and the sequence is seekable, loopable, and
unit-testable without a browser.

Two layers, and the split is the reason the animation looks smooth:

* :class:`SceneSpec` is the **identity layer** — built once, never per frame. It
  fixes *which point is which*: the ``(groove, radial, across)`` grid of the
  rifling, the unit-disc wash samples, the local ``(along, across)``
  coordinates filling each limb, the muzzle-flash directions, the blood
  fingers. Point ``i`` means the same thing in every frame of the sequence.
* :func:`frame_columns` is the **motion layer** — it maps that fixed identity
  through the frame's barrel geometry and skeleton pose.

Because identity is stable, row ``i`` in frame ``k`` and row ``i`` in frame
``k + 1`` are the same sample of the same feature, so a straight line between
them *is* the correct in-between: a groove point sweeps its own arc, a knee
point tracks the knee. That is what lets the server publish ~12 keyframes a
second while the engine's ``match="index"`` position interpolation renders the
60 fps motion in between, instead of the server pushing 60 frames of columns
down the websocket.

Coordinates are world units on a fixed axis domain (:data:`WORLD_X` /
:data:`WORLD_Y`); nothing here knows about pixels. Rows parked outside that
domain are clipped by the plot rect, which is how the blood waits above the
frame before it falls.

Every mark in the scene is a **scatter** (see ``charts.py``). That is not an
accident: closed curves are not functions of x, and a line mark spanning one
per-column min/max would paint a filled disc instead of a ring — so the barrel
walls are dense point rings, which also keeps every mark on the interpolating
path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

__all__ = [
    "BEATS",
    "CYCLE",
    "WORLD_ASPECT",
    "WORLD_X",
    "WORLD_Y",
    "SceneSpec",
    "beat_label",
    "frame_columns",
    "scene_spec",
]

# --- the stage ---------------------------------------------------------------

WORLD_X = (-1.6, 1.6)
WORLD_Y = (-1.0, 1.0)
#: Width / height of the stage. The barrel is a *circle*, so the plot rect has
#: to carry this ratio or every ring renders as an ellipse — there is no
#: engine-level "equal aspect" lock on the composition API, so the container
#: shape and a zero-padding plot rect are what keep the geometry honest.
WORLD_ASPECT = (WORLD_X[1] - WORLD_X[0]) / (WORLD_Y[1] - WORLD_Y[0])
_TOP = WORLD_Y[1]
_PARK = _TOP + 0.28  # blood waits here, above the clip rect

# --- the timeline ------------------------------------------------------------
# One 15-second cycle, then it loops. Beats are (start, end) in seconds; the
# helpers below read them, so retiming the sequence is a one-line edit here.

CYCLE = 15.0
BEATS: dict[str, tuple[float, float]] = {
    "open": (0.0, 2.2),  # the dot travels in and irises open into the barrel
    "walk": (2.5, 6.5),  # silhouette walks in from frame right
    "aim": (6.5, 7.4),  # settles, squares up, brings the gun to horizontal
    "fire": (7.4, 7.9),  # muzzle flash
    "bleed": (7.7, 12.2),  # blood runs down over everything
    "fade": (12.6, 15.0),  # iris shuts, scene resets for the loop
}


def beat_label(t: float) -> str:
    """The beat name for a cycle time, for the app's status readout."""
    t = float(t) % CYCLE
    for name in ("fade", "bleed", "fire", "aim", "walk", "open"):
        start, end = BEATS[name]
        if start <= t < end:
            return name
    return "hold"


def _phase(t: float, beat: str) -> float:
    """Linear 0→1 progress through a beat, clamped outside it."""
    start, end = BEATS[beat]
    if end <= start:
        return 1.0
    return float(np.clip((t - start) / (end - start), 0.0, 1.0))


def _smooth(x: float) -> float:
    """Smoothstep — C1 ease at both ends, so beats join without a velocity kink."""
    x = float(np.clip(x, 0.0, 1.0))
    return x * x * (3.0 - 2.0 * x)


def _ease_out(x: float) -> float:
    return 1.0 - (1.0 - float(np.clip(x, 0.0, 1.0))) ** 3


# --- the identity layer -----------------------------------------------------

# Relative shares of the point budget. The rifling and the blood are the two
# full-frame textures, so they carry the most points; the silhouette gets
# enough to hold a clean edge at any reasonable canvas size.
_SHARES = {
    "wash": 0.22,
    "rifling": 0.32,
    "rings": 0.05,
    "figure": 0.16,
    "flash": 0.03,
    "blood": 0.22,
}

# Limb shares within the figure budget.
_LIMB_SHARES = {
    "torso": 0.26,
    "head": 0.09,
    "hat": 0.08,
    "thigh_near": 0.09,
    "shin_near": 0.08,
    "thigh_far": 0.08,
    "shin_far": 0.07,
    "arm_near": 0.07,
    "fore_near": 0.06,
    "arm_far": 0.05,
    "fore_far": 0.05,
    "gun": 0.02,
}

_BLOOD_FINGER_POINTS = 90  # points down one drip, so fingers read as fingers


def _sunflower(n: int) -> tuple[np.ndarray, np.ndarray]:
    """``n`` evenly spread unit-disc samples (golden-angle spiral).

    Deterministic and index-stable, and far more even than rejection sampling
    at the same count — the wash reads as a lit surface, not as noise.
    """
    i = np.arange(n, dtype=np.float64) + 0.5
    r = np.sqrt(i / n)
    theta = i * (math.pi * (3.0 - math.sqrt(5.0)))
    return r * np.cos(theta), r * np.sin(theta)


def _limb_uv(n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Fixed local fill coordinates for one limb: ``along`` 0→1, ``across`` -1→1.

    A jittered stratified grid: even enough to fill the limb without banding,
    random enough that the silhouette edge does not look machined.
    """
    cols = max(2, int(round(math.sqrt(n / 3.0))))
    rows = max(1, n // cols)
    total = rows * cols
    idx = np.arange(total)
    along = ((idx // cols) + rng.random(total)) / rows
    across = ((idx % cols) + rng.random(total)) / cols * 2.0 - 1.0
    return along[:n], across[:n]


@dataclass(frozen=True)
class SceneSpec:
    """Frame-independent sampling — the thing that makes point ``i`` mean one thing.

    Built once per point budget by :func:`scene_spec` and shared by every frame;
    :func:`frame_columns` only ever reads it.
    """

    points: int
    # barrel interior wash: unit-disc samples plus their static shading
    wash_x: np.ndarray
    wash_y: np.ndarray
    wash_shade: np.ndarray
    # rifling: per-point position within its groove
    rifle_groove: np.ndarray
    rifle_along: np.ndarray  # 0 at the outer wall, 1 at the inner lip
    rifle_across: np.ndarray  # -1..1 within the groove's angular width
    rifle_grooves: int
    # the two barrel walls, as dense point rings
    ring_theta: np.ndarray
    # silhouette: local fill coordinates per limb, and the head disc
    limb_along: dict[str, np.ndarray]
    limb_across: dict[str, np.ndarray]
    head_x: np.ndarray
    head_y: np.ndarray
    # muzzle flash: fixed per-spark direction, speed and spikiness
    flash_angle: np.ndarray
    flash_speed: np.ndarray
    # blood: per-point finger column, lag, width and position along the finger
    blood_col: np.ndarray
    blood_lag: np.ndarray
    blood_width: np.ndarray
    blood_wobble: np.ndarray
    blood_along: np.ndarray
    blood_across: np.ndarray

    @property
    def figure_points(self) -> int:
        return sum(len(v) for v in self.limb_along.values()) + len(self.head_x)

    @property
    def total(self) -> int:
        """Rows actually published per frame.

        The share table is approximate — grooves and blood fingers round to whole
        units — so this is the honest count, not the requested budget.
        """
        return (
            len(self.wash_x)
            + len(self.rifle_along)
            + 2 * len(self.ring_theta)
            + self.figure_points
            + len(self.flash_angle)
            + len(self.blood_along)
        )


@lru_cache(maxsize=4)
def scene_spec(points: int = 90_000) -> SceneSpec:
    """Build (and cache) the identity layer for a total point budget."""
    if points < 2_000:
        raise ValueError(f"point budget must be at least 2000, got {points}")
    rng = np.random.default_rng(7)  # 007
    n = {name: max(1, int(points * share)) for name, share in _SHARES.items()}

    wash_x, wash_y = _sunflower(n["wash"])
    # Jitter by about half the sample spacing. A pure golden-angle spiral is
    # *too* regular: once the on-screen point spacing approaches the point size
    # its arms beat against the pixel grid and the interior shows moiré. The
    # offset is fixed per point, so identity — and therefore the tween — is
    # untouched; it only breaks the coherence.
    spacing = 1.0 / math.sqrt(max(1, n["wash"]))
    wash_x = wash_x + rng.uniform(-0.6, 0.6, n["wash"]) * spacing
    wash_y = wash_y + rng.uniform(-0.6, 0.6, n["wash"]) * spacing
    # Brighter toward the middle: a lit tube interior, not a flat grey disc.
    wash_shade = 0.44 + 0.30 * (1.0 - np.clip(np.hypot(wash_x, wash_y), 0.0, 1.0) ** 1.7)

    grooves = 26
    across_n = 9
    per = max(across_n, n["rifling"] // grooves)
    along_n = max(2, per // across_n)
    gi, ai, ci = np.meshgrid(
        np.arange(grooves), np.arange(along_n), np.arange(across_n), indexing="ij"
    )
    size = gi.size
    rifle_along = (ai.ravel() + rng.random(size)) / along_n
    rifle_across = (ci.ravel() + rng.random(size)) / across_n * 2.0 - 1.0

    # Two rings share the ring budget.
    ring_theta = np.linspace(0.0, 2.0 * math.pi, max(240, n["rings"] // 2), endpoint=False)

    limb_along: dict[str, np.ndarray] = {}
    limb_across: dict[str, np.ndarray] = {}
    for limb, share in _LIMB_SHARES.items():
        if limb == "head":
            continue
        along, across = _limb_uv(max(24, int(n["figure"] * share)), rng)
        limb_along[limb] = along
        limb_across[limb] = across
    head_x, head_y = _sunflower(max(24, int(n["figure"] * _LIMB_SHARES["head"])))

    nf = n["flash"]
    flash_angle = rng.uniform(-math.pi, math.pi, nf)
    # Spikiness baked in per spark: a few long lances over a dense core.
    flash_speed = (0.16 + 0.84 * rng.random(nf) ** 2.1) * (
        0.55 + 0.45 * np.abs(np.cos(flash_angle * 5.0 + 0.7))
    )

    # Blood as coherent fingers: the per-finger values are shared by every
    # point in that finger, so a drip stays one drip as it grows.
    fingers = max(8, n["blood"] // _BLOOD_FINGER_POINTS)
    f_col = rng.uniform(WORLD_X[0] - 0.05, WORLD_X[1] + 0.05, fingers)
    f_lag = rng.random(fingers) ** 1.5
    f_width = 0.022 + 0.038 * rng.random(fingers)
    f_wobble = rng.uniform(0.0, 2.0 * math.pi, fingers)
    rep = _BLOOD_FINGER_POINTS
    along = (np.tile(np.arange(rep), fingers) + rng.random(fingers * rep)) / rep

    return SceneSpec(
        points=points,
        wash_x=wash_x,
        wash_y=wash_y,
        wash_shade=wash_shade,
        rifle_groove=gi.ravel().astype(np.float64),
        rifle_along=rifle_along,
        rifle_across=rifle_across,
        rifle_grooves=grooves,
        ring_theta=ring_theta,
        limb_along=limb_along,
        limb_across=limb_across,
        head_x=head_x,
        head_y=head_y,
        flash_angle=flash_angle,
        flash_speed=flash_speed,
        blood_col=np.repeat(f_col, rep),
        blood_lag=np.repeat(f_lag, rep),
        blood_width=np.repeat(f_width, rep),
        blood_wobble=np.repeat(f_wobble, rep),
        blood_along=along,
        blood_across=rng.uniform(-1.0, 1.0, fingers * rep),
    )


# --- the barrel -------------------------------------------------------------


def _barrel(t: float) -> tuple[float, float, float, float]:
    """Barrel centre and radii for a cycle time: ``(cx, cy, r_inner, r_outer)``.

    The iris opens from a travelling dot, holds, and shuts again for the loop.
    """
    open_p = _ease_out(_phase(t, "open"))
    shut = _smooth(_phase(t, "fade"))
    scale = open_p * (1.0 - 0.99 * shut)
    # The dot flies in from frame left and settles just left of centre, the way
    # the barrel tracks its subject before locking on. The shut factor also
    # walks the centre back to where the dot came in, so the last frame of the
    # cycle and the first frame agree — the loop has nothing to tween across.
    cx = -1.30 + 1.16 * open_p * (1.0 - shut)
    cy = 0.0
    r_outer = 0.010 + (0.965 - 0.010) * scale
    r_inner = r_outer * (0.605 + 0.02 * math.sin(t * 1.7))
    return cx, cy, r_inner, r_outer


def _rifling(spec: SceneSpec, t: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The spiral grooves cut into the barrel wall.

    Each groove is a band swept from the outer wall to the inner lip, twisting
    as it goes — the rifling that makes the barrel read as a barrel. Point
    identity is ``(groove, along, across)``, so a groove point always sweeps its
    own arc and the frame-to-frame tween stays geometrically honest.
    """
    cx, cy, r_in, r_out = _barrel(t)
    along = spec.rifle_along
    # Ease the radial spacing so grooves crowd toward the bright inner lip.
    r = r_out + (r_in - r_out) * along**0.78
    width = (math.pi / spec.rifle_grooves) * 0.60
    spin = t * 0.40
    twist = 1.20  # radians of spiral from outer wall to inner lip
    theta = (
        spec.rifle_groove * (2.0 * math.pi / spec.rifle_grooves)
        + twist * along
        + spec.rifle_across * width
        + spin
    )
    x = cx + r * np.cos(theta)
    y = cy + r * np.sin(theta)
    # Bright at the inner lip, falling off toward the outer wall, with a slow
    # rotating specular so the metal reads as lit rather than painted.
    spec_hi = 0.5 + 0.5 * np.cos(theta - spin * 1.6 - 0.6)
    shade = 0.26 + 0.52 * along**1.3 + 0.22 * spec_hi * along
    return x, y, np.clip(shade + 0.30 * _flash_energy(t), 0.0, 1.0)


def _wash(spec: SceneSpec, t: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The lit interior disc the silhouette stands in."""
    cx, cy, r_in, _ = _barrel(t)
    x = cx + spec.wash_x * r_in
    y = cy + spec.wash_y * r_in
    # The muzzle flash blows the interior out toward white for a few frames.
    return x, y, np.clip(spec.wash_shade + 0.42 * _flash_energy(t), 0.0, 1.0)


def _rings(spec: SceneSpec, t: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The outer wall and the bright inner lip, as two dense point rings."""
    cx, cy, r_in, r_out = _barrel(t)
    theta = spec.ring_theta
    cos, sin = np.cos(theta), np.sin(theta)
    x = np.concatenate([cx + r_out * cos, cx + r_in * cos])
    y = np.concatenate([cy + r_out * sin, cy + r_in * sin])
    shade = np.concatenate([np.full(theta.shape, 0.34), np.full(theta.shape, 0.97)])
    return x, y, np.clip(shade + 0.03 * _flash_energy(t), 0.0, 1.0)


# --- the silhouette ---------------------------------------------------------
# A skeleton in figure-local units (feet at y=0, crown near y=1.03), posed by
# angles and then mirrored to face frame left. Poses are *blended as angles* and
# only then run through forward kinematics, so the walk-to-aim transition bends
# joints instead of sliding limbs through the body.

_HIP_Y = 0.50
_SHOULDER_Y = 0.775
_L_THIGH = 0.245
_L_SHIN = 0.245
_L_UPPER = 0.180
_L_FORE = 0.175
_SHOULDER_DX = 0.052

# Half-widths (start, end) along each bone: a tailored suit, broad in the
# shoulder and tapering out to the cuffs.
_LIMB_WIDTH = {
    "torso": (0.092, 0.134),
    "thigh_near": (0.055, 0.042),
    "shin_near": (0.040, 0.026),
    "thigh_far": (0.052, 0.040),
    "shin_far": (0.038, 0.025),
    "arm_near": (0.041, 0.033),
    "fore_near": (0.033, 0.026),
    "arm_far": (0.038, 0.031),
    "fore_far": (0.031, 0.024),
    "gun": (0.030, 0.013),
}

_D = math.radians  # degrees -> radians, used only in the pose tables below

# A pose is eight joint angles plus a torso lean and a hip drop. Legs: thigh
# angle from straight-down and the knee's backward fold. Arms: upper-arm angle
# from straight-down and the elbow's fold.
_POSE_KEYS = (
    "thigh_near",
    "knee_near",
    "thigh_far",
    "knee_far",
    "arm_near",
    "elbow_near",
    "arm_far",
    "elbow_far",
    "lean",
    "drop",
)
_AIM_POSE = {
    "thigh_near": _D(-11.0),
    "knee_near": _D(7.0),
    "thigh_far": _D(15.0),
    "knee_far": _D(11.0),
    "arm_near": _D(90.0),  # gun arm out to horizontal
    "elbow_near": _D(-3.0),
    "arm_far": _D(-22.0),
    "elbow_far": _D(-44.0),
    "lean": _D(-4.0),
    "drop": 0.020,
}


def _walk_pose(phase: float) -> dict[str, float]:
    """One frame of the walk cycle, ``phase`` in turns.

    The knee folds only while its leg is travelling backward and lifting, which
    is what keeps the forward leg straight and stops the stride reading as a
    kick.
    """
    w = 2.0 * math.pi * phase
    swing = _D(23.0)
    fold = lambda ph: _D(5.0) + _D(34.0) * max(0.0, -math.sin(ph - 0.5))  # noqa: E731
    return {
        "thigh_near": swing * math.sin(w),
        "knee_near": fold(w),
        "thigh_far": swing * math.sin(w + math.pi),
        "knee_far": fold(w + math.pi),
        "arm_near": _D(19.0) * math.sin(w + math.pi),
        "elbow_near": _D(-26.0) - _D(14.0) * max(0.0, math.sin(w)),
        "arm_far": _D(19.0) * math.sin(w),
        "elbow_far": _D(-26.0) - _D(14.0) * max(0.0, math.sin(w + math.pi)),
        "lean": _D(3.0),
        # Two hip dips per stride — the bob that reads as weight.
        "drop": 0.011 * (1.0 - math.cos(2.0 * w)) * 0.5,
    }


def _blend(a: dict[str, float], b: dict[str, float], k: float) -> dict[str, float]:
    return {key: a[key] + (b[key] - a[key]) * k for key in _POSE_KEYS}


def _joints(pose: dict[str, float]) -> dict[str, tuple[float, float]]:
    """Forward kinematics: pose angles → joint positions in figure-local units.

    Angles are measured so that 0 hangs straight down and positive swings toward
    the figure's front (local +x, which the caller mirrors).
    """
    lean = pose["lean"]
    hip_y = _HIP_Y - pose["drop"]
    hip = (0.0, hip_y)
    spine = _SHOULDER_Y - _HIP_Y
    sh_c = (hip[0] + math.sin(lean) * spine, hip_y + math.cos(lean) * spine)

    out: dict[str, tuple[float, float]] = {"hip": hip, "shoulder_c": sh_c}
    for side in ("near", "far"):
        a1 = pose[f"thigh_{side}"]
        knee = (hip[0] + _L_THIGH * math.sin(a1), hip[1] - _L_THIGH * math.cos(a1))
        a2 = a1 - pose[f"knee_{side}"]
        ankle = (knee[0] + _L_SHIN * math.sin(a2), knee[1] - _L_SHIN * math.cos(a2))
        out[f"knee_{side}"] = knee
        out[f"ankle_{side}"] = ankle

        dx = _SHOULDER_DX * (1.0 if side == "near" else -1.0)
        shoulder = (sh_c[0] + dx, sh_c[1])
        b1 = pose[f"arm_{side}"]
        elbow = (shoulder[0] + _L_UPPER * math.sin(b1), shoulder[1] - _L_UPPER * math.cos(b1))
        b2 = b1 + pose[f"elbow_{side}"]
        wrist = (elbow[0] + _L_FORE * math.sin(b2), elbow[1] - _L_FORE * math.cos(b2))
        out[f"shoulder_{side}"] = shoulder
        out[f"elbow_{side}"] = elbow
        out[f"wrist_{side}"] = wrist
    return out


def _pose_at(t: float) -> tuple[dict[str, tuple[float, float]], float]:
    """The figure's joints and its local x offset for a cycle time."""
    walk_p = _phase(t, "walk")
    aim_p = _smooth(_phase(t, "aim"))
    # Stride turns over the whole walk, so the feet never skate.
    pose = _blend(_walk_pose(walk_p * 3.35), _AIM_POSE, aim_p)
    # Enters from frame right, decelerating into position. Before the walk beat
    # the figure sits outside the lit interior, where black-on-black hides it —
    # no visibility fudge needed, and nothing to tween in from.
    x_from, x_to = 1.55, 0.26
    return _joints(pose), x_from + (x_to - x_from) * _smooth(walk_p)


def _figure_frame(t: float) -> tuple[float, float, float, float]:
    """``(cx, base_y, height, offset)`` mapping figure-local units to the world."""
    cx, cy, r_in, _ = _barrel(t)
    _, offset = _pose_at(t)
    height = r_in * 1.66  # the figure fills the lit interior
    return cx, cy - r_in * 0.82, height, offset


def _to_world(
    x: np.ndarray | float, y: np.ndarray | float, t: float
) -> tuple[np.ndarray | float, np.ndarray | float]:
    """Figure-local → world, mirrored so the figure faces frame left."""
    cx, base_y, height, offset = _figure_frame(t)
    return cx + (offset - x) * height * 0.62, base_y + y * height


def _capsule(
    spec: SceneSpec, limb: str, a: tuple[float, float], b: tuple[float, float]
) -> tuple[np.ndarray, np.ndarray]:
    """Fill a tapered capsule from ``a`` to ``b`` with this limb's fixed samples."""
    along = spec.limb_along[limb]
    across = spec.limb_across[limb]
    w0, w1 = _LIMB_WIDTH[limb]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1e-9
    nx, ny = -dy / length, dx / length
    half = w0 + (w1 - w0) * along
    # Round the ends slightly so joints read as joints, not mitred boxes.
    half = half * (1.0 - 0.5 * np.clip(np.abs(along * 2.0 - 1.0) - 0.74, 0.0, 1.0) / 0.26)
    return a[0] + dx * along + nx * across * half, a[1] + dy * along + ny * across * half


def _gun_axis(joints: dict[str, tuple[float, float]]) -> tuple[float, float, float, float]:
    """Wrist position and unit direction of the gun, in figure-local units."""
    wrist, elbow = joints["wrist_near"], joints["elbow_near"]
    dx, dy = wrist[0] - elbow[0], wrist[1] - elbow[1]
    length = math.hypot(dx, dy) or 1e-9
    return wrist[0], wrist[1], dx / length, dy / length


def _figure(spec: SceneSpec, t: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The silhouette, as a filled point cloud in world coordinates."""
    joints, _ = _pose_at(t)
    parts: list[tuple[np.ndarray, np.ndarray]] = []

    # Far limbs first so the near ones read as in front.
    parts.append(_capsule(spec, "thigh_far", joints["hip"], joints["knee_far"]))
    parts.append(_capsule(spec, "shin_far", joints["knee_far"], joints["ankle_far"]))
    parts.append(_capsule(spec, "arm_far", joints["shoulder_far"], joints["elbow_far"]))
    parts.append(_capsule(spec, "fore_far", joints["elbow_far"], joints["wrist_far"]))
    parts.append(_capsule(spec, "torso", joints["hip"], joints["shoulder_c"]))
    parts.append(_capsule(spec, "thigh_near", joints["hip"], joints["knee_near"]))
    parts.append(_capsule(spec, "shin_near", joints["knee_near"], joints["ankle_near"]))

    # Head, carried on the torso's lean, and the fedora that makes the
    # silhouette read as 1962 rather than as a generic stick figure.
    sh, hip = joints["shoulder_c"], joints["hip"]
    head_c = (sh[0] + (sh[0] - hip[0]) * 0.34, sh[1] + 0.104)
    parts.append((head_c[0] + spec.head_x * 0.070, head_c[1] + spec.head_y * 0.083))
    brim_along, brim_across = spec.limb_along["hat"], spec.limb_across["hat"]
    crown = brim_along < 0.42
    # Brim: a flat slab resting on the crown of the head. Crown: a shallow block
    # above it. Both are offsets from the head centre, so the hat rides the lean.
    hat_dx = np.where(crown, brim_across * 0.063, brim_across * 0.150)
    hat_dy = np.where(
        crown,
        0.068 + (brim_along / 0.42) * 0.042,
        0.049 + ((brim_along - 0.42) / 0.58) * 0.018,
    )
    parts.append((head_c[0] + hat_dx, head_c[1] + hat_dy))

    parts.append(_capsule(spec, "arm_near", joints["shoulder_near"], joints["elbow_near"]))
    parts.append(_capsule(spec, "fore_near", joints["elbow_near"], joints["wrist_near"]))

    # The gun, carried along the forearm's line past the wrist.
    wx, wy, ux, uy = _gun_axis(joints)
    parts.append(_capsule(spec, "gun", (wx, wy), (wx + ux * 0.108, wy + uy * 0.108)))

    lx = np.concatenate([p[0] for p in parts])
    ly = np.concatenate([p[1] for p in parts])
    x, y = _to_world(lx, ly, t)
    shade = np.full(lx.shape, 0.03 + 0.34 * _flash_energy(t), dtype=np.float64)
    return x, y, shade


def _muzzle(t: float) -> tuple[float, float]:
    """World position of the muzzle at a cycle time."""
    joints, _ = _pose_at(t)
    wx, wy, ux, uy = _gun_axis(joints)
    mx, my = _to_world(wx + ux * 0.118, wy + uy * 0.118, t)
    return float(mx), float(my)


def _flash_energy(t: float) -> float:
    """0→1→0 over the fire beat: a hard onset and a fast decay."""
    p = _phase(t, "fire")
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return float(math.sin(math.pi * p**0.38) ** 2.4)


def _flash(spec: SceneSpec, t: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The muzzle flash: sparks parked *at* the muzzle until the shot.

    Parked sparks sit at zero radius rather than off-stage, so the frame-to-frame
    tween blooms the flash out of the muzzle instead of flying it in from the
    edge of the frame.
    """
    mx, my = _muzzle(t)
    energy = _flash_energy(t)
    reach = 0.26 * _ease_out(_phase(t, "fire")) if energy > 0.0 else 0.0
    r = spec.flash_speed * reach
    cos, sin = np.cos(spec.flash_angle), np.sin(spec.flash_angle)
    # Stretched along the barrel's line and pushed forward: a flash leaves the
    # muzzle, it does not sit on it.
    x = mx + r * cos * 1.85 - reach * 0.45
    y = my + r * sin * 0.78
    # White-hot core falling off to cordite orange at the lance tips.
    shade = energy * (1.0 - 0.55 * spec.flash_speed**1.4)
    return x, y, np.clip(shade, 0.0, 1.0)


def _blood(spec: SceneSpec, t: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Blood running down the frame in fingers of uneven speed.

    Parked above the clip rect before the bleed beat, so the tween that brings it
    in *is* the blood running down from the top of the frame. Every finger starts
    at the top edge, so the top band goes solid while the fastest fingers reach
    the bottom.
    """
    p = _smooth(_phase(t, "bleed"))
    depth = p * (1.15 + 2.45 * spec.blood_lag)
    y = _PARK - spec.blood_along * depth
    # Fingers taper toward the tip and wander instead of running ruler-straight.
    taper = 1.0 - 0.55 * spec.blood_along
    x = (
        spec.blood_col
        + spec.blood_across * spec.blood_width * taper
        + 0.030 * np.sin(spec.blood_wobble + y * 2.7)
    )
    # Darker at the leading tip, fuller behind it — and dark at *both* ends of
    # the cycle: it fades in with the bleed and out as the iris shuts. Both
    # matter. The depth snaps back to zero at the loop seam, so if the blood
    # were lit at either end the tween across that seam would interpolate a
    # half-lit sheet flying back up the frame. Zero at both ends interpolates
    # to zero throughout.
    lit = min(1.0, p * 6.0) * (1.0 - _smooth(_phase(t, "fade")))
    shade = (0.42 + 0.52 * (1.0 - spec.blood_along**0.7)) * lit
    return x, y, np.clip(shade, 0.0, 1.0)


# --- the frame --------------------------------------------------------------


def frame_columns(t: float, *, points: int = 90_000) -> dict[str, np.ndarray]:
    """Every column the chart needs for cycle time ``t``, as float32 arrays.

    Column *lengths are constant across frames* — that is the contract the
    engine's ``match="index"`` interpolation relies on, and the reason a ~12 Hz
    publish renders as continuous motion.
    """
    spec = scene_spec(points)
    t = float(t) % CYCLE

    groups = {
        "wash": _wash(spec, t),
        "rifle": _rifling(spec, t),
        "ring": _rings(spec, t),
        "fig": _figure(spec, t),
        "flash": _flash(spec, t),
        "blood": _blood(spec, t),
    }
    columns: dict[str, np.ndarray] = {}
    for name, (x, y, c) in groups.items():
        columns[f"{name}_x"] = np.ascontiguousarray(x, dtype=np.float32)
        columns[f"{name}_y"] = np.ascontiguousarray(y, dtype=np.float32)
        columns[f"{name}_c"] = np.ascontiguousarray(c, dtype=np.float32)
    return columns
