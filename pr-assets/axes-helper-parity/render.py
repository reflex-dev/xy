from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("matplotlib", "xy"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.engine == "matplotlib":
        import matplotlib.pyplot as plt
    else:
        import xy.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.2))
    series = (
        ([0, 1, 2, 3], [2.0, 3.5, 2.8, 4.2]),
        ([0, 1, 2, 3], [1.2, 2.0, 3.1, 3.7]),
        ([0, 1, 2, 3], [3.8, 3.1, 2.6, 2.0]),
        ([0, 1, 2, 3], [1.0, 2.7, 2.2, 4.0]),
    )
    colors = ("#2563eb", "#dc2626", "#059669", "#7c3aed")
    for index, (ax, (x_values, y_values), color) in enumerate(
        zip(axes.flat, series, colors, strict=True),
        start=1,
    ):
        ax.plot(x_values, y_values, marker="o", color=color, linewidth=2)
        ax.set_title(f"Experiment {index}")
        ax.set_xlabel("Elapsed time (hours)")
        ax.set_ylabel("Measured response (units)")
        ax.set_xticks([0, 1, 2, 3])
        ax.set_yticks([1, 2, 3, 4])
        ax.grid(True, alpha=0.25)
        ax.label_outer()

    fig.subplots_adjust(
        left=0.12,
        right=0.96,
        bottom=0.13,
        top=0.9,
        wspace=0.32,
        hspace=0.35,
    )
    fig.savefig(args.output, dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
