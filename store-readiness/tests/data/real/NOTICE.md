# Test data

The `.pb` and `.axml` files are AndroidManifest.xml entries extracted from test files in
https://github.com/google/bundletool (`src/test/resources/.../testdata/`), licensed under the Apache License 2.0.
The `.expected.json` files were produced by independent decoders: the aapt2 `Resources.proto` schema from AOSP
(for bundles) and androguard (for the APK). They exist to check storecheck's own decoders against real,
tool-built manifests.
