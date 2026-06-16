"""Behaviour tests for the claude-fable-harness gates and Stop hook.

Run:  python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOALS = ROOT / "scripts" / "fable_goals.py"
FINDINGS = ROOT / "scripts" / "fable_findings.py"
STOP_HOOK = ROOT / "hooks" / "fable_stop_gate.py"


def run(args, cwd, **kw):
    return subprocess.run(
        [sys.executable, *map(str, args)], cwd=cwd, capture_output=True, text=True, **kw
    )


class GoalGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_nonfinal_goal_completes_with_evidence(self):
        run([GOALS, "create", "--brief", "x", "--goal", "a::do a", "--goal", "b::verify"], self.tmp)
        run([GOALS, "next"], self.tmp)
        r = run([GOALS, "checkpoint", "--id", "G001", "--status", "complete",
                 "--evidence", "did a"], self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_complete_requires_evidence(self):
        run([GOALS, "create", "--goal", "a::only"], self.tmp)
        r = run([GOALS, "checkpoint", "--id", "G001", "--status", "complete"], self.tmp)
        self.assertNotEqual(r.returncode, 0)

    def test_final_goal_requires_verification(self):
        run([GOALS, "create", "--brief", "x", "--goal", "a::do a", "--goal", "b::verify"], self.tmp)
        run([GOALS, "checkpoint", "--id", "G001", "--status", "complete", "--evidence", "did a"], self.tmp)
        # final goal complete without verify evidence -> must fail
        r = run([GOALS, "checkpoint", "--id", "G002", "--status", "complete", "--evidence", "done"], self.tmp)
        self.assertNotEqual(r.returncode, 0)

    def test_final_goal_completes_with_verification(self):
        run([GOALS, "create", "--goal", "a::do a", "--goal", "b::verify"], self.tmp)
        run([GOALS, "checkpoint", "--id", "G001", "--status", "complete", "--evidence", "did a"], self.tmp)
        r = run([GOALS, "checkpoint", "--id", "G002", "--status", "complete",
                 "--evidence", "done", "--verify-cmd", "pytest", "--verify-evidence", "all pass"], self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_final_goal_blocked_by_open_finding(self):
        run([GOALS, "create", "--goal", "a::do a", "--goal", "b::verify"], self.tmp)
        run([GOALS, "checkpoint", "--id", "G001", "--status", "complete", "--evidence", "did a"], self.tmp)
        run([FINDINGS, "add", "--title", "t", "--evidence", "e"], self.tmp)
        r = run([GOALS, "checkpoint", "--id", "G002", "--status", "complete",
                 "--evidence", "done", "--verify-cmd", "pytest", "--verify-evidence", "all pass"], self.tmp)
        self.assertNotEqual(r.returncode, 0)


class FindingsGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_gate_passes_when_empty(self):
        r = run([FINDINGS, "gate"], self.tmp)
        self.assertEqual(r.returncode, 0)

    def test_gate_blocks_with_open_finding(self):
        run([FINDINGS, "add", "--title", "t", "--evidence", "e", "--severity", "high"], self.tmp)
        r = run([FINDINGS, "gate"], self.tmp)
        self.assertEqual(r.returncode, 1)

    def test_gate_passes_after_resolve(self):
        run([FINDINGS, "add", "--title", "t", "--evidence", "e"], self.tmp)
        run([FINDINGS, "resolve", "--id", "F001", "--evidence", "fixed"], self.tmp)
        r = run([FINDINGS, "gate"], self.tmp)
        self.assertEqual(r.returncode, 0)

    def test_gate_passes_after_reject(self):
        run([FINDINGS, "add", "--title", "t", "--evidence", "e"], self.tmp)
        run([FINDINGS, "reject", "--id", "F001", "--reason", "false positive"], self.tmp)
        r = run([FINDINGS, "gate"], self.tmp)
        self.assertEqual(r.returncode, 0)


class StopHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _stop(self, env_extra=None, stdin=""):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.tmp)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(STOP_HOOK)],
            input=stdin, capture_output=True, text=True, env=env,
        )

    def test_allows_without_findings(self):
        r = self._stop()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_blocks_with_open_finding(self):
        run([FINDINGS, "add", "--title", "t", "--evidence", "e"], self.tmp)
        r = self._stop(stdin=json.dumps({"session_id": "s1"}))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["decision"], "block")

    def test_override_env_allows(self):
        run([FINDINGS, "add", "--title", "t", "--evidence", "e"], self.tmp)
        r = self._stop(env_extra={"FABLE_ALLOW_STOP": "1"}, stdin=json.dumps({"session_id": "s1"}))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_round_limit_releases(self):
        run([FINDINGS, "add", "--title", "t", "--evidence", "e"], self.tmp)
        env = {"FABLE_MAX_STOP_BLOCKS": "2"}
        s = json.dumps({"session_id": "s1"})
        self.assertEqual(json.loads(self._stop(env, s).stdout)["decision"], "block")
        self.assertEqual(json.loads(self._stop(env, s).stdout)["decision"], "block")
        # third call: counter exhausted -> allow
        self.assertEqual(self._stop(env, s).stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
