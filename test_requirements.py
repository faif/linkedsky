from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class RequirementsTests(unittest.TestCase):
    def test_install_enforces_hashes_and_includes_conditional_dependencies(self):
        lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn("--require-hashes", lines)
        self.assertIn("-r requirements-conditional.lock", lines)
        conditional = (ROOT / "requirements-conditional.lock").read_text(encoding="utf-8")
        self.assertRegex(conditional, r'(?m)^colorama==\S+\s*;\s*platform_system == "Windows"')
        self.assertRegex(conditional, r'(?m)^zstandard==\S+\s*;\s*python_version < "3\.14"')

    def test_each_requirement_has_a_version_pin_and_sha256_hash(self):
        for filename in ("requirements.txt", "requirements-conditional.lock"):
            contents = (ROOT / filename).read_text(encoding="utf-8")
            for line in contents.replace("\\\n", " ").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-")):
                    continue
                with self.subTest(file=filename, package=line.split("==")[0]):
                    requirement, *hashes = line.split("--hash=")
                    self.assertRegex(requirement, r"^[\w.-]+==[0-9][\w.+!-]*(?:\s|;|$)")
                    self.assertTrue(hashes)
                    for digest in hashes:
                        self.assertRegex(digest.strip(), r"\Asha256:[0-9a-f]{64}\Z")
