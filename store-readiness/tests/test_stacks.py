"""Stack-reach regressions found by scanning real Godot, .NET MAUI, NativeScript and KMP apps."""
import tempfile
import unittest
from pathlib import Path

from storecheck.engine import scan

ELF = Path(__file__).parent / "data" / "elf" / "x86_64_libglide-webp.head"


def make(files: dict) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        f = d / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content if isinstance(content, bytes) else content.encode())
    return d


class StackTests(unittest.TestCase):
    def ids(self, files):
        project, findings = scan(str(make(files)))
        return project, {f.rule_id for f in findings}

    def test_desktop_plugin_library_is_not_an_android_library(self):
        # bytes are 4 KB-aligned ELF: an Android path would be flagged, a desktop addon path must not be
        raw = ELF.read_bytes()
        _, ids = self.ids({"addons/sqlite/bin/linux/x86_64/lib.so": raw, "app/src/main/AndroidManifest.xml":
                           '<manifest xmlns:android="http://schemas.android.com/apk/res/android"/>'})
        self.assertNotIn("play.16kb", ids)
        _, ids = self.ids({"app/src/main/jniLibs/x86_64/lib.so": raw, "app/src/main/AndroidManifest.xml":
                           '<manifest xmlns:android="http://schemas.android.com/apk/res/android"/>'})
        self.assertIn("play.16kb", ids)

    def test_xcframework_container_plist_is_not_an_app(self):
        project, ids = self.ids({"addons/x.xcframework/Info.plist":
                                 '<?xml version="1.0"?><plist version="1.0"><dict><key>AvailableLibraries</key>'
                                 '<array/></dict></plist>', "Podfile": "pod 'A'"})
        self.assertEqual(project.plists, [])

    def test_godot_presets_give_android_target_permissions_and_ios_plist(self):
        cfg = ('[preset.0]\nname="A"\nplatform="Android"\n[preset.0.options]\ngradle_build/target_sdk="33"\n'
               'permissions/manage_external_storage=true\n[preset.1]\nname="I"\nplatform="iOS"\n[preset.1.options]\n'
               'application/bundle_identifier="com.x.y"\nprivacy/camera_usage_description="Take photos"\n')
        project, ids = self.ids({"project.godot": "config_version=5", "export_presets.cfg": cfg})
        self.assertIn("godot", project.frameworks)
        self.assertTrue(project.has_android and project.has_ios)
        self.assertIn("play.target_sdk", ids)
        self.assertIn("play.sensitive_permissions", ids)
        self.assertNotIn("apple.version_keys", ids)       # generated at export

    def test_godot_unset_target_is_unknown_not_a_pass(self):
        cfg = '[preset.0]\nplatform="Android"\n[preset.0.options]\ngradle_build/target_sdk=""\n'
        _, ids = self.ids({"export_presets.cfg": cfg})
        self.assertIn("play.target_sdk_unknown", ids)

    def test_maui_target_from_tfm_and_maccatalyst_plist_ignored(self):
        proj = ('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><UseMaui>true</UseMaui>'
                '<TargetFrameworks>net8.0-android34.0;net8.0-ios;net8.0-maccatalyst</TargetFrameworks>'
                '</PropertyGroup></Project>')
        plist = ('<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleIdentifier</key>'
                 '<string>a.b</string></dict></plist>')
        project, ids = self.ids({"App/App.csproj": proj, "App/Platforms/iOS/Info.plist": plist,
                                 "App/Platforms/MacCatalyst/Info.plist": plist})
        self.assertIn("dotnet-maui", project.frameworks)
        self.assertIn("play.target_sdk", ids)             # API 34 < required level
        self.assertEqual(len(project.plists), 1)          # Mac Catalyst plist dropped
        self.assertNotIn("apple.version_keys", ids)       # MAUI generates them from the csproj

    def test_nativescript_and_kmp_detected(self):
        project, _ = self.ids({"package.json": '{"dependencies":{"@nativescript/core":"8"}}'})
        self.assertIn("nativescript", project.frameworks)
        project, _ = self.ids({"build.gradle.kts": 'plugins { kotlin("multiplatform") }\n'})
        self.assertIn("kotlin-multiplatform", project.frameworks)

    def test_cordova_geolocation_2x_supplies_its_own_location_key(self):
        def cfg(v):
            return ('<widget id="a.b" xmlns="http://www.w3.org/ns/widgets" xmlns:cdv="http://cordova.apache.org/ns/1.0">'
                    '<platform name="ios"/><plugin name="cordova-plugin-geolocation" spec="~' + v + '"/></widget>')
        files = {"www/app.js": "navigator.geolocation.getCurrentPosition(f)"}
        _, old = self.ids({**files, "config.xml": cfg("2.1.0")})
        _, new = self.ids({**files, "config.xml": cfg("4.0.0")})
        self.assertNotIn("apple.usage_strings", old)
        self.assertIn("apple.usage_strings", new)

    def test_minified_library_does_not_trigger_signals(self):
        _, ids = self.ids({"capacitor.config.json": "{}", "ios/App/App/Info.plist":
                           '<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>a</string></dict></plist>',
                           "www/lib/ionic.bundle.min.js": "function f(){report();blockUser();comment.post(userContent)}"})
        self.assertNotIn("both.ugc_moderation", ids)

    def test_shader_and_gitignore_are_not_sdk_evidence(self):
        from storecheck import privacy
        from storecheck.discover import discover
        d = make({"Assets/Water.hlsl": "float amplitude = 1;", ".gitignore": "crashlytics-build.properties",
                  "app/src/main/AndroidManifest.xml": '<manifest xmlns:android="http://schemas.android.com/apk/res/android"/>'})
        self.assertEqual(privacy.build_draft(discover(d))["rows"], [])

    def test_lfs_pointer_icon_is_reported_as_such(self):
        icons = '{"images":[{"idiom":"ios-marketing","size":"1024x1024","scale":"1x","filename":"i.png"}]}'
        d = make({"A/Assets.xcassets/AppIcon.appiconset/Contents.json": icons,
                  "A/Assets.xcassets/AppIcon.appiconset/i.png": "version https://git-lfs.github.com/spec/v1\noid sha256:ab\nsize 5\n",
                  "A/Info.plist": '<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>a</string></dict></plist>',
                  "A.xcodeproj/project.pbxproj": "x"})
        _, findings = scan(str(d))
        icon = [f for f in findings if f.rule_id == "apple.app_icon"]
        self.assertTrue(icon and "LFS" in icon[0].detail and icon[0].severity == "advisory")

    def test_capacitor_ts_config_detected(self):
        project, _ = self.ids({"capacitor.config.ts": "export default {}"})
        self.assertIn("capacitor", project.frameworks)


