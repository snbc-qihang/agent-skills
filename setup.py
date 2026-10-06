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
        for name in ("catalog", "skills", "packs", "schemas", "evals", "config"):
            shutil.copytree(root / name, assets / name, dirs_exist_ok=True)
        shutil.copyfile(root / "VERSIONING.md", assets / "VERSIONING.md")


setup(cmdclass={"build_py": BuildRuntime})
