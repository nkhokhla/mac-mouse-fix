"""Source moves must change test inputs with Xcode, or fail before compilation."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("project_inputs", SCRIPTS / "project-inputs.py")
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)
ROOT, OUTPUT, ENGINE = ("A" * 24, "B" * 24, "C" * 24)
OLD = "Helper/Core/Drag/ThreeFingerSwipe"
MOVED = "Helper/Core/Drag/Output/ThreeFingerSwipe"
ENGINE_PATH = OLD + "/InstantSpaceSwitcher"


def project(plugin_directory=MOVED, anchored=True):
    names = {"plugin": "ModifiedDragOutputThreeFingerSwipe.m", "engine": "ISS.c",
             "serializer": "event_serialize.c", "serializer_header": "event_serialize.h",
             "engine_header": "include/ISS.h", "license": "InstantSpaceSwitcher-LICENSE.txt"}
    def section(name, body):
        return f"/* Begin {name} section */\n{body}/* End {name} section */\n"
    def group(identifier, path, children, source_tree="<group>"):
        children = "".join(f"\t\t\t\t{child} /* Child */,\n" for child in children)
        return (f"\t\t{identifier} = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = (\n"
                + children + f'\t\t\t);\n\t\t\tpath = "{path}";\n\t\t\tsourceTree = "{source_tree}";\n\t\t}};\n')
    references = "".join(f'\t\t{identifier} /* {names[name]} */ = {{isa = PBXFileReference; path = "{names[name]}"; sourceTree = "<group>"; }};\n'
                         for name, identifier in inputs.INPUTS.items())
    groups = (group(ROOT, "", [OUTPUT])
              + group(OUTPUT, plugin_directory, [inputs.INPUTS["plugin"], ENGINE])
              + group(ENGINE, ENGINE_PATH if anchored else "InstantSpaceSwitcher",
                      [identifier for name, identifier in inputs.INPUTS.items() if name != "plugin"],
                      "SOURCE_ROOT" if anchored else "<group>"))
    return (section("PBXFileReference", references) + section("PBXGroup", groups)
            + section("PBXProject", f"mainGroup = {ROOT};\n"))


class ProjectInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for relative in [MOVED + "/ModifiedDragOutputThreeFingerSwipe.m", ENGINE_PATH + "/ISS.c",
                         ENGINE_PATH + "/event_serialize.c", ENGINE_PATH + "/event_serialize.h",
                         ENGINE_PATH + "/include/ISS.h", ENGINE_PATH + "/InstantSpaceSwitcher-LICENSE.txt"]:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("// " + relative + "\n")

    def test_moved_source_is_found_through_groups(self):
        resolved = inputs.input_paths(project(), self.root)
        self.assertEqual(resolved["plugin"], self.root / MOVED / "ModifiedDragOutputThreeFingerSwipe.m")
        self.assertEqual(resolved["engine"], self.root / ENGINE_PATH / "ISS.c")

    def test_legacy_layout_works_without_another_code_path(self):
        shutil.move(self.root / MOVED / "ModifiedDragOutputThreeFingerSwipe.m", self.root / OLD)
        resolved = inputs.input_paths(project(OLD), self.root)
        self.assertEqual(resolved["plugin"], self.root / OLD / "ModifiedDragOutputThreeFingerSwipe.m")

    def test_symlinked_repository_root_is_canonicalized(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        resolved = inputs.input_paths(project(), alias)
        self.assertEqual(resolved["plugin"], self.root / MOVED / "ModifiedDragOutputThreeFingerSwipe.m")

    def test_parent_move_cannot_hide_missing_engine_behind_valid_file_ids(self):
        with self.assertRaisesRegex(ValueError, "engine input is missing"):
            inputs.input_paths(project(anchored=False), self.root)

    def test_stale_copy_is_not_selected_instead_of_the_compiled_source(self):
        stale = self.root / OLD / "ModifiedDragOutputThreeFingerSwipe.m"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("// stale source must never be tested")
        resolved = inputs.input_paths(project(), self.root)
        self.assertNotEqual(resolved["plugin"], stale)

    def test_missing_header_is_rejected_before_native_compilation(self):
        (self.root / ENGINE_PATH / "include/ISS.h").unlink()
        with self.assertRaisesRegex(ValueError, "engine_header input is missing"):
            inputs.input_paths(project(), self.root)

    def test_missing_warp_declaration_is_rejected(self):
        (self.root / MOVED / "ModifiedDragOutputThreeFingerSwipe.m").write_text("WarpDeltaCompensator_ReportFreeze();")
        with self.assertRaisesRegex(ValueError, "WarpDeltaCompensator header"):
            inputs.input_paths(project(), self.root)

    def test_warp_dependency_stages_the_real_project_header(self):
        identifier = "D" * 24
        text = project().replace("/* End PBXFileReference section */",
            f'\t\t{identifier} /* WarpDeltaCompensator.h */ = {{isa = PBXFileReference; path = "WarpDeltaCompensator.h"; sourceTree = "<group>"; }};\n'
            + "/* End PBXFileReference section */")
        child = f"\t\t\t\t{ENGINE} /* Child */,\n"
        text = text.replace(child, child + f"\t\t\t\t{identifier} /* Child */,\n")
        header = self.root / MOVED / "WarpDeltaCompensator.h"
        header.write_text("// exact upstream API declaration")
        (self.root / MOVED / "ModifiedDragOutputThreeFingerSwipe.m").write_text("WarpDeltaCompensator_ReportFreeze();")
        resolved = inputs.input_paths(text, self.root)
        destination = self.root / "stage"
        inputs.stage(resolved, destination)
        self.assertEqual((destination / "WarpDeltaCompensator.h").read_bytes(), header.read_bytes())

    def test_escaping_group_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported Xcode input path"):
            inputs.input_paths(project("../outside"), self.root)

    def test_ambiguous_parent_is_rejected(self):
        text = project().replace(f"\t\t\t\t{OUTPUT} /* Child */,\n",
                                 f"\t\t\t\t{OUTPUT} /* Child */,\n" * 2)
        with self.assertRaisesRegex(ValueError, "ambiguous parent"):
            inputs.input_paths(text, self.root)

    def test_staging_preserves_engine_local_includes(self):
        resolved = inputs.input_paths(project(), self.root)
        destination = self.root / "stage"
        inputs.stage(resolved, destination)
        self.assertEqual((destination / "InstantSpaceSwitcher/ISS.c").read_bytes(), resolved["engine"].read_bytes())
        self.assertEqual((destination / "InstantSpaceSwitcher/include/ISS.h").read_bytes(), resolved["engine_header"].read_bytes())
        self.assertEqual((destination / "ModifiedDragOutputThreeFingerSwipe.m").read_bytes(), resolved["plugin"].read_bytes())

    def test_shell_runner_uses_staged_sources_after_directory_move(self):
        # Smoke-test file selection and shell plumbing; macOS CI separately
        # compiles and executes the real C/Objective-C tests.
        scripts = self.root / ".github/scripts"
        scripts.mkdir(parents=True)
        for name in ["project-inputs.py", "resolve-upstream-conflicts.py"]:
            shutil.copyfile(SCRIPTS / name, scripts / name)
        test_root = SCRIPTS.parents[1] / "Tests/InstantSpaces"
        shutil.copytree(test_root, self.root / "Tests/InstantSpaces")
        path = self.root / inputs.policy.PROJECT
        path.parent.mkdir(); path.write_text(project())
        binary = self.root / "bin"
        binary.mkdir()
        compiler = binary / "clang"
        compiler.write_text('#!/usr/bin/env python3\nimport pathlib,sys\na=sys.argv[1:]\n'
                            'for p in a:\n if p.endswith((".c",".m")): assert pathlib.Path(p).is_file(),p\n'
                            'p=pathlib.Path(a[a.index("-o")+1]);p.write_text("#!/bin/sh\\nexit 0\\n");p.chmod(0o755)\n')
        compiler.chmod(0o755)
        environment = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"], TMPDIR=str(self.root))
        subprocess.run(["bash", "Tests/InstantSpaces/run.sh"], cwd=self.root, env=environment,
                       check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