if __name__ == "__main__":
    unittest.main()


class DeploymentTargetTests(unittest.TestCase):
    PBX = '''// !$*UTF8*$!
{
	objects = {
		A00000000000000000000001 /* Debug */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				IPHONEOS_DEPLOYMENT_TARGET = 11.0;
			};
			name = Debug;
		};
		A00000000000000000000002 /* Debug */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				%s
			};
			name = Debug;
		};
		B00000000000000000000001 /* Build configuration list for PBXProject "A" */ = {
			isa = XCConfigurationList;
			buildConfigurations = (
				A00000000000000000000001 /* Debug */,
			);
		};
		B00000000000000000000002 /* Build configuration list for PBXNativeTarget "App" */ = {
			isa = XCConfigurationList;
			buildConfigurations = (
				A00000000000000000000002 /* Debug */,
			);
		};
		C00000000000000000000001 /* App */ = {
			isa = PBXNativeTarget;
			buildConfigurationList = B00000000000000000000002;
			name = App;
		};
		D00000000000000000000001 /* Project object */ = {
			isa = PBXProject;
			buildConfigurationList = B00000000000000000000001;
		};
	};
}
'''

    def ids(self, setting):
        d = make({"A.xcodeproj/project.pbxproj": self.PBX % setting})
        _, findings = scan(str(d))
        return [f for f in findings if f.rule_id == "apple.deployment_target"]

    def test_project_default_overridden_by_target_is_not_reported(self):
        self.assertEqual(self.ids("IPHONEOS_DEPLOYMENT_TARGET = 16.4;"), [])

    def test_target_inheriting_a_low_project_default_is_reported(self):
        self.assertEqual(len(self.ids("")), 1)

    def test_watch_target_does_not_inherit_the_iphone_default(self):
        self.assertEqual(self.ids("SDKROOT = watchos;"), [])
