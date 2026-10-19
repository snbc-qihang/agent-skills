"""Copy Runtime author resources only into a distribution build tree."""
from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildRuntime(build_py):
    def run(self):
        super().run()
        if self.editable_mode:
            return
        root = Path(__file__).resolve().parent
        assets = Path(self.build_lib) / "engineering_assistant/_assets"
        assets.mkdir(parents=True, exist_ok=True)
        for name in ("catalog", "skills", "packs", "schemas", "config"):
            shutil.copytree(root / name, assets / name, dirs_exist_ok=True)
        for name in ("VERSIONING.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
            shutil.copyfile(root / name, assets / name)


setup(cmdclass={"build_py": BuildRuntime})
