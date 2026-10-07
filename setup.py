"""Bundle only public runtime resources in wheels (no local state)."""
from pathlib import Path
import shutil
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithAssets(build_py):
    def run(self):
        super().run()
        root = Path(__file__).parent
        target = Path(self.build_lib) / "contextcanon_cli" / "_assets"
        for folder in ("examples", "benchmark", "deploy"):
            for source in (root / folder).rglob("*"):
                if (source.is_file() and source.suffix in (".py", ".json", ".yml", ".md")
                        and "__pycache__" not in source.parts and "results" not in source.parts):
                    dest = target / source.relative_to(root)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, dest)


setup(cmdclass={"build_py": BuildWithAssets})
