"""The diagnose-stutter and bisect-regression prompts: listed, built only from tools that exist, and safe against
arguments that are not plain names."""
import re

from support import ROOT  # noqa: F401  (puts src/ on sys.path)

from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
from metal_gpu_trace import protocol, registry


def get(name, arguments=None):
    params = {"name": name} if arguments is None else {"name": name, "arguments": arguments}
    return protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": params})


def text_of(name, arguments=None):
    return get(name, arguments)["result"]["messages"][0]["content"]["text"]


def tools_named(text):
    """The words of `text` that start a tool call: a tool name followed by a space and `name=`, `run=`, `a=` ... or the
    tool's name between backticks is not used by these prompts, so only `tool_name key=` counts."""
    return set(re.findall(r"\b([a-z]+_[a-z_]+)(?= [a-z_]+=)", text))


def test_both_prompts_are_listed_with_their_arguments():
    listed = {p["name"]: p for p in protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})["result"]["prompts"]}
    assert {"diagnose-stutter", "bisect-regression"} <= set(listed), sorted(listed)
    assert [a["name"] for a in listed["bisect-regression"]["arguments"]] == ["good_rev", "bad_rev", "workload"]
    assert all("render" not in p for p in listed.values())


def test_diagnose_stutter_follows_the_tools_in_order():
    text = text_of("diagnose-stutter", {"workload": "drawstress"})
    steps = [text.index(word) for word in ("perf_cold_warm", "first_seen_hitches", "perf_diagnose")]
    assert steps == sorted(steps) and "workload=drawstress" in text, text


def test_diagnose_stutter_names_only_fields_the_tools_return():
    """Every field the text quotes must be one the experiment reports: no invented `top_limiter`."""
    from metal_gpu_trace import experiments
    report = experiments.cold_warm_report("x", ("a", {}), ("b", {}))
    text = text_of("diagnose-stutter")
    for field in ("first_seen_hitches", "extra_hitches_in_first", "compiler_busy_ms"):
        assert field in text and (field in report or field in report["first"]), field
    assert "top_limiter" not in text
    assert "unpresented" in text, "a run whose window was hidden is not a diagnosis: the text says to record again"


def test_prompts_name_only_existing_tools():
    for name, arguments in (("diagnose-stutter", None),
                            ("bisect-regression", {"good_rev": "v1.0", "bad_rev": "abc123", "workload": "drawstress"})):
        used = tools_named(text_of(name, arguments))
        assert used and used <= set(registry.TOOLS), (name, used - set(registry.TOOLS))


def test_bisect_regression_uses_both_revisions_and_the_workload():
    text = text_of("bisect-regression", {"good_rev": "v1.0", "bad_rev": "abc123", "workload": "drawstress"})
    assert "git bisect start abc123 v1.0" in text and "workload=drawstress" in text, text
    for word in ("perf_record", "perf_check", "Repeat step 3"):
        assert word in text, word


def test_bisect_regression_does_not_run_commands_itself():
    """The server only gives the text; the agent runs git with its own permissions."""
    assert not hasattr(registry, "tool_bisect") and not any("bisect" in name for name in registry.TOOLS)


def test_prompt_arguments_exist_in_each_tools_schema():
    """Each `tool key=` the prompts write names a parameter of that tool's input schema, so renaming one breaks here."""
    for name, arguments in (("diagnose-stutter", None),
                            ("bisect-regression", {"good_rev": "v1.0", "bad_rev": "abc123", "workload": "drawstress"})):
        for tool, keys in re.findall(r"\b([a-z]+_[a-z_]+) ((?:[a-z_]+=\S+ ?)+)", text_of(name, arguments)):
            known = registry.TOOLS[tool][1]["properties"]
            assert all(k in known for k in re.findall(r"([a-z_]+)=", keys)), (name, tool, keys)


def test_bisect_regression_records_the_baseline_before_it_starts_bisecting():
    text = text_of("bisect-regression", {"good_rev": "v1.0", "bad_rev": "abc123"})
    assert text.index("perf_baseline_record name=bisect-good") < text.index("git bisect start"), text
    assert "baseline=bisect-good" in text


def test_bisect_regression_accepts_a_number_and_refuses_a_leading_dash_in_either_revision():
    assert "git bisect start 456 123" in text_of("bisect-regression", {"good_rev": 123, "bad_rev": 456})
    for arguments in ({"good_rev": "v1.0", "bad_rev": "--help"}, {"good_rev": "-x", "bad_rev": "abc123"}):
        assert get("bisect-regression", arguments)["error"]["code"] == -32602, arguments


def test_diagnose_stutter_diagnoses_both_runs():
    text = text_of("diagnose-stutter")
    assert "first run's name" in text and "second run's name" in text, text


def test_bisect_regression_requires_both_revisions():
    for arguments in (None, {"good_rev": "v1.0"}, {"bad_rev": "abc123"}):
        got = get("bisect-regression", arguments)
        assert got["error"]["code"] == -32602, (arguments, got)


def test_bisect_regression_drops_revisions_that_are_not_plain_names():
    """`;`, `$(`, spaces and slashes never reach the text: the argument is dropped, so the prompt is refused."""
    for bad in ("main; rm -rf /", "$(reboot)", "a b", "--help", "feature/x", "`id`"):
        got = get("bisect-regression", {"good_rev": bad, "bad_rev": "abc123"})
        assert "error" in got, (bad, got)
    safe = text_of("bisect-regression", {"good_rev": "v1.0", "bad_rev": "abc123", "workload": "x; rm -rf /"})
    assert "rm -rf" not in safe and "workload=drawstress" in safe, safe


def test_diagnose_stutter_drops_an_argument_that_is_not_a_plain_name():
    assert "rm -rf" not in text_of("diagnose-stutter", {"workload": "x; rm -rf /"})
