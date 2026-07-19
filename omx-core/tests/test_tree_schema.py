"""Task 1 — tree.yaml schema loader, ts-format compiler, run_id grammar."""
import pytest
from omx_core.tree import (
    DEFAULT_TREE_YAML,
    TreeError,
    compile_ts_pattern,
    load_tree_schema,
    parse_run_id,
)

WORKSPACE_SHAPED = """\
version: 1
trees:
  index:
    root: experiments
    levels: [framework, exp, "camp?"]
  data:
    root: heavy/fw
    levels: [exp]
run_id:
  grammar: "<label>[_<tag>]_<ts>"
  ts_format: "%y%m%d_%H%M%S"
  tag: required
links:
  train:  {kind: data_pointer, required: true}
  latest: {kind: alias, scope: camp}
run_dir:
  requires: [manifest.json]
  entries: [config, analysis]
  eval_pattern: "eval/<mode>_<ts>"
  eval_modes: [static, periodic]
  deprecated:
    - {pattern: "eval_dr", message: "pre-standard fallback dir"}
walk:
  ignore: ["legacy", "_*"]
"""


def _write(tmp_path, text):
    fp = tmp_path / "tree.yaml"
    fp.write_text(text, encoding="utf-8")
    return fp


class TestCompileTs:
    def test_short_format(self):
        pat, n = compile_ts_pattern("%y%m%d_%H%M%S")
        assert n == 2
        assert pat.fullmatch("260601_120000")
        assert not pat.fullmatch("2026_1200")

    def test_long_year(self):
        pat, n = compile_ts_pattern("%Y%m%d_%H%M%S")
        assert n == 2
        assert pat.fullmatch("20260601_120000")

    def test_dash_literal_allowed(self):
        pat, n = compile_ts_pattern("%Y-%m-%d_%H-%M-%S")
        assert n == 2
        assert pat.fullmatch("2026-06-01_12-00-00")

    def test_unknown_token_loud_fails(self):
        with pytest.raises(TreeError, match="unsupported"):
            compile_ts_pattern("%y%b%d_%H%M%S")  # %b is alphabetic month

    def test_alpha_literal_loud_fails(self):
        with pytest.raises(TreeError):
            compile_ts_pattern("%y%m%dT%H%M%S")


class TestLoadSchema:
    def test_loads_workspace_shaped(self, tmp_path):
        s = load_tree_schema(_write(tmp_path, WORKSPACE_SHAPED))
        assert s.version == 1
        assert set(s.trees) == {"index", "data"}
        assert s.trees["index"].levels == (("framework", False), ("exp", False), ("camp", True))
        assert s.tag == "required"
        assert s.links["train"].kind == "data_pointer" and s.links["train"].required
        assert s.links["latest"].scope == "camp"
        assert s.requires == ("manifest.json",)
        assert s.entries == ("config", "analysis")
        assert s.eval_modes == ("static", "periodic")
        assert s.deprecated == (("eval_dr", "pre-standard fallback dir"),)
        assert s.ignore == ("legacy", "_*")

    def test_missing_file_names_both_recovery_verbs(self, tmp_path):
        with pytest.raises(TreeError, match="omx init.*tree-codify"):
            load_tree_schema(tmp_path / "tree.yaml")

    def test_unknown_top_key_rejected(self, tmp_path):
        with pytest.raises(TreeError, match="unknown keys"):
            load_tree_schema(_write(tmp_path, "version: 1\ntrees: {index: {root: x}}\nbogus: 1\n"))

    def test_index_tree_required(self, tmp_path):
        with pytest.raises(TreeError, match="index"):
            load_tree_schema(_write(tmp_path, "version: 1\ntrees: {data: {root: x}}\n"))

    def test_bad_version_rejected(self, tmp_path):
        with pytest.raises(TreeError, match="version"):
            load_tree_schema(_write(tmp_path, "version: 2\ntrees: {index: {root: x}}\n"))

    def test_alias_scope_must_be_root_or_declared_level(self, tmp_path):
        bad = WORKSPACE_SHAPED.replace("scope: camp", "scope: nonlevel")
        with pytest.raises(TreeError, match="scope"):
            load_tree_schema(_write(tmp_path, bad))

    def test_bad_tag_value_rejected(self, tmp_path):
        bad = WORKSPACE_SHAPED.replace("tag: required", "tag: always")
        with pytest.raises(TreeError, match="tag"):
            load_tree_schema(_write(tmp_path, bad))

    def test_eval_pattern_needs_placeholders(self, tmp_path):
        bad = WORKSPACE_SHAPED.replace('eval_pattern: "eval/<mode>_<ts>"',
                                       'eval_pattern: "eval/static"')
        with pytest.raises(TreeError, match="placeholder"):
            load_tree_schema(_write(tmp_path, bad))

    def test_default_instance_loads_and_is_flat(self, tmp_path):
        s = load_tree_schema(_write(tmp_path, DEFAULT_TREE_YAML))
        assert set(s.trees) == {"index"}
        assert s.trees["index"].levels == ()
        assert s.tag == "optional"
        assert list(s.links) == ["latest"] and s.links["latest"].scope == "root"


class TestParseRunId:
    @pytest.fixture()
    def schema(self, tmp_path):
        return load_tree_schema(_write(tmp_path, WORKSPACE_SHAPED))

    def test_label_tag_ts(self, schema):
        assert parse_run_id(schema, "alpha_tune1_260601_120000") == {
            "label": "alpha", "tag": "tune1", "ts": "260601_120000"}

    def test_no_tag(self, schema):
        assert parse_run_id(schema, "alpha_260601_120000") == {
            "label": "alpha", "tag": "", "ts": "260601_120000"}

    def test_dashed_label(self, schema):
        assert parse_run_id(schema, "alpha-enc_260601_120000")["label"] == "alpha-enc"

    def test_multi_underscore_tag(self, schema):
        assert parse_run_id(schema, "alpha_per_axis_floor_260601_120000")["tag"] == "per_axis_floor"

    def test_underscore_label_missplits_but_never_crashes(self, schema):
        # M1 documented limitation: an underscore-bearing label (reference
        # writer's fallback path) parses with its tail mis-attributed to the tag.
        got = parse_run_id(schema, "alpha_full_beta_260601_120000")
        assert got == {"label": "alpha", "tag": "full_beta", "ts": "260601_120000"}

    def test_non_run_leaf_is_none(self, schema):
        assert parse_run_id(schema, "analysis") is None
        assert parse_run_id(schema, "alpha_26x601_120000") is None
        assert parse_run_id(schema, "Alpha_260601_120000") is None  # label charset
