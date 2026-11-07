#!/usr/bin/env bash
set -euo pipefail
probe_root=tools/apk-install-probe
probe_out=install-probe-build
probe_tools="$ANDROID_HOME/build-tools/37.0.0"
mkdir -p "$probe_out/classes" "$probe_out/dex"
javac -source 8 -target 8 -bootclasspath "$ANDROID_HOME/platforms/android-36/android.jar" -d "$probe_out/classes" "$probe_root/Launcher.java"
"$probe_tools/d8" --lib "$ANDROID_HOME/platforms/android-36/android.jar" --min-api 23 --output "$probe_out/dex" "$probe_out/classes/ir/dicode/installprobe/Launcher.class" "$probe_out/classes/ir/dicode/installprobe/Launcher\$Files.class"
"$probe_tools/aapt2" link -I "$ANDROID_HOME/platforms/android-36/android.jar" --manifest "$probe_root/AndroidManifest.xml" -o "$probe_out/probe.apk"
(cd "$probe_out/dex" && zip -q ../probe.apk classes.dex)
keytool -genkeypair -keystore "$probe_out/probe.jks" -storepass probe-only -keypass probe-only -alias probe -keyalg RSA -dname CN=LocalInstallProbe -validity 2 -noprompt
"$probe_tools/apksigner" sign --ks "$probe_out/probe.jks" --ks-pass pass:probe-only "$probe_out/probe.apk"
