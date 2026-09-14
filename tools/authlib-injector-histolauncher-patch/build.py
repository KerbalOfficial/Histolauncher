#!/usr/bin/env python3

import argparse
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

PATCH_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(PATCH_DIR))
SOURCE_DIR = os.path.join(PATCH_DIR, "src", "main", "java")
DEFAULT_OUTPUT = os.path.join(PROJECT_ROOT, "src", "assets", "authlib-injector.jar")

DOWNLOAD_URL = (
    "https://github.com/yushijinhun/authlib-injector/releases/download/"
    "v{version}/authlib-injector-{version}.jar"
)

EXPECTED_CLASS_MAJOR = 52  # Java 8

MANIFEST_MARKER = "Histolauncher-Patched"


def log(message):
    print("[build-authlib] " + message)


def fail(message):
    print("[build-authlib] ERROR: " + message, file=sys.stderr)
    raise SystemExit(1)


def patch_sources():
    sources = []
    for dirpath, _dirnames, filenames in os.walk(SOURCE_DIR):
        for name in filenames:
            if name.endswith(".java"):
                sources.append(os.path.join(dirpath, name))
    if not sources:
        fail("no .java sources found under " + SOURCE_DIR)
    return sorted(sources)


def download_upstream(version, destination):
    url = DOWNLOAD_URL.format(version=version)
    log("downloading " + url)
    with urllib.request.urlopen(url, timeout=180) as response:
        data = response.read()
    with open(destination, "wb") as handle:
        handle.write(data)
    log("downloaded %d bytes" % len(data))
    return destination


def upstream_version(jar_path):
    with zipfile.ZipFile(jar_path) as archive:
        manifest = archive.read("META-INF/MANIFEST.MF").decode("utf-8")
    match = re.search(r"^Implementation-Version:\s*(.+)$", manifest, re.M)
    return match.group(1).strip() if match else "unknown"


def compile_patch(upstream_jar, classes_dir):
    sources = patch_sources()
    log("compiling %d patch source(s) against %s" % (len(sources), os.path.basename(upstream_jar)))
    command = [
        "javac",
        "--release", "8",
        "-encoding", "UTF-8",
        "-nowarn",
        "-Xlint:-options",
        "-cp", upstream_jar,
        "-d", classes_dir,
    ] + sources
    result = subprocess.run(command, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        fail("javac failed")
    produced = {}
    for dirpath, _dirnames, filenames in os.walk(classes_dir):
        for name in filenames:
            if not name.endswith(".class"):
                continue
            full = os.path.join(dirpath, name)
            entry = os.path.relpath(full, classes_dir).replace(os.sep, "/")
            produced[entry] = full
    log("compiled %d class file(s)" % len(produced))
    return produced


def patched_manifest(original, version):
    text = original.decode("utf-8")
    text = "\r\n".join(line for line in text.splitlines() if line.strip())
    text += "\r\n%s: true\r\n" % MANIFEST_MARKER
    text += "Histolauncher-Patch-Base: %s\r\n" % version
    text += "\r\n"
    return text.encode("utf-8")


def build(upstream_jar, output_path):
    version = upstream_version(upstream_jar)
    log("upstream authlib-injector %s" % version)

    with tempfile.TemporaryDirectory() as workdir:
        classes_dir = os.path.join(workdir, "classes")
        os.makedirs(classes_dir)
        produced = compile_patch(upstream_jar, classes_dir)

        staged = os.path.join(workdir, "authlib-injector.jar")
        replaced = []
        added = []
        with zipfile.ZipFile(upstream_jar) as source:
            infos = source.infolist()
            existing = {info.filename for info in infos}
            with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as target:
                for info in infos:
                    name = info.filename
                    if name == "META-INF/MANIFEST.MF":
                        payload = patched_manifest(source.read(name), version)
                    elif name in produced:
                        payload = open(produced[name], "rb").read()
                        replaced.append(name)
                    else:
                        payload = source.read(name)
                    target.writestr(info, payload)
                stamp = infos[0].date_time if infos else (1980, 1, 1, 0, 0, 0)
                for name in sorted(set(produced) - existing):
                    info = zipfile.ZipInfo(name, date_time=stamp)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    target.writestr(info, open(produced[name], "rb").read())
                    added.append(name)

        verify(staged, produced, version)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        shutil.copyfile(staged, output_path)

    log("replaced %d upstream class(es), added %d new class(es)" % (len(replaced), len(added)))
    for name in replaced:
        log("  ~ " + name)
    log("wrote %s (%d bytes)" % (output_path, os.path.getsize(output_path)))


def verify(jar_path, produced, version):
    with zipfile.ZipFile(jar_path) as archive:
        names = set(archive.namelist())
        missing = sorted(set(produced) - names)
        if missing:
            fail("patched classes missing from the jar: " + ", ".join(missing))

        bad_version = []
        for name in sorted(names):
            if not name.endswith(".class"):
                continue
            header = archive.read(name)[:8]
            major = struct.unpack(">H", header[6:8])[0]
            if name in produced and major != EXPECTED_CLASS_MAJOR:
                bad_version.append("%s (major %d)" % (name, major))
        if bad_version:
            fail("unexpected class file version: " + ", ".join(bad_version))

        manifest = archive.read("META-INF/MANIFEST.MF").decode("utf-8")
        if MANIFEST_MARKER not in manifest:
            fail("manifest marker missing")
        if "Premain-Class: moe.yushi.authlibinjector.Premain" not in manifest:
            fail("Premain-Class missing from manifest")
        if ("Implementation-Version: %s" % version) not in manifest:
            fail("Implementation-Version missing from manifest")

        for required in (
            "moe/yushi/authlibinjector/Premain.class",
            "moe/yushi/authlibinjector/internal/fi/iki/elonen/NanoHTTPD$ClientHandler.class",
            "mojang_publickey.der",
        ):
            if required not in names:
                fail("missing required entry " + required)

    log("verified %d entries" % len(names))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--upstream", help="path to a stock upstream authlib-injector jar")
    group.add_argument("--download", metavar="VERSION", help="download this upstream version (e.g. 1.2.8)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="output jar (default: src/assets/authlib-injector.jar)")
    args = parser.parse_args()

    if shutil.which("javac") is None:
        fail("javac not found on PATH (JDK 11 or newer required)")

    with tempfile.TemporaryDirectory() as downloads:
        if args.download:
            upstream = download_upstream(args.download, os.path.join(downloads, "upstream.jar"))
        else:
            upstream = os.path.abspath(args.upstream)
            if not os.path.exists(upstream):
                fail("upstream jar not found: " + upstream)
        build(upstream, os.path.abspath(args.output))


if __name__ == "__main__":
    main()
