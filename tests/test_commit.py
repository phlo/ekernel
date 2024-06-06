import os
import shutil
import subprocess
import sys
import unittest

from ekernel import Kernel
from tests import git, capture_stdout, capture_stderr, colorless
import tests.data.kernel as data

import ekernel

def run (*argv):
    return ekernel.commit(list(argv))

class Tests (unittest.TestCase):

    def setUp (self):
        # setup test environment
        data.setup()
        self.current = Kernel.current()
        self.latest = Kernel.latest()
        # update src symlink to new kernel
        data.linux.unlink()
        data.linux.symlink_to(data.latest)
        # initialize git repository
        os.chdir(data.tmp)
        git(["init"])
        git(["config", "user.email", "some@e.mail"])
        git(["config", "user.name", "some body"])
        git(["add", "-f", self.current.config])
        git(["commit", "-m", "initial"])
        # additional files
        self.oldconfig = data.latest / ".config.old"
        self.newoptions = data.latest / ".newoptions"
        # create config files
        self.latest.config.write_text(data.newconfig)
        self.oldconfig.write_text(data.oldconfig)
        self.newoptions.write_text(data.newoptions)
        # old config removed by ekernel-clean
        self.current.config.unlink()

    def check_commit (self, msg):
        # check message
        self.assertEqual(
            git(["log", "-1", "--pretty=%B"]).stdout.decode(),
            msg
        )
        # check if config has been commited
        self.assertEqual(
            git([
                "cat-file",
                "-e",
                f"HEAD:{self.latest.config.relative_to(data.tmp)}"]
            ).returncode,
            0
        )

    def test_commit (self):
        self.assertEqual(run("-q"), 0)
        self.check_commit(
            f"kernel update: {self.current.version} → {self.latest.version}\n"
            "\n"
            "new:\n"
            "* CONFIG_D = n\n"
            "* CONFIG_E = n\n"
            "* CONFIG_F = n\n"
            "\n"
            "enabled:\n"
            "* CONFIG_D = y\n"
            "* CONFIG_F = y\n"
            "\n"
            "changed:\n"
            "* CONFIG_C = y → m\n"
            "\n"
            "removed:\n"
            "* CONFIG_B\n"
            "\n"
        )

    def test_commit_message (self):
        self.assertEqual(run("-q", "-m", "details"), 0)
        self.check_commit(
            f"kernel update: {self.current.version} → {self.latest.version}\n"
            "\n"
            "details\n"
            "\n"
            "new:\n"
            "* CONFIG_D = n\n"
            "* CONFIG_E = n\n"
            "* CONFIG_F = n\n"
            "\n"
            "enabled:\n"
            "* CONFIG_D = y\n"
            "* CONFIG_F = y\n"
            "\n"
            "changed:\n"
            "* CONFIG_C = y → m\n"
            "\n"
            "removed:\n"
            "* CONFIG_B\n"
            "\n"
        )

    def test_commit_missing_newoptions (self):
        self.newoptions.unlink()
        self.assertEqual(run("-q", "-m", "details"), 0)
        self.check_commit(
            f"kernel update: {self.current.version} → {self.latest.version}\n"
            "\n"
            "details\n"
            "\n"
            "enabled:\n"
            "* CONFIG_D = y\n"
            "* CONFIG_F = y\n"
            "\n"
            "changed:\n"
            "* CONFIG_C = y → m\n"
            "\n"
            "removed:\n"
            "* CONFIG_B\n"
            "\n"
        )

    def test_commit_missing_oldconfig (self):
        self.latest.config.write_text(data.newconfig)
        self.oldconfig.unlink()
        self.newoptions.unlink()
        self.assertEqual(run("-q", "-m", "details"), 0)
        self.check_commit(f"kernel {self.latest.version}\n\ndetails\n\n")

    def test_commit_only_removals (self):
        self.latest.config.write_text(data.newconfig)
        self.oldconfig.unlink()
        self.newoptions.unlink()
        git(["add", "-f", self.latest.config])
        git(["commit", "-m", "update", self.latest.config])
        self.assertEqual(run("-q", "-m", "details"), 0)
        self.check_commit("removed old kernel leftovers\n\ndetails\n\n")

    @colorless
    @capture_stderr
    def test_commit_missing_repository (self):
        shutil.rmtree(data.tmp / ".git")
        with self.assertRaises(SystemExit):
            self.assertEqual(run(), 1)
        self.assertRegex(sys.stderr.getvalue(), r"not a git repository")

    @colorless
    @capture_stderr
    def test_commit_missing_config (self):
        self.latest.config.unlink()
        with self.assertRaises(SystemExit):
            self.assertEqual(run(), 1)
        self.assertEqual(
            sys.stderr.getvalue(),
            f" * missing config: {self.latest.config}\n"
        )

    @colorless
    @capture_stderr
    def test_commit_staged (self):
        staged = self.latest.src / ".garbage"
        staged.touch()
        subprocess.run(["git", "add", "-f", staged])
        with self.assertRaises(SystemExit):
            self.assertEqual(run(), 1)
        self.assertEqual(
            sys.stderr.getvalue(),
            " * please commit or stash staged changes\n"
        )

    @colorless
    @capture_stdout
    def test_commit_dry_run (self):
        #  self.maxDiff = None
        self.assertEqual(run("-n"), 0)
        self.assertEqual(sys.stdout.getvalue(),
            " * changes to be committed:\n"
            f"   - {self.current.config}\n"
            f"   + {self.latest.config}\n"
            " * commit message:\n"
            "   kernel update: "
            f"{self.current.version} → {self.latest.version}\n"
            "\n"
            "   new:\n"
            "   * CONFIG_D = n\n"
            "   * CONFIG_E = n\n"
            "   * CONFIG_F = n\n"
            "\n"
            "   enabled:\n"
            "   * CONFIG_D = y\n"
            "   * CONFIG_F = y\n"
            "\n"
            "   changed:\n"
            "   * CONFIG_C = y → m\n"
            "\n"
            "   removed:\n"
            "   * CONFIG_B\n"
        )
        self.assertEqual(
            git(["log", "-1", "--pretty=%B"]).stdout.decode(),
            "initial\n\n"
        )

    @colorless
    @capture_stdout
    def test_commit_dry_run_only_removals (self):
        self.latest.config.write_text(data.newconfig)
        self.oldconfig.unlink()
        self.newoptions.unlink()
        git(["add", "-f", self.latest.config])
        git(["commit", "-m", "test", self.latest.config])
        self.assertEqual(run("-n", "-m", "details"), 0)
        self.assertEqual(sys.stdout.getvalue(),
            " * changes to be committed:\n"
            f"   - {self.current.config}\n"
            " * commit message:\n"
            "   removed old kernel leftovers\n\n"
            "   details\n"
        )
        self.assertEqual(
            git(["log", "-1", "--pretty=%B"]).stdout.decode(),
            "test\n\n"
        )
