import numpy as np
from omx_core.reduce.plot import line_plot, bar_plot


def _is_png(path):
    return path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_line_plot_writes_valid_png(tmp_path):
    out = tmp_path / "curve.png"
    x = np.linspace(0, 1, 200)
    res = line_plot(x, {"roll": np.sin(x * 6.28), "pitch": np.cos(x * 6.28)},
                    out, title="attitude")
    assert res == out
    assert out.exists() and out.stat().st_size > 0
    assert _is_png(out)


def test_line_plot_caps_width_px(tmp_path):
    # default matplotlib figure is 6.4in*100dpi = 640px; max_px=400 forces the
    # cap branch in _save to scale it down (640 > 400). A cap that did nothing
    # would leave the PNG at ~640px and fail this assertion.
    out = tmp_path / "wide.png"
    x = np.arange(50)
    line_plot(x, {"a": x}, out, max_px=400)
    try:
        from PIL import Image
        w, _ = Image.open(out).size
    except ImportError:
        b = out.read_bytes()
        w = int.from_bytes(b[16:20], "big")  # PNG IHDR width, bytes 16-20 big-endian
    assert w <= 400


def test_bar_plot_writes_valid_png(tmp_path):
    out = tmp_path / "bars.png"
    res = bar_plot(["roll", "pitch", "yaw"], [0.76, 0.20, 0.001], out,
                   title="ss_error by axis")
    assert res == out
    assert _is_png(out)


def test_plot_creates_parent_dir(tmp_path):
    out = tmp_path / "nested" / "deep" / "curve.png"
    line_plot(np.arange(10), {"a": np.arange(10)}, out)
    assert out.exists()
