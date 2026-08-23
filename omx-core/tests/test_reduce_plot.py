import numpy as np
from omx_core.reduce.plot import bar_plot, line_plot


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


def _png_width(path):
    return int.from_bytes(path.read_bytes()[16:20], "big")  # PNG IHDR width


def test_line_plot_dpi_scales_pixels_not_inches(tmp_path):
    # Raising dpi must ADD pixels. If _save computed the width cap from the
    # requested dpi instead of the reference one, a 300-dpi render would be
    # shrunk back in inches and land on the same pixel count — the flag would
    # silently do nothing, which is the failure T24 was opened for.
    x = np.arange(50)
    lo, hi = tmp_path / "lo.png", tmp_path / "hi.png"
    line_plot(x, {"a": x}, lo)
    line_plot(x, {"a": x}, hi, dpi=300)
    assert _png_width(hi) > 2 * _png_width(lo)


def test_line_plot_writes_vector_pdf_with_labels(tmp_path):
    out = tmp_path / "curve.pdf"
    line_plot(np.arange(10), {"a": np.arange(10)}, out,
              title=None, xlabel="step", ylabel="reward")
    assert out.read_bytes()[:5] == b"%PDF-"


def test_line_plot_defaults_unchanged(tmp_path):
    # The triage render must not move: with no dpi/label arguments the output is
    # the same 100-dpi PNG as before the paper-figure options existed.
    out = tmp_path / "same.png"
    line_plot(np.arange(50), {"a": np.arange(50)}, out, title="t")
    assert _is_png(out)
    assert _png_width(out) <= 640  # 6.4in * 100dpi, minus bbox_inches="tight"


def test_plot_creates_parent_dir(tmp_path):
    out = tmp_path / "nested" / "deep" / "curve.png"
    line_plot(np.arange(10), {"a": np.arange(10)}, out)
    assert out.exists()
