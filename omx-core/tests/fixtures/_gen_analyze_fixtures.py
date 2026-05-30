"""Generate tiny, REAL TB + wandb fixtures for the analyze-adapter tests.

Run once; products are committed. Kept deterministic (fixed values, no RNG) so
the fixtures are reproducible and the adapter tests are exact.

    python3 tests/fixtures/_gen_analyze_fixtures.py

Notes on TB writer choice:
- tensorboard.summary.Writer.add_scalar writes tensor-format events; those land
  in EventAccumulator.Tags()['tensors'], NOT ['scalars'].
- We need simple_value proto events so that Tags()['scalars'] is populated.
  The only reliable path is the low-level EventFileWriter + event_pb2/summary_pb2.
- EventFileWriter uses a background thread; a time.sleep(1) after close() is
  required to ensure the OS write buffer is fully flushed before rename.
- EventAccumulator must be pointed at the DIRECTORY containing the event file,
  not the file itself; pointing at the file raises NotFoundError.
"""
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _scalar_event(tag, value, step):
    from tensorboard.compat.proto import event_pb2, summary_pb2
    s = summary_pb2.Summary(
        value=[summary_pb2.Summary.Value(tag=tag, simple_value=value)]
    )
    return event_pb2.Event(step=step, summary=s)


def gen_tb():
    """Write a real TB event file with 2 scalar tags x 5 steps."""
    from tensorboard.summary.writer.event_file_writer import EventFileWriter
    out_dir = HERE / "tb"
    out_dir.mkdir(parents=True, exist_ok=True)
    writer = EventFileWriter(str(out_dir))
    for step in range(5):
        writer.add_event(_scalar_event("Reward/total", -0.5 + 0.1 * step, step))
        writer.add_event(_scalar_event("Track/att/roll_err_deg", 20.0 - 2.0 * step, step))
    writer.flush()
    writer.close()
    # Background thread needs time to finish writing before rename
    time.sleep(1)
    # TB names the file events.out.tfevents.<time>.<host>...; rename to a stable name
    produced = sorted(f for f in out_dir.glob("events.out.tfevents.*")
                      if f.name != "events.out.tfevents.synthetic")
    assert produced, "TB writer produced no event file"
    stable = out_dir / "events.out.tfevents.synthetic"
    if stable.exists():
        stable.unlink()
    produced[0].rename(stable)
    for extra in produced[1:]:
        extra.unlink()
    print("wrote", stable)


if __name__ == "__main__":
    gen_tb()
