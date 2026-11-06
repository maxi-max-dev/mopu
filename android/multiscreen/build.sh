#!/bin/sh
# Builds an unsigned APK; signing credentials must stay outside the repository.
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
: "${ANDROID_HOME:?Set ANDROID_HOME to an Android SDK installation}"
: "${ANDROID_BUILD_TOOLS:?Set ANDROID_BUILD_TOOLS to an installed build-tools version}"
PLATFORM=${ANDROID_PLATFORM:-android-35}
TOOLS="$ANDROID_HOME/build-tools/$ANDROID_BUILD_TOOLS"
PLATFORM_JAR="$ANDROID_HOME/platforms/$PLATFORM/android.jar"
BUILD_DIR=${MOPU_ANDROID_BUILD_DIR:-"$PROJECT_DIR/build"}
mkdir -p "$BUILD_DIR/classes" "$BUILD_DIR/dex"
javac -source 8 -target 8 -Xlint:-options -cp "$PLATFORM_JAR" -d "$BUILD_DIR/classes" "$PROJECT_DIR"/src/dev/mopu/multiscreen/*.java
"$TOOLS/d8" --lib "$PLATFORM_JAR" --output "$BUILD_DIR/dex" "$BUILD_DIR"/classes/dev/mopu/multiscreen/*.class
"$TOOLS/aapt2" compile --dir "$PROJECT_DIR/res" -o "$BUILD_DIR/resources.zip"
"$TOOLS/aapt2" link -o "$BUILD_DIR/unsigned.apk" --manifest "$PROJECT_DIR/AndroidManifest.xml" -I "$PLATFORM_JAR" "$BUILD_DIR/resources.zip"
python3 - "$BUILD_DIR" <<'PY'
import pathlib,sys,zipfile
root=pathlib.Path(sys.argv[1])
with zipfile.ZipFile(root/'unsigned.apk','a',compression=zipfile.ZIP_DEFLATED) as archive:
    archive.write(root/'dex/classes.dex','classes.dex')
PY
"$TOOLS/zipalign" -f 4 "$BUILD_DIR/unsigned.apk" "$BUILD_DIR/multiscreen-unsigned.apk"
printf '%s\n' "Unsigned APK: $BUILD_DIR/multiscreen-unsigned.apk"
