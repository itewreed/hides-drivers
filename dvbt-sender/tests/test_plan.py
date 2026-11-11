import pytest

from dvbt_sender.config import Config, Program
from dvbt_sender.dvbt import useful_bitrate
from dvbt_sender.pipeline import PlanError, ffmpeg_command, make_plan, tsp_command


@pytest.mark.parametrize("bw,cons,cr,gi,expected", [
    (8_000_000, "64-QAM", "2/3", "1/32", 24_128_342),
    (8_000_000, "64-QAM", "3/4", "1/4", 22_394_117),
    (8_000_000, "16-QAM", "2/3", "1/4", 13_270_588),
    (8_000_000, "QPSK", "1/2", "1/4", 4_976_470),
    (7_000_000, "64-QAM", "2/3", "1/32", 21_112_299),
])
def test_useful_bitrate_matches_en300744(bw, cons, cr, gi, expected):
    for mode in ("2K", "8K"):
        assert abs(useful_bitrate(bw, cons, cr, gi, mode) - expected) <= 1


def test_plan_splits_rate_and_fits():
    cfg = Config(programs=[Program(name=f"P{i}", source_type="testbild") for i in range(4)])
    plan = make_plan(cfg)
    assert plan.allocated <= plan.usable_bitrate
    assert [p.service_id for p in plan.programs] == [1, 2, 3, 4]
    assert len({p.pmt_pid for p in plan.programs}) == 4
    assert len({p.port for p in plan.programs}) == 4


def test_plan_rejects_too_many_programs():
    cfg = Config(programs=[Program(name=f"P{i}", source_type="testbild") for i in range(20)])
    with pytest.raises(PlanError):
        make_plan(cfg)


def test_commands_contain_parameters():
    cfg = Config(programs=[Program(name="Mein Sender", source="/x/a.mp4")])
    cfg.transmitter.gain = 6
    cfg.transmitter.device = "/dev/usb-it950x0"
    plan = make_plan(cfg)
    tsp = tsp_command(cfg, plan)
    i = tsp.index("hides")
    out = tsp[i:]
    assert out[out.index("--frequency") + 1] == "482000000"
    assert out[out.index("--gain") + 1] == "6"
    assert out[out.index("--device") + 1] == "/dev/usb-it950x0"
    ff = ffmpeg_command(cfg, plan.programs[0])
    assert "service_name=Mein Sender" in ff
    assert "-stream_loop" in ff
