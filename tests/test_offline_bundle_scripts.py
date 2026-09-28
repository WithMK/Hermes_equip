import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PREPARE = (ROOT / "scripts" / "Prepare-HermesOfflineBundle.ps1").read_text(encoding="utf-8")
INSTALL = (ROOT / "scripts" / "Install-HermesOffline.ps1").read_text(encoding="utf-8")


class OfflineBundleScriptTests(unittest.TestCase):
    def test_hermes_source_is_pinned_by_tag_and_commit(self):
        self.assertIn('HermesTag = "v2026.9.7"', PREPARE)
        self.assertIn('HermesCommit = "2237be355906fbe6065ce1815711eee52b2d646e"', PREPARE)
        self.assertIn("git.exe -C $hermesSource rev-parse HEAD", PREPARE)
        self.assertIn("git.exe -C $hermesSource rev-list -n 1 $HermesTag", PREPARE)

    def test_downloaded_executables_require_valid_windows_signature(self):
        self.assertIn("Get-AuthenticodeSignature", PREPARE)
        self.assertGreaterEqual(PREPARE.count("Assert-ValidAuthenticodeSignature"), 3)

    def test_installer_has_no_network_download_path(self):
        self.assertNotIn("Invoke-WebRequest", INSTALL)
        self.assertIn("--no-index", INSTALL)
        self.assertIn('$env:PIP_NO_INDEX = "1"', INSTALL)

    def test_integrity_is_checked_before_python_is_executed(self):
        hash_check = INSTALL.index("Get-FileHash")
        python_install = INSTALL.index("Installing private Python")
        self.assertLess(hash_check, python_install)
        self.assertIn("files not covered by the manifest", INSTALL)

    def test_existing_install_is_backed_up_not_deleted(self):
        self.assertIn("Move-Item -LiteralPath $InstallRoot -Destination $backup", INSTALL)
        self.assertNotIn("Remove-Item -LiteralPath $InstallRoot", INSTALL)

    def test_restricted_poc_components_are_copied(self):
        self.assertIn('integration "plugin\\hermes-equipment-platform"', INSTALL)
        self.assertIn('integration "skills"', INSTALL)
        self.assertIn('integration "config\\profiles"', INSTALL)


if __name__ == "__main":
    unittest.main()
