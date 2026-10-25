"""Matplotlib charts embedded in Qt, styled from config/theme.json."""
from __future__ import annotations

import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from ui.folder_a_shell.context import ctx  # noqa: E402


class Chart(FigureCanvasQTAgg):
    def __init__(self, height: float = 3.0):
        self.fig = Figure(figsize=(5, height), tight_layout=True)
        super().__init__(self.fig)
        self.setMinimumHeight(int(height * 80))

    def _ax(self, title: str):
        t = ctx().theme
        c = t.c
        self.fig.clear()
        self.fig.set_facecolor(c["surface"])
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(c["surface"])
        ax.set_title(title, color=c["text"], fontsize=10.5, fontweight="semibold", loc="left", pad=10)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(c["border"])
        ax.tick_params(colors=c["muted"], labelsize=8, length=0)
        ax.grid(axis="y", color=c["border"], linewidth=0.6)
        ax.set_axisbelow(True)
        return ax, t.cfg["chart_palette"]

    def empty(self, title: str, message: str):
        ax, _ = self._ax(title)
        ax.text(0.5, 0.5, message, ha="center", va="center", color=ctx().theme.c["muted"], transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
        self.draw()

    @staticmethod
    def _money_axis(axis):
        from matplotlib.ticker import FuncFormatter

        from backend.shared.formatting import format_money_compact
        axis.set_major_formatter(FuncFormatter(lambda v, _pos: format_money_compact(v)))

    def line(self, title, x, series: dict[str, list], dashed: set[str] = frozenset(), money: bool = False):
        if not x:
            return self.empty(title, "No data for this period")
        ax, pal = self._ax(title)
        if money:
            self._money_axis(ax.yaxis)
        for i, (name, ys) in enumerate(series.items()):
            xs = x[: len(ys)] if len(ys) <= len(x) else x
            ax.plot(xs, ys, color=pal[i % len(pal)], linewidth=2, label=name, linestyle="--" if name in dashed else "-")
            if i == 0:
                ax.fill_between(range(len(ys)), ys, color=pal[0], alpha=0.08)
        step = max(1, len(x) // 8)
        ax.set_xticks(range(0, len(x), step))
        ax.set_xticklabels([str(v)[5:] if len(str(v)) == 10 else str(v) for v in x[::step]], rotation=0)
        if len(series) > 1:
            ax.legend(frameon=False, fontsize=8, labelcolor=ctx().theme.c["text"])
        self.draw()

    def bar(self, title, labels, values, horizontal: bool = False, money: bool = False):
        if not labels:
            return self.empty(title, "No data for this period")
        ax, pal = self._ax(title)
        # One series, one colour: the brand colour, with a lighter tint behind the grid
        colors = [pal[0]] * len(labels)
        if horizontal:
            ax.barh(labels[::-1], values[::-1], color=colors[::-1], height=0.6)
            ax.grid(axis="x", color=ctx().theme.c["border"], linewidth=0.6)
            ax.grid(axis="y", visible=False)
            ax.spines["left"].set_visible(False)
            if money:
                self._money_axis(ax.xaxis)
        else:
            ax.bar(labels, values, color=colors, width=0.6)
            if money:
                self._money_axis(ax.yaxis)
            for lbl in ax.get_xticklabels():
                lbl.set_rotation(35)
                lbl.set_horizontalalignment("right")
        self.draw()

    def pie(self, title, labels, values):
        if not labels:
            return self.empty(title, "No data")
        ax, pal = self._ax(title)
        ax.grid(False)
        ax.pie(values, labels=labels, colors=pal[: len(labels)], autopct="%1.0f%%", startangle=90,
               wedgeprops={"width": 0.45, "edgecolor": ctx().theme.c["surface"]},
               textprops={"color": ctx().theme.c["text"], "fontsize": 9}, pctdistance=0.78)
        ax.axis("equal")
        self.draw()
